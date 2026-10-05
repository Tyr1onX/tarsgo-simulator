from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match() -> Match:
    match = Match.from_scenario(SCENARIO)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _structure(match: Match, team_id: str, structure_type: str) -> Structure:
    return next(
        structure
        for structure in match.structures
        if structure.team == team_id and structure.type == structure_type
    )


def _activate_small(match: Match, robot_id: str = "tarsgo-infantry-1") -> bool:
    return match.ruleset.activate_small_energy_mechanism_buff(
        match,
        _robot(match, robot_id),
        match.elapsed_time,
    )


def test_small_energy_only_accepts_confirmed_activation_from_eligible_source() -> None:
    match = _match()
    rules = match.ruleset

    assert not _activate_small(match, "tarsgo-hero")
    assert not _activate_small(match, "tarsgo-engineer")
    assert _activate_small(match, "opponent-infantry-1")
    assert _activate_small(match, "tarsgo-sentry")
    assert not _activate_small(match, "tarsgo-infantry-1")

    activation = rules._energy_mechanism_buffs_by_team[RED][0]
    assert (activation.mechanism, activation.defense, activation.remaining) == (
        "small",
        0.25,
        45.0,
    )
    assert activation.experience_bonus_remaining == 1200.0
    assert rules._energy_mechanism_buffs_by_team[BLUE][0].mechanism == "small"


def test_small_energy_opportunities_accumulate_at_90_seconds_and_are_not_replayed() -> None:
    match = _match()

    assert _activate_small(match)
    match.update(45.0)
    assert match.ruleset._current_small_energy_mechanism_defense(RED) == 0.0

    match.update(44.999)
    assert not match.ruleset.activate_small_energy_mechanism_buff(
        match, _robot(match, "tarsgo-infantry-1"), 89.999
    )
    match.update(0.001)
    assert match.elapsed_time == pytest.approx(90.0)
    assert match.ruleset.activate_small_energy_mechanism_buff(
        match, _robot(match, "tarsgo-infantry-1"), 90.0
    )

    match.update(45.0)
    assert not match.ruleset.activate_small_energy_mechanism_buff(
        match, _robot(match, "tarsgo-sentry"), 90.0
    )
    match.update(45.0)
    assert match.elapsed_time == pytest.approx(180.0)
    assert not match.ruleset.activate_small_energy_mechanism_buff(
        match, _robot(match, "tarsgo-infantry-1"), 179.0
    )


def test_small_energy_confirmed_result_must_complete_within_20_seconds_and_phase() -> None:
    match = _match()
    match.update(19.999)
    assert match.ruleset.activate_small_energy_mechanism_buff(
        match, _robot(match, "tarsgo-infantry-1"), 0.0
    )

    expired = _match()
    expired.update(20.0)
    assert not expired.ruleset.activate_small_energy_mechanism_buff(
        expired, _robot(expired, "tarsgo-infantry-1"), 0.0
    )

    switched = _match()
    switched.update(180.0)
    assert not switched.ruleset.activate_small_energy_mechanism_buff(
        switched, _robot(switched, "tarsgo-infantry-1"), 179.0
    )


def test_small_energy_defense_is_team_scoped_for_robots_and_structures() -> None:
    match = _match()
    assert _activate_small(match)
    rules = match.ruleset

    for robot_id in (
        "tarsgo-hero",
        "tarsgo-engineer",
        "tarsgo-infantry-1",
        "tarsgo-infantry-2",
        "tarsgo-sentry",
        "tarsgo-drone",
    ):
        assert rules._effective_defense(_robot(match, robot_id)) == pytest.approx(0.25)
    for robot_id in (
        "opponent-hero",
        "opponent-engineer",
        "opponent-infantry-1",
        "opponent-infantry-2",
        "opponent-sentry",
        "opponent-drone",
    ):
        assert rules._effective_defense(_robot(match, robot_id)) == 0.0

    assert rules._effective_defense(_structure(match, RED, "base")) == pytest.approx(
        0.25
    )
    assert rules._effective_defense(
        _structure(match, RED, "outpost")
    ) == pytest.approx(0.25)
    assert rules._effective_defense(_structure(match, BLUE, "base")) == 0.0
    assert rules._effective_defense(_structure(match, BLUE, "outpost")) == 0.0

    status_by_robot = dict(rules.display_state.robot_statuses)
    assert "DEF 25%" in status_by_robot["tarsgo-infantry-1"]
    assert "DEF 25%" not in status_by_robot.get("opponent-infantry-1", "")


def test_small_energy_doubles_eligible_experience_up_to_team_cap() -> None:
    match = _match()
    assert _activate_small(match)
    rules = match.ruleset
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    drone = _robot(match, "tarsgo-drone")
    blue_hero = _robot(match, "opponent-hero")

    rules._grant_experience(hero.id, 1000.0)
    rules._grant_experience(infantry.id, 500.0)
    rules._grant_experience(drone.id, 10.0)
    rules._grant_experience(blue_hero.id, 75.0)

    assert rules._progression_by_robot[hero.id].experience == pytest.approx(2000.0)
    assert rules._progression_by_robot[infantry.id].experience == pytest.approx(700.0)
    assert rules._progression_by_robot[drone.id].experience == pytest.approx(10.0)
    assert rules._progression_by_robot[blue_hero.id].experience == pytest.approx(75.0)
    small_buff = rules._energy_mechanism_buffs_by_team[RED][0]
    assert small_buff.experience_bonus_remaining == 0.0


def test_small_energy_xp_reuses_drone_level_performance_and_existing_hud_progression() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    assert rules.start_drone_air_support(match, drone)
    assert _activate_small(match)

    rules._grant_experience(drone.id, 275.0)

    progression = rules._progression_by_robot[drone.id]
    assert (progression.level, progression.experience) == (2, 550.0)
    heat = rules._effective_heat_parameters(drone.id)
    assert (heat.heat_limit, heat.cooling_per_second) == (110, 30)
    displayed = next(
        row for row in rules.display_state.robot_progression if row[0] == drone.id
    )
    assert displayed[1:3] == (2, 550.0)


def test_small_energy_does_not_mutate_drone_air_support_radar_heat_or_allowance() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    assert rules.start_drone_air_support(match, drone)
    assert rules.set_radar_anti_drone_laser(BLUE, drone, True)
    rules._advance_radar_anti_drone(0.1)
    radar = rules._radar_anti_drone_by_robot[drone.id]
    support_before = (
        rules.drone_air_support_active(drone.id),
        rules.drone_air_support_available(drone.id),
    )
    radar_before = (
        radar.progress,
        radar.continuous_elapsed,
        radar.consecutive_ticks,
        radar.illuminated_by_team_id,
        radar.lock_remaining,
        radar.activations,
    )
    heat_before = (
        rules._shooting_heat_by_robot[drone.id].heat,
        rules._effective_heat_parameters(drone.id).heat_limit,
        rules._effective_heat_parameters(drone.id).cooling_per_second,
    )
    allowance_before = rules._projectile_allowance_by_robot[drone.id].allowed

    assert _activate_small(match)

    assert (
        rules.drone_air_support_active(drone.id),
        rules.drone_air_support_available(drone.id),
    ) == support_before
    assert (
        radar.progress,
        radar.continuous_elapsed,
        radar.consecutive_ticks,
        radar.illuminated_by_team_id,
        radar.lock_remaining,
        radar.activations,
    ) == radar_before
    assert (
        rules._shooting_heat_by_robot[drone.id].heat,
        rules._effective_heat_parameters(drone.id).heat_limit,
        rules._effective_heat_parameters(drone.id).cooling_per_second,
    ) == heat_before
    assert rules._projectile_allowance_by_robot[drone.id].allowed == allowance_before


def test_small_and_large_energy_share_timers_and_use_max_defense() -> None:
    match = _match()
    rules = match.ruleset
    assert _activate_small(match)
    assert rules.activate_large_energy_mechanism_buff(RED, 9.5, 5)
    hero = _robot(match, "tarsgo-hero")

    assert rules._effective_defense(hero) == pytest.approx(0.50)
    assert rules._effective_attack_multiplier(RED) == pytest.approx(3.0)

    match.update(30.0)

    assert rules._current_large_energy_mechanism_defense(RED) == 0.0
    assert rules._current_small_energy_mechanism_defense(RED) == pytest.approx(0.25)
    assert rules._effective_defense(hero) == pytest.approx(0.25)
    assert rules._effective_attack_multiplier(RED) == 1.0


def test_match_reset_clears_small_energy_buffs_opportunities_and_progression() -> None:
    match = _match()
    assert _activate_small(match)
    match.ruleset._grant_experience("tarsgo-hero", 25.0)

    match.reset()

    assert match.elapsed_time == 0.0
    assert match.ruleset._energy_mechanism_buffs_by_team == {RED: [], BLUE: []}
    assert match.ruleset._small_energy_mechanism_activation_times_by_team == {
        RED: [],
        BLUE: [],
    }
    assert all(
        state.experience == 0.0 and state.level == 1
        for state in match.ruleset._progression_by_robot.values()
    )
    assert _activate_small(match)


def test_rmuc_small_energy_full_match_smoke_with_large_energy_overlap() -> None:
    match = _match()
    rules = match.ruleset
    hero = _robot(match, "tarsgo-hero")

    assert _activate_small(match)
    rules._grant_experience(hero.id, 50.0)
    match.update(179.0)
    assert _activate_small(match)
    assert rules._current_small_energy_mechanism_defense(RED) == pytest.approx(0.25)

    match.update(1.0)
    assert rules.activate_large_energy_mechanism_buff(RED, 9.5, 5)
    assert rules._effective_defense(hero) == pytest.approx(0.50)
    match.update(match.time_limit - match.elapsed_time)

    assert match.elapsed_time == pytest.approx(420.0)
    assert len(rules._small_energy_mechanism_activation_times_by_team[RED]) == 2
    assert sum(_state.experience for _state in rules._progression_by_robot.values())
    assert rules._energy_mechanism_buffs_by_team == {RED: [], BLUE: []}
    assert rules._effective_attack_multiplier(RED) == 1.0
