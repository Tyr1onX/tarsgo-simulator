from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match() -> Match:
    match = Match.from_scenario(SCENARIO)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _zone_center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _place_in_resource(match: Match, engineer: Robot) -> None:
    engineer.position = _zone_center(match.ruleset._resource_zone_by_team[engineer.team])


def _place_in_assembly(match: Match, engineer: Robot) -> None:
    engineer.position = _zone_center(match.ruleset._assembly_zone_by_team[engineer.team])


def _pickup(match: Match, engineer: Robot) -> None:
    _place_in_resource(match, engineer)
    assert match.ruleset.pickup_energy_unit(match, engineer)


def _start(match: Match, engineer: Robot, difficulty: int) -> None:
    _place_in_assembly(match, engineer)
    assert match.ruleset.start_tech_core_assembly(match, engineer, difficulty)


def _confirm(match: Match, engineer: Robot) -> None:
    _place_in_assembly(match, engineer)
    assert match.ruleset.confirm_tech_core_assembly(match, engineer)


def _complete(match: Match, engineer: Robot, difficulty: int) -> None:
    _pickup(match, engineer)
    _start(match, engineer, difficulty)
    _confirm(match, engineer)


def _complete_d1(match: Match, engineer: Robot) -> None:
    _complete(match, engineer, 1)


def _complete_d2(match: Match, engineer: Robot) -> None:
    if match.ruleset._tech_core_by_team[engineer.team].completion_count_by_difficulty[1] == 0:
        _complete_d1(match, engineer)
    match.elapsed_time = max(match.elapsed_time, 60.0)
    _complete(match, engineer, 2)


def _complete_d3(match: Match, engineer: Robot) -> None:
    if match.ruleset._tech_core_by_team[engineer.team].completion_count_by_difficulty[2] == 0:
        _complete_d2(match, engineer)
    match.elapsed_time = max(match.elapsed_time, 120.0)
    _complete(match, engineer, 3)


def test_initial_tech_core_state_is_empty_and_cap_five() -> None:
    match = _match()

    assert match.ruleset._level_cap_by_team == {RED: 5, BLUE: 5}
    for team_id in (RED, BLUE):
        state = match.ruleset._tech_core_by_team[team_id]
        assert state.completion_count_by_difficulty == {1: 0, 2: 0, 3: 0}
        assert state.active_attempt is None

    for engineer_id in ("tarsgo-engineer", "opponent-engineer"):
        assert not match.ruleset._engineer_resources_by_id[
            engineer_id
        ].carrying_energy_unit


def test_synthetic_resource_and_assembly_zones_are_bound_per_team() -> None:
    match = _match()

    assert match.ruleset._resource_zone_by_team[RED].id == "red-resource"
    assert match.ruleset._resource_zone_by_team[BLUE].id == "blue-resource"
    assert match.ruleset._assembly_zone_by_team[RED].id == "red-assembly"
    assert match.ruleset._assembly_zone_by_team[BLUE].id == "blue-assembly"


def test_engineer_can_pickup_once_only_in_own_resource_zone() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _place_in_resource(match, engineer)
    assert match.ruleset.pickup_energy_unit(match, engineer)
    assert not match.ruleset.pickup_energy_unit(match, engineer)

    state = match.ruleset._engineer_resources_by_id[engineer.id]
    assert state.carrying_energy_unit


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-infantry-1", "tarsgo-sentry"],
)
def test_non_engineer_cannot_pickup_energy_unit(robot_id: str) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    robot.position = _zone_center(match.ruleset._resource_zone_by_team[RED])

    assert not match.ruleset.pickup_energy_unit(match, robot)


def test_engineer_cannot_pickup_from_enemy_resource_zone() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _zone_center(match.ruleset._resource_zone_by_team[BLUE])

    assert not match.ruleset.pickup_energy_unit(match, engineer)


def test_difficulty_one_can_start_immediately_and_confirm_without_cap_change() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d1(match, engineer)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.completion_count_by_difficulty == {1: 1, 2: 0, 3: 0}
    assert state.active_attempt is None
    assert match.ruleset._level_cap_by_team[RED] == 5
    assert not match.ruleset._engineer_resources_by_id[
        engineer.id
    ].carrying_energy_unit


def test_difficulty_two_requires_sixty_seconds_after_d1() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d1(match, engineer)

    _pickup(match, engineer)
    _place_in_assembly(match, engineer)
    match.elapsed_time = 59.99
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 2)

    match.elapsed_time = 60.0
    assert match.ruleset.start_tech_core_assembly(match, engineer, 2)


def test_difficulty_two_requires_difficulty_one_even_long_after_time_gate() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    match.elapsed_time = 300.0
    _pickup(match, engineer)
    _place_in_assembly(match, engineer)

    assert not match.ruleset.start_tech_core_assembly(match, engineer, 2)


def test_difficulty_three_requires_120_seconds_after_d2() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d2(match, engineer)

    _pickup(match, engineer)
    _place_in_assembly(match, engineer)
    match.elapsed_time = 119.99
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 3)

    match.elapsed_time = 120.0
    assert match.ruleset.start_tech_core_assembly(match, engineer, 3)


def test_difficulty_three_requires_difficulty_two_even_if_d1_is_complete() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d1(match, engineer)
    match.elapsed_time = 400.0

    _pickup(match, engineer)
    _place_in_assembly(match, engineer)

    assert not match.ruleset.start_tech_core_assembly(match, engineer, 3)


def test_first_difficulty_two_completion_unlocks_cap_seven() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d2(match, engineer)

    assert match.ruleset._tech_core_by_team[RED].completion_count_by_difficulty[2] == 1
    assert match.ruleset._level_cap_by_team[RED] == 7


def test_repeated_difficulty_two_increments_count_without_changing_cap_again() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d2(match, engineer)

    _complete(match, engineer, 2)

    assert match.ruleset._tech_core_by_team[RED].completion_count_by_difficulty[2] == 2
    assert match.ruleset._level_cap_by_team[RED] == 7


def test_first_difficulty_three_completion_unlocks_cap_ten() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d3(match, engineer)

    assert match.ruleset._tech_core_by_team[RED].completion_count_by_difficulty[3] == 1
    assert match.ruleset._level_cap_by_team[RED] == 10


def test_cap_unlock_does_not_auto_level_or_restore_lost_experience() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    hero = _robot(match, "tarsgo-hero")

    match.ruleset._grant_experience(hero.id, 99999)
    progression = match.ruleset._progression_by_robot[hero.id]
    assert (progression.level, progression.experience) == (5, 2200)

    match.ruleset._grant_experience(hero.id, 99999)
    assert (progression.level, progression.experience) == (5, 2200)

    _complete_d2(match, engineer)

    assert match.ruleset._level_cap_by_team[RED] == 7
    assert (progression.level, progression.experience) == (5, 2200)
    assert hero.max_hp == 210


def test_experience_resumes_after_difficulty_two_unlock() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    hero = _robot(match, "tarsgo-hero")

    match.ruleset._grant_experience(hero.id, 2200)
    _complete_d2(match, engineer)
    match.ruleset._grant_experience(hero.id, 550)

    progression = match.ruleset._progression_by_robot[hero.id]
    performance = match.ruleset._effective_performance(hero.id)
    assert (progression.level, progression.experience) == (6, 2750)
    assert (hero.hp, hero.max_hp) == (225, 225)
    assert (
        performance.chassis_power_limit,
        performance.heat_limit,
        performance.cooling_per_second,
    ) == (75, 110, 35)


def test_difficulty_three_unlock_allows_progression_to_level_ten() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    hero = _robot(match, "tarsgo-hero")

    match.ruleset._grant_experience(hero.id, 2200)
    _complete_d3(match, engineer)
    match.ruleset._grant_experience(hero.id, 2800)

    progression = match.ruleset._progression_by_robot[hero.id]
    assert match.ruleset._level_cap_by_team[RED] == 10
    assert (progression.level, progression.experience) == (10, 5000)
    assert hero.max_hp == 300


def test_active_attempt_cannot_switch_difficulty() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d1(match, engineer)
    match.elapsed_time = 60.0
    _pickup(match, engineer)
    _start(match, engineer, 2)

    assert not match.ruleset.start_tech_core_assembly(match, engineer, 1)
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 2)
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 3)


def test_start_requires_energy_unit_and_assembly_zone() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _place_in_assembly(match, engineer)

    assert not match.ruleset.start_tech_core_assembly(match, engineer, 1)

    _pickup(match, engineer)
    engineer.position = (1000.0, 1000.0)
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 1)


def test_difficulty_four_is_explicitly_unsupported() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _pickup(match, engineer)
    _place_in_assembly(match, engineer)
    match.elapsed_time = 400.0

    assert not match.ruleset.start_tech_core_assembly(match, engineer, 4)


def test_continuous_fifteen_seconds_outside_assembly_fails_attempt() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _pickup(match, engineer)
    _start(match, engineer, 1)

    engineer.position = (1400.0, 750.0)
    match.update(14.9)
    state = match.ruleset._tech_core_by_team[RED]
    assert state.active_attempt is not None
    assert state.active_attempt.outside_zone_elapsed == pytest.approx(14.9)

    match.update(0.1)

    assert state.active_attempt is None
    assert not match.ruleset._engineer_resources_by_id[
        engineer.id
    ].carrying_energy_unit
    assert state.completion_count_by_difficulty[1] == 0


def test_returning_to_assembly_resets_outside_timer() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _pickup(match, engineer)
    _start(match, engineer, 1)

    engineer.position = (1400.0, 750.0)
    match.update(10.0)
    state = match.ruleset._tech_core_by_team[RED]
    assert state.active_attempt is not None
    assert state.active_attempt.outside_zone_elapsed == pytest.approx(10.0)

    _place_in_assembly(match, engineer)
    match.update(0.1)
    assert state.active_attempt is not None
    assert state.active_attempt.outside_zone_elapsed == 0

    engineer.position = (1400.0, 750.0)
    match.update(10.0)
    assert state.active_attempt is not None
    assert state.active_attempt.outside_zone_elapsed == pytest.approx(10.0)


def test_engineer_death_fails_active_attempt_and_clears_energy_unit() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    attacker = _robot(match, "opponent-hero")
    _pickup(match, engineer)
    _start(match, engineer, 1)

    assert match.apply_damage(engineer, engineer.hp, source_robot=attacker) == 250
    match.update(0)

    state = match.ruleset._tech_core_by_team[RED]
    assert not engineer.alive
    assert state.active_attempt is None
    assert state.completion_count_by_difficulty == {1: 0, 2: 0, 3: 0}
    assert match.ruleset._level_cap_by_team[RED] == 5
    assert not match.ruleset._engineer_resources_by_id[
        engineer.id
    ].carrying_energy_unit


def test_engineer_death_before_start_uses_synthetic_recovery_simplification() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    attacker = _robot(match, "opponent-hero")
    _pickup(match, engineer)

    assert match.apply_damage(engineer, engineer.hp, source_robot=attacker) == 250
    match.update(0)

    assert not match.ruleset._engineer_resources_by_id[
        engineer.id
    ].carrying_energy_unit
    assert match.ruleset._tech_core_by_team[RED].active_attempt is None


def test_repeat_order_tracks_counts_and_keeps_cap_ten() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d1(match, engineer)
    match.elapsed_time = 60.0
    _complete(match, engineer, 2)
    match.elapsed_time = 120.0
    _complete(match, engineer, 3)
    _complete(match, engineer, 2)
    _complete(match, engineer, 1)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.completion_count_by_difficulty == {1: 2, 2: 2, 3: 1}
    assert match.ruleset._level_cap_by_team[RED] == 10


def test_reward_metadata_is_loaded_but_only_level_cap_is_consumed() -> None:
    match = _match()
    rules = match.ruleset

    assert rules._tech_core_difficulties[1].first_periodic_gold_per_10s == 50
    assert rules._tech_core_difficulties[1].repeat_periodic_gold_per_10s == 5
    assert rules._tech_core_difficulties[2].first_level_cap == 7
    assert rules._tech_core_difficulties[2].first_periodic_gold_per_10s == 25
    assert rules._tech_core_difficulties[2].repeat_periodic_gold_per_10s == 10
    assert rules._tech_core_difficulties[3].first_level_cap == 10
    assert rules._tech_core_difficulties[3].first_defense_bonus == pytest.approx(0.25)
    assert rules._tech_core_difficulties[3].first_periodic_gold_per_10s == 25
    assert rules._tech_core_difficulties[3].repeat_periodic_gold_per_10s == 15

    assert match.ruleset.display_state.coins == ()


def test_display_state_exposes_minimal_tech_core_and_energy_unit_status() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _pickup(match, engineer)
    _start(match, engineer, 1)
    engineer.position = (1400.0, 750.0)
    match.update(3.0)

    display = match.ruleset.display_state
    tech_core = {
        team_id: (cap, d1, d2, d3, active, outside)
        for team_id, cap, d1, d2, d3, active, outside in display.tech_core_status
    }
    energy_units = dict(display.engineer_energy_units)

    assert tech_core[RED] == (5, 0, 0, 0, 1, pytest.approx(3.0))
    assert energy_units[engineer.id]


def test_reset_clears_tech_core_state_energy_unit_and_restores_cap_five() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    hero = _robot(match, "tarsgo-hero")

    _complete_d3(match, engineer)
    match.ruleset._grant_experience(hero.id, 2800)
    _pickup(match, engineer)
    _start(match, engineer, 1)

    match.reset()

    assert match.ruleset._level_cap_by_team == {RED: 5, BLUE: 5}
    for state in match.ruleset._tech_core_by_team.values():
        assert state.completion_count_by_difficulty == {1: 0, 2: 0, 3: 0}
        assert state.active_attempt is None
    for resource_state in match.ruleset._engineer_resources_by_id.values():
        assert not resource_state.carrying_energy_unit
    progression = match.ruleset._progression_by_robot["tarsgo-hero"]
    assert (progression.level, progression.experience) == (1, 0.0)
