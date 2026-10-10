from __future__ import annotations

from pathlib import Path

import pytest

from tarsgo_simulator.core.config import load_match_config
from tarsgo_simulator.core.map import GameMap, TerrainRegion
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.pathfinding import find_path
from tarsgo_simulator.core.projectiles import Projectile, ProjectileSystem
from tarsgo_simulator.core.robot import Robot


ROOT = Path(__file__).resolve().parents[1]
RMUC_SCENARIO = ROOT / "configs/scenarios/rmuc-2026-region-rules-lab.yaml"


def _rmuc_map():
    return Match(load_match_config(RMUC_SCENARIO)).map


def test_terrain_region_rectangle_fast_path_preserves_polygon_boundaries() -> None:
    rectangle = TerrainRegion(
        id="rectangle",
        kind="platform",
        vertices=((0, 0), (10, 0), (10, 5), (0, 5)),
        height_mm=20,
    )
    triangle = TerrainRegion(
        id="triangle",
        kind="platform",
        vertices=((0, 0), (10, 0), (5, 10)),
        height_mm=20,
    )

    assert rectangle.contains((0, 2.5))
    assert rectangle.contains((10, 5))
    assert not rectangle.contains((10.1, 5))
    assert triangle.contains((5, 5))
    assert not triangle.contains((1, 9))


def test_official_central_ramp_geometry_drives_path_and_live_movement() -> None:
    game_map = _rmuc_map()
    assert len(game_map.terrain_regions) == 5
    assert abs(game_map.terrain_height_at((14000, 203.7)) - 3.55) < 0.1
    assert abs(game_map.terrain_height_at((14000, 2090)) - 386.5) < 0.1
    assert abs(game_map.terrain_height_at((14000, 1146.85)) - 195.0) < 0.1
    assert abs(game_map.terrain_height_at((14000, 7500)) - 480.9) < 0.1

    start = (14000.0, 500.0)
    goal = (14000.0, 7500.0)
    path = find_path(game_map, start, goal)
    assert path == [start, goal]
    assert all(game_map.can_traverse(a, b) for a, b in zip(path, path[1:]))

    robot = Robot(
        id="terrain-test",
        team="red",
        position=start,
        hp=100,
        max_hp=100,
        speed=3000,
        attack_range=0,
        attack_interval=1,
        damage=0,
    )
    robot.set_path(path)
    proposal = robot.propose_movement(1.0, game_map)
    robot.commit_movement(proposal)
    assert 3000 < robot.position[1] < 4000
    assert abs(game_map.terrain_height_at(robot.position) - 411.1) < 0.1

    # The highland's vertical side is not a legal ground-to-platform route.
    assert not game_map.can_traverse((9900, 7500), (11000, 7500))


def test_direct_grade_check_only_covers_single_planar_surface_segments() -> None:
    game_map = _rmuc_map()

    assert game_map._direct_ground_slope_traversable(
        (6000.0, 1000.0),
        (6000.0, 7000.0),
    ) is True
    assert game_map._direct_ground_slope_traversable(
        (12000.0, 3000.0),
        (16000.0, 3000.0),
    ) is True
    assert game_map._direct_ground_slope_traversable(
        (14000.0, 500.0),
        (14000.0, 1800.0),
    ) is True
    assert game_map._direct_ground_slope_traversable(
        (6000.0, 7000.0),
        (6000.0, 8000.0),
    ) is None


def test_official_field_cross_slope_drives_height_movement_sight_and_projectiles() -> None:
    game_map = _rmuc_map()
    slopes = {
        region.id: region
        for region in game_map.terrain_regions
        if region.kind == "ground_slope"
    }
    assert set(slopes) == {"field-cross-slope-north", "field-cross-slope-south"}
    assert all(region.slope_degrees == 1.0 for region in slopes.values())
    assert all("1°–2°" in region.approximation for region in slopes.values())

    for x in (500.0, 6000.0, 14000.0, 27000.0):
        assert game_map.terrain_height_at((x, 0)) == 0
        field_center_ground = max(
            region.height_at((x, 7500)) or 0.0 for region in slopes.values()
        )
        assert abs(field_center_ground - 130.9) < 0.1
        assert game_map.terrain_height_at((x, 15000)) == 0
    for point in ((500.0, 1000.0), (6000.0, 3000.0), (27000.0, 7000.0)):
        mirrored = (28000.0 - point[0], 15000.0 - point[1])
        height = max(region.height_at(point) or 0.0 for region in slopes.values())
        mirrored_height = max(
            region.height_at(mirrored) or 0.0 for region in slopes.values()
        )
        assert mirrored_height == pytest.approx(height, abs=0.1)
    assert abs(game_map.terrain_height_at((14000, 7500)) - 480.9) < 0.1

    start, goal = (6000.0, 1000.0), (6000.0, 14000.0)
    path = find_path(game_map, start, goal)
    assert path == [start, goal]
    assert game_map.can_traverse(start, goal)
    assert not game_map.has_line_of_sight(start, goal)
    assert game_map.has_line_of_sight(
        start,
        goal,
        start_height_mm=200,
        end_height_mm=200,
    )

    robot = Robot(
        id="cross-slope-movement",
        team="red",
        position=start,
        hp=100,
        max_hp=100,
        speed=3000,
        attack_range=0,
        attack_interval=1,
        damage=0,
    )
    robot.set_path(path)
    moved, remaining = robot.propose_movement(1.0, game_map)
    assert moved[1] > start[1]
    assert game_map.terrain_height_at(moved) > game_map.terrain_height_at(start)
    assert remaining == [goal]

    shooter = Robot(
        id="cross-slope-projectile",
        team="red",
        position=start,
        hp=100,
        max_hp=100,
        speed=0,
        attack_range=0,
        attack_interval=1,
        damage=0,
    )
    projectiles = ProjectileSystem()
    projectiles.projectiles.append(
        Projectile(
            id=1,
            shooter_id=shooter.id,
            shooter_team_id=shooter.team,
            caliber="17mm",
            damage=10,
            radius=5,
            speed=10000,
            effective_range=10000,
            position=start,
            previous_position=start,
            velocity=(0, 10000),
        )
    )
    projectiles.advance(
        1.0,
        [shooter],
        [],
        game_map,
        apply_damage=lambda _target, _damage, _shooter: 0,
    )
    assert len(projectiles.impacts) == 1
    assert projectiles.impacts[0].surface == "obstacle"
    assert projectiles.impacts[0].position[1] < 14000


def test_projectile_clearance_prevents_false_ground_slope_line_of_sight_block() -> None:
    game_map = _rmuc_map()
    start, end = (6000.0, 7000.0), (6000.0, 8000.0)

    assert not game_map.has_line_of_sight(start, end)
    assert game_map.has_line_of_sight(start, end, clearance_mm=8.4)


def test_ramp_side_path_and_frame_movement_share_traversability_for_both_halves() -> None:
    game_map = _rmuc_map()
    red_start = (10120.130680893357, 300.0)
    red_goal = (17853.57851287976, 300.0)
    mirrored_start = (
        game_map.width - red_start[0],
        game_map.height - red_start[1],
    )
    mirrored_goal = (
        game_map.width - red_goal[0],
        game_map.height - red_goal[1],
    )

    for start, goal in (
        (red_start, red_goal),
        (mirrored_start, mirrored_goal),
    ):
        path = find_path(game_map, start, goal)
        assert path == [start, goal]
        assert game_map.can_traverse(start, goal)

        robot = Robot(
            id="ramp-side-regression",
            team="red",
            position=start,
            hp=100,
            max_hp=100,
            speed=1900,
            attack_range=0,
            attack_interval=1,
            damage=0,
        )
        robot.set_path(path)
        next_position, remaining_path = robot.propose_movement(1 / 60, game_map)

        assert next_position != start
        assert game_map.can_traverse(start, next_position)
        assert remaining_path == [goal]


def test_a_star_seeds_a_reachable_neighbor_when_start_cell_center_is_blocked() -> None:
    game_map = _rmuc_map()
    mirrored_routes = (
        ((17817.7, 578.0), (25076.0, 1268.0), (17900.0, 500.0)),
        ((10182.3, 14422.0), (2924.0, 13732.0), (10100.0, 14500.0)),
    )

    for start, goal, blocked_cell_center in mirrored_routes:
        assert not game_map.can_traverse(start, blocked_cell_center)

        path = find_path(game_map, start, goal)

        assert path is not None
        assert all(
            game_map.can_traverse(first, second)
            for first, second in zip(path, path[1:])
        )
        assert path[1] != blocked_cell_center

        robot = Robot(
            id="terrain-start-seed",
            team="blue",
            position=start,
            hp=100,
            max_hp=100,
            speed=1800,
            attack_range=0,
            attack_interval=1,
            damage=0,
        )
        robot.set_path(path)
        next_position, _remaining_path = robot.propose_movement(1 / 60, game_map)
        assert next_position != start


def test_central_highland_blocks_ground_sight_and_projectile_but_not_platform_sight() -> None:
    game_map = _rmuc_map()
    assert not game_map.has_line_of_sight((9000, 7500), (19000, 7500))
    assert game_map.has_line_of_sight((12000, 7500), (16000, 7500))

    shooter = Robot(
        id="ground-shooter",
        team="red",
        position=(9000, 7500),
        hp=100,
        max_hp=100,
        speed=0,
        attack_range=0,
        attack_interval=1,
        damage=0,
    )
    system = ProjectileSystem()
    system.projectiles.append(
        Projectile(
            id=1,
            shooter_id=shooter.id,
            shooter_team_id=shooter.team,
            caliber="17mm",
            damage=10,
            radius=5,
            speed=10000,
            effective_range=10000,
            position=shooter.position,
            previous_position=shooter.position,
            velocity=(10000, 0),
        )
    )
    system.advance(
        1.0,
        [shooter],
        [],
        game_map,
        apply_damage=lambda _target, _damage, _shooter: 0,
    )
    assert len(system.impacts) == 1
    assert system.impacts[0].target_kind == "obstacle"
    assert system.impacts[0].target_id is None
    assert system.impacts[0].position[0] < 10150


def test_central_terrain_is_center_symmetric_for_both_field_halves() -> None:
    game_map = _rmuc_map()
    for point in ((14000, 500), (13000, 1500), (14000, 7500), (17000, 14000)):
        mirrored = (game_map.width - point[0], game_map.height - point[1])
        assert abs(game_map.terrain_height_at(point) - game_map.terrain_height_at(mirrored)) < 1e-6


def test_local_tunnel_section_enforces_clearance_and_robot_width() -> None:
    # Dimensions come from Figure 4-34, p.61. Fixture coordinates only exercise
    # the generic tunnel volume; the manual does not place both tunnels in XY.
    tunnel = TerrainRegion(
        id="test-road-tunnel",
        kind="tunnel",
        vertices=((500, 150), (1500, 150), (1500, 850), (500, 850)),
        axis_start=(500, 500),
        axis_end=(1500, 500),
        clearance_mm=250,
        source="§4.4, Figure 4-34, p.61",
        approximation="Test-only portal coordinates.",
    )
    game_map = GameMap(
        2000,
        1000,
        [],
        collision_radius=180,
        path_grid_size=100,
        terrain_regions=(tunnel,),
    )
    start, end = (300, 500), (1700, 500)
    assert game_map.can_traverse(start, end, agent_height_mm=250)
    assert not game_map.can_traverse(start, end, agent_height_mm=251)
    assert not game_map.can_traverse(start, end)
    assert game_map.terrain_collision_fraction(start, end, 200, 200) is None
    assert game_map.terrain_collision_fraction(start, end, 251, 251) is not None

    low_robot = Robot(
        id="low-tunnel-robot",
        team="red",
        position=start,
        hp=100,
        max_hp=100,
        speed=1400,
        attack_range=0,
        attack_interval=1,
        damage=0,
        body_height_mm=250,
    )
    tunnel_path = find_path(
        game_map,
        start,
        end,
        agent_height_mm=low_robot.body_height_mm,
    )
    assert tunnel_path == [start, end]
    low_robot.set_path(tunnel_path)
    moved, remaining = low_robot.propose_movement(1.0, game_map)
    assert moved == end
    assert remaining == []

    tall_robot = Robot(
        id="tall-tunnel-robot",
        team="red",
        position=start,
        hp=100,
        max_hp=100,
        speed=1400,
        attack_range=0,
        attack_interval=1,
        damage=0,
        body_height_mm=251,
    )
    tall_robot.set_path([end])
    blocked, remaining = tall_robot.propose_movement(1.0, game_map)
    assert blocked == start
    assert remaining == []

    too_wide = GameMap(
        2000,
        1000,
        [],
        collision_radius=351,
        path_grid_size=100,
        terrain_regions=(tunnel,),
    )
    assert not too_wide.can_traverse((400, 500), (1600, 500), agent_height_mm=200)
