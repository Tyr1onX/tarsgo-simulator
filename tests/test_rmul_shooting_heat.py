import math
from pathlib import Path

import pytest

from tarsgo_simulator.core.config import default_scenario_path, load_match_config
from tarsgo_simulator.core.match import Match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RULES_LAB_PATH = REPOSITORY_ROOT / "configs" / "scenarios" / "rmul-2026-rules-lab.yaml"

HERO = "tarsgo-hero"
INFANTRY = "tarsgo-infantry"
SENTRY = "tarsgo-sentry"
OPPONENT_HERO = "opponent-hero"
TARS_TEAM = "tarsgo-rmul-2026"


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _rules_lab_match() -> Match:
    match = Match(load_match_config(RULES_LAB_PATH))
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 999.0
    return match


def _keep_only(match: Match, *robot_ids: str) -> None:
    keep = set(robot_ids)
    for robot in match.robots:
        if robot.id not in keep:
            robot.hp = 0
            robot.alive = False
            robot.path.clear()


def _prepare_hero_shot(match: Match):
    _keep_only(match, HERO, OPPONENT_HERO)
    attacker = _robot(match, HERO)
    target = _robot(match, OPPONENT_HERO)
    attacker.position = (450.0, 260.0)
    target.position = (550.0, 260.0)
    attacker.attack_cooldown = 0.0
    target.attack_cooldown = 999.0
    match.ruleset.allowed_projectiles_by_robot[HERO] = 1
    return attacker, target


def test_rmul_shooting_heat_initial_state_and_profiles() -> None:
    match = _rules_lab_match()
    rules = match.ruleset

    assert rules._heat_cooling_hz == 10
    assert rules._lab_infantry_launcher_profile == "cooling-priority"

    hero = rules._shooting_heat_rules["hero"]
    infantry = rules._shooting_heat_rules["infantry"]
    sentry = rules._shooting_heat_rules["sentry"]
    assert (
        hero.heat_limit,
        hero.cooling_per_second,
        hero.projectile_heat,
        hero.permanent_lock_extra,
    ) == (200, 24, 100, 200)
    assert (
        infantry.heat_limit,
        infantry.cooling_per_second,
        infantry.projectile_heat,
        infantry.permanent_lock_extra,
    ) == (88, 24, 10, 100)
    assert (
        sentry.heat_limit,
        sentry.cooling_per_second,
        sentry.projectile_heat,
        sentry.permanent_lock_extra,
    ) == (260, 30, 10, 100)

    assert len(rules._robot_shooting_states) == 6
    assert all(
        state.heat == 0
        and not state.heat_locked
        and not state.permanently_locked
        for state in rules._robot_shooting_states.values()
    )
    displayed = {
        robot_id: (heat, limit, locked, permanent)
        for robot_id, heat, limit, locked, permanent
        in rules.display_state.robot_shooting_heat
    }
    assert displayed[HERO] == (0, 200, False, False)
    assert displayed[INFANTRY] == (0, 88, False, False)
    assert displayed[SENTRY] == (0, 260, False, False)


def test_hero_committed_shot_decrements_allowance_and_adds_42mm_heat() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    rules = match.ruleset
    rules.allowed_projectiles_by_robot[HERO] = 3

    rules.on_attack_committed(robot)

    assert rules.allowed_projectiles_by_robot[HERO] == 2
    assert rules._robot_shooting_states[HERO].heat == 100


@pytest.mark.parametrize("robot_id", [INFANTRY, SENTRY])
def test_17mm_committed_shot_adds_ten_heat(robot_id: str) -> None:
    match = _rules_lab_match()
    robot = _robot(match, robot_id)
    rules = match.ruleset
    rules.allowed_projectiles_by_robot[robot_id] = 2

    rules.on_attack_committed(robot)

    assert rules.allowed_projectiles_by_robot[robot_id] == 1
    assert rules._robot_shooting_states[robot_id].heat == 10


def test_no_legal_target_does_not_commit_or_heat_shot() -> None:
    match = _rules_lab_match()
    _keep_only(match, HERO)
    attacker = _robot(match, HERO)
    attacker.attack_cooldown = 0.0
    match.ruleset.allowed_projectiles_by_robot[HERO] = 1

    match.update(0.01)

    assert attacker.attack_cooldown == 0
    assert match.ruleset.allowed_projectiles_by_robot[HERO] == 1
    assert match.ruleset._robot_shooting_states[HERO].heat == 0


def test_invincible_target_still_commits_shot_without_damage() -> None:
    match = _rules_lab_match()
    attacker, target = _prepare_hero_shot(match)
    match.ruleset._robot_lifecycles[OPPONENT_HERO].invincible_remaining = 30.0
    hp_before = target.hp

    match.update(0.01)

    assert match.ruleset.allowed_projectiles_by_robot[HERO] == 0
    assert match.ruleset._robot_shooting_states[HERO].heat == 100
    assert attacker.attack_cooldown == attacker.attack_interval
    assert target.hp == hp_before
    assert match.ruleset.attack_damage_by_team[TARS_TEAM] == 0


def test_heat_cooling_is_quantized_at_ten_hz() -> None:
    match = _rules_lab_match()
    state = match.ruleset._robot_shooting_states[HERO]
    state.heat = 100

    match.ruleset.prepare_combat(match, 0.09)
    assert state.heat == 100

    match.ruleset.prepare_combat(match, 0.01)
    assert math.isclose(state.heat, 97.6, abs_tol=1e-9)

    sentry_match = _rules_lab_match()
    sentry_state = sentry_match.ruleset._robot_shooting_states[SENTRY]
    sentry_state.heat = 100
    sentry_match.ruleset.prepare_combat(sentry_match, 0.1)
    assert sentry_state.heat == 97


def test_large_dt_cooling_runs_every_tick_and_keeps_remainder() -> None:
    match = _rules_lab_match()
    state = match.ruleset._robot_shooting_states[HERO]
    state.heat = 100

    match.ruleset.prepare_combat(match, 0.35)

    assert math.isclose(state.heat, 92.8, abs_tol=1e-9)
    assert math.isclose(
        match.ruleset._heat_cooling_accumulator, 0.05, abs_tol=1e-9
    )


def test_cooling_is_dt_slice_invariant_without_shooting() -> None:
    whole = _rules_lab_match()
    sliced = _rules_lab_match()
    whole.ruleset._robot_shooting_states[HERO].heat = 100
    sliced.ruleset._robot_shooting_states[HERO].heat = 100

    whole.ruleset.prepare_combat(whole, 1.0)
    for _ in range(100):
        sliced.ruleset.prepare_combat(sliced, 0.01)

    assert math.isclose(
        whole.ruleset._robot_shooting_states[HERO].heat,
        sliced.ruleset._robot_shooting_states[HERO].heat,
        abs_tol=1e-9,
    )
    assert math.isclose(
        whole.ruleset._robot_shooting_states[HERO].heat, 76.0, abs_tol=1e-9
    )


def test_new_shot_does_not_receive_same_frame_retroactive_cooling() -> None:
    match = _rules_lab_match()
    _prepare_hero_shot(match)

    match.update(1.0)

    assert match.ruleset._robot_shooting_states[HERO].heat == 100


def test_q0_exact_does_not_lock_but_crossing_q0_temporarily_locks() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    rules = match.ruleset
    state = rules._robot_shooting_states[HERO]

    rules.allowed_projectiles_by_robot[HERO] = 2
    state.heat = 100
    rules.on_attack_committed(robot)
    assert state.heat == 200
    assert not state.heat_locked
    assert not state.permanently_locked
    assert rules.can_attack(robot)

    state.heat = 150
    rules.on_attack_committed(robot)
    assert state.heat == 250
    assert state.heat_locked
    assert not state.permanently_locked
    assert not rules.can_attack(robot)


def test_temporary_lock_survives_below_q0_until_heat_reaches_zero() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    state = rules._robot_shooting_states[HERO]
    rules.allowed_projectiles_by_robot[HERO] = 1
    state.heat = 250
    state.heat_locked = True

    rules.prepare_combat(match, 2.5)
    assert math.isclose(state.heat, 190.0, abs_tol=1e-9)
    assert state.heat_locked
    assert not rules.can_attack(_robot(match, HERO))

    rules.prepare_combat(match, 7.9)
    assert math.isclose(state.heat, 0.4, abs_tol=1e-9)
    assert state.heat_locked

    rules.prepare_combat(match, 0.1)
    assert state.heat == 0
    assert not state.heat_locked
    assert rules.can_attack(_robot(match, HERO))


def test_q2_boundary_permanently_locks_and_cooling_does_not_unlock() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    rules = match.ruleset
    state = rules._robot_shooting_states[HERO]
    rules.allowed_projectiles_by_robot[HERO] = 2
    state.heat = 300

    rules.on_attack_committed(robot)

    assert state.heat == 400
    assert state.permanently_locked
    assert not state.heat_locked
    assert not rules.can_attack(robot)

    rules.prepare_combat(match, 20.0)
    assert state.heat == 0
    assert state.permanently_locked
    assert not rules.can_attack(robot)


def test_death_resets_heat_and_temporary_lock_but_not_allowance() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    rules = match.ruleset
    state = rules._robot_shooting_states[HERO]
    state.heat = 250
    state.heat_locked = True
    rules.allowed_projectiles_by_robot[HERO] = 5

    match.apply_damage(robot, robot.hp)
    match.update(0.01)

    state = rules._robot_shooting_states[HERO]
    assert state.heat == 0
    assert not state.heat_locked
    assert not state.permanently_locked
    assert rules.allowed_projectiles_by_robot[HERO] == 5

    match.update(5.0)
    assert robot.alive
    assert rules._robot_lifecycles[HERO].weak
    robot.position = (200.0, 300.0)
    match.update(0.0)
    assert not rules._robot_lifecycles[HERO].weak
    assert rules.can_attack(robot)


def test_death_and_respawn_do_not_clear_permanent_lock() -> None:
    match = _rules_lab_match()
    robot = _robot(match, HERO)
    rules = match.ruleset
    state = rules._robot_shooting_states[HERO]
    state.heat = 400
    state.permanently_locked = True
    rules.allowed_projectiles_by_robot[HERO] = 5

    match.apply_damage(robot, robot.hp)
    match.update(0.01)
    assert state.heat == 0
    assert state.permanently_locked
    assert rules.allowed_projectiles_by_robot[HERO] == 5

    match.update(5.0)
    assert robot.alive
    assert rules._robot_lifecycles[HERO].weak
    robot.position = (200.0, 300.0)
    match.update(0.0)

    assert not rules._robot_lifecycles[HERO].weak
    assert state.permanently_locked
    assert not rules.can_attack(robot)


def test_match_reset_clears_all_heat_locks_and_cooling_accumulator() -> None:
    match = _rules_lab_match()
    rules = match.ruleset
    rules._robot_shooting_states[HERO].heat = 250
    rules._robot_shooting_states[HERO].heat_locked = True
    rules._robot_shooting_states[SENTRY].permanently_locked = True
    rules._heat_cooling_accumulator = 0.05

    match.reset()

    assert rules._heat_cooling_accumulator == 0
    assert all(
        state.heat == 0
        and not state.heat_locked
        and not state.permanently_locked
        for state in rules._robot_shooting_states.values()
    )


def test_training_v0_has_no_shooting_heat_state_or_display() -> None:
    match = Match(load_match_config(default_scenario_path()))

    match.ruleset.prepare_combat(match, 10.0)

    assert match.ruleset.display_state is None
    assert not hasattr(match.ruleset, "_robot_shooting_states")
