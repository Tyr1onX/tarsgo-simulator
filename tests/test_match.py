from dataclasses import replace
from pathlib import Path
import shutil
import sys

import pytest

from tarsgo_simulator.core.config import (
    ConfigError,
    default_scenario_path,
    load_match_config,
)
from tarsgo_simulator.core.map import GameMap, Rectangle
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.pathfinding import find_path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_training_rules_and_scenario_load() -> None:
    config = load_match_config(default_scenario_path())

    assert config.rules_id == "training-v0"
    assert config.scenario.teams["red"].robot_type == "infantry"
    assert config.scenario.teams["blue"].robot_type == "infantry"
    assert config.infantry.max_hp > 0
    assert config.infantry.damage > 0


def test_core_imports_without_pygame() -> None:
    assert "pygame" not in sys.modules


def test_missing_required_rule_field_has_clear_error(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    shutil.copytree(REPOSITORY_ROOT / "configs", config_root)
    rules_file = config_root / "rules" / "training-v0.yaml"
    rules_file.write_text(
        rules_file.read_text(encoding="utf-8").replace("  attack_range: 125\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"infantry\.attack_range"):
        load_match_config(config_root / "scenarios" / "first-steps.yaml")


def test_map_passability_and_obstacle_collision() -> None:
    game_map = GameMap(200, 120, [Rectangle(80, 30, 40, 60)], collision_radius=10)

    assert game_map.is_passable((30, 60))
    assert not game_map.is_passable((100, 60))
    assert not game_map.can_traverse((30, 60), (170, 60))


def test_a_star_routes_around_obstacle() -> None:
    game_map = GameMap(240, 180, [Rectangle(100, 40, 40, 100)], collision_radius=10)
    start = (30.0, 80.0)
    goal = (210.0, 80.0)

    path = find_path(game_map, start, goal)

    assert path is not None
    assert path[0] == start
    assert path[-1] == goal
    assert all(game_map.is_passable(point) for point in path)
    assert all(game_map.can_traverse(a, b) for a, b in zip(path, path[1:]))
    assert any(point[1] < 30 or point[1] > 150 for point in path)


def test_match_moves_robot_to_ordered_destination() -> None:
    base_config = load_match_config(default_scenario_path())
    config = replace(base_config, infantry=replace(base_config.infantry, attack_range=1))
    match = Match(config)
    robot = next(robot for robot in match.robots if robot.team == "tarsgo")
    start = robot.position
    goal = (680.0, 260.0)

    assert match.order_move(robot.id, goal)
    for _ in range(300):
        match.update(0.05)

    assert robot.position != start
    assert abs(robot.position[0] - goal[0]) < 1.5
    assert abs(robot.position[1] - goal[1]) < 1.5
    assert match.map.is_passable(robot.position)


def test_combat_damage_and_attack_cooldown() -> None:
    match = Match(load_match_config(default_scenario_path()))
    player, opponent = match.robots
    player.position = (300.0, 260.0)
    opponent.position = (360.0, 260.0)

    match.update(0.1)
    first_hp = (player.hp, opponent.hp)
    assert first_hp == (90, 90)
    assert player.attack_cooldown > 0
    assert opponent.attack_cooldown > 0

    match.update(0.2)
    assert (player.hp, opponent.hp) == first_hp

    match.update(0.6)
    assert player.hp < first_hp[0]
    assert opponent.hp < first_hp[1]


def test_match_ends_with_winner_when_robot_dies() -> None:
    match = Match(load_match_config(default_scenario_path()))
    player, opponent = match.robots
    player.position = (300.0, 260.0)
    opponent.position = (360.0, 260.0)
    opponent.hp = 10

    match.update(0.1)

    assert not opponent.alive
    assert match.finished
    assert match.winner == "tarsgo"


def test_reset_restores_match_state() -> None:
    match = Match(load_match_config(default_scenario_path()))
    player, opponent = match.robots
    player.position = (300.0, 260.0)
    opponent.position = (360.0, 260.0)
    opponent.hp = 10
    match.update(0.1)
    assert match.finished

    match.reset()

    assert not match.finished
    assert match.winner is None
    assert match.elapsed_time == 0
    assert match.robots[0].hp == match.robots[0].max_hp
    assert match.robots[0].position == (120.0, 260.0)
    assert match.robots[1].position == (780.0, 260.0)


def test_playable_vertical_slice_roundtrip() -> None:
    match = Match(load_match_config(default_scenario_path()))
    player, opponent = match.robots
    goal = (700.0, 260.0)

    assert match.order_move(player.id, goal)
    assert player.path
    assert all(match.map.can_traverse(a, b) for a, b in zip(player.path, player.path[1:]))

    start = player.position
    for _ in range(600):
        match.update(0.05)
        assert match.map.is_passable(player.position)
        if match.finished:
            break

    assert player.position != start
    assert not opponent.alive
    assert match.finished
    assert match.winner == "tarsgo"

    match.reset()
    assert not match.finished
    assert match.winner is None
    assert all(robot.hp == robot.max_hp for robot in match.robots)
    assert match.robots[0].position == (120.0, 260.0)
