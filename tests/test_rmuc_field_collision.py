from pathlib import Path

from tarsgo_simulator.core.combat import update_combat
from tarsgo_simulator.core.config import load_match_config
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.pathfinding import find_path
from tarsgo_simulator.core.robot import Robot


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RMUC_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)


def _match(*, spectator_ai: bool = False) -> Match:
    return Match(
        load_match_config(RMUC_SCENARIO),
        rmuc_spectator_ai=spectator_ai,
    )


def _structure(match: Match, structure_id: str):
    return next(item for item in match.structures if item.id == structure_id)


def _robot(match: Match, robot_id: str) -> Robot:
    return next(item for item in match.robots if item.id == robot_id)


def test_rmuc_structures_use_rule_footprints_as_shared_map_blockers() -> None:
    match = _match()
    red_base = match.map.structure_bounds("red-base")
    red_outpost = match.map.structure_bounds("red-outpost")
    blue_outpost = match.map.structure_bounds("blue-outpost")
    blue_base = match.map.structure_bounds("blue-base")

    assert (match.map.width, match.map.height) == (28000, 15000)
    assert red_base is not None
    assert (red_base.width, red_base.height) == (1881, 1609)
    red_base_structure = _structure(match, "red-base")
    assert red_base_structure.footprint_shape == "polygon"
    assert len(red_base_structure.footprint_vertices) == 6
    assert red_outpost is not None
    assert (red_outpost.width, red_outpost.height) == (550, 550)
    assert _structure(match, "red-outpost").footprint_shape == "circle"
    assert blue_outpost is not None
    assert (blue_outpost.width, blue_outpost.height) == (550, 550)
    assert blue_base is not None
    assert (blue_base.width, blue_base.height) == (1881, 1609)
    assert _structure(match, "red-base").position == (2407, 7500)
    assert _structure(match, "red-outpost").position == (6600, 7500)
    assert _structure(match, "blue-base").position == (25593, 7500)
    assert _structure(match, "blue-outpost").position == (21400, 7500)
    red_start = next(zone for zone in match.map.zones if zone.id == "red-start")
    assert len(red_start.vertices) == 6
    assert red_start.width == 4185
    assert red_start.height == 3906
    blue_start = next(zone for zone in match.map.zones if zone.id == "blue-start")
    assert blue_start.width == red_start.width
    assert blue_start.height == red_start.height
    assert red_base.x == 1466.5
    assert red_base.y == 6695.5
    assert not match.map.is_passable(_structure(match, "red-base").position)
    assert not match.map.is_passable(_structure(match, "red-outpost").position)
    assert not match.map.is_passable(_structure(match, "blue-outpost").position)
    assert not match.map.is_passable(_structure(match, "blue-base").position)
    # The official Base is hexagonal and the Outpost body is circular; their
    # unused bounding-box corners remain traversable.
    assert match.map.is_passable((3307.0, 8250.0))
    assert match.map.is_passable((7000.0, 7900.0))
    assert match.map.has_line_of_sight((3307.0, 8250.0), (3360.0, 8300.0))
    assert match.map.has_line_of_sight((7000.0, 7900.0), (7100.0, 8000.0))
    # Semantic buff/terrain zones are not physical collision geometry.
    assert match.map.is_passable((2475.0, 12850.0))


def test_astar_routes_around_rmuc_outpost_and_robots_stop_at_it() -> None:
    match = _match()
    start, goal = (4500.0, 7500.0), (8700.0, 7500.0)

    path = find_path(match.map, start, goal)

    assert path is not None
    assert path[0] == start and path[-1] == goal
    assert all(
        match.map.can_traverse(first, second)
        for first, second in zip(path, path[1:])
    )
    assert any(point[1] < 7045.0 or point[1] > 7955.0 for point in path)

    base_path = find_path(match.map, (1000.0, 7500.0), (4000.0, 7500.0))
    assert base_path is not None
    assert all(
        match.map.can_traverse(first, second)
        for first, second in zip(base_path, base_path[1:])
    )
    assert any(point[1] <= 6645.0 or point[1] >= 8355.0 for point in base_path)

    for robot_id in ("tarsgo-infantry-1", "tarsgo-drone"):
        robot = _robot(match, robot_id)
        robot.position = start
        robot.speed = 1000.0
        robot.alive = True
        robot.path = [goal]
        proposed_position, proposed_path = robot.propose_movement(5.0, match.map)
        assert proposed_position == start
        assert proposed_path == []


def test_rmuc_structure_target_is_exempt_but_other_structure_blocks_sight() -> None:
    match = _match()
    base = _structure(match, "red-base")
    outpost = _structure(match, "red-outpost")

    assert not match.map.has_line_of_sight((1000.0, 7500.0), base.position)
    assert match.map.has_line_of_sight((1000.0, 7500.0), base.position, base.id)
    assert not match.map.has_line_of_sight((6000.0, 7500.0), (7200.0, 7500.0))
    assert not match.map.has_line_of_sight((6000.0, 7500.0), outpost.position, base.id)


def test_rmuc_combat_blocks_occluded_shots_and_allows_clear_structure_hits() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    blue = _robot(match, "opponent-hero")
    red.position = (1000.0, 7500.0)
    blue.position = (4000.0, 7500.0)
    red.attack_range = blue.attack_range = 5000.0
    old_hp = (red.hp, blue.hp)

    def apply_damage(target, amount, _attacker):
        target.hp -= amount
        return amount

    update_combat(
        [red, blue],
        match.map,
        can_attack=lambda _robot: True,
        apply_damage=apply_damage,
        can_target=lambda target: isinstance(target, Robot),
    )

    assert (red.hp, blue.hp) == old_hp

    red.position = (4000.0, 6000.0)
    blue.position = (4000.0, 8000.0)
    update_combat(
        [red, blue],
        match.map,
        can_attack=lambda _robot: True,
        apply_damage=apply_damage,
        can_target=lambda target: isinstance(target, Robot),
    )
    assert red.hp < old_hp[0] and blue.hp < old_hp[1]

    blue.position = (5000.0, 7500.0)
    blue.attack_cooldown = 0.0
    red_base = _structure(match, "red-base")
    hits: list[str] = []
    update_combat(
        [blue],
        match.map,
        can_attack=lambda _robot: True,
        apply_damage=lambda target, amount, _attacker: hits.append(target.id) or amount,
        structures=[red_base],
        can_target=lambda _target: True,
    )
    assert hits == [red_base.id]


def test_rmuc_ai_paths_to_a_passable_attack_approach_for_structure_targets() -> None:
    match = _match(spectator_ai=True)
    hero = _robot(match, "tarsgo-hero")
    target = _structure(match, "blue-outpost")
    hero.position = (16000.0, 7500.0)

    match._set_ai_goal(
        hero,
        "进攻前哨站",
        target.position,
        target_key=f"structure:{target.id}",
    )

    assert hero.path
    points = [hero.position, *hero.path]
    assert all(
        match.map.can_traverse(first, second)
        for first, second in zip(points, points[1:])
    )
    assert match.map.is_passable(hero.path[-1])
    assert match.map.structure_bounds(target.id) is not None


def test_rmuc_reset_rebuilds_blockers_and_destroyed_structures_remain_solid() -> None:
    match = _match()
    old_map = match.map
    old_structures = old_map.structures
    old_outpost = _structure(match, "red-outpost")
    old_outpost.alive = False
    assert not old_map.is_passable(old_outpost.position)

    match.reset()

    new_outpost = _structure(match, "red-outpost")
    assert match.map is not old_map
    assert new_outpost is not old_outpost
    assert new_outpost.alive
    assert not match.map.is_passable(new_outpost.position)
    assert old_map.structures == old_structures
    assert all(item is old for item, old in zip(old_map.structures, old_structures))


def test_rmuc_420_second_smoke_keeps_movement_out_of_structures(
    monkeypatch,
) -> None:
    match = _match(spectator_ai=True)
    monkeypatch.setattr(match.ruleset, "can_attack", lambda _robot: False)

    for _ in range(4200):
        match.update(0.1)
        assert all(match.map.is_passable(robot.position) for robot in match.robots)

    assert abs(match.elapsed_time - 420.0) < 1e-9
