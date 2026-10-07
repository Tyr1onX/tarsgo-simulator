import math
from pathlib import Path

from tarsgo_simulator.core.config import default_scenario_path, load_match_config
from tarsgo_simulator.core.match import Match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RULES_LAB_PATH = REPOSITORY_ROOT / "configs" / "scenarios" / "rmul-2026-rules-lab.yaml"

HERO = "tarsgo-hero"
INFANTRY = "tarsgo-infantry"
SENTRY = "tarsgo-sentry"
OPPONENT_HERO = "opponent-hero"
OPPONENT_SENTRY = "opponent-sentry"
TARS_TEAM = "tarsgo-rmul-2026"


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _rules_lab_match() -> Match:
    match = Match(load_match_config(RULES_LAB_PATH))
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0
    return match


def _set_player_path(match: Match, robot_id: str, goal: tuple[float, float]) -> None:
    robot = _robot(match, robot_id)
    robot.speed = match.ruleset.robot_parameters(robot.type).move_speed
    assert match.order_move(robot_id, goal)
    assert robot.path


def test_rmul_chassis_profiles_and_initial_buffer() -> None:
    match = _rules_lab_match()
    rules = match.ruleset

    assert rules._chassis_power_detection_hz == 10
    assert rules._buffer_energy_max == 60
    assert rules._power_off_duration == 5
    assert rules._stationary_power_demand == 0
    assert rules._lab_infantry_chassis_profile == "power-priority"

    hero = rules._chassis_power_rules["hero"]
    infantry = rules._chassis_power_rules["infantry"]
    sentry = rules._chassis_power_rules["sentry"]
    assert (hero.power_limit, hero.moving_power_demand) == (100, 105)
    assert (infantry.power_limit, infantry.moving_power_demand) == (90, 95)
    assert (sentry.power_limit, sentry.moving_power_demand) == (100, 105)

    assert len(rules._robot_chassis_states) == 6
    assert all(
        state.buffer_energy == 60
        and state.power_off_remaining == 0
        and not state.blocked_this_frame
        for state in rules._robot_chassis_states.values()
    )
    displayed = {
        robot_id: (buffer, maximum, power, limit, power_off)
        for robot_id, buffer, maximum, power, limit, power_off
        in rules.display_state.robot_chassis_power
    }
    assert displayed[HERO] == (60, 60, 0, 100, 0)
    assert displayed[INFANTRY] == (60, 60, 0, 90, 0)
    assert displayed[SENTRY] == (60, 60, 0, 100, 0)


def test_power_settlement_waits_for_full_100ms_tick() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    state = rules._robot_chassis_states[HERO]
    _robot(match, HERO).path = [(600.0, 190.0)]

    rules.prepare_movement(match, 0.09)
    assert state.buffer_energy == 60
    assert math.isclose(rules._chassis_power_accumulator, 0.09, abs_tol=1e-9)

    rules.prepare_movement(match, 0.01)
    assert math.isclose(state.buffer_energy, 59.5, abs_tol=1e-9)
    assert math.isclose(rules._chassis_power_accumulator, 0.0, abs_tol=1e-9)


def test_moving_hero_drains_five_joules_per_second() -> None:
    match = _rules_lab_match()
    state = match.ruleset._robot_chassis_states[HERO]
    _robot(match, HERO).path = [(600.0, 190.0)]

    match.ruleset.prepare_movement(match, 1.0)

    assert math.isclose(state.buffer_energy, 55.0, abs_tol=1e-9)


def test_stationary_power_recovers_buffer_and_caps_at_sixty() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    state = rules._robot_chassis_states[HERO]

    state.buffer_energy = 30
    rules.prepare_movement(match, 0.3)
    assert state.buffer_energy == 60

    state.buffer_energy = 59
    rules.prepare_movement(match, 0.1)
    assert state.buffer_energy == 60


def test_power_settlement_is_dt_slice_invariant() -> None:
    whole = _rules_lab_match()
    sliced = _rules_lab_match()
    _robot(whole, HERO).path = [(600.0, 190.0)]
    _robot(sliced, HERO).path = [(600.0, 190.0)]

    whole.ruleset.prepare_movement(whole, 1.0)
    for _ in range(100):
        sliced.ruleset.prepare_movement(sliced, 0.01)

    assert math.isclose(
        whole.ruleset._robot_chassis_states[HERO].buffer_energy,
        sliced.ruleset._robot_chassis_states[HERO].buffer_energy,
        abs_tol=1e-9,
    )
    assert math.isclose(
        whole.ruleset._robot_chassis_states[HERO].buffer_energy,
        55.0,
        abs_tol=1e-9,
    )


def test_buffer_exhaustion_triggers_five_second_chassis_off() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    robot = _robot(match, HERO)
    state = rules._robot_chassis_states[HERO]
    state.buffer_energy = 0.2
    robot.path = [(600.0, 190.0)]

    rules.prepare_movement(match, 0.1)

    assert state.buffer_energy == 0
    assert state.power_off_remaining == 5
    assert state.blocked_this_frame
    assert not rules.can_move(robot)


def test_power_off_blocks_movement_and_preserves_path() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    _set_player_path(match, HERO, (600.0, 190.0))
    old_path = list(robot.path)
    start = robot.position
    state = match.ruleset._robot_chassis_states[HERO]
    state.buffer_energy = 0.2

    match.update(0.1)

    assert robot.position == start
    assert robot.path == old_path
    assert state.buffer_energy == 0
    assert state.power_off_remaining == 5


def test_powered_off_robot_remains_dynamic_blocker_and_intent_draws_power() -> None:
    match = _rules_lab_match()
    mover = _robot(match, HERO)
    blocker = _robot(match, INFANTRY)
    mover.position = (290.0, 260.0)
    blocker.position = (330.0, 260.0)
    _set_player_path(match, HERO, (500.0, 260.0))
    start = mover.position
    blocker_state = match.ruleset._robot_chassis_states[INFANTRY]
    blocker_state.power_off_remaining = 5

    match.update(0.1)

    assert mover.position != start
    assert blocker.position == (330.0, 260.0)
    assert math.dist(mover.position, blocker.position) >= match.map.collision_radius * 2
    assert math.isclose(
        match.ruleset._robot_chassis_states[HERO].buffer_energy,
        59.5,
        abs_tol=1e-9,
    )
    assert mover.path


def test_chassis_off_does_not_lock_launcher() -> None:
    match = _rules_lab_match()
    attacker = _robot(match, HERO)
    target = _robot(match, OPPONENT_HERO)
    attacker.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    attacker.attack_cooldown = 0.0
    target.attack_cooldown = 999.0
    match.ruleset.allowed_projectiles_by_robot[HERO] = 1
    match.ruleset._robot_chassis_states[HERO].power_off_remaining = 5
    hp_before = target.hp

    match.update(0.01)

    assert target.hp == hp_before - attacker.damage
    assert match.ruleset.allowed_projectiles_by_robot[HERO] == 0
    assert match.ruleset._robot_shooting_states[HERO].heat == 100
    assert match.ruleset._robot_chassis_states[HERO].power_off_remaining == 5


def test_chassis_off_robot_still_controls_center() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    robot.position = (600.0, 400.0)
    match.ruleset._robot_chassis_states[HERO].power_off_remaining = 5

    match.update(1.0)

    assert match.ruleset.control_owner == TARS_TEAM


def test_chassis_off_robot_still_receives_supply_healing() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    robot.position = (200.0, 300.0)
    robot.hp = 100
    match.ruleset._robot_chassis_states[HERO].power_off_remaining = 5

    match.update(0.4)

    assert robot.hp == 135


def test_power_off_recovers_buffer_then_resumes_existing_path() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    _set_player_path(match, HERO, (600.0, 190.0))
    state = match.ruleset._robot_chassis_states[HERO]
    state.buffer_energy = 0
    state.power_off_remaining = 5
    start = robot.position

    for _ in range(50):
        match.update(0.1)

    assert robot.position == start
    assert robot.path
    assert state.buffer_energy == 60
    assert state.power_off_remaining == 0

    match.update(0.01)
    assert robot.position != start


def test_order_move_can_replace_path_during_power_off() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    robot.speed = match.ruleset.robot_parameters("hero").move_speed
    state = match.ruleset._robot_chassis_states[HERO]
    state.power_off_remaining = 5
    start = robot.position

    assert match.order_move(HERO, (500.0, 190.0))
    assert match.order_move(HERO, (600.0, 330.0))
    assert robot.path[-1] == (600.0, 330.0)

    match.update(0.01)
    assert robot.position == start
    assert robot.path[-1] == (600.0, 330.0)

    state.power_off_remaining = 0
    match.update(0.01)
    assert robot.position != start


def test_ai_can_replan_while_powered_off_and_resume_after_power_returns() -> None:
    match = _rules_lab_match()
    sentry = _robot(match, OPPONENT_SENTRY)
    sentry.speed = match.ruleset.robot_parameters("sentry").move_speed
    state = match.ruleset._robot_chassis_states[OPPONENT_SENTRY]
    state.power_off_remaining = 5
    start = sentry.position

    match.update(0.5)

    assert sentry.position == start
    assert sentry.path
    assert math.isclose(state.power_off_remaining, 4.5, abs_tol=1e-9)

    state.power_off_remaining = 0
    match.update(0.01)
    assert sentry.position != start


def test_large_dt_settles_all_power_ticks_but_blocks_whole_movement_frame() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    _set_player_path(match, HERO, (600.0, 190.0))
    state = match.ruleset._robot_chassis_states[HERO]
    state.buffer_energy = 0.2
    start = robot.position

    match.update(5.5)

    assert robot.position == start
    assert robot.path
    assert state.power_off_remaining == 0
    assert math.isclose(state.buffer_energy, 58.0, abs_tol=1e-9)

    match.update(0.01)
    assert robot.position != start


def test_death_resets_heat_and_buffer_in_same_event_consumer() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    rules = match.ruleset
    shooting = rules._robot_shooting_states[HERO]
    chassis = rules._robot_chassis_states[HERO]
    shooting.heat = 250
    shooting.heat_locked = True
    shooting.permanently_locked = True
    chassis.buffer_energy = 10
    chassis.power_off_remaining = 4.2

    match.apply_damage(robot, robot.hp)
    match.update(0.01)

    assert shooting.heat == 0
    assert not shooting.heat_locked
    assert shooting.permanently_locked
    assert chassis.buffer_energy == 60
    assert chassis.power_off_remaining == 0
    assert not chassis.blocked_this_frame


def test_respawn_starts_with_full_buffer_and_existing_weak_invincible_state() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    rules = match.ruleset
    rules._robot_chassis_states[HERO].buffer_energy = 10
    rules._robot_shooting_states[HERO].heat = 100

    match.apply_damage(robot, robot.hp)
    match.update(0.01)
    match.update(5.0)

    assert robot.alive
    assert rules._robot_chassis_states[HERO].buffer_energy == 60
    assert rules._robot_chassis_states[HERO].power_off_remaining == 0
    assert rules._robot_shooting_states[HERO].heat == 0
    assert rules._robot_lifecycles[HERO].weak
    assert rules._robot_lifecycles[HERO].invincible_remaining > 0


def test_match_reset_restores_chassis_heat_and_rule_state() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    robot = _robot(match, HERO)
    robot.path = [(600.0, 190.0)]
    rules._robot_chassis_states[HERO].buffer_energy = 12
    rules._robot_chassis_states[HERO].power_off_remaining = 3
    rules._chassis_power_accumulator = 0.05
    rules._robot_shooting_states[HERO].heat = 250
    rules._robot_shooting_states[HERO].heat_locked = True
    rules.coins_by_team[TARS_TEAM] = 400
    rules._robot_penalties[HERO].yellow_cards = 2
    rules._robot_lifecycles[HERO].death_count = 2

    match.reset()

    assert rules._chassis_power_accumulator == 0
    assert all(
        state.buffer_energy == 60
        and state.power_off_remaining == 0
        and not state.blocked_this_frame
        for state in rules._robot_chassis_states.values()
    )
    assert all(
        state.heat == 0
        and not state.heat_locked
        and not state.permanently_locked
        for state in rules._robot_shooting_states.values()
    )
    assert all(not robot.path for robot in match.robots)
    assert all(value == 0 for value in rules.coins_by_team.values())
    assert all(state.yellow_cards == 0 for state in rules._robot_penalties.values())
    assert all(state.death_count == 0 for state in rules._robot_lifecycles.values())


def test_training_v0_has_no_chassis_power_state_and_movement_is_unchanged() -> None:
    match = Match(load_match_config(default_scenario_path()))
    robot = match.robots[0]
    start = robot.position

    assert match.ruleset.can_move(robot)
    match.ruleset.prepare_movement(match, 10.0)
    assert not hasattr(match.ruleset, "_robot_chassis_states")
    assert match.ruleset.display_state is None

    assert match.order_move(robot.id, (200.0, 150.0))
    match.update(0.1)
    assert robot.position != start
