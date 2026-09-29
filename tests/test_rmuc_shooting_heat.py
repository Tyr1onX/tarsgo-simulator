from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_match_config, load_rule_document
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RULES = REPOSITORY_ROOT / "configs" / "rules" / "rmuc-2026-region-v1.4.0.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match() -> Match:
    match = Match(load_match_config(SCENARIO))
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _heat(match: Match, robot_id: str):
    return match.ruleset._shooting_heat_by_robot[robot_id]


def _allowance(match: Match, robot_id: str):
    return match.ruleset._projectile_allowance_by_robot[robot_id]


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_initial_heat_state_and_dynamic_limits() -> None:
    match = _match()
    hero = match.ruleset._effective_heat_parameters("tarsgo-hero")
    infantry = match.ruleset._effective_heat_parameters("tarsgo-infantry-1")
    sentry = match.ruleset._effective_heat_parameters("tarsgo-sentry")

    assert (_heat(match, "tarsgo-hero").heat, hero.heat_limit) == (0.0, 100.0)
    assert (_heat(match, "tarsgo-infantry-1").heat, infantry.heat_limit) == (
        0.0,
        40.0,
    )
    assert (_heat(match, "tarsgo-sentry").heat, sentry.heat_limit) == (0.0, 260.0)
    assert "tarsgo-engineer" not in match.ruleset._shooting_heat_by_robot


def test_17mm_committed_shot_consumes_allowance_adds_heat_and_xp() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _allowance(match, infantry.id).allowed = 2

    match.ruleset.on_attack_committed(infantry)

    assert _allowance(match, infantry.id).allowed == 1
    assert _heat(match, infantry.id).heat == 10
    assert match.ruleset._progression_by_robot[infantry.id].experience == 1
    assert not _heat(match, infantry.id).temporarily_locked
    assert not _heat(match, infantry.id).permanently_locked


def test_hero_first_42mm_shot_reaches_q0_without_lock() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _allowance(match, hero.id).allowed = 2

    match.ruleset.on_attack_committed(hero)

    state = _heat(match, hero.id)
    assert state.heat == 100
    assert not state.temporarily_locked
    assert not state.permanently_locked
    assert _allowance(match, hero.id).allowed == 1
    assert match.ruleset._progression_by_robot[hero.id].experience == 10


def test_hero_second_42mm_shot_causes_temporary_lock() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _allowance(match, hero.id).allowed = 2

    match.ruleset.on_attack_committed(hero)
    match.ruleset.on_attack_committed(hero)

    state = _heat(match, hero.id)
    assert state.heat == 200
    assert state.temporarily_locked
    assert not state.permanently_locked
    assert _allowance(match, hero.id).allowed == 0
    assert match.ruleset._progression_by_robot[hero.id].experience == 20


def test_temporary_lock_blocks_commit_without_mutating_resources() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    target = _robot(match, "opponent-infantry-1")
    hero.position = (1200.0, 750.0)
    target.position = (1300.0, 750.0)
    hero.attack_cooldown = 0.0
    allowance = _allowance(match, hero.id)
    allowance.allowed = 5
    heat = _heat(match, hero.id)
    heat.heat = 150
    heat.temporarily_locked = True
    before_xp = match.ruleset._progression_by_robot[hero.id].experience

    match.update(0.01)

    assert allowance.allowed == 5
    assert heat.heat == 150
    assert match.ruleset._progression_by_robot[hero.id].experience == before_xp
    assert hero.attack_cooldown == 0.0


def test_temporary_lock_persists_below_q0_until_heat_reaches_zero() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 150
    state.temporarily_locked = True

    match.ruleset.prepare_combat(match, 5.0)

    assert state.heat == pytest.approx(50.0)
    assert state.temporarily_locked

    match.ruleset.prepare_combat(match, 2.5)

    assert state.heat == 0
    assert not state.temporarily_locked


def test_17mm_q2_equality_is_permanent_lock() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _allowance(match, infantry.id).allowed = 1
    state = _heat(match, infantry.id)
    state.heat = 130

    match.ruleset.on_attack_committed(infantry)

    assert state.heat == 140
    assert state.permanently_locked
    assert not state.temporarily_locked


def test_42mm_q2_equality_is_permanent_lock() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _allowance(match, hero.id).allowed = 1
    state = _heat(match, hero.id)
    state.heat = 200

    match.ruleset.on_attack_committed(hero)

    assert state.heat == 300
    assert state.permanently_locked
    assert not state.temporarily_locked


def test_permanent_lock_remains_when_heat_cools_to_zero() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 2
    state.permanently_locked = True
    _allowance(match, hero.id).allowed = 5

    match.ruleset.prepare_combat(match, 0.1)

    assert state.heat == 0
    assert state.permanently_locked
    assert not match.ruleset.can_attack(hero)


def test_cooling_runs_at_ten_hz() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 100

    match.ruleset.prepare_combat(match, 0.1)

    assert state.heat == pytest.approx(98.0)
    assert match.ruleset._heat_cooling_accumulator == pytest.approx(0.0)


def test_partial_cooling_tick_is_retained() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 100

    match.ruleset.prepare_combat(match, 0.09)
    assert state.heat == 100
    assert match.ruleset._heat_cooling_accumulator == pytest.approx(0.09)

    match.ruleset.prepare_combat(match, 0.01)
    assert state.heat == pytest.approx(98.0)
    assert match.ruleset._heat_cooling_accumulator == pytest.approx(0.0)


def test_large_dt_cooling_executes_all_full_ticks() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 100

    match.ruleset.prepare_combat(match, 0.35)

    assert state.heat == pytest.approx(94.0)
    assert match.ruleset._heat_cooling_accumulator == pytest.approx(0.05)


def test_prepare_combat_before_shot_prevents_same_frame_retroactive_cooling() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _allowance(match, infantry.id).allowed = 1

    match.ruleset.prepare_combat(match, 1.0)
    match.ruleset.on_attack_committed(infantry)

    assert _heat(match, infantry.id).heat == 10


def test_hero_level_up_changes_heat_limit_and_cooling_without_changing_heat() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 37

    before = match.ruleset._effective_heat_parameters(hero.id)
    match.ruleset._grant_experience(hero.id, 550)
    after = match.ruleset._effective_heat_parameters(hero.id)

    assert (before.heat_limit, before.cooling_per_second) == (100, 20)
    assert (after.heat_limit, after.cooling_per_second) == (102, 23)
    assert state.heat == 37


def test_infantry_level_up_changes_heat_limit_and_cooling() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")

    before = match.ruleset._effective_heat_parameters(infantry.id)
    match.ruleset._grant_experience(infantry.id, 550)
    after = match.ruleset._effective_heat_parameters(infantry.id)

    assert (before.heat_limit, before.cooling_per_second) == (40, 12)
    assert (after.heat_limit, after.cooling_per_second) == (48, 14)


def test_level_up_does_not_clear_existing_temporary_lock() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    match.ruleset._level_cap_by_team[RED] = 10
    state = _heat(match, infantry.id)
    state.heat = 80
    state.temporarily_locked = True
    _allowance(match, infantry.id).allowed = 5

    match.ruleset._grant_experience(infantry.id, 3300)

    assert match.ruleset._effective_heat_parameters(infantry.id).heat_limit == 88
    assert state.heat == 80
    assert state.temporarily_locked
    assert not match.ruleset.can_attack(infantry)


def test_same_shot_level_up_uses_pre_shot_heat_threshold() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    progression = match.ruleset._progression_by_robot[hero.id]
    progression.experience = 540
    progression.level = 1
    _allowance(match, hero.id).allowed = 1
    state = _heat(match, hero.id)
    state.heat = 200

    match.ruleset.on_attack_committed(hero)

    assert state.heat == 300
    assert state.permanently_locked
    assert progression.level == 2
    assert progression.experience == 550
    assert match.ruleset._effective_heat_parameters(hero.id).heat_limit == 102


def test_sentry_uses_fixed_automatic_heat_parameters() -> None:
    match = _match()
    sentry = match.ruleset._effective_heat_parameters("tarsgo-sentry")

    assert sentry.projectile_type == "17mm"
    assert sentry.heat_limit == 260
    assert sentry.cooling_per_second == 30
    assert sentry.permanent_threshold == 360


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-infantry-1", "tarsgo-sentry"],
)
def test_death_resets_heat_and_temporary_lock(robot_id: str) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    state = _heat(match, robot.id)
    state.heat = 123
    state.temporarily_locked = True

    assert match.apply_damage(robot, robot.hp, source_team_id=BLUE) > 0
    match.update(0)

    assert state.heat == 0
    assert not state.temporarily_locked
    assert not state.permanently_locked


def test_death_preserves_permanent_lock() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 250
    state.temporarily_locked = True
    state.permanently_locked = True

    assert match.apply_damage(hero, hero.hp, source_team_id=BLUE) == 150
    match.update(0)

    assert state.heat == 0
    assert not state.temporarily_locked
    assert state.permanently_locked


def test_reset_clears_heat_locks_and_cooling_accumulator() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _heat(match, hero.id)
    state.heat = 200
    state.temporarily_locked = True
    state.permanently_locked = True
    match.ruleset._heat_cooling_accumulator = 0.07

    match.reset()

    reset_state = _heat(match, hero.id)
    assert reset_state.heat == 0
    assert not reset_state.temporarily_locked
    assert not reset_state.permanently_locked
    assert match.ruleset._heat_cooling_accumulator == 0


def test_display_state_reuses_robot_shooting_heat_with_dynamic_limits() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    match.ruleset._grant_experience(hero.id, 550)
    _heat(match, hero.id).heat = 33
    _heat(match, hero.id).temporarily_locked = True

    display = {
        robot_id: (heat, limit, locked, permanent)
        for robot_id, heat, limit, locked, permanent
        in match.ruleset.display_state.robot_shooting_heat
    }

    assert display[hero.id] == (33, 102, True, False)
    assert display["tarsgo-sentry"] == (0, 260, False, False)
    assert "tarsgo-engineer" not in display


def test_heat_lock_and_allowance_gate_are_independent() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    allowance = _allowance(match, hero.id)
    state = _heat(match, hero.id)

    allowance.allowed = 0
    assert not match.ruleset.can_attack(hero)

    allowance.allowed = 5
    state.temporarily_locked = True
    assert not match.ruleset.can_attack(hero)

    state.temporarily_locked = False
    assert match.ruleset.can_attack(hero)


def test_shot_causing_lock_still_consumes_allowance_and_grants_xp() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    allowance = _allowance(match, hero.id)
    allowance.allowed = 5
    state = _heat(match, hero.id)
    state.heat = 100

    match.ruleset.on_attack_committed(hero)

    assert allowance.allowed == 4
    assert state.heat == 200
    assert state.temporarily_locked
    assert match.ruleset._progression_by_robot[hero.id].experience == 10


def test_no_target_means_no_allowance_heat_xp_or_cooldown_commit() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.attack_cooldown = 0.0
    hero.position = (100.0, 100.0)
    _allowance(match, hero.id).allowed = 1
    for robot in match.robots:
        if robot.team == BLUE:
            robot.position = (2700.0, 1400.0)

    match.update(0.01)

    assert _allowance(match, hero.id).allowed == 1
    assert _heat(match, hero.id).heat == 0
    assert match.ruleset._progression_by_robot[hero.id].experience == 0
    assert hero.attack_cooldown == 0.0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["shooting_heat"].__setitem__("detection_hz", 9),
        lambda data: data["shooting_heat"]["per_shot"].__setitem__("17mm", 11),
        lambda data: data["shooting_heat"]["per_shot"].__setitem__("42mm", 99),
        lambda data: data["shooting_heat"]["permanent_margin"].__setitem__(
            "17mm", 99
        ),
        lambda data: data["shooting_heat"]["permanent_margin"].__setitem__(
            "42mm", 199
        ),
        lambda data: data["shooting_heat"]["sentry"].__setitem__(
            "mode", "semi-automatic"
        ),
        lambda data: data["shooting_heat"]["sentry"].__setitem__("heat_limit", 259),
        lambda data: data["shooting_heat"]["sentry"].__setitem__(
            "cooling_per_second", 29
        ),
    ],
)
def test_shooting_heat_config_rejects_non_v140_values(
    tmp_path: Path,
    mutate,
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))
