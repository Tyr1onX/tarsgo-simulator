from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_match_config, load_rule_document
from tarsgo_simulator.core.events import MatchEvent, MatchEventType
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure
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


def _structure(match: Match, team_id: str, structure_type: str) -> Structure:
    return next(
        structure
        for structure in match.structures
        if structure.team == team_id and structure.type == structure_type
    )


def _progress(match: Match, robot_id: str):
    return match.ruleset._progression_by_robot[robot_id]


def _destroy_outpost_without_personal_xp(match: Match, team_id: str) -> None:
    outpost = _structure(match, team_id, "outpost")
    attacker_team = BLUE if team_id == RED else RED
    match.apply_damage(outpost, outpost.hp, source_team_id=attacker_team)
    match.update(0)


def _kill_event(
    match: Match,
    attacker_id: str,
    victim_id: str,
) -> MatchEvent:
    attacker = _robot(match, attacker_id)
    victim = _robot(match, victim_id)
    return MatchEvent(
        type=MatchEventType.ROBOT_DESTROYED,
        time=match.elapsed_time,
        robot_id=victim.id,
        team_id=victim.team,
        attacker_id=attacker.id,
        attacker_team_id=attacker.team,
    )


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_progression_state_exists_only_for_hero_and_infantry_and_uses_float() -> None:
    match = _match()

    assert len(match.ruleset._progression_by_robot) == 6
    for robot in match.robots:
        if robot.type in {"hero", "infantry"}:
            state = _progress(match, robot.id)
            assert state.level == 1
            assert state.experience == 0.0
            assert isinstance(state.experience, float)
        else:
            assert robot.id not in match.ruleset._progression_by_robot


def test_default_performance_selection_and_level_one_stats() -> None:
    match = _match()
    rules = match.ruleset

    assert rules._hero_profile == "long-range-priority"
    assert rules._infantry_chassis_profile == "hp-priority"
    assert rules._infantry_launcher_profile == "cooling-priority"

    hero = _robot(match, "tarsgo-hero")
    hero_performance = rules._effective_performance(hero.id)
    assert (hero.hp, hero.max_hp) == (150, 150)
    assert (
        hero_performance.max_hp,
        hero_performance.chassis_power_limit,
        hero_performance.heat_limit,
        hero_performance.cooling_per_second,
    ) == (150, 50, 100, 20)

    infantry = _robot(match, "tarsgo-infantry-1")
    infantry_performance = rules._effective_performance(infantry.id)
    assert (infantry.hp, infantry.max_hp) == (200, 200)
    assert (
        infantry_performance.max_hp,
        infantry_performance.chassis_power_limit,
        infantry_performance.heat_limit,
        infantry_performance.cooling_per_second,
    ) == (200, 45, 40, 12)

    assert rules.robot_parameters("hero").max_hp == 150
    assert rules.robot_parameters("infantry").max_hp == 200


def test_engineer_and_sentry_remain_fixed_outside_performance_system() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    sentry = _robot(match, "tarsgo-sentry")

    assert (engineer.max_hp, match.ruleset._chassis_power_limit_by_type["engineer"]) == (
        250,
        120,
    )
    assert sentry.max_hp == 400
    assert engineer.id not in match.ruleset._progression_by_robot
    assert sentry.id not in match.ruleset._progression_by_robot


def test_all_level_one_to_ten_tables_are_loaded_including_cooling_lv9_114() -> None:
    rules = _match().ruleset
    expected_levels = set(range(1, 11))

    assert set(rules._level_thresholds) == expected_levels
    assert rules._level_thresholds == {
        1: 0.0,
        2: 550.0,
        3: 1100.0,
        4: 1650.0,
        5: 2200.0,
        6: 2750.0,
        7: 3300.0,
        8: 3850.0,
        9: 4400.0,
        10: 5000.0,
    }
    for table in rules._hero_performance.values():
        assert set(table) == expected_levels
    for table in rules._infantry_chassis_performance.values():
        assert set(table) == expected_levels
    for table in rules._infantry_launcher_performance.values():
        assert set(table) == expected_levels

    assert rules._infantry_launcher_performance["cooling-priority"][9][
        "heat_limit"
    ] == 114


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["experience"]["level_thresholds"].pop(),
        lambda data: data["experience"]["level_thresholds"].__setitem__(
            9, {"level": 9, "experience": 5000}
        ),
        lambda data: data["performance"]["infantry"]["launcher"][
            "cooling-priority"
        ][8].__setitem__("heat_limit", -1),
    ],
)
def test_level_tables_reject_missing_duplicate_or_negative_rows(
    tmp_path: Path, mutate
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))


def test_initial_level_cap_is_five_for_both_teams() -> None:
    match = _match()

    assert match.ruleset._level_cap_by_team == {RED: 5, BLUE: 5}


def test_shot_experience_uses_existing_attack_committed_hook() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    sentry = _robot(match, "tarsgo-sentry")
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 1
    match.ruleset._projectile_allowance_by_robot[infantry.id].allowed = 1

    match.ruleset.on_attack_committed(hero)
    match.ruleset.on_attack_committed(infantry)
    match.ruleset.on_attack_committed(sentry)

    assert _progress(match, hero.id).experience == 10
    assert _progress(match, infantry.id).experience == 1
    assert sentry.id not in match.ruleset._progression_by_robot


def test_no_legal_attack_target_means_no_shot_experience() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.attack_cooldown = 0.0
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 1
    hero.position = (100.0, 100.0)
    for robot in match.robots:
        if robot.team == BLUE:
            robot.position = (2700.0, 1400.0)

    match.update(0.01)

    assert _progress(match, hero.id).experience == 0


def test_robot_damage_experience_uses_actual_hp_loss() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    target = _robot(match, "opponent-infantry-1")

    assert match.apply_damage(target, 20, source_robot=hero) == 20
    match.update(0)

    assert _progress(match, hero.id).experience == 80


def test_outpost_damage_experience_uses_actual_hp_loss() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    outpost = _structure(match, BLUE, "outpost")

    assert match.apply_damage(outpost, 100, source_robot=hero) == 100
    match.update(0)

    assert _progress(match, hero.id).experience == 200


@pytest.mark.parametrize(
    ("damage", "expected"),
    [(1, 1), (2, 1), (3, 2)],
)
def test_base_damage_experience_rounds_odd_damage_up(
    damage: int, expected: int
) -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _destroy_outpost_without_personal_xp(match, BLUE)
    base = _structure(match, BLUE, "base")

    assert match.apply_damage(base, damage, source_robot=hero) == damage
    match.update(0)

    assert _progress(match, hero.id).experience == expected


def test_invincible_base_produces_no_damage_event_or_damage_experience() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    base = _structure(match, BLUE, "base")

    assert match.apply_damage(base, 200, source_robot=hero) == 0
    match.update(0)

    assert _progress(match, hero.id).experience == 0


def test_outpost_overkill_experience_uses_only_actual_five_hp() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    outpost = _structure(match, BLUE, "outpost")
    outpost.hp = 5

    assert match.apply_damage(outpost, 200, source_robot=hero) == 5
    match.update(0)

    assert _progress(match, hero.id).experience == 10


def test_hero_level_two_increases_current_hp_only_by_max_hp_delta() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.hp = 100

    match.ruleset._grant_experience(hero.id, 550)

    state = _progress(match, hero.id)
    assert (state.level, state.experience) == (2, 550)
    assert (hero.hp, hero.max_hp) == (115, 165)
    performance = match.ruleset._effective_performance(hero.id)
    assert (
        performance.chassis_power_limit,
        performance.heat_limit,
        performance.cooling_per_second,
    ) == (55, 102, 23)


def test_infantry_level_two_uses_selected_chassis_and_launcher_tables() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")

    match.ruleset._grant_experience(infantry.id, 550)

    state = _progress(match, infantry.id)
    performance = match.ruleset._effective_performance(infantry.id)
    assert (state.level, state.experience) == (2, 550)
    assert (infantry.hp, infantry.max_hp) == (225, 225)
    assert (
        performance.chassis_power_limit,
        performance.heat_limit,
        performance.cooling_per_second,
    ) == (50, 48, 14)


def test_one_large_experience_grant_can_cross_multiple_levels() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.hp = 100

    match.ruleset._grant_experience(hero.id, 1300)

    state = _progress(match, hero.id)
    assert (state.level, state.experience) == (3, 1300)
    assert (hero.hp, hero.max_hp) == (130, 180)


def test_current_level_cap_stops_experience_exactly_at_level_five_threshold() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    target = _robot(match, "opponent-infantry-1")

    match.ruleset._grant_experience(hero.id, 99999)
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 1
    state = _progress(match, hero.id)
    assert (state.level, state.experience) == (5, 2200)

    match.ruleset.on_attack_committed(hero)
    assert state.experience == 2200

    match.apply_damage(target, 1, source_robot=hero)
    match.update(0)
    assert state.experience == 2200

    match.ruleset._grant_kill_experience(
        _kill_event(match, hero.id, target.id)
    )
    assert state.experience == 2200


def test_level_five_effective_stats_match_selected_profiles() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")

    match.ruleset._grant_experience(hero.id, 2200)
    match.ruleset._grant_experience(infantry.id, 2200)

    hero_stats = match.ruleset._effective_performance(hero.id)
    infantry_stats = match.ruleset._effective_performance(infantry.id)
    assert (
        hero_stats.max_hp,
        hero_stats.chassis_power_limit,
        hero_stats.heat_limit,
        hero_stats.cooling_per_second,
    ) == (210, 70, 108, 32)
    assert (
        infantry_stats.max_hp,
        infantry_stats.chassis_power_limit,
        infantry_stats.heat_limit,
        infantry_stats.cooling_per_second,
    ) == (300, 65, 72, 20)


def test_kill_experience_equal_level_uses_base_factor_only() -> None:
    match = _match()
    attacker = _robot(match, "tarsgo-infantry-1")
    victim = _robot(match, "opponent-infantry-1")
    match.ruleset._level_cap_by_team[RED] = 10
    match.ruleset._level_cap_by_team[BLUE] = 10
    match.ruleset._grant_experience(attacker.id, 550)
    match.ruleset._grant_experience(victim.id, 550)

    match.ruleset._grant_kill_experience(_kill_event(match, attacker.id, victim.id))

    assert _progress(match, attacker.id).experience == 650


def test_kill_experience_higher_level_victim_matches_official_example() -> None:
    match = _match()
    attacker = _robot(match, "tarsgo-infantry-1")
    victim = _robot(match, "opponent-infantry-1")
    match.ruleset._level_cap_by_team[RED] = 10
    match.ruleset._level_cap_by_team[BLUE] = 10
    match.ruleset._grant_experience(attacker.id, 550)
    match.ruleset._grant_experience(victim.id, 2750)

    match.ruleset._grant_kill_experience(_kill_event(match, attacker.id, victim.id))

    assert _progress(match, attacker.id).experience == 1090


def test_kill_experience_attacker_higher_than_victim_uses_zero_level_difference() -> None:
    match = _match()
    attacker = _robot(match, "tarsgo-infantry-1")
    victim = _robot(match, "opponent-infantry-1")
    match.ruleset._level_cap_by_team[RED] = 10
    match.ruleset._level_cap_by_team[BLUE] = 10
    match.ruleset._grant_experience(attacker.id, 2750)
    match.ruleset._grant_experience(victim.id, 550)

    match.ruleset._grant_kill_experience(_kill_event(match, attacker.id, victim.id))

    assert _progress(match, attacker.id).experience == 2850


@pytest.mark.parametrize("victim_id", ["opponent-engineer", "opponent-sentry"])
def test_engineer_and_sentry_victims_are_treated_as_level_one(victim_id: str) -> None:
    match = _match()
    attacker = _robot(match, "tarsgo-infantry-1")

    match.ruleset._grant_kill_experience(_kill_event(match, attacker.id, victim_id))

    assert _progress(match, attacker.id).experience == 50


def test_sentry_damage_still_counts_team_attack_damage_but_never_personal_xp() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    target = _robot(match, "opponent-infantry-1")

    assert match.apply_damage(target, 20, source_robot=sentry) == 20
    match.update(0)

    assert match.ruleset.attack_damage_by_team[RED] == 20
    assert sentry.id not in match.ruleset._progression_by_robot


def test_dead_robot_level_change_updates_max_hp_without_reviving() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.alive = False
    hero.hp = 0

    match.ruleset._grant_experience(hero.id, 550)

    assert _progress(match, hero.id).level == 2
    assert hero.max_hp == 165
    assert hero.hp == 0
    assert not hero.alive


def test_reset_clears_progression_and_reapplies_level_one_performance() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    match.ruleset._grant_experience(hero.id, 2200)
    match.ruleset._grant_experience(infantry.id, 1100)
    _destroy_outpost_without_personal_xp(match, RED)

    match.reset()

    for robot_id in (
        "tarsgo-hero",
        "tarsgo-infantry-1",
        "tarsgo-infantry-2",
        "opponent-hero",
        "opponent-infantry-1",
        "opponent-infantry-2",
    ):
        state = _progress(match, robot_id)
        assert (state.level, state.experience) == (1, 0.0)

    assert (_robot(match, "tarsgo-hero").hp, _robot(match, "tarsgo-hero").max_hp) == (
        150,
        150,
    )
    assert (
        _robot(match, "tarsgo-infantry-1").hp,
        _robot(match, "tarsgo-infantry-1").max_hp,
    ) == (200, 200)
    assert _structure(match, RED, "base").hp == 5000
    assert _structure(match, RED, "outpost").hp == 1500
    assert _structure(match, RED, "outpost").alive
    assert not match.ruleset._team_states[RED].outpost_ever_destroyed


def test_display_state_exposes_progression_and_effective_parameters() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    match.ruleset._grant_experience(hero.id, 550)

    display = match.ruleset.display_state
    progression = {
        robot_id: (level, experience, cap)
        for robot_id, level, experience, cap in display.robot_progression
    }
    performance = {
        robot_id: (max_hp, power, heat, cooling)
        for robot_id, max_hp, power, heat, cooling in display.robot_performance
    }

    assert progression[hero.id] == (2, 550, 5)
    assert performance[hero.id] == (165, 55, 102, 23)
