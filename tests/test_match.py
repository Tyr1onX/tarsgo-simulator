from dataclasses import replace
import math
from pathlib import Path
import shutil
import sys

import pytest
import yaml

from tarsgo_simulator.core.combat import update_combat
from tarsgo_simulator.core.config import ConfigError, default_scenario_path, load_match_config
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.map import GameMap, Rectangle, Zone
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.pathfinding import find_path
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.registry import UnknownRuleSetError
from tarsgo_simulator.rules.training_v0 import TrainingV0Rules


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RULES_LAB_PATH = REPOSITORY_ROOT / "configs" / "scenarios" / "rmul-2026-rules-lab.yaml"
T1 = "tarsgo-infantry-1"
T2 = "tarsgo-infantry-2"
O1 = "opponent-infantry-1"
O2 = "opponent-infantry-2"
RMUL_HERO = "tarsgo-hero"
RMUL_INFANTRY = "tarsgo-infantry"
RMUL_SENTRY = "tarsgo-sentry"
RMUL_OPPONENT_HERO = "opponent-hero"
RMUL_OPPONENT_INFANTRY = "opponent-infantry"
RMUL_OPPONENT_SENTRY = "opponent-sentry"
RMUL_TARS_TEAM = "tarsgo-rmul-2026"
RMUL_OPPONENT_TEAM = "opponent-rmul-2026"


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _team_robots(match: Match, team_id: str) -> list[Robot]:
    return [robot for robot in match.robots if robot.team == team_id]


def _make_opponents_stationary_and_distant(match: Match) -> None:
    for robot_id, position in ((O1, (950.0, 50.0)), (O2, (950.0, 650.0))):
        robot = _robot(match, robot_id)
        robot.position = position
        robot.speed = 0.0


def _assert_no_robot_overlap(match: Match) -> None:
    minimum_distance = match.map.collision_radius * 2
    for index, first in enumerate(match.robots):
        for second in match.robots[index + 1 :]:
            assert math.dist(first.position, second.position) >= minimum_distance - 1e-8


def _keep_only(match: Match, *robot_ids: str) -> None:
    keep = set(robot_ids)
    for robot in match.robots:
        if robot.id not in keep:
            # This helper builds a fixture; avoid emitting in-match damage facts.
            robot.hp = 0
            robot.alive = False
            robot.path.clear()


def _copy_configs(tmp_path: Path) -> Path:
    config_root = tmp_path / "configs"
    shutil.copytree(REPOSITORY_ROOT / "configs", config_root)
    return config_root


def _open_field_match() -> Match:
    config = load_match_config(default_scenario_path())
    scenario = replace(
        config.scenario,
        map_width=1000,
        map_height=700,
        obstacles=(),
        spawns={
            T1: (120.0, 120.0),
            T2: (120.0, 520.0),
            O1: (780.0, 120.0),
            O2: (780.0, 520.0),
        },
    )
    return Match(replace(config, scenario=scenario))


def _rules_lab_match() -> Match:
    match = Match(load_match_config(RULES_LAB_PATH))
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0
    return match


def _zone_center(match: Match, zone_id: str) -> tuple[float, float]:
    zone = next(zone for zone in match.map.zones if zone.id == zone_id)
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _own_supply_center(match: Match, robot: Robot) -> tuple[float, float]:
    zone = match.ruleset._supply_zones[robot.team]
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _enemy_supply_center(match: Match, robot: Robot) -> tuple[float, float]:
    zone = match.ruleset._forbidden_zones[robot.team]
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _complete_rmul_respawn(match: Match, robot_id: str) -> Robot:
    robot = _robot(match, robot_id)
    match.apply_damage(robot, robot.hp)
    match.update(0.01)
    lifecycle = match.ruleset._robot_lifecycles[robot_id]
    assert lifecycle.respawn_required is not None
    match.update(lifecycle.respawn_required)
    return robot


def _write_scenario(tmp_path: Path, mutate) -> Path:
    config_root = _copy_configs(tmp_path)
    scenario_file = config_root / "scenarios" / "first-steps.yaml"
    data = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    mutate(data)
    scenario_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return scenario_file


def _short_wall_match() -> Match:
    config = load_match_config(default_scenario_path())
    scenario = replace(
        config.scenario,
        obstacles=(Rectangle(440, 200, 20, 120),),
        spawns={
            T1: (400.0, 260.0),
            T2: (120.0, 100.0),
            O1: (500.0, 260.0),
            O2: (780.0, 100.0),
        },
    )
    return Match(replace(config, scenario=scenario))


def _combat_robot(
    robot_id: str,
    team: str,
    position: tuple[float, float],
    *,
    cooldown: float = 0.0,
) -> Robot:
    return Robot(
        id=robot_id,
        team=team,
        position=position,
        hp=100,
        max_hp=100,
        speed=190,
        attack_range=125,
        attack_interval=0.75,
        damage=10,
        attack_cooldown=cooldown,
    )


def test_training_config_loads_two_infantry_per_team() -> None:
    config = load_match_config(default_scenario_path())
    match = Match(config)

    assert config.rule_document.metadata.id == "training-v0"
    assert isinstance(match.ruleset, TrainingV0Rules)
    assert [robot.id for robot in config.scenario.teams["red"].robots] == [T1, T2]
    assert [robot.id for robot in config.scenario.teams["blue"].robots] == [O1, O2]
    assert all(
        robot.type == "infantry"
        for team in config.scenario.teams.values()
        for robot in team.robots
    )
    assert match.ruleset.robot_parameters("infantry").max_hp > 0
    assert match.ruleset.robot_parameters("infantry").damage > 0
    assert len(match.robots) == 4
    assert config.scenario.player_controlled == frozenset({T1, T2})


def test_generic_team_loader_accepts_robot_types_without_rule_knowledge(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    team_file = config_root / "teams" / "tarsgo.yaml"
    team_data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    team_data["robots"][0]["type"] = "hero"
    team_data["robots"][1]["type"] = "sentry"
    team_file.write_text(yaml.safe_dump(team_data, sort_keys=False), encoding="utf-8")

    config = load_match_config(config_root / "scenarios" / "first-steps.yaml")

    assert [robot.type for robot in config.scenario.teams["red"].robots] == [
        "hero",
        "sentry",
    ]


def test_training_v0_rejects_hero_through_its_ruleset(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    team_file = config_root / "teams" / "tarsgo.yaml"
    team_data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    team_data["robots"][0]["type"] = "hero"
    team_file.write_text(yaml.safe_dump(team_data, sort_keys=False), encoding="utf-8")

    config = load_match_config(config_root / "scenarios" / "first-steps.yaml")
    with pytest.raises(ConfigError, match="training-v0 不支持机器人类型 `hero`"):
        Match(config)


@pytest.mark.parametrize(
    ("controlled", "message"),
    [
        ([], "非空字符串列表"),
        ([T1, T1], "必须唯一"),
        (["missing-robot"], "未配置的机器人"),
        ([O1], "只能包含 `player_team`"),
    ],
)
def test_scenario_validates_player_controlled_ids(
    tmp_path: Path, controlled: list[str], message: str
) -> None:
    scenario_file = _write_scenario(
        tmp_path, lambda data: data.__setitem__("player_controlled", controlled)
    )
    with pytest.raises(ConfigError, match=message):
        load_match_config(scenario_file)


def test_scenario_requires_explicit_player_controlled_ids(tmp_path: Path) -> None:
    scenario_file = _write_scenario(
        tmp_path, lambda data: data.pop("player_controlled")
    )
    with pytest.raises(ConfigError, match="缺少必要字段 `player_controlled`"):
        load_match_config(scenario_file)


def test_unknown_ruleset_id_fails_explicitly_without_fallback(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    scenario_file = config_root / "scenarios" / "first-steps.yaml"
    scenario_file.write_text(
        scenario_file.read_text(encoding="utf-8").replace(
            "rules: training-v0", "rules: unknown-ruleset"
        ),
        encoding="utf-8",
    )
    unsupported_rules = config_root / "rules" / "unknown-ruleset.yaml"
    unsupported_rules.write_text(
        (config_root / "rules" / "training-v0.yaml")
        .read_text(encoding="utf-8")
        .replace("id: training-v0", "id: unknown-ruleset"),
        encoding="utf-8",
    )

    config = load_match_config(scenario_file)
    with pytest.raises(UnknownRuleSetError, match=r"Unknown RuleSet id `unknown-ruleset`"):
        Match(config)


def test_generic_rule_loader_accepts_non_synthetic_status(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    rules_file = config_root / "rules" / "training-v0.yaml"
    rules_file.write_text(
        rules_file.read_text(encoding="utf-8").replace(
            "status: synthetic", "status: official"
        ),
        encoding="utf-8",
    )

    config = load_match_config(config_root / "scenarios" / "first-steps.yaml")
    assert config.rule_document.metadata.status == "official"
    with pytest.raises(ConfigError, match=r"training-v0 requires `status: synthetic`"):
        Match(config)


def test_core_imports_without_pygame() -> None:
    assert "pygame" not in sys.modules


def test_missing_required_rule_field_has_clear_error(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    rules_file = config_root / "rules" / "training-v0.yaml"
    rules_file.write_text(
        rules_file.read_text(encoding="utf-8").replace("  attack_range: 125\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"infantry\.attack_range"):
        Match(load_match_config(config_root / "scenarios" / "first-steps.yaml"))


def test_team_rejects_duplicate_robot_ids(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    team_file = config_root / "teams" / "tarsgo.yaml"
    team_file.write_text(
        team_file.read_text(encoding="utf-8").replace(T2, T1),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="同一队中重复"):
        load_match_config(config_root / "scenarios" / "first-steps.yaml")


def test_scenario_rejects_robot_ids_repeated_across_teams(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    team_file = config_root / "teams" / "opponent-balanced.yaml"
    team_file.write_text(
        team_file.read_text(encoding="utf-8").replace(O2, T1),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="全局唯一"):
        load_match_config(config_root / "scenarios" / "first-steps.yaml")


def test_scenario_requires_spawn_for_every_robot(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    scenario_file = config_root / "scenarios" / "first-steps.yaml"
    scenario_file.write_text(
        scenario_file.read_text(encoding="utf-8").replace(f"    {T2}: [120, 310]\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=T2):
        load_match_config(scenario_file)


def test_scenario_rejects_spawn_for_unknown_robot(tmp_path: Path) -> None:
    config_root = _copy_configs(tmp_path)
    scenario_file = config_root / "scenarios" / "first-steps.yaml"
    scenario_file.write_text(
        scenario_file.read_text(encoding="utf-8") + "    ghost: [400, 100]\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="未配置的机器人"):
        load_match_config(scenario_file)


def test_map_passability_and_obstacle_collision() -> None:
    game_map = GameMap(200, 120, [Rectangle(80, 30, 40, 60)], collision_radius=10)

    assert game_map.is_passable((30, 60))
    assert not game_map.is_passable((100, 60))
    assert not game_map.can_traverse((30, 60), (170, 60))


def test_line_of_sight_is_clear_on_an_empty_map() -> None:
    game_map = GameMap(300, 200, [], collision_radius=10)

    assert game_map.has_line_of_sight((30, 100), (270, 100))


def test_wall_blocks_line_of_sight_including_its_boundary() -> None:
    game_map = GameMap(300, 200, [Rectangle(130, 70, 40, 60)], collision_radius=10)

    assert not game_map.has_line_of_sight((30, 100), (270, 100))
    assert not game_map.has_line_of_sight((30, 70), (270, 70))


def test_line_of_sight_uses_wall_bounds_not_movement_inflation() -> None:
    game_map = GameMap(300, 200, [Rectangle(130, 100, 40, 40)], collision_radius=10)
    start, end = (30, 95), (270, 95)

    assert not game_map.can_traverse(start, end)
    assert game_map.has_line_of_sight(start, end)


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


def test_match_creates_four_separated_robots() -> None:
    match = Match(load_match_config(default_scenario_path()))

    assert len(match.robots) == 4
    assert len(_team_robots(match, "tarsgo")) == 2
    assert len(_team_robots(match, "opponent-balanced")) == 2
    assert len({robot.id for robot in match.robots}) == 4
    assert all(match.map.is_passable(robot.position) for robot in match.robots)
    assert all(
        math.dist(left.position, right.position) > match.map.collision_radius * 2
        for index, left in enumerate(match.robots)
        for right in match.robots[index + 1 :]
    )


def test_match_rejects_overlapping_robot_spawns_with_both_ids() -> None:
    config = load_match_config(default_scenario_path())
    spawns = dict(config.scenario.spawns)
    spawns[T2] = spawns[T1]
    invalid_config = replace(config, scenario=replace(config.scenario, spawns=spawns))

    with pytest.raises(ValueError, match=f"{T1}.*{T2}"):
        Match(invalid_config)


def test_robots_moving_toward_same_goal_do_not_overlap() -> None:
    match = _open_field_match()
    _make_opponents_stationary_and_distant(match)
    first, second = _robot(match, T1), _robot(match, T2)
    first.position = (400.0, 300.0)
    second.position = (600.0, 300.0)
    goal = (500.0, 300.0)

    assert match.order_move(T1, goal)
    assert match.order_move(T2, goal)
    for _ in range(100):
        match.update(0.05)
        _assert_no_robot_overlap(match)

    assert first.position != second.position
    assert math.dist(first.position, goal) < 50
    assert math.dist(second.position, goal) < 50
    assert first.path
    assert second.path


def _head_on_result(reverse_robots: bool) -> tuple[tuple[float, float], tuple[float, float]]:
    match = _open_field_match()
    _make_opponents_stationary_and_distant(match)
    first, second = _robot(match, T1), _robot(match, T2)
    first.position = (300.0, 300.0)
    second.position = (500.0, 300.0)
    assert match.order_move(T1, second.position)
    assert match.order_move(T2, first.position)
    if reverse_robots:
        match.robots.reverse()

    for _ in range(50):
        match.update(0.05)
        _assert_no_robot_overlap(match)
        assert first.position[0] <= second.position[0]
    return first.position, second.position


def test_head_on_robot_movement_is_fair_independent_of_robot_order() -> None:
    forward_order = _head_on_result(False)
    reverse_order = _head_on_result(True)

    assert reverse_order == forward_order
    assert forward_order[0][0] < forward_order[1][0]


def test_head_on_movement_cannot_pass_through_during_a_long_frame() -> None:
    match = _open_field_match()
    _make_opponents_stationary_and_distant(match)
    first, second = _robot(match, T1), _robot(match, T2)
    first.position = (300.0, 310.0)
    second.position = (500.0, 310.0)
    assert match.order_move(T1, second.position)
    assert match.order_move(T2, first.position)
    first_start, second_start = first.position, second.position
    first_path, second_path = list(first.path), list(second.path)

    match.update(1.0)

    assert first.position == first_start
    assert second.position == second_start
    assert first.path == first_path
    assert second.path == second_path


def test_stationary_robot_blocks_without_consuming_path_then_allows_motion() -> None:
    match = _open_field_match()
    _make_opponents_stationary_and_distant(match)
    moving, blocker = _robot(match, T1), _robot(match, T2)
    moving.position = (300.0, 310.0)
    blocker.position = (450.0, 310.0)
    assert match.order_move(T1, (700.0, 310.0))

    for _ in range(40):
        match.update(0.05)
        _assert_no_robot_overlap(match)

    blocked_position = moving.position
    blocked_path = list(moving.path)
    assert blocked_position[0] < blocker.position[0]
    assert moving.path
    match.update(0.1)
    assert moving.position == blocked_position
    assert moving.path == blocked_path

    moving.attack_cooldown = 0.8
    match.update(0.2)
    assert moving.attack_cooldown == pytest.approx(0.6)
    assert moving.position == blocked_position
    assert moving.path == blocked_path

    assert match.order_move(T2, (750.0, 310.0))
    for _ in range(40):
        match.update(0.05)
        _assert_no_robot_overlap(match)

    assert moving.position[0] > blocked_position[0]


def test_dead_robot_remains_a_collision_blocker() -> None:
    match = _open_field_match()
    _make_opponents_stationary_and_distant(match)
    moving, blocker = _robot(match, T1), _robot(match, T2)
    moving.position = (300.0, 300.0)
    blocker.position = (450.0, 300.0)
    blocker.hp = 0
    blocker.alive = False
    assert match.order_move(T1, (700.0, 300.0))

    for _ in range(40):
        match.update(0.05)
        _assert_no_robot_overlap(match)

    assert not blocker.alive
    assert moving.position[0] < blocker.position[0]
    assert moving.path


def test_combat_still_resolves_while_robot_is_physically_blocked() -> None:
    match = _open_field_match()
    _make_opponents_stationary_and_distant(match)
    player, blocker, opponent = _robot(match, T1), _robot(match, T2), _robot(match, O1)
    player.position = (300.0, 300.0)
    blocker.position = (330.0, 300.0)
    opponent.position = (240.0, 370.0)
    assert match.order_move(T1, (500.0, 300.0))
    player_start = player.position

    match.update(0.1)

    assert player.position == player_start
    assert player.path
    assert player.hp < player.max_hp
    assert opponent.hp < opponent.max_hp


def test_player_can_move_each_friendly_robot_independently() -> None:
    match = Match(load_match_config(default_scenario_path()))
    first = _robot(match, T1)
    second = _robot(match, T2)
    first_start, second_start = first.position, second.position

    assert match.order_move(T1, (200.0, 150.0))
    assert match.order_move(T2, (200.0, 370.0))
    assert not match.order_move(O1, (400.0, 200.0))
    assert first.path
    assert second.path

    for _ in range(10):
        match.update(0.05)

    assert first.position != first_start
    assert second.position != second_start
    assert match.map.is_passable(first.position)
    assert match.map.is_passable(second.position)


def _prepare_group_move(match: Match) -> tuple[Robot, Robot]:
    _make_opponents_stationary_and_distant(match)
    first, second = _robot(match, T1), _robot(match, T2)
    first.position = (100.0, 200.0)
    second.position = (100.0, 300.0)
    return first, second


def test_group_move_preserves_relative_goal_offsets() -> None:
    match = _open_field_match()
    first, second = _prepare_group_move(match)

    assert match.order_group_move([T1, T2], (500.0, 400.0))

    assert first.path[-1] == (500.0, 350.0)
    assert second.path[-1] == (500.0, 450.0)
    assert second.path[-1][0] - first.path[-1][0] == 0
    assert second.path[-1][1] - first.path[-1][1] == 100


def test_group_move_moves_both_robots_without_overlapping() -> None:
    match = _open_field_match()
    first, second = _prepare_group_move(match)
    first_start, second_start = first.position, second.position

    assert match.order_group_move([T1, T2], (500.0, 400.0))
    for _ in range(100):
        match.update(0.05)
        _assert_no_robot_overlap(match)

    assert first.position != first_start
    assert second.position != second_start
    assert math.dist(first.position, (500.0, 350.0)) <= 20
    assert math.dist(second.position, (500.0, 450.0)) <= 20


def test_group_move_failure_is_atomic_when_one_target_is_outside_map() -> None:
    match = _open_field_match()
    first, second = _prepare_group_move(match)
    first.position = (200.0, 300.0)
    second.position = (300.0, 300.0)
    first.path = [(200.0, 300.0), (240.0, 300.0)]
    second.path = [(300.0, 300.0), (340.0, 300.0)]
    old_paths = (list(first.path), list(second.path))

    assert not match.order_group_move([T1, T2], (950.0, 300.0))

    assert (first.path, second.path) == old_paths


def test_group_move_rejects_enemy_and_preserves_all_paths() -> None:
    match = _open_field_match()
    _make_opponents_stationary_and_distant(match)
    first, enemy = _robot(match, T1), _robot(match, O1)
    first.path = [(120.0, 120.0), (160.0, 120.0)]
    enemy.path = [(950.0, 50.0), (900.0, 50.0)]
    old_paths = (list(first.path), list(enemy.path))

    assert not match.order_group_move([T1, O1], (500.0, 300.0))

    assert (first.path, enemy.path) == old_paths


def test_group_move_rejects_dead_robot_without_moving_other_members() -> None:
    match = _open_field_match()
    first, second = _prepare_group_move(match)
    first.path = [(100.0, 200.0), (140.0, 200.0)]
    second.path = [(100.0, 300.0), (140.0, 300.0)]
    second.hp = 0
    second.alive = False
    second.path.clear()
    old_paths = (list(first.path), list(second.path))

    assert not match.order_group_move([T1, T2], (500.0, 400.0))

    assert (first.path, second.path) == old_paths


def test_group_move_is_independent_of_robot_id_input_order() -> None:
    forward = _open_field_match()
    reverse = _open_field_match()
    forward_robots = _prepare_group_move(forward)
    reverse_robots = _prepare_group_move(reverse)

    assert forward.order_group_move([T1, T2], (500.0, 400.0))
    assert reverse.order_group_move([T2, T1], (500.0, 400.0))

    assert [robot.path for robot in forward_robots] == [
        robot.path for robot in reverse_robots
    ]


def test_group_move_rejects_duplicate_ids_without_changing_paths() -> None:
    match = _open_field_match()
    first, second = _prepare_group_move(match)
    first.path = [(100.0, 200.0), (140.0, 200.0)]
    second.path = [(100.0, 300.0), (140.0, 300.0)]
    old_paths = (list(first.path), list(second.path))

    assert not match.order_group_move([T1, T1], (500.0, 400.0))

    assert (first.path, second.path) == old_paths


def test_group_move_rejects_unknown_robot_id_without_changing_paths() -> None:
    match = _open_field_match()
    first, second = _prepare_group_move(match)
    first.path = [(100.0, 200.0), (140.0, 200.0)]
    second.path = [(100.0, 300.0), (140.0, 300.0)]
    old_paths = (list(first.path), list(second.path))

    assert not match.order_group_move([T1, "missing-robot"], (500.0, 400.0))

    assert (first.path, second.path) == old_paths


def test_combat_damage_and_attack_cooldown() -> None:
    match = Match(load_match_config(default_scenario_path()))
    _keep_only(match, T1, O1)
    player, opponent = _robot(match, T1), _robot(match, O1)
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


def test_robots_in_range_do_not_damage_each_other_through_wall() -> None:
    match = _short_wall_match()
    _keep_only(match, T1, O1)
    player, opponent = _robot(match, T1), _robot(match, O1)
    assert math.dist(player.position, opponent.position) <= player.attack_range
    assert not match.map.has_line_of_sight(player.position, opponent.position)

    for _ in range(6):
        match.update(0.1)

    assert player.hp == player.max_hp
    assert opponent.hp == opponent.max_hp


def test_match_continues_when_one_robot_dies_and_ends_when_team_is_eliminated() -> None:
    match = Match(load_match_config(default_scenario_path()))
    match.apply_damage(_robot(match, T1), 100)
    match.update(0.01)

    assert not match.finished
    assert _robot(match, T2).alive

    match.apply_damage(_robot(match, T2), 100)
    match.update(0.01)

    assert match.finished
    assert match.winner == "opponent-balanced"


def test_match_time_winner_uses_total_remaining_team_hp() -> None:
    match = Match(load_match_config(default_scenario_path()))
    _robot(match, T1).hp = 80
    _robot(match, T2).hp = 40
    _robot(match, O1).hp = 50
    _robot(match, O2).hp = 60
    match.elapsed_time = match.time_limit - 0.01

    match.update(0.02)

    assert match.finished
    assert match.winner == "tarsgo"


@pytest.mark.parametrize("reverse_robots", [False, True])
def test_simultaneous_final_attacks_draw_independent_of_robot_order(
    reverse_robots: bool,
) -> None:
    match = Match(load_match_config(default_scenario_path()))
    _keep_only(match, T1, O1)
    player, opponent = _robot(match, T1), _robot(match, O1)
    player.position = (300.0, 260.0)
    opponent.position = (360.0, 260.0)
    player.hp = opponent.hp = 10
    player.attack_cooldown = opponent.attack_cooldown = 0.0
    if reverse_robots:
        match.robots.reverse()

    match.update(0.01)

    assert not player.alive
    assert not opponent.alive
    assert match.finished
    assert match.winner is None


def test_match_move_fight_and_reset_roundtrip() -> None:
    match = Match(load_match_config(default_scenario_path()))
    player = _robot(match, T1)
    start = player.position
    assert match.order_move(T1, (700.0, 210.0))

    for _ in range(30):
        match.update(0.05)
        assert all(match.map.is_passable(robot.position) for robot in match.robots)

    assert player.position != start
    assert match.map.is_passable(player.position)
    match.reset()
    assert len(match.robots) == 4
    assert _robot(match, T1).position == (120.0, 210.0)


def test_training_ruleset_restarts_with_match_reset() -> None:
    match = Match(load_match_config(default_scenario_path()))
    ruleset = match.ruleset
    match.apply_damage(_robot(match, T1), 100)
    match.apply_damage(_robot(match, T2), 100)
    match.update(0.01)
    assert match.finished

    match.reset()

    assert match.ruleset is ruleset
    assert not match.finished
    assert match.winner is None
    assert match.elapsed_time == 0.0
    assert all(robot.hp == robot.max_hp for robot in match.robots)


@pytest.mark.parametrize("reverse_robots", [False, True])
def test_combat_targets_nearest_enemy_independent_of_list_order(
    reverse_robots: bool,
) -> None:
    attacker = _combat_robot("attacker", "tarsgo", (100.0, 100.0))
    farther = _combat_robot("a-far", "opponent", (200.0, 100.0), cooldown=10)
    nearer = _combat_robot("z-near", "opponent", (150.0, 100.0), cooldown=10)
    robots = [attacker, farther, nearer]
    if reverse_robots:
        robots.reverse()
    hits = []

    update_combat(
        robots,
        GameMap(400, 300, [], collision_radius=10),
        can_attack=lambda robot: robot.alive,
        apply_damage=lambda target, damage, attacker: hits.append((target.id, damage)) or damage,
    )

    assert hits == [("z-near", 10)]


@pytest.mark.parametrize("reverse_robots", [False, True])
def test_combat_ties_choose_lexicographically_smallest_robot_id(
    reverse_robots: bool,
) -> None:
    attacker = _combat_robot("attacker", "tarsgo", (100.0, 100.0))
    later_id = _combat_robot("enemy-z", "opponent", (150.0, 100.0), cooldown=10)
    earlier_id = _combat_robot("enemy-a", "opponent", (100.0, 150.0), cooldown=10)
    robots = [attacker, later_id, earlier_id]
    if reverse_robots:
        robots.reverse()
    hits = []

    update_combat(
        robots,
        GameMap(400, 300, [], collision_radius=10),
        can_attack=lambda robot: robot.alive,
        apply_damage=lambda target, damage, attacker: hits.append((target.id, damage)) or damage,
    )

    assert hits == [("enemy-a", 10)]


def test_both_opponent_robots_move_with_independent_timers() -> None:
    match = Match(load_match_config(default_scenario_path()))
    starts = {robot.id: robot.position for robot in _team_robots(match, "opponent-balanced")}

    for _ in range(20):
        match.update(0.05)

    assert set(match._ai_replan_elapsed) == {O1, O2}
    assert all(_robot(match, robot_id).position != starts[robot_id] for robot_id in (O1, O2))
    assert all(0 <= elapsed < 0.5 for elapsed in match._ai_replan_elapsed.values())


def test_opponent_ai_timer_for_each_robot_advances_independently() -> None:
    match = _open_field_match()
    _robot(match, T1).position = (300.0, 120.0)
    _robot(match, O1).position = (400.0, 120.0)
    _robot(match, T2).position = (100.0, 520.0)
    _robot(match, O2).position = (800.0, 520.0)

    match.update(0.2)

    assert match._ai_replan_elapsed[O1] == 0.0
    assert match._ai_replan_elapsed[O2] == pytest.approx(0.2)


def test_opponent_ai_routes_around_obstacles_in_match_updates() -> None:
    match = Match(load_match_config(default_scenario_path()))
    previous = {robot.id: robot.position for robot in match.robots}

    for _ in range(100):
        match.update(0.05)
        for robot in match.robots:
            assert match.map.is_passable(robot.position)
            assert match.map.can_traverse(previous[robot.id], robot.position)
            previous[robot.id] = robot.position

    opponent = _robot(match, O1)
    player = _robot(match, T1)
    assert abs(opponent.position[1] - player.position[1]) > 1
    assert abs(opponent.position[0] - player.position[0]) < 660


def test_opponent_stops_near_player_to_attack() -> None:
    match = _open_field_match()
    _keep_only(match, T1, O1)
    player, opponent = _robot(match, T1), _robot(match, O1)

    for _ in range(300):
        match.update(0.02)
        if not opponent.path and math.dist(opponent.position, player.position) <= opponent.attack_range:
            break

    distance = math.dist(opponent.position, player.position)
    assert distance <= opponent.attack_range
    assert distance > 20
    assert not opponent.path


def test_opponent_replans_toward_moving_player() -> None:
    match = _open_field_match()
    _keep_only(match, T1, O1)
    player, opponent = _robot(match, T1), _robot(match, O1)

    for _ in range(20):
        match.update(0.05)
    old_target_y = player.position[1]
    old_opponent_y = opponent.position[1]
    assert opponent.position[0] < 780

    assert match.order_move(T1, (120.0, 300.0))
    for _ in range(100):
        match.update(0.05)

    assert player.position[1] > old_target_y
    assert opponent.position[1] > old_opponent_y


def test_opponent_does_not_stop_in_range_behind_wall() -> None:
    match = _short_wall_match()
    _keep_only(match, T1, O1)
    player, opponent = _robot(match, T1), _robot(match, O1)
    spawn = opponent.position

    assert math.dist(player.position, opponent.position) < opponent.attack_range
    assert not match.map.has_line_of_sight(opponent.position, player.position)

    match.update(0.5)

    assert opponent.position != spawn
    assert opponent.path
    assert match.map.is_passable(opponent.position)


def test_opponent_routes_around_wall_then_both_robots_fire() -> None:
    match = _short_wall_match()
    _keep_only(match, T1, O1)
    player, opponent = _robot(match, T1), _robot(match, O1)
    moved_around_wall = False

    for _ in range(400):
        previous = opponent.position
        match.update(0.05)
        assert match.map.is_passable(opponent.position)
        assert match.map.can_traverse(previous, opponent.position)
        moved_around_wall |= opponent.position[1] < 200 or opponent.position[1] > 320
        if player.hp < player.max_hp and opponent.hp < opponent.max_hp:
            break

    assert moved_around_wall
    assert match.map.has_line_of_sight(opponent.position, player.position)
    assert player.hp < player.max_hp
    assert opponent.hp < opponent.max_hp


def test_opponents_retarget_when_their_nearest_player_dies() -> None:
    match = _open_field_match()
    player1, player2 = _robot(match, T1), _robot(match, T2)
    opponent1, opponent2 = _robot(match, O1), _robot(match, O2)
    player1.position = (700.0, 120.0)
    player2.position = (500.0, 500.0)
    opponent1.position = (650.0, 120.0)
    opponent2.position = (650.0, 200.0)
    initial_distances = {
        O1: math.dist(opponent1.position, player2.position),
        O2: math.dist(opponent2.position, player2.position),
    }

    match.update(0.05)
    assert not match.finished
    match.apply_damage(player1, player1.hp)
    match.update(0.5)

    assert not match.finished
    assert player2.alive
    assert math.dist(opponent1.position, player2.position) < initial_distances[O1]
    assert math.dist(opponent2.position, player2.position) < initial_distances[O2]


def test_reset_restores_all_robots_and_ai_state() -> None:
    match = Match(load_match_config(default_scenario_path()))
    assert match.order_move(T1, (220.0, 150.0))
    for _ in range(15):
        match.update(0.05)
    match.apply_damage(_robot(match, T1), 30)
    match.apply_damage(_robot(match, T2), 100)
    match.apply_damage(_robot(match, O1), 20)
    match.update(0.05)

    match.reset()

    assert not match.finished
    assert match.winner is None
    assert len(match.robots) == 4
    for robot_id, spawn in match.config.scenario.spawns.items():
        robot = _robot(match, robot_id)
        assert robot.position == spawn
        assert robot.hp == robot.max_hp
        assert robot.alive
        assert not robot.path
    assert match._ai_replan_elapsed == {O1: 0.0, O2: 0.0}


def test_zone_contains_interior_exterior_and_inclusive_edges() -> None:
    zone = Zone("center", 10, 20, 30, 40)

    assert zone.contains((25, 40))
    assert zone.contains((10, 20))
    assert zone.contains((40, 60))
    assert not zone.contains((9.99, 40))
    assert not zone.contains((40, 60.01))


def test_training_scenario_without_zones_still_loads() -> None:
    config = load_match_config(default_scenario_path())

    assert config.scenario.zones == ()


def test_scenario_rejects_duplicate_zone_ids(tmp_path: Path) -> None:
    def add_duplicate_zones(data: dict) -> None:
        data["setup"]["map"]["zones"] = [
            {"id": "center", "x": 10, "y": 10, "width": 20, "height": 20},
            {"id": "center", "x": 40, "y": 10, "width": 20, "height": 20},
        ]

    with pytest.raises(ConfigError, match="区域 id `center` 重复"):
        load_match_config(_write_scenario(tmp_path, add_duplicate_zones))


def test_scenario_rejects_zone_outside_map(tmp_path: Path) -> None:
    def add_outside_zone(data: dict) -> None:
        map_width = data["setup"]["map"]["width"]
        data["setup"]["map"]["zones"] = [
            {"id": "outside", "x": map_width - 10, "y": 10, "width": 20, "height": 20}
        ]

    with pytest.raises(ConfigError, match="超出地图边界"):
        load_match_config(_write_scenario(tmp_path, add_outside_zone))


def test_match_emits_one_robot_destroyed_event_only_once() -> None:
    match = Match(load_match_config(default_scenario_path()))
    robot = _robot(match, T1)
    assert match.apply_damage(robot, robot.hp) == robot.max_hp
    assert match.apply_damage(robot, 10) == 0

    assert [(event.type, event.robot_id, event.team_id) for event in match.current_events] == [
        (MatchEventType.ROBOT_DAMAGED, T1, "tarsgo"),
        (MatchEventType.ROBOT_DESTROYED, T1, "tarsgo"),
    ]

    match.update(0.01)
    assert sum(
        event.type == MatchEventType.ROBOT_DESTROYED
        for event in match.current_events
    ) == 1

    match.update(0.01)
    assert match.current_events == []


def test_match_emits_all_same_frame_robot_destroyed_events() -> None:
    match = Match(load_match_config(default_scenario_path()))
    match.apply_damage(_robot(match, T1), _robot(match, T1).hp)
    match.apply_damage(_robot(match, O1), _robot(match, O1).hp)

    match.update(0.01)

    assert {
        (event.robot_id, event.team_id)
        for event in match.current_events
        if event.type == MatchEventType.ROBOT_DESTROYED
    } == {
        (T1, "tarsgo"),
        (O1, "opponent-balanced"),
    }


def test_match_reset_clears_current_events() -> None:
    match = Match(load_match_config(default_scenario_path()))
    match.apply_damage(_robot(match, T1), _robot(match, T1).hp)
    match.update(0.01)
    assert match.current_events

    match.reset()

    assert match.current_events == []


def test_rmul_rules_lab_initializes_victory_points_and_time_from_yaml() -> None:
    match = _rules_lab_match()
    rules_yaml = yaml.safe_load(
        (REPOSITORY_ROOT / "configs" / "rules" / "rmul-2026-3v3.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert match.time_limit == rules_yaml["match_duration"] == 300
    assert match.ruleset.victory_points == {
        team_id: rules_yaml["victory_points"]["initial"]
        for team_id in (RMUL_TARS_TEAM, RMUL_OPPONENT_TEAM)
    }
    assert match.ruleset.control_owner is None


def _write_rmul_configs(
    tmp_path: Path,
    *,
    mutate_scenario=None,
    mutate_tarsgo_team=None,
) -> Path:
    config_root = _copy_configs(tmp_path)
    scenario_file = config_root / "scenarios" / "rmul-2026-rules-lab.yaml"
    if mutate_scenario is not None:
        data = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
        mutate_scenario(data)
        scenario_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    if mutate_tarsgo_team is not None:
        team_file = config_root / "teams" / "tarsgo-rmul-2026.yaml"
        data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
        mutate_tarsgo_team(data)
        team_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return scenario_file


def test_rmul_rules_lab_uses_six_robot_hero_infantry_sentry_rosters() -> None:
    match = _rules_lab_match()
    expected = {"hero": 1, "infantry": 1, "sentry": 1}

    assert len(match.robots) == 6
    for team in match.config.scenario.teams.values():
        assert {
            robot_type: sum(robot.type == robot_type for robot in match.robots if robot.team == team.team_id)
            for robot_type in expected
        } == expected
    assert match.ruleset.robot_parameters("hero").max_hp == 350
    assert match.ruleset.robot_parameters("infantry").max_hp == 300
    assert match.ruleset.robot_parameters("sentry").max_hp == 400
    assert match.ruleset.robot_parameters("sentry").move_speed == 190


@pytest.mark.parametrize("roster_error", ["missing-hero", "two-infantry", "missing-sentry"])
def test_rmul_ruleset_rejects_incomplete_or_duplicate_rosters(
    tmp_path: Path, roster_error: str
) -> None:
    def mutate_team(data: dict) -> None:
        robots = data["robots"]
        if roster_error == "missing-hero":
            robots[:] = [robot for robot in robots if robot["type"] != "hero"]
        elif roster_error == "two-infantry":
            robots[0]["type"] = "infantry"
        else:
            robots[:] = [robot for robot in robots if robot["type"] != "sentry"]

    def mutate_scenario(data: dict) -> None:
        if roster_error == "missing-hero":
            data["player_controlled"].remove(RMUL_HERO)
            data["setup"]["spawns"].pop(RMUL_HERO)
        elif roster_error == "missing-sentry":
            data["setup"]["spawns"].pop(RMUL_SENTRY)

    scenario_file = _write_rmul_configs(
        tmp_path,
        mutate_scenario=mutate_scenario,
        mutate_tarsgo_team=mutate_team,
    )
    config = load_match_config(scenario_file)

    with pytest.raises(ConfigError, match="恰好包含 1 hero、1 infantry、1 sentry"):
        Match(config)


def test_rmul_sentry_must_remain_ai_controlled(tmp_path: Path) -> None:
    scenario_file = _write_rmul_configs(
        tmp_path,
        mutate_scenario=lambda data: data["player_controlled"].append(RMUL_SENTRY),
    )
    with pytest.raises(ConfigError, match="sentry 必须由 AI 控制"):
        Match(load_match_config(scenario_file))


def test_rmul_direct_control_and_group_move_permissions() -> None:
    match = _rules_lab_match()
    assert match.config.scenario.player_controlled == frozenset(
        {RMUL_HERO, RMUL_INFANTRY}
    )
    assert match.is_player_controlled(RMUL_HERO)
    assert match.is_player_controlled(RMUL_INFANTRY)
    assert not match.is_player_controlled(RMUL_SENTRY)
    assert not match.is_player_controlled(RMUL_OPPONENT_HERO)

    assert match.order_move(RMUL_HERO, (180.0, 190.0))
    assert match.order_move(RMUL_INFANTRY, (180.0, 260.0))
    assert not match.order_move(RMUL_SENTRY, (180.0, 330.0))

    assert match.order_group_move([RMUL_HERO, RMUL_INFANTRY], (220.0, 225.0))
    hero_path = [(300.0, 300.0)]
    sentry_path = [(320.0, 330.0)]
    _robot(match, RMUL_HERO).path = list(hero_path)
    _robot(match, RMUL_SENTRY).path = list(sentry_path)
    assert not match.order_group_move([RMUL_HERO, RMUL_SENTRY], (260.0, 260.0))
    assert _robot(match, RMUL_HERO).path == hero_path
    assert _robot(match, RMUL_SENTRY).path == sentry_path


def test_rmul_ai_controls_sentry_and_each_opponent_independently() -> None:
    match = _rules_lab_match()
    starts = {robot.id: robot.position for robot in match.robots}

    assert set(match._ai_replan_elapsed) == {
        RMUL_SENTRY,
        RMUL_OPPONENT_HERO,
        RMUL_OPPONENT_INFANTRY,
        RMUL_OPPONENT_SENTRY,
    }
    for robot in match.robots:
        robot.speed = match.ruleset.robot_parameters(robot.type).move_speed
    match.update(0.5)

    for robot_id in match._ai_replan_elapsed:
        assert _robot(match, robot_id).position != starts[robot_id]
        assert match._ai_replan_elapsed[robot_id] == 0.0


def test_ai_robot_targets_nearest_enemy_and_never_a_teammate() -> None:
    match = _rules_lab_match()
    sentry = _robot(match, RMUL_SENTRY)
    sentry.position = (350.0, 260.0)
    _robot(match, RMUL_HERO).position = (340.0, 260.0)
    nearest_enemy = _robot(match, RMUL_OPPONENT_SENTRY)
    nearest_enemy.position = (600.0, 260.0)
    _robot(match, RMUL_OPPONENT_HERO).position = (800.0, 130.0)
    _robot(match, RMUL_OPPONENT_INFANTRY).position = (800.0, 390.0)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0

    match.update(0.5)

    assert sentry.path[-1] == nearest_enemy.position

    _robot(match, RMUL_OPPONENT_HERO).position = (550.0, 260.0)
    _robot(match, RMUL_OPPONENT_INFANTRY).position = (150.0, 260.0)
    _robot(match, RMUL_OPPONENT_SENTRY).position = (800.0, 390.0)
    match.update(0.5)

    assert sentry.path[-1] == _robot(match, RMUL_OPPONENT_HERO).position


def test_opponent_ai_can_target_autonomous_player_sentry() -> None:
    match = _rules_lab_match()
    opponent = _robot(match, RMUL_OPPONENT_HERO)
    sentry = _robot(match, RMUL_SENTRY)
    opponent.position = (600.0, 260.0)
    sentry.position = (450.0, 260.0)
    _robot(match, RMUL_HERO).position = (100.0, 100.0)
    _robot(match, RMUL_INFANTRY).position = (100.0, 430.0)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0

    match.update(0.5)

    assert opponent.path[-1] == sentry.position


def test_desktop_selection_excludes_sentry_and_opponents() -> None:
    pygame = pytest.importorskip("pygame")
    from tarsgo_simulator.desktop.app import (
        _select_player_robot,
        _select_player_robots_in_rectangle,
        _viewport_for_match,
    )

    match = _rules_lab_match()
    viewport = _viewport_for_match(match)
    hero = _robot(match, RMUL_HERO)
    sentry = _robot(match, RMUL_SENTRY)
    assert _select_player_robot(hero.position, match) == RMUL_HERO
    assert _select_player_robot(sentry.position, match) is None
    all_map = pygame.Rect(0, 0, 1100, 780)
    assert _select_player_robots_in_rectangle(all_map, match, viewport) == {
        RMUL_HERO,
        RMUL_INFANTRY,
    }


def test_rmul_sentry_respawn_uses_shared_lifecycle_and_supply_release() -> None:
    match = _rules_lab_match()
    sentry = _robot(match, RMUL_SENTRY)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0

    _complete_rmul_respawn(match, RMUL_SENTRY)
    lifecycle = match.ruleset._robot_lifecycles[RMUL_SENTRY]

    assert sentry.alive
    assert sentry.hp == 80
    assert lifecycle.death_count == 1
    assert lifecycle.weak
    assert lifecycle.invincible_remaining == 30
    assert match.ruleset.victory_points[RMUL_TARS_TEAM] == 180
    match.update(0.01)
    assert not lifecycle.weak
    assert lifecycle.invincible_remaining == 0


def test_rmul_sentry_red_card_prevents_respawn() -> None:
    match = _rules_lab_match()
    sentry, _ = _prepare_rmul_forbidden_zone(match, RMUL_SENTRY)

    match.update(23.1)

    penalty = match.ruleset._robot_penalties[RMUL_SENTRY]
    lifecycle = match.ruleset._robot_lifecycles[RMUL_SENTRY]
    assert penalty.disqualified
    assert not sentry.alive
    assert lifecycle.respawn_required is None
    match.update(30.0)
    assert not sentry.alive
    assert lifecycle.respawn_required is None


def _prepare_rmul_forbidden_zone(
    match: Match, offender_id: str = RMUL_HERO
) -> tuple[Robot, Robot]:
    offender = _robot(match, offender_id)
    teammate = next(
        robot for robot in _team_robots(match, offender.team) if robot is not offender
    )
    offender.position = _enemy_supply_center(match, offender)
    teammate.position = (600.0, 700.0)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0
        robot.path.clear()
    return offender, teammate


def test_rmul_yellow_card_requires_more_than_three_seconds_and_attributes_damage() -> None:
    match = _rules_lab_match()
    offender, teammate = _prepare_rmul_forbidden_zone(match)

    match.update(3.0)
    assert match.ruleset._robot_penalties[RMUL_HERO].yellow_cards == 0
    assert offender.hp == offender.max_hp

    match.update(0.01)

    assert match.ruleset._robot_penalties[RMUL_HERO].yellow_cards == 1
    assert offender.hp == 297
    assert teammate.hp == 285
    sentry = _robot(match, RMUL_SENTRY)
    assert sentry.hp == 381
    assert match.ruleset.attack_damage_by_team == {
        RMUL_TARS_TEAM: 0,
        RMUL_OPPONENT_TEAM: 88,
    }
    assert dict(match.ruleset.display_state.robot_statuses)[RMUL_HERO].startswith(
        "Y1 FORB"
    )
    damage = [
        event for event in match.current_events
        if event.type == MatchEventType.ROBOT_DAMAGED
    ]
    assert {(event.robot_id, event.attacker_team_id, event.damage) for event in damage} == {
        (RMUL_HERO, RMUL_OPPONENT_TEAM, 53),
        (RMUL_INFANTRY, RMUL_OPPONENT_TEAM, 15),
        (RMUL_SENTRY, RMUL_OPPONENT_TEAM, 20),
    }


def test_rmul_yellow_cards_repeat_every_ten_seconds_then_third_is_red() -> None:
    match = _rules_lab_match()
    offender, teammate = _prepare_rmul_forbidden_zone(match)

    match.update(3.01)
    assert offender.hp == 297
    match.update(9.99)
    assert match.ruleset._robot_penalties[RMUL_HERO].yellow_cards == 1
    match.update(0.01)
    assert match.ruleset._robot_penalties[RMUL_HERO].yellow_cards == 2
    assert offender.hp == 192
    assert teammate.hp == 270

    match.update(10.0)

    penalty = match.ruleset._robot_penalties[RMUL_HERO]
    lifecycle = match.ruleset._robot_lifecycles[RMUL_HERO]
    assert penalty.yellow_cards == 3
    assert penalty.disqualified
    assert dict(match.ruleset.display_state.robot_statuses)[RMUL_HERO] == "RED"
    assert not offender.alive
    assert offender.hp == 0
    assert not offender.path
    assert lifecycle.respawn_required is None
    assert match.ruleset.victory_points[RMUL_TARS_TEAM] == 180
    assert teammate.hp == 255
    assert match.ruleset.attack_damage_by_team == {
        RMUL_TARS_TEAM: 0,
        RMUL_OPPONENT_TEAM: 455,
    }


def test_rmul_yellow_damage_leaves_low_hp_robots_at_one_and_alive() -> None:
    match = _rules_lab_match()
    offender, teammate = _prepare_rmul_forbidden_zone(match)
    offender.hp = 10
    teammate.hp = 2

    match.update(3.01)

    assert offender.hp == teammate.hp == 1
    assert offender.alive and teammate.alive
    assert not any(
        event.type == MatchEventType.ROBOT_DESTROYED
        and event.robot_id in {offender.id, teammate.id}
        for event in match.current_events
    )
    assert match.ruleset.attack_damage_by_team[RMUL_OPPONENT_TEAM] == 30


def test_rmul_yellow_repeat_percentage_returns_to_base_after_thirty_seconds() -> None:
    match = _rules_lab_match()
    offender, teammate = _prepare_rmul_forbidden_zone(match)
    match.update(3.01)
    assert offender.hp == 297

    offender.position = (600.0, 700.0)
    match.update(30.1)
    offender.position = _enemy_supply_center(match, offender)
    match.update(3.01)

    assert match.ruleset._robot_penalties[RMUL_HERO].yellow_cards == 2
    assert offender.hp == 244
    assert teammate.hp == 270
    assert match.ruleset.attack_damage_by_team[RMUL_OPPONENT_TEAM] == 176


def test_rmul_large_update_and_small_updates_apply_same_forbidden_zone_cards() -> None:
    large = _rules_lab_match()
    small = _rules_lab_match()
    large_offender, large_teammate = _prepare_rmul_forbidden_zone(large)
    small_offender, small_teammate = _prepare_rmul_forbidden_zone(small)

    large.update(23.1)
    for _ in range(231):
        small.update(0.1)

    assert large.ruleset._robot_penalties[RMUL_HERO] == small.ruleset._robot_penalties[RMUL_HERO]
    assert (large_offender.hp, large_teammate.hp) == (
        small_offender.hp,
        small_teammate.hp,
    ) == (0, 255)
    assert large.ruleset.attack_damage_by_team == small.ruleset.attack_damage_by_team
    assert large.ruleset.victory_points == small.ruleset.victory_points


def test_rmul_red_card_disables_opponent_ai_and_respawn() -> None:
    match = _rules_lab_match()
    opponent, _ = _prepare_rmul_forbidden_zone(match, RMUL_OPPONENT_HERO)
    _robot(match, RMUL_HERO).position = (500.0, 450.0)

    match.update(23.1)
    assert match.ruleset._robot_penalties[RMUL_OPPONENT_HERO].disqualified
    assert not opponent.alive
    assert not opponent.path
    assert not any(
        event.type == MatchEventType.ROBOT_DAMAGED and event.attacker_id == RMUL_OPPONENT_HERO
        for event in match.current_events
    )
    assert match.ruleset.victory_points[RMUL_OPPONENT_TEAM] == 180

    position_after_red = opponent.position
    match.update(6.0)

    assert not opponent.alive
    assert opponent.position == position_after_red
    assert not opponent.path
    assert match.ruleset._robot_lifecycles[RMUL_OPPONENT_HERO].respawn_required is None
    assert match.ruleset.victory_points[RMUL_OPPONENT_TEAM] == 180


def test_rmul_leaving_enemy_supply_resets_only_continuous_violation_timer() -> None:
    match = _rules_lab_match()
    offender, _ = _prepare_rmul_forbidden_zone(match)
    match.update(2.0)
    state = match.ruleset._robot_penalties[RMUL_HERO]
    assert state.forbidden_elapsed == pytest.approx(2.0)

    offender.position = (600.0, 700.0)
    match.update(0.1)
    assert state.forbidden_elapsed == 0.0
    assert state.next_yellow_at == 3.0
    match.update(2.0)
    offender.position = _enemy_supply_center(match, offender)
    match.update(2.0)

    assert state.yellow_cards == 0
    assert state.forbidden_elapsed == pytest.approx(2.0)


def test_rmul_death_stops_violation_timer_but_keeps_yellow_count() -> None:
    match = _rules_lab_match()
    offender, _ = _prepare_rmul_forbidden_zone(match)
    match.update(3.01)
    state = match.ruleset._robot_penalties[RMUL_HERO]
    assert state.yellow_cards == 1

    match.apply_damage(offender, offender.hp, source_team_id=RMUL_OPPONENT_TEAM)
    match.update(0.01)
    assert not offender.alive
    assert state.forbidden_elapsed == 0.0
    assert state.yellow_cards == 1

    lifecycle = match.ruleset._robot_lifecycles[RMUL_HERO]
    match.update(lifecycle.respawn_required or 5.0)
    assert offender.alive
    assert state.forbidden_elapsed == 0.0
    match.update(0.1)
    assert state.yellow_cards == 1
    assert state.forbidden_elapsed == pytest.approx(0.1)


def test_rmul_enemy_supply_zone_remains_pathable_and_robot_can_enter() -> None:
    match = _rules_lab_match()
    robot = _robot(match, RMUL_HERO)
    robot.position = (800.0, 400.0)
    robot.speed = 100.0
    _robot(match, RMUL_INFANTRY).position = (300.0, 700.0)
    _robot(match, RMUL_OPPONENT_HERO).position = (1100.0, 650.0)
    _robot(match, RMUL_OPPONENT_INFANTRY).position = (950.0, 700.0)
    target = _enemy_supply_center(match, robot)

    assert match.order_move(RMUL_HERO, target)
    assert robot.path
    assert robot.path[-1] == target
    assert match.map.is_passable(target)
    for _ in range(40):
        match.update(0.1)
        if match.ruleset._forbidden_zones[robot.team].contains(robot.position):
            break
    assert match.ruleset._forbidden_zones[robot.team].contains(robot.position)
    assert match.ruleset._robot_penalties[RMUL_HERO].forbidden_elapsed > 0


def test_rmul_player_red_card_cannot_be_moved_or_group_moved_and_reset_clears_state() -> None:
    match = _rules_lab_match()
    offender, _ = _prepare_rmul_forbidden_zone(match)
    match.update(23.1)

    state = match.ruleset._robot_penalties[RMUL_HERO]
    assert state.disqualified
    assert not offender.alive
    assert offender.hp == 0
    assert not offender.path
    assert not match.order_move(RMUL_HERO, (400.0, 260.0))
    assert not match.order_group_move([RMUL_HERO, RMUL_INFANTRY], (400.0, 260.0))

    match.reset()

    reset_offender = _robot(match, RMUL_HERO)
    reset_state = match.ruleset._robot_penalties[RMUL_HERO]
    assert reset_offender.alive
    assert reset_offender.hp == reset_offender.max_hp
    assert not reset_offender.path
    assert reset_state.yellow_cards == 0
    assert reset_state.last_yellow_time is None
    assert reset_state.last_yellow_fraction == 0.0
    assert not reset_state.disqualified
    assert reset_state.forbidden_elapsed == 0.0
    assert reset_state.next_yellow_at == 3.0
    assert match.ruleset.attack_damage_by_team == {
        RMUL_TARS_TEAM: 0,
        RMUL_OPPONENT_TEAM: 0,
    }


def test_training_rules_do_not_apply_rmul_supply_zone_penalties() -> None:
    match = Match(load_match_config(default_scenario_path()))
    offender = _robot(match, T1)
    offender.position = (790.0, 260.0)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0

    match.update(30.0)

    assert offender.hp == offender.max_hp
    assert not hasattr(match.ruleset, "_robot_penalties")


def test_rmul_robot_destroyed_penalty_applies_to_owning_team() -> None:
    match = _rules_lab_match()
    match.apply_damage(_robot(match, RMUL_HERO), _robot(match, RMUL_HERO).hp)

    match.update(0.01)

    assert match.ruleset.victory_points == {RMUL_TARS_TEAM: 180, RMUL_OPPONENT_TEAM: 200}


def test_rmul_multiple_robot_deaths_apply_each_penalty_in_same_frame() -> None:
    match = _rules_lab_match()
    for robot_id in (RMUL_HERO, RMUL_INFANTRY, RMUL_OPPONENT_HERO):
        robot = _robot(match, robot_id)
        match.apply_damage(robot, robot.hp)

    match.update(0.01)

    assert match.ruleset.victory_points == {RMUL_TARS_TEAM: 160, RMUL_OPPONENT_TEAM: 180}
    assert len(match.current_events) == 6


def test_rmul_simultaneous_deaths_penalize_both_teams() -> None:
    match = _rules_lab_match()
    for robot_id in (RMUL_HERO, RMUL_OPPONENT_HERO):
        robot = _robot(match, robot_id)
        match.apply_damage(robot, robot.hp)

    match.update(0.01)

    assert match.ruleset.victory_points == {RMUL_TARS_TEAM: 180, RMUL_OPPONENT_TEAM: 180}
    assert len(match.current_events) == 4


def test_rmul_reaching_zero_vp_ends_match_immediately() -> None:
    match = _rules_lab_match()
    match.ruleset.victory_points[RMUL_TARS_TEAM] = 20
    match.apply_damage(_robot(match, RMUL_HERO), _robot(match, RMUL_HERO).hp)

    match.update(0.01)

    assert match.ruleset.victory_points[RMUL_TARS_TEAM] == 0
    assert match.finished
    assert match.winner == RMUL_OPPONENT_TEAM


def test_rmul_control_capture_and_integer_second_scoring() -> None:
    match = _rules_lab_match()
    _robot(match, RMUL_HERO).position = _zone_center(match, "center-control")

    match.update(0.0)
    assert match.ruleset.control_owner == RMUL_TARS_TEAM
    assert match.ruleset.victory_points[RMUL_OPPONENT_TEAM] == 200

    match.update(0.99)
    assert match.ruleset.victory_points[RMUL_OPPONENT_TEAM] == 200
    match.update(0.02)
    assert match.ruleset.victory_points[RMUL_OPPONENT_TEAM] == 199
    match.update(2.4)
    assert match.ruleset.victory_points[RMUL_OPPONENT_TEAM] == 197


def _simultaneous_zone_claim(reverse_robots: bool) -> tuple[str | None, dict[str, int]]:
    match = _rules_lab_match()
    control_x, control_y = _zone_center(match, "center-control")
    _robot(match, RMUL_HERO).position = (control_x - 20.0, control_y - 20.0)
    _robot(match, RMUL_OPPONENT_HERO).position = (control_x + 20.0, control_y + 20.0)
    if reverse_robots:
        match.robots.reverse()

    match.update(0.0)
    first_owner = match.ruleset.control_owner
    match.update(0.1)

    assert match.ruleset.control_owner == first_owner
    return match.ruleset.control_owner, dict(match.ruleset.victory_points)


def test_rmul_simultaneous_zone_claim_is_deterministic_and_order_independent() -> None:
    forward = _simultaneous_zone_claim(False)
    reverse = _simultaneous_zone_claim(True)

    assert forward == reverse
    assert forward[0] == RMUL_OPPONENT_TEAM


def test_rmul_owner_keeps_zone_during_two_second_loss_delay_then_opponent_claims() -> None:
    match = _rules_lab_match()
    _robot(match, RMUL_HERO).position = _zone_center(match, "center-control")
    match.update(0.01)
    assert match.ruleset.control_owner == RMUL_TARS_TEAM

    _robot(match, RMUL_HERO).position = (400.0, 400.0)
    match.update(1.5)
    assert match.ruleset.control_owner == RMUL_TARS_TEAM
    match.update(0.49)
    assert match.ruleset.control_owner == RMUL_TARS_TEAM
    match.update(0.02)
    assert match.ruleset.control_owner is None

    _robot(match, RMUL_OPPONENT_HERO).position = _zone_center(match, "center-control")
    match.update(0.01)
    assert match.ruleset.control_owner == RMUL_OPPONENT_TEAM


def test_rmul_reset_restores_victory_points_and_control_state() -> None:
    match = _rules_lab_match()
    _robot(match, RMUL_HERO).position = _zone_center(match, "center-control")
    match.update(0.01)
    match.update(1.0)
    assert match.ruleset.control_owner == RMUL_TARS_TEAM
    assert match.ruleset.victory_points[RMUL_OPPONENT_TEAM] == 199

    match.reset()

    assert match.elapsed_time == 0
    assert not match.finished
    assert match.ruleset.control_owner is None
    assert match.ruleset.victory_points == {RMUL_TARS_TEAM: 200, RMUL_OPPONENT_TEAM: 200}


def test_rmul_reset_restores_all_six_robot_and_ai_rule_states() -> None:
    match = _rules_lab_match()
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0
    _robot(match, RMUL_HERO).position = _zone_center(match, "center-control")
    match.update(0.01)
    assert match.ruleset.control_owner == RMUL_TARS_TEAM

    _prepare_rmul_forbidden_zone(match, RMUL_HERO)
    match.update(3.01)
    assert match.ruleset._robot_penalties[RMUL_HERO].yellow_cards == 1
    _robot(match, RMUL_HERO).position = _zone_center(match, "center-control")
    match.update(0.01)
    sentry = _robot(match, RMUL_SENTRY)
    match.apply_damage(sentry, sentry.hp)
    match.update(0.01)
    match.update(1.0)
    assert match.ruleset._robot_lifecycles[RMUL_SENTRY].respawn_progress == 1
    assert match.order_move(RMUL_INFANTRY, (180.0, 260.0))

    match.reset()

    assert len(match.robots) == 6
    for robot_id, spawn in match.config.scenario.spawns.items():
        robot = _robot(match, robot_id)
        assert robot.position == spawn
        assert robot.hp == robot.max_hp
        assert robot.alive
        assert robot.path == []
    assert match._ai_replan_elapsed == {
        RMUL_SENTRY: 0.0,
        RMUL_OPPONENT_HERO: 0.0,
        RMUL_OPPONENT_INFANTRY: 0.0,
        RMUL_OPPONENT_SENTRY: 0.0,
    }
    assert set(match.ruleset._robot_lifecycles) == set(match.config.scenario.spawns)
    assert set(match.ruleset._robot_penalties) == set(match.config.scenario.spawns)
    assert all(state.yellow_cards == 0 for state in match.ruleset._robot_penalties.values())
    assert all(state.death_count == 0 for state in match.ruleset._robot_lifecycles.values())
    assert match.ruleset.victory_points == {
        RMUL_TARS_TEAM: 200,
        RMUL_OPPONENT_TEAM: 200,
    }
    assert match.ruleset.control_owner is None
    assert match.ruleset.attack_damage_by_team == {
        RMUL_TARS_TEAM: 0,
        RMUL_OPPONENT_TEAM: 0,
    }


def test_rmul_timeout_vp_and_damage_tie_uses_total_remaining_hp() -> None:
    match = _rules_lab_match()
    _robot(match, RMUL_HERO).hp = 1
    _robot(match, RMUL_INFANTRY).hp = 1
    _robot(match, RMUL_OPPONENT_HERO).hp = 100
    _robot(match, RMUL_OPPONENT_INFANTRY).hp = 100
    match.elapsed_time = match.time_limit - 0.01

    match.update(0.02)

    assert match.finished
    assert match.winner == RMUL_OPPONENT_TEAM


def test_rmul_timeout_attack_damage_breaks_vp_tie_before_hp() -> None:
    match = _rules_lab_match()
    _robot(match, RMUL_HERO).hp = 1
    _robot(match, RMUL_INFANTRY).hp = 1
    _robot(match, RMUL_OPPONENT_HERO).hp = 100
    _robot(match, RMUL_OPPONENT_INFANTRY).hp = 100
    match.ruleset.attack_damage_by_team.update(
        {RMUL_TARS_TEAM: 12, RMUL_OPPONENT_TEAM: 11}
    )
    match.elapsed_time = match.time_limit - 0.01

    match.update(0.02)

    assert match.finished
    assert match.winner == RMUL_TARS_TEAM


def test_rmul_timeout_draws_when_vp_damage_and_total_hp_all_tie() -> None:
    match = _rules_lab_match()
    for robot in match.robots:
        robot.hp = 50
    match.elapsed_time = match.time_limit - 0.01

    match.update(0.02)

    assert match.finished
    assert match.winner is None


def test_rmul_timeout_vp_takes_priority_over_damage_and_hp() -> None:
    match = _rules_lab_match()
    match.ruleset.victory_points.update({RMUL_TARS_TEAM: 150, RMUL_OPPONENT_TEAM: 151})
    match.ruleset.attack_damage_by_team.update(
        {RMUL_TARS_TEAM: 100, RMUL_OPPONENT_TEAM: 1}
    )
    _robot(match, RMUL_HERO).hp = _robot(match, RMUL_INFANTRY).hp = 1
    match.elapsed_time = match.time_limit - 0.01

    match.update(0.02)

    assert match.finished
    assert match.winner == RMUL_OPPONENT_TEAM


def test_rmul_supply_healing_is_per_robot_and_slice_invariant() -> None:
    whole = _rules_lab_match()
    sliced = _rules_lab_match()
    for match in (whole, sliced):
        _robot(match, RMUL_HERO).position = (80.0, 300.0)
        _robot(match, RMUL_INFANTRY).position = (200.0, 500.0)
        _robot(match, RMUL_HERO).hp = 50
        _robot(match, RMUL_INFANTRY).hp = 50

    whole.update(1.0)
    for _ in range(10):
        sliced.update(0.1)

    for match in (whole, sliced):
        assert _robot(match, RMUL_HERO).hp == 137
        assert _robot(match, RMUL_INFANTRY).hp == 125
    assert [robot.hp for robot in whole.robots] == [robot.hp for robot in sliced.robots]


def test_rmul_supply_healing_clears_fraction_on_leaving_and_at_full_hp() -> None:
    match = _rules_lab_match()
    robot = _robot(match, RMUL_HERO)
    lifecycle = match.ruleset._robot_lifecycles[RMUL_HERO]
    robot.position = _own_supply_center(match, robot)
    robot.hp = 50
    match.update(0.01)
    assert lifecycle.healing_hp_fraction == pytest.approx(0.875)

    robot.position = (450.0, 260.0)
    match.update(0.0)
    assert lifecycle.healing_hp_fraction == 0
    robot.position = _own_supply_center(match, robot)
    match.update(0.03)
    assert robot.hp == 52
    assert lifecycle.healing_hp_fraction == pytest.approx(0.625)

    robot.hp = robot.max_hp - 1
    lifecycle.healing_hp_fraction = 0
    match.update(0.1)
    assert robot.hp == robot.max_hp
    assert lifecycle.healing_hp_fraction == 0
    robot.hp -= 1
    match.update(0.02)
    assert robot.hp == robot.max_hp
    assert lifecycle.healing_hp_fraction == 0


def test_rmul_counts_only_actual_hp_lost_as_attack_damage() -> None:
    match = _rules_lab_match()
    attacker, target = _robot(match, RMUL_HERO), _robot(match, RMUL_OPPONENT_HERO)
    attacker.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    target.hp = 5
    attacker.attack_cooldown = 0
    target.attack_cooldown = 999
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1

    match.update(0.01)

    damage_events = [
        event for event in match.current_events
        if event.type == MatchEventType.ROBOT_DAMAGED
    ]
    assert len(damage_events) == 1
    assert damage_events[0].attacker_id == RMUL_HERO
    assert damage_events[0].attacker_team_id == RMUL_TARS_TEAM
    assert damage_events[0].robot_id == RMUL_OPPONENT_HERO
    assert damage_events[0].damage == 5
    assert match.ruleset.attack_damage_by_team == {
        RMUL_TARS_TEAM: 5,
        RMUL_OPPONENT_TEAM: 0,
    }
    assert dict(match.ruleset.display_state.attack_damage)[RMUL_TARS_TEAM] == 5


def test_rmul_first_death_read_progress_and_respawn_position() -> None:
    match = _rules_lab_match()
    robot = _robot(match, RMUL_HERO)
    death_position = (250.0, 220.0)
    robot.position = death_position
    robot.path = [(290.0, 220.0)]
    match.apply_damage(robot, robot.hp)

    # The full five-second death frame starts the read bar at zero.
    match.update(5.0)

    lifecycle = match.ruleset._robot_lifecycles[RMUL_HERO]
    assert len([
        event for event in match.current_events
        if event.robot_id == RMUL_HERO and event.type == MatchEventType.ROBOT_DESTROYED
    ]) == 1
    assert match.ruleset.victory_points[RMUL_TARS_TEAM] == 180
    assert not robot.alive
    assert lifecycle.death_count == 1
    assert lifecycle.respawn_progress == 0
    assert lifecycle.respawn_required == 5
    assert dict(match.ruleset.display_state.robot_statuses)[RMUL_HERO] == "RESP 0.0/5"

    match.update(4.0)
    assert not robot.alive
    assert lifecycle.respawn_progress == 4
    match.update(1.0)

    assert robot.alive
    assert robot.hp == int(robot.max_hp * 0.2) == 70
    assert robot.position == death_position
    assert robot.path == []
    assert lifecycle.weak
    assert lifecycle.invincible_remaining == 30


def test_rmul_repeat_death_increases_only_that_robots_read_requirement() -> None:
    match = _rules_lab_match()
    robot = _robot(match, RMUL_HERO)
    match.apply_damage(robot, robot.hp)
    match.update(0.01)
    match.update(5.0)
    assert robot.alive

    robot.position = (300.0, 260.0)
    match.apply_damage(robot, robot.hp, bypass_invincibility=True)
    match.update(3.0)

    lifecycle = match.ruleset._robot_lifecycles[RMUL_HERO]
    assert match.ruleset.victory_points[RMUL_TARS_TEAM] == 160
    assert len([
        event for event in match.current_events
        if event.robot_id == RMUL_HERO and event.type == MatchEventType.ROBOT_DESTROYED
    ]) == 1
    assert lifecycle.death_count == 2
    assert lifecycle.respawn_progress == 0
    assert lifecycle.respawn_required == 10

    match.update(9.0)
    assert not robot.alive
    assert lifecycle.respawn_progress == 9
    match.update(1.0)
    assert robot.alive
    assert lifecycle.weak

    other = _robot(match, RMUL_INFANTRY)
    match.apply_damage(other, other.hp)
    match.update(0.01)
    other_lifecycle = match.ruleset._robot_lifecycles[RMUL_INFANTRY]
    assert other_lifecycle.death_count == 1
    assert other_lifecycle.respawn_required == 5
    assert match.ruleset.victory_points[RMUL_TARS_TEAM] == 140


def test_rmul_weak_robot_cannot_attack_and_invincibility_expires_separately() -> None:
    match = _rules_lab_match()
    player = _complete_rmul_respawn(match, RMUL_HERO)
    opponent = _robot(match, RMUL_OPPONENT_HERO)
    player.position = (450.0, 260.0)
    opponent.position = (550.0, 260.0)
    player.attack_cooldown = 0
    opponent.attack_cooldown = 0
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1
    match.ruleset.allowed_projectiles_by_robot[RMUL_OPPONENT_HERO] = 1

    match.update(0.01)

    lifecycle = match.ruleset._robot_lifecycles[RMUL_HERO]
    assert lifecycle.weak
    assert not match.ruleset.can_attack(player)
    assert player.attack_cooldown == 0
    assert opponent.attack_cooldown == opponent.attack_interval
    assert player.hp == 70
    assert opponent.hp == opponent.max_hp
    assert not any(
        event.type == MatchEventType.ROBOT_DAMAGED
        for event in match.current_events
    )
    assert match.ruleset.attack_damage_by_team[RMUL_OPPONENT_TEAM] == 0
    assert match.ruleset.control_owner is None

    # Invincibility expires after 30 seconds; weak remains until supply detection.
    match.update(30.0)
    assert lifecycle.invincible_remaining == 0
    assert lifecycle.weak
    assert match.ruleset.can_receive_damage(player)
    assert not match.ruleset.can_attack(player)

    opponent.attack_cooldown = 0
    match.ruleset.allowed_projectiles_by_robot[RMUL_OPPONENT_HERO] = 1
    match.update(0.01)
    assert player.hp < 70
    assert player.attack_cooldown == 0


def test_match_damage_entry_enforces_invincibility_unless_penalty_bypasses_it() -> None:
    match = _rules_lab_match()
    robot = _complete_rmul_respawn(match, RMUL_HERO)
    robot.position = (400.0, 300.0)
    match.update(0.0)
    hp_before = robot.hp

    assert match.apply_damage(robot, 5) == 0
    assert robot.hp == hp_before
    assert match.current_events == []

    assert match.apply_damage(robot, 5, bypass_invincibility=True) == 5
    assert robot.hp == hp_before - 5
    assert [event.type for event in match.current_events] == [
        MatchEventType.ROBOT_DAMAGED
    ]


def test_rmul_weak_excludes_control_until_supply_zone_clears_state() -> None:
    match = _rules_lab_match()
    robot = _complete_rmul_respawn(match, RMUL_HERO)
    robot.position = (450.0, 260.0)

    match.update(0.0)
    assert match.ruleset.control_owner is None
    assert match.ruleset._robot_lifecycles[RMUL_HERO].weak

    # Supply zones only release state; they do not heal.
    robot.hp = 15
    robot.position = _own_supply_center(match, robot)
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1
    match.update(0.0)
    lifecycle = match.ruleset._robot_lifecycles[RMUL_HERO]
    assert not lifecycle.weak
    assert lifecycle.invincible_remaining == 0
    assert robot.hp == 15
    assert match.ruleset.can_attack(robot)
    assert match.ruleset.can_receive_damage(robot)

    robot.position = (450.0, 260.0)
    opponent = _robot(match, RMUL_OPPONENT_HERO)
    opponent.position = (550.0, 260.0)
    robot.attack_cooldown = 0
    opponent.attack_cooldown = 0
    match.ruleset.allowed_projectiles_by_robot[RMUL_OPPONENT_HERO] = 1
    match.update(0.01)

    assert match.ruleset.control_owner == RMUL_TARS_TEAM
    assert robot.hp == 5
    assert opponent.hp < opponent.max_hp


def test_rmul_only_each_teams_own_supply_zone_releases_states() -> None:
    match = _rules_lab_match()
    t1, o1 = _robot(match, RMUL_HERO), _robot(match, RMUL_OPPONENT_HERO)
    match.apply_damage(t1, t1.hp)
    match.apply_damage(o1, o1.hp)
    match.update(0.01)
    match.update(5.0)
    rules = match.ruleset

    assert rules._supply_zones[RMUL_TARS_TEAM].id == "red-supply"
    assert rules._supply_zones[RMUL_OPPONENT_TEAM].id == "blue-supply"
    assert t1.alive and o1.alive
    assert rules._robot_lifecycles[RMUL_HERO].weak
    assert rules._robot_lifecycles[RMUL_OPPONENT_HERO].weak

    # Put each revived robot in the other team's supply zone.
    t1.position = _enemy_supply_center(match, t1)
    o1.position = _enemy_supply_center(match, o1)
    match.update(0.1)
    assert rules._robot_lifecycles[RMUL_HERO].weak
    assert rules._robot_lifecycles[RMUL_HERO].invincible_remaining > 0
    assert rules._robot_lifecycles[RMUL_OPPONENT_HERO].weak
    assert rules._robot_lifecycles[RMUL_OPPONENT_HERO].invincible_remaining > 0

    t1.position = _own_supply_center(match, t1)
    o1.position = _own_supply_center(match, o1)
    match.update(0.0)
    assert not rules._robot_lifecycles[RMUL_HERO].weak
    assert rules._robot_lifecycles[RMUL_HERO].invincible_remaining == 0
    assert not rules._robot_lifecycles[RMUL_OPPONENT_HERO].weak
    assert rules._robot_lifecycles[RMUL_OPPONENT_HERO].invincible_remaining == 0


def test_rmul_reset_clears_repeated_death_and_temporary_lifecycle_state() -> None:
    match = _rules_lab_match()
    robot = _robot(match, RMUL_HERO)
    match.apply_damage(robot, robot.hp)
    match.update(0.01)
    match.update(5.0)
    robot.position = (300.0, 260.0)
    match.apply_damage(robot, robot.hp, bypass_invincibility=True)
    match.update(0.01)
    assert match.ruleset._robot_lifecycles[RMUL_HERO].respawn_required == 10
    match.update(10.0)
    assert match.ruleset._robot_lifecycles[RMUL_HERO].weak
    assert match.ruleset._robot_lifecycles[RMUL_HERO].invincible_remaining == 30

    _robot(match, RMUL_INFANTRY).position = (450.0, 260.0)
    match.update(0.01)
    assert match.ruleset.control_owner == RMUL_TARS_TEAM
    assert match.ruleset.victory_points[RMUL_TARS_TEAM] == 160
    match.ruleset.attack_damage_by_team[RMUL_TARS_TEAM] = 25
    match.ruleset._robot_lifecycles[RMUL_HERO].healing_hp_fraction = 0.5

    match.reset()

    assert match.ruleset.victory_points == {
        RMUL_TARS_TEAM: 200,
        RMUL_OPPONENT_TEAM: 200,
    }
    assert match.ruleset.control_owner is None
    assert match.ruleset.attack_damage_by_team == {
        RMUL_TARS_TEAM: 0,
        RMUL_OPPONENT_TEAM: 0,
    }
    for robot_id, spawn in match.config.scenario.spawns.items():
        reset_robot = _robot(match, robot_id)
        lifecycle = match.ruleset._robot_lifecycles[robot_id]
        assert reset_robot.alive
        assert reset_robot.hp == reset_robot.max_hp
        assert reset_robot.position == spawn
        assert reset_robot.path == []
        assert lifecycle.death_count == 0
        assert lifecycle.respawn_progress == 0
        assert lifecycle.respawn_required is None
        assert not lifecycle.weak
        assert lifecycle.invincible_remaining == 0
        assert lifecycle.healing_hp_fraction == 0


def test_training_v0_keeps_dead_robots_permanently_dead() -> None:
    match = Match(load_match_config(default_scenario_path()))
    for robot in match.robots:
        robot.speed = 0
        robot.attack_cooldown = 999
    robot = _robot(match, T1)
    match.apply_damage(robot, robot.hp)
    match.update(0.01)
    match.update(10.0)

    assert not robot.alive
    assert match.ruleset.display_state is None


def _write_rmul_rule_config(tmp_path: Path, mutate) -> Path:
    config_root = _copy_configs(tmp_path)
    rules_file = config_root / "rules" / "rmul-2026-3v3.yaml"
    data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
    mutate(data)
    rules_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return config_root / "scenarios" / "rmul-2026-rules-lab.yaml"


def test_rmul_economy_and_allowed_projectiles_start_from_yaml() -> None:
    match = _rules_lab_match()
    rules = match.ruleset

    assert rules.coins_by_team == {
        RMUL_TARS_TEAM: 0,
        RMUL_OPPONENT_TEAM: 0,
    }
    assert rules.allowed_projectiles_by_robot == {
        RMUL_HERO: 0,
        RMUL_INFANTRY: 0,
        RMUL_SENTRY: 750,
        RMUL_OPPONENT_HERO: 0,
        RMUL_OPPONENT_INFANTRY: 0,
        RMUL_OPPONENT_SENTRY: 750,
    }
    assert dict(match.ruleset.display_state.coins) == rules.coins_by_team
    assert dict(
        (robot_id, (projectile, count))
        for robot_id, projectile, count in match.ruleset.display_state.robot_projectiles
    ) == {
        RMUL_HERO: ("42mm", 0),
        RMUL_INFANTRY: ("17mm", 0),
        RMUL_SENTRY: ("17mm", 750),
        RMUL_OPPONENT_HERO: ("42mm", 0),
        RMUL_OPPONENT_INFANTRY: ("17mm", 0),
        RMUL_OPPONENT_SENTRY: ("17mm", 750),
    }
    for robot_id in (
        RMUL_HERO,
        RMUL_INFANTRY,
        RMUL_OPPONENT_HERO,
        RMUL_OPPONENT_INFANTRY,
    ):
        assert not rules.can_attack(_robot(match, robot_id))
    assert rules.can_attack(_robot(match, RMUL_SENTRY))
    assert rules.can_attack(_robot(match, RMUL_OPPONENT_SENTRY))


def test_rmul_timed_coin_grant_uses_threshold_crossing_and_never_repeats() -> None:
    match = _rules_lab_match()
    rules = match.ruleset

    match.update(0.9)
    assert set(rules.coins_by_team.values()) == {0}
    match.update(0.2)
    assert set(rules.coins_by_team.values()) == {200}
    assert rules._granted_timed_coin_events == {299}

    match.update(0.5)
    assert set(rules.coins_by_team.values()) == {200}


def test_rmul_all_timed_coin_grants_are_large_dt_and_slice_invariant() -> None:
    one_step = _rules_lab_match()
    sliced = _rules_lab_match()

    one_step.update(300.0)
    for dt in (1.0, 60.0, 60.0, 60.0, 60.0, 59.0):
        sliced.update(dt)

    expected = {RMUL_TARS_TEAM: 1200, RMUL_OPPONENT_TEAM: 1200}
    expected_events = {299, 239, 179, 119, 59}
    assert one_step.ruleset.coins_by_team == expected
    assert sliced.ruleset.coins_by_team == expected
    assert one_step.ruleset._granted_timed_coin_events == expected_events
    assert sliced.ruleset._granted_timed_coin_events == expected_events


def test_rmul_vp_gap_rewards_trigger_when_crossed_and_only_once() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    rules.victory_points.update({RMUL_TARS_TEAM: 200, RMUL_OPPONENT_TEAM: 131})
    opponent_hero = _robot(match, RMUL_OPPONENT_HERO)
    match.apply_damage(opponent_hero, opponent_hero.hp)
    match.update(0.01)

    assert rules.victory_points[RMUL_TARS_TEAM] - rules.victory_points[RMUL_OPPONENT_TEAM] == 89
    assert rules.coins_by_team == {RMUL_TARS_TEAM: 0, RMUL_OPPONENT_TEAM: 200}
    assert rules._granted_vp_gap_thresholds == {70}

    rules.victory_points[RMUL_OPPONENT_TEAM] = 61
    opponent_infantry = _robot(match, RMUL_OPPONENT_INFANTRY)
    match.apply_damage(opponent_infantry, opponent_infantry.hp)
    match.update(0.01)

    assert rules.victory_points[RMUL_TARS_TEAM] - rules.victory_points[RMUL_OPPONENT_TEAM] == 159
    assert rules.coins_by_team == {RMUL_TARS_TEAM: 0, RMUL_OPPONENT_TEAM: 400}
    assert rules._granted_vp_gap_thresholds == {70, 140}


def test_rmul_vp_gap_jump_awards_both_thresholds_and_leader_reversal_does_not_repeat() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    rules.victory_points.update({RMUL_TARS_TEAM: 200, RMUL_OPPONENT_TEAM: 140})
    rules._grant_vp_gap_coins(previous_gap=60)

    rules.victory_points.update({RMUL_TARS_TEAM: 290, RMUL_OPPONENT_TEAM: 140})
    rules._grant_vp_gap_coins(previous_gap=60)
    assert rules._granted_vp_gap_thresholds == {70, 140}
    assert rules.coins_by_team == {RMUL_TARS_TEAM: 0, RMUL_OPPONENT_TEAM: 400}

    rules.victory_points.update({RMUL_TARS_TEAM: 120, RMUL_OPPONENT_TEAM: 200})
    rules._grant_vp_gap_coins(previous_gap=150)
    rules.victory_points.update({RMUL_TARS_TEAM: 210, RMUL_OPPONENT_TEAM: 200})
    rules._grant_vp_gap_coins(previous_gap=10)
    assert rules.coins_by_team == {RMUL_TARS_TEAM: 0, RMUL_OPPONENT_TEAM: 400}


def test_rmul_hero_and_infantry_exchange_one_unit_in_own_supply() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    rules.coins_by_team[RMUL_TARS_TEAM] = 20

    assert match.order_exchange_projectiles(RMUL_HERO)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 10
    assert rules.allowed_projectiles_by_robot[RMUL_HERO] == 1
    assert match.order_exchange_projectiles(RMUL_INFANTRY)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 0
    assert rules.allowed_projectiles_by_robot[RMUL_INFANTRY] == 10
    assert rules.allowed_projectiles_by_robot[RMUL_SENTRY] == 750


def test_rmul_exchange_failures_are_atomic_and_respect_supply_and_control() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    hero = _robot(match, RMUL_HERO)
    red_balance = rules.coins_by_team[RMUL_TARS_TEAM]
    counts = dict(rules.allowed_projectiles_by_robot)

    rules.coins_by_team[RMUL_TARS_TEAM] = 9
    assert not match.order_exchange_projectiles(RMUL_HERO)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 9
    assert rules.allowed_projectiles_by_robot == counts

    rules.coins_by_team[RMUL_TARS_TEAM] = 100
    hero.position = (600.0, 700.0)
    assert not match.order_exchange_projectiles(RMUL_HERO)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 100
    assert rules.allowed_projectiles_by_robot == counts

    hero.position = _enemy_supply_center(match, hero)
    assert not match.order_exchange_projectiles(RMUL_HERO)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 100
    assert rules._robot_penalties[RMUL_HERO].forbidden_elapsed == 0

    hero.position = _own_supply_center(match, hero)
    rules.coins_by_team[RMUL_TARS_TEAM] = 1000
    assert not match.order_exchange_projectiles(RMUL_SENTRY)
    assert rules.allowed_projectiles_by_robot[RMUL_SENTRY] == 750
    assert not match.order_exchange_projectiles(RMUL_OPPONENT_HERO)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 1000
    assert rules.allowed_projectiles_by_robot == counts

    rules._robot_penalties[RMUL_HERO].disqualified = True
    assert not match.order_exchange_projectiles(RMUL_HERO)
    rules._robot_penalties[RMUL_HERO].disqualified = False
    hero.alive = False
    assert not match.order_exchange_projectiles(RMUL_HERO)
    hero.alive = True
    match.finished = True
    assert not match.order_exchange_projectiles(RMUL_HERO)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 1000
    assert rules.allowed_projectiles_by_robot == counts
    assert red_balance == 0


def test_rmul_committed_attack_consumes_one_projectile_and_zero_blocks_followup() -> None:
    match = _rules_lab_match()
    attacker = _robot(match, RMUL_HERO)
    target = _robot(match, RMUL_OPPONENT_HERO)
    attacker.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    attacker.attack_cooldown = 0
    target.attack_cooldown = 999
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1

    match.update(0.01)
    assert match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] == 0
    assert target.hp == target.max_hp - attacker.damage
    assert attacker.attack_cooldown == attacker.attack_interval

    attacker.attack_cooldown = 0
    match.update(0.01)
    assert match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] == 0
    assert target.hp == target.max_hp - attacker.damage
    assert attacker.attack_cooldown == 0


def test_rmul_zero_projectiles_prevents_attack_without_setting_cooldown() -> None:
    match = _rules_lab_match()
    attacker = _robot(match, RMUL_HERO)
    target = _robot(match, RMUL_OPPONENT_HERO)
    attacker.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    attacker.attack_cooldown = 0
    target.attack_cooldown = 999

    match.update(0.01)

    assert not match.ruleset.can_attack(attacker)
    assert attacker.attack_cooldown == 0
    assert target.hp == target.max_hp
    assert match.ruleset.attack_damage_by_team[RMUL_TARS_TEAM] == 0


@pytest.mark.parametrize("missing_target", ["none", "range", "line_of_sight"])
def test_rmul_uncommitted_attack_does_not_consume_projectile(
    missing_target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    match = _rules_lab_match()
    attacker = _robot(match, RMUL_HERO)
    attacker.position = (450.0, 260.0)
    attacker.attack_cooldown = 0
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1
    if missing_target == "none":
        for robot in match.robots:
            if robot.team == RMUL_OPPONENT_TEAM:
                robot.alive = False
    elif missing_target == "range":
        _robot(match, RMUL_OPPONENT_HERO).position = (850.0, 260.0)
    else:
        monkeypatch.setattr(match.map, "has_line_of_sight", lambda *_: False)

    match.update(0.01)

    assert match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] == 1
    assert attacker.attack_cooldown == 0
    assert match.ruleset.attack_damage_by_team[RMUL_TARS_TEAM] == 0


def test_rmul_invincible_target_still_consumes_committed_projectile() -> None:
    match = _rules_lab_match()
    attacker = _robot(match, RMUL_HERO)
    target = _robot(match, RMUL_OPPONENT_HERO)
    attacker.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    attacker.attack_cooldown = 0
    target.attack_cooldown = 999
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1
    match.ruleset._robot_lifecycles[RMUL_OPPONENT_HERO].invincible_remaining = 10

    match.update(0.01)

    assert match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] == 0
    assert attacker.attack_cooldown == attacker.attack_interval
    assert target.hp == target.max_hp
    assert match.ruleset.attack_damage_by_team[RMUL_TARS_TEAM] == 0


def test_rmul_weak_robot_does_not_consume_projectile() -> None:
    match = _rules_lab_match()
    attacker = _robot(match, RMUL_HERO)
    target = _robot(match, RMUL_OPPONENT_HERO)
    attacker.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    attacker.attack_cooldown = 0
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1
    match.ruleset._robot_lifecycles[RMUL_HERO].weak = True

    match.update(0.01)

    assert match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] == 1
    assert attacker.attack_cooldown == 0
    assert target.hp == target.max_hp


def test_rmul_sentry_consumes_one_of_its_750_allowed_projectiles() -> None:
    match = _rules_lab_match()
    sentry = _robot(match, RMUL_SENTRY)
    target = _robot(match, RMUL_OPPONENT_HERO)
    sentry.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    sentry.attack_cooldown = 0
    target.attack_cooldown = 999

    match.update(0.01)

    assert match.ruleset.allowed_projectiles_by_robot[RMUL_SENTRY] == 749
    assert target.hp == target.max_hp - sentry.damage


def test_rmul_each_committed_attack_consumes_even_if_target_was_already_killed() -> None:
    match = _rules_lab_match()
    hero = _robot(match, RMUL_HERO)
    infantry = _robot(match, RMUL_INFANTRY)
    target = _robot(match, RMUL_OPPONENT_HERO)
    hero.position = (450.0, 250.0)
    infantry.position = (450.0, 280.0)
    target.position = (530.0, 265.0)
    target.hp = 10
    hero.attack_cooldown = 0
    infantry.attack_cooldown = 0
    target.attack_cooldown = 999
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 1
    match.ruleset.allowed_projectiles_by_robot[RMUL_INFANTRY] = 1

    match.update(0.01)

    assert not target.alive
    assert match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] == 0
    assert match.ruleset.allowed_projectiles_by_robot[RMUL_INFANTRY] == 0


def test_rmul_allowed_projectiles_survive_death_and_respawn() -> None:
    match = _rules_lab_match()
    match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] = 37

    _complete_rmul_respawn(match, RMUL_HERO)

    assert _robot(match, RMUL_HERO).alive
    assert match.ruleset.allowed_projectiles_by_robot[RMUL_HERO] == 37


def test_rmul_reset_restores_coins_grants_and_all_projectile_allowances() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    match.update(1.1)
    rules.victory_points.update({RMUL_TARS_TEAM: 200, RMUL_OPPONENT_TEAM: 120})
    rules._grant_vp_gap_coins(previous_gap=69)
    assert match.order_exchange_projectiles(RMUL_HERO)
    rules.allowed_projectiles_by_robot[RMUL_SENTRY] = 749
    assert rules._granted_timed_coin_events == {299}
    assert rules._granted_vp_gap_thresholds == {70}

    match.reset()

    assert rules.coins_by_team == {RMUL_TARS_TEAM: 0, RMUL_OPPONENT_TEAM: 0}
    assert rules._granted_timed_coin_events == set()
    assert rules._granted_vp_gap_thresholds == set()
    assert rules.allowed_projectiles_by_robot == {
        RMUL_HERO: 0,
        RMUL_INFANTRY: 0,
        RMUL_SENTRY: 750,
        RMUL_OPPONENT_HERO: 0,
        RMUL_OPPONENT_INFANTRY: 0,
        RMUL_OPPONENT_SENTRY: 750,
    }


def test_rmul_red_card_has_no_extra_economy_side_effects() -> None:
    match = _rules_lab_match()
    match.elapsed_time = 20.0
    rules = match.ruleset
    offender, _ = _prepare_rmul_forbidden_zone(match, RMUL_HERO)
    rules.coins_by_team[RMUL_TARS_TEAM] = 25
    before_allowances = dict(rules.allowed_projectiles_by_robot)

    match.update(23.1)

    assert rules._robot_penalties[RMUL_HERO].disqualified
    assert not offender.alive
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 25
    assert rules.allowed_projectiles_by_robot == before_allowances
    assert not match.order_exchange_projectiles(RMUL_HERO)
    assert rules.coins_by_team[RMUL_TARS_TEAM] == 25


def test_training_rules_have_no_exchange_or_projectile_limit() -> None:
    match = _open_field_match()
    attacker = _robot(match, T1)
    target = _robot(match, O1)
    attacker.position = (400.0, 260.0)
    target.position = (500.0, 260.0)
    attacker.attack_cooldown = 0
    target.attack_cooldown = 999

    assert not match.order_exchange_projectiles(T1)
    assert match.ruleset.display_state is None
    assert match.ruleset.can_attack(attacker)
    match.update(0.01)
    assert target.hp == target.max_hp - attacker.damage


@pytest.mark.parametrize(
    "invalid_case",
    [
        "empty_timed_grants",
        "duplicate_timed_time",
        "invalid_timed_amount",
        "timed_time_out_of_range",
        "duplicate_vp_threshold",
        "negative_initial_allowance",
        "sentry_exchangeable",
        "missing_exchange_amount",
    ],
)
def test_rmul_invalid_economy_yaml_is_rejected(
    tmp_path: Path, invalid_case: str
) -> None:
    def mutate(data: dict) -> None:
        if invalid_case == "empty_timed_grants":
            data["economy"]["timed_grants"] = []
        elif invalid_case == "duplicate_timed_time":
            data["economy"]["timed_grants"][1]["remaining_time"] = 299
        elif invalid_case == "invalid_timed_amount":
            data["economy"]["timed_grants"][0]["amount"] = 0
        elif invalid_case == "timed_time_out_of_range":
            data["economy"]["timed_grants"][0]["remaining_time"] = 300
        elif invalid_case == "duplicate_vp_threshold":
            data["economy"]["vp_gap_grants"][1]["threshold"] = 70
        elif invalid_case == "negative_initial_allowance":
            data["allowed_projectiles"]["hero"]["initial"] = -1
        elif invalid_case == "sentry_exchangeable":
            data["allowed_projectiles"]["sentry"]["exchangeable"] = True
        else:
            del data["allowed_projectiles"]["infantry"]["exchange_amount"]

    scenario_file = _write_rmul_rule_config(tmp_path, mutate)
    with pytest.raises(ConfigError):
        Match(load_match_config(scenario_file))
