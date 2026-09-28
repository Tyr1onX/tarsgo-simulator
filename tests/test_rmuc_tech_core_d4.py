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


def _give_credits(match: Match, engineer: Robot, count: int = 2) -> None:
    _place_in_resource(match, engineer)
    state = match.ruleset._engineer_resources_by_id[engineer.id]
    while state.energy_unit_credits < count:
        assert match.ruleset.pickup_energy_unit(match, engineer)
    _place_in_assembly(match, engineer)


def _unlock_d4(match: Match, team_id: str) -> None:
    state = match.ruleset._tech_core_by_team[team_id]
    state.completion_count_by_difficulty[1] = 1
    state.completion_count_by_difficulty[2] = 1
    state.completion_count_by_difficulty[3] = 1
    match.ruleset._level_cap_by_team[team_id] = 10


def _prepare_d4(match: Match, engineer: Robot, *, elapsed: float = 180.0) -> None:
    _unlock_d4(match, engineer.team)
    match.elapsed_time = elapsed
    _give_credits(match, engineer, 2)


def _start_d4(match: Match, engineer: Robot) -> None:
    assert match.ruleset.start_tech_core_assembly(match, engineer, 4)


def _confirm_pair(match: Match, engineer: Robot, step: int) -> None:
    assert match.ruleset.confirm_d4_step(match, engineer, "own", step)
    assert match.ruleset.confirm_d4_step(match, engineer, "opponent", step)


def _advance_to_step(match: Match, engineer: Robot, step: int) -> None:
    state = match.ruleset._tech_core_by_team[engineer.team]
    while state.d4_attempt is not None and state.d4_attempt.current_step < step:
        _confirm_pair(match, engineer, state.d4_attempt.current_step)


def _complete_d4(match: Match, engineer: Robot) -> None:
    for step in range(1, 7):
        _confirm_pair(match, engineer, step)


def _start_blue_d2(match: Match) -> Robot:
    engineer = _robot(match, "opponent-engineer")
    state = match.ruleset._tech_core_by_team[BLUE]
    state.completion_count_by_difficulty[1] = 1
    match.elapsed_time = max(match.elapsed_time, 180.0)
    _give_credits(match, engineer, 1)
    assert match.ruleset.start_tech_core_assembly(match, engineer, 2)
    return engineer


def test_d4_time_gate_requires_180_seconds() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _unlock_d4(match, RED)
    _give_credits(match, engineer, 2)

    match.elapsed_time = 179.99
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 4)

    match.elapsed_time = 180.0
    assert match.ruleset.start_tech_core_assembly(match, engineer, 4)


def test_d4_requires_d3_prerequisite() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    state = match.ruleset._tech_core_by_team[RED]
    state.completion_count_by_difficulty[1] = 1
    state.completion_count_by_difficulty[2] = 1
    match.elapsed_time = 300.0
    _give_credits(match, engineer, 2)

    assert not match.ruleset.start_tech_core_assembly(match, engineer, 4)


def test_d4_requires_two_energy_unit_credits() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _unlock_d4(match, RED)
    match.elapsed_time = 180.0
    _place_in_assembly(match, engineer)

    assert not match.ruleset.start_tech_core_assembly(match, engineer, 4)

    _give_credits(match, engineer, 1)
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 4)

    _give_credits(match, engineer, 2)
    assert match.ruleset.start_tech_core_assembly(match, engineer, 4)
    assert match.ruleset._engineer_resources_by_id[engineer.id].energy_unit_credits == 0


def test_d1_reserves_one_credit_without_clearing_second_credit() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _give_credits(match, engineer, 2)

    assert match.ruleset.start_tech_core_assembly(match, engineer, 1)

    assert match.ruleset._engineer_resources_by_id[engineer.id].energy_unit_credits == 1
    assert match.ruleset.confirm_tech_core_assembly(match, engineer)
    assert match.ruleset._engineer_resources_by_id[engineer.id].energy_unit_credits == 1


def test_d4_immediately_activates_when_opponent_has_no_attempt() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)

    _start_d4(match, engineer)

    coordinator = match.ruleset._d4_coordinator
    state = match.ruleset._tech_core_by_team[RED]
    assert coordinator.active_team_id == RED
    assert coordinator.pending_team_id is None
    assert state.d4_attempt is not None
    assert state.d4_attempt.activated_at == pytest.approx(180.0)
    assert state.d4_attempt.current_step == 1
    assert not state.d4_attempt.priority_takeover


def test_active_d4_blocks_other_team_d4_and_d1_to_d3() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    blue = _robot(match, "opponent-engineer")
    _prepare_d4(match, red)
    _start_d4(match, red)

    _unlock_d4(match, BLUE)
    _give_credits(match, blue, 2)

    assert not match.ruleset.start_tech_core_assembly(match, blue, 4)
    assert not match.ruleset.start_tech_core_assembly(match, blue, 1)
    assert not match.ruleset.start_tech_core_assembly(match, blue, 2)
    assert not match.ruleset.start_tech_core_assembly(match, blue, 3)


def test_priority_request_waits_full_fifteen_seconds_without_starting_total_timer() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    blue = _start_blue_d2(match)
    _unlock_d4(match, RED)
    _give_credits(match, red, 2)

    assert match.ruleset.start_tech_core_assembly(match, red, 4)

    coordinator = match.ruleset._d4_coordinator
    assert coordinator.pending_team_id == RED
    assert coordinator.active_team_id is None
    assert coordinator.priority_buffer_remaining == pytest.approx(15.0)
    assert match.ruleset._tech_core_by_team[BLUE].active_attempt is not None
    assert match.ruleset._tech_core_by_team[RED].d4_attempt is None

    match.update(14.9)

    assert coordinator.pending_team_id == RED
    assert coordinator.active_team_id is None
    assert coordinator.priority_buffer_remaining == pytest.approx(0.1)
    assert match.ruleset._tech_core_by_team[BLUE].active_attempt is not None
    assert match.ruleset._tech_core_by_team[RED].d4_attempt is None


def test_priority_buffer_expiry_forces_opponent_attempt_out_and_activates_d4() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    _start_blue_d2(match)
    _unlock_d4(match, RED)
    _give_credits(match, red, 2)
    requested_at = match.elapsed_time
    assert match.ruleset.start_tech_core_assembly(match, red, 4)

    match.update(15.0)

    coordinator = match.ruleset._d4_coordinator
    red_state = match.ruleset._tech_core_by_team[RED]
    assert coordinator.pending_team_id is None
    assert coordinator.active_team_id == RED
    assert match.ruleset._tech_core_by_team[BLUE].active_attempt is None
    assert red_state.d4_attempt is not None
    assert red_state.d4_attempt.activated_at == pytest.approx(requested_at + 15.0)
    assert red_state.d4_attempt.priority_takeover


def test_opponent_finishing_early_does_not_shorten_priority_buffer() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    blue = _start_blue_d2(match)
    _unlock_d4(match, RED)
    _give_credits(match, red, 2)
    requested_at = match.elapsed_time
    assert match.ruleset.start_tech_core_assembly(match, red, 4)

    match.update(5.0)
    assert match.ruleset.confirm_tech_core_assembly(match, blue)
    assert match.ruleset._d4_coordinator.pending_team_id == RED
    assert match.ruleset._d4_coordinator.priority_buffer_remaining == pytest.approx(10.0)

    match.update(10.0)

    attempt = match.ruleset._tech_core_by_team[RED].d4_attempt
    assert attempt is not None
    assert attempt.activated_at == pytest.approx(requested_at + 15.0)
    assert attempt.priority_takeover


def test_large_dt_priority_buffer_uses_exact_activation_time() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    _start_blue_d2(match)
    _unlock_d4(match, RED)
    _give_credits(match, red, 2)
    requested_at = match.elapsed_time
    assert match.ruleset.start_tech_core_assembly(match, red, 4)

    match.update(20.0)

    attempt = match.ruleset._tech_core_by_team[RED].d4_attempt
    assert attempt is not None
    assert attempt.activated_at == pytest.approx(requested_at + 15.0)
    assert match.elapsed_time - attempt.activated_at == pytest.approx(5.0)


def test_step_one_has_no_pair_deadline() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)

    assert match.ruleset.confirm_d4_step(match, engineer, "own", 1)
    match.update(8.0)
    assert match.ruleset.confirm_d4_step(match, engineer, "opponent", 1)

    attempt = match.ruleset._tech_core_by_team[RED].d4_attempt
    assert attempt is not None
    assert attempt.current_step == 2


@pytest.mark.parametrize("step", [2, 3, 5, 6])
def test_paired_steps_accept_second_core_within_five_seconds(step: int) -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _advance_to_step(match, engineer, step)

    assert match.ruleset.confirm_d4_step(match, engineer, "own", step)
    match.update(4.9)
    assert match.ruleset.confirm_d4_step(match, engineer, "opponent", step)

    state = match.ruleset._tech_core_by_team[RED]
    if step == 6:
        assert state.completion_count_by_difficulty[4] == 1
        assert state.d4_attempt is None
    else:
        assert state.d4_attempt is not None
        assert state.d4_attempt.current_step == step + 1


def test_paired_step_exactly_five_seconds_is_allowed() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _advance_to_step(match, engineer, 2)

    assert match.ruleset.confirm_d4_step(match, engineer, "own", 2)
    match.update(5.0)

    assert match.ruleset._tech_core_by_team[RED].d4_attempt is not None
    assert match.ruleset.confirm_d4_step(match, engineer, "opponent", 2)
    assert match.ruleset._tech_core_by_team[RED].d4_attempt.current_step == 3


@pytest.mark.parametrize("step", [2, 3, 5, 6])
def test_paired_steps_fail_when_second_core_exceeds_five_seconds(step: int) -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _advance_to_step(match, engineer, step)

    assert match.ruleset.confirm_d4_step(match, engineer, "own", step)
    first_time = match.elapsed_time
    match.update(5.01)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.d4_attempt is None
    assert state.completion_count_by_difficulty[4] == 0
    assert state.d4_retry_after == pytest.approx(first_time + 5.0 + 90.0)


def test_step_four_has_no_pair_deadline() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _advance_to_step(match, engineer, 4)

    assert match.ruleset.confirm_d4_step(match, engineer, "own", 4)
    match.update(8.0)
    assert match.ruleset.confirm_d4_step(match, engineer, "opponent", 4)

    attempt = match.ruleset._tech_core_by_team[RED].d4_attempt
    assert attempt is not None
    assert attempt.current_step == 5


def test_cannot_skip_steps_or_confirm_same_core_twice() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _advance_to_step(match, engineer, 2)

    assert not match.ruleset.confirm_d4_step(match, engineer, "own", 3)
    assert match.ruleset.confirm_d4_step(match, engineer, "own", 2)
    assert not match.ruleset.confirm_d4_step(match, engineer, "own", 2)


def test_total_window_allows_44_9_but_fails_after_45_seconds() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    activated_at = match.ruleset._tech_core_by_team[RED].d4_attempt.activated_at

    match.update(44.9)
    assert match.ruleset._tech_core_by_team[RED].d4_attempt is not None

    match.update(0.2)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.d4_attempt is None
    assert state.d4_retry_after == pytest.approx(activated_at + 45.0 + 90.0)


def test_final_step_command_exactly_at_total_deadline_is_allowed() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _advance_to_step(match, engineer, 6)
    activated_at = match.ruleset._tech_core_by_team[RED].d4_attempt.activated_at

    match.elapsed_time = activated_at + 44.9
    assert match.ruleset.confirm_d4_step(match, engineer, "own", 6)
    match.elapsed_time = activated_at + 45.0
    assert match.ruleset.confirm_d4_step(match, engineer, "opponent", 6)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.completion_count_by_difficulty[4] == 1
    assert state.d4_attempt is None


def test_complete_d4_sets_count_once_and_clears_global_active_state() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)

    _complete_d4(match, engineer)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.completion_count_by_difficulty[4] == 1
    assert state.d4_attempt is None
    assert match.ruleset._d4_coordinator.active_team_id is None
    assert match.ruleset._engineer_resources_by_id[engineer.id].energy_unit_credits == 0

    _give_credits(match, engineer, 2)
    match.elapsed_time += 1.0
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 4)


def test_normal_failure_locks_d4_for_exactly_ninety_seconds() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _advance_to_step(match, engineer, 2)
    assert match.ruleset.confirm_d4_step(match, engineer, "own", 2)
    failure_at = match.elapsed_time + 5.0

    match.update(5.01)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.d4_retry_after == pytest.approx(failure_at + 90.0)

    state.completion_count_by_difficulty[3] = 1
    _give_credits(match, engineer, 2)
    match.elapsed_time = state.d4_retry_after - 0.1
    assert not match.ruleset.start_tech_core_assembly(match, engineer, 4)

    match.elapsed_time = state.d4_retry_after
    assert match.ruleset.start_tech_core_assembly(match, engineer, 4)


def test_priority_takeover_failure_permanently_locks_d4_and_records_penalty() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    _start_blue_d2(match)
    _unlock_d4(match, RED)
    _give_credits(match, red, 2)
    assert match.ruleset.start_tech_core_assembly(match, red, 4)
    match.update(15.0)

    _advance_to_step(match, red, 2)
    assert match.ruleset.confirm_d4_step(match, red, "own", 2)
    match.update(5.01)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.d4_attempt is None
    assert state.permanently_locked_out_of_d4
    assert state.d4_priority_failure_gold_penalty == 25
    assert state.d4_retry_after == 0

    _give_credits(match, red, 2)
    match.elapsed_time += 200.0
    assert not match.ruleset.start_tech_core_assembly(match, red, 4)
    assert match.ruleset._periodic_gold_rate(RED)[1:] == (25, -25)


def test_engineer_death_fails_active_d4_with_normal_lockout() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    attacker = _robot(match, "opponent-hero")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    failure_at = match.elapsed_time

    assert match.apply_damage(engineer, engineer.hp, source_robot=attacker) == 250
    match.update(0)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.d4_attempt is None
    assert state.d4_retry_after == pytest.approx(failure_at + 90.0)
    assert match.ruleset._engineer_resources_by_id[engineer.id].energy_unit_credits == 0


def test_active_d4_fails_after_continuous_fifteen_seconds_outside_zone() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    activated_at = match.elapsed_time

    engineer.position = (1400.0, 750.0)
    match.update(14.9)
    attempt = match.ruleset._tech_core_by_team[RED].d4_attempt
    assert attempt is not None
    assert attempt.outside_zone_elapsed == pytest.approx(14.9)

    match.update(0.1)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.d4_attempt is None
    assert state.d4_retry_after == pytest.approx(activated_at + 15.0 + 90.0)


def test_active_d4_outside_timer_resets_when_engineer_returns() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)

    engineer.position = (1400.0, 750.0)
    match.update(10.0)
    attempt = match.ruleset._tech_core_by_team[RED].d4_attempt
    assert attempt is not None
    assert attempt.outside_zone_elapsed == pytest.approx(10.0)

    _place_in_assembly(match, engineer)
    match.update(0.1)
    attempt = match.ruleset._tech_core_by_team[RED].d4_attempt
    assert attempt is not None
    assert attempt.outside_zone_elapsed == 0

    engineer.position = (1400.0, 750.0)
    match.update(10.0)
    assert match.ruleset._tech_core_by_team[RED].d4_attempt is not None


def test_d4_success_applies_only_periodic_gold_reward_gameplay() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    target = _robot(match, "tarsgo-infantry-1")
    _prepare_d4(match, engineer)
    _start_d4(match, engineer)
    _complete_d4(match, engineer)

    red_base = next(
        structure
        for structure in match.structures
        if structure.team == RED and structure.type == "base"
    )
    assert (red_base.hp, red_base.max_hp) == (5000, 5000)
    assert not hasattr(red_base, "shield")
    assert match.ruleset._periodic_gold_rate(RED) == (50, 0, 50)

    before = target.hp
    assert match.apply_damage(target, 20, source_team_id=BLUE) == 20
    assert target.hp == before - 20


def test_d4_display_state_exposes_pending_active_lock_and_penalty_fields() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    _start_blue_d2(match)
    _unlock_d4(match, RED)
    _give_credits(match, red, 2)
    assert match.ruleset.start_tech_core_assembly(match, red, 4)

    status = {
        team_id: values
        for (
            team_id,
            *values,
        ) in match.ruleset.display_state.d4_status
    }
    assert status[RED][0] == "pending"
    assert status[RED][4] == pytest.approx(15.0)

    match.update(15.0)
    status = {
        team_id: values
        for (
            team_id,
            *values,
        ) in match.ruleset.display_state.d4_status
    }
    assert status[RED][0] == "active"
    assert status[RED][1] == 1


def test_reset_clears_d4_coordinator_lockouts_penalty_and_resources() -> None:
    match = _match()
    red = _robot(match, "tarsgo-engineer")
    _start_blue_d2(match)
    _unlock_d4(match, RED)
    _give_credits(match, red, 2)
    assert match.ruleset.start_tech_core_assembly(match, red, 4)
    match.update(15.0)
    _advance_to_step(match, red, 2)
    assert match.ruleset.confirm_d4_step(match, red, "own", 2)
    match.update(5.01)
    assert match.ruleset._tech_core_by_team[RED].permanently_locked_out_of_d4

    match.reset()

    coordinator = match.ruleset._d4_coordinator
    assert coordinator.active_team_id is None
    assert coordinator.pending_team_id is None
    assert coordinator.pending_engineer_id is None
    assert coordinator.priority_buffer_remaining == 0
    for state in match.ruleset._tech_core_by_team.values():
        assert state.completion_count_by_difficulty == {1: 0, 2: 0, 3: 0, 4: 0}
        assert state.active_attempt is None
        assert state.d4_attempt is None
        assert state.d4_retry_after == 0
        assert not state.permanently_locked_out_of_d4
        assert state.d4_priority_failure_gold_penalty == 0
    for resource in match.ruleset._engineer_resources_by_id.values():
        assert resource.energy_unit_credits == 0
