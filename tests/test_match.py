from dataclasses import replace
import math
from pathlib import Path
import shutil
import sys

import pytest

from tarsgo_simulator.core.combat import update_combat
from tarsgo_simulator.core.config import ConfigError, default_scenario_path, load_match_config
from tarsgo_simulator.core.map import GameMap, Rectangle
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.pathfinding import find_path
from tarsgo_simulator.core.robot import Robot


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
T1 = "tarsgo-infantry-1"
T2 = "tarsgo-infantry-2"
O1 = "opponent-infantry-1"
O2 = "opponent-infantry-2"


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _team_robots(match: Match, team_id: str) -> list[Robot]:
    return [robot for robot in match.robots if robot.team == team_id]


def _keep_only(match: Match, *robot_ids: str) -> None:
    keep = set(robot_ids)
    for robot in match.robots:
        if robot.id not in keep:
            robot.take_damage(robot.hp)


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

    assert config.rules_id == "training-v0"
    assert [robot.id for robot in config.scenario.teams["red"].robots] == [T1, T2]
    assert [robot.id for robot in config.scenario.teams["blue"].robots] == [O1, O2]
    assert all(
        robot.type == "infantry"
        for team in config.scenario.teams.values()
        for robot in team.robots
    )
    assert config.infantry.max_hp > 0
    assert config.infantry.damage > 0


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
        load_match_config(config_root / "scenarios" / "first-steps.yaml")


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
    _robot(match, T1).take_damage(100)
    match.update(0.01)

    assert not match.finished
    assert _robot(match, T2).alive

    _robot(match, T2).take_damage(100)
    match.update(0.01)

    assert match.finished
    assert match.winner == "opponent-balanced"


def test_match_time_winner_uses_total_remaining_team_hp() -> None:
    match = Match(load_match_config(default_scenario_path()))
    _robot(match, T1).hp = 80
    _robot(match, T2).hp = 40
    _robot(match, O1).hp = 50
    _robot(match, O2).hp = 60
    match.elapsed_time = match.config.match_duration - 0.01

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

    update_combat(robots, GameMap(400, 300, [], collision_radius=10))

    assert nearer.hp == 90
    assert farther.hp == 100


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

    update_combat(robots, GameMap(400, 300, [], collision_radius=10))

    assert earlier_id.hp == 90
    assert later_id.hp == 100


def test_both_opponent_robots_move_with_independent_timers() -> None:
    match = Match(load_match_config(default_scenario_path()))
    starts = {robot.id: robot.position for robot in _team_robots(match, "opponent-balanced")}

    for _ in range(20):
        match.update(0.05)

    assert set(match._opponent_replan_elapsed) == {O1, O2}
    assert all(_robot(match, robot_id).position != starts[robot_id] for robot_id in (O1, O2))
    assert all(0 <= elapsed < 0.5 for elapsed in match._opponent_replan_elapsed.values())


def test_opponent_ai_timer_for_each_robot_advances_independently() -> None:
    match = _open_field_match()
    _robot(match, T1).position = (300.0, 120.0)
    _robot(match, O1).position = (400.0, 120.0)
    _robot(match, T2).position = (100.0, 520.0)
    _robot(match, O2).position = (800.0, 520.0)

    match.update(0.2)

    assert match._opponent_replan_elapsed[O1] == 0.0
    assert match._opponent_replan_elapsed[O2] == pytest.approx(0.2)


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
    player2.position = (700.0, 500.0)
    opponent1.position = (680.0, 120.0)
    opponent2.position = (850.0, 500.0)

    match.update(0.05)
    assert not match.finished
    player1.take_damage(player1.hp)
    match.update(0.5)

    assert not match.finished
    assert player2.alive
    assert opponent1.position[1] > 120
    assert opponent2.position[0] < 850


def test_reset_restores_all_robots_and_ai_state() -> None:
    match = Match(load_match_config(default_scenario_path()))
    assert match.order_move(T1, (220.0, 150.0))
    for _ in range(15):
        match.update(0.05)
    _robot(match, T1).take_damage(30)
    _robot(match, T2).take_damage(100)
    _robot(match, O1).take_damage(20)
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
    assert match._opponent_replan_elapsed == {O1: 0.0, O2: 0.0}
