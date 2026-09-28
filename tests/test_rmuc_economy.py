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


def _give_credits(match: Match, engineer: Robot, count: int) -> None:
    _place_in_resource(match, engineer)
    state = match.ruleset._engineer_resources_by_id[engineer.id]
    while state.energy_unit_credits < count:
        assert match.ruleset.pickup_energy_unit(match, engineer)
    _place_in_assembly(match, engineer)


def _complete(match: Match, engineer: Robot, difficulty: int) -> None:
    _give_credits(match, engineer, 1)
    assert match.ruleset.start_tech_core_assembly(match, engineer, difficulty)
    assert match.ruleset.confirm_tech_core_assembly(match, engineer)


def _advance_to(match: Match, elapsed: float) -> None:
    assert elapsed + 1e-9 >= match.elapsed_time
    match.update(max(0.0, elapsed - match.elapsed_time))


def _complete_d1(match: Match, engineer: Robot) -> None:
    _complete(match, engineer, 1)


def _complete_d2(match: Match, engineer: Robot) -> None:
    state = match.ruleset._tech_core_by_team[engineer.team]
    if state.completion_count_by_difficulty[1] == 0:
        _complete_d1(match, engineer)
    _advance_to(match, 60.0)
    _complete(match, engineer, 2)


def _complete_d3(match: Match, engineer: Robot) -> None:
    state = match.ruleset._tech_core_by_team[engineer.team]
    if state.completion_count_by_difficulty[2] == 0:
        _complete_d2(match, engineer)
    _advance_to(match, 120.0)
    _complete(match, engineer, 3)


def _prepare_d4_without_reward_history(match: Match, engineer: Robot) -> None:
    state = match.ruleset._tech_core_by_team[engineer.team]
    state.completion_count_by_difficulty[1] = 1
    state.completion_count_by_difficulty[2] = 1
    state.completion_count_by_difficulty[3] = 1
    match.ruleset._level_cap_by_team[engineer.team] = 10
    _advance_to(match, 180.0)
    _give_credits(match, engineer, 2)


def _complete_d4(match: Match, engineer: Robot) -> None:
    assert match.ruleset.start_tech_core_assembly(match, engineer, 4)
    for step in range(1, 7):
        assert match.ruleset.confirm_d4_step(match, engineer, "own", step)
        assert match.ruleset.confirm_d4_step(match, engineer, "opponent", step)


def _start_priority_d4(match: Match, requester: Robot) -> None:
    opponent = _robot(
        match,
        "opponent-engineer" if requester.team == RED else "tarsgo-engineer",
    )
    opponent_state = match.ruleset._tech_core_by_team[opponent.team]
    opponent_state.completion_count_by_difficulty[1] = 1

    requester_state = match.ruleset._tech_core_by_team[requester.team]
    requester_state.completion_count_by_difficulty[1] = max(
        1, requester_state.completion_count_by_difficulty[1]
    )
    requester_state.completion_count_by_difficulty[2] = 1
    requester_state.completion_count_by_difficulty[3] = 1
    match.ruleset._level_cap_by_team[requester.team] = 10

    _advance_to(match, 180.0)
    _give_credits(match, opponent, 1)
    assert match.ruleset.start_tech_core_assembly(match, opponent, 2)
    _give_credits(match, requester, 2)
    assert match.ruleset.start_tech_core_assembly(match, requester, 4)
    match.update(15.0)


def _fail_active_d4_pair_window(match: Match, engineer: Robot) -> None:
    state = match.ruleset._tech_core_by_team[engineer.team]
    assert state.d4_attempt is not None
    while state.d4_attempt.current_step < 2:
        step = state.d4_attempt.current_step
        assert match.ruleset.confirm_d4_step(match, engineer, "own", step)
        assert match.ruleset.confirm_d4_step(match, engineer, "opponent", step)
    assert match.ruleset.confirm_d4_step(match, engineer, "own", 2)
    match.update(5.01)


def test_default_rules_lab_initial_coins_are_400_with_neutral_b_b_ratings() -> None:
    match = _match()

    assert match.ruleset._economy_lab_rating == {
        "project_document": "B",
        "technical_solution": "B",
    }
    assert {
        team_id: state.coins
        for team_id, state in match.ruleset._economy_by_team.items()
    } == {RED: 400, BLUE: 400}
    assert dict(match.ruleset.display_state.coins) == {RED: 400, BLUE: 400}


def test_official_rating_modifiers_produce_s_s_600_and_d_d_300() -> None:
    match = _match()

    assert match.ruleset._initial_coins_for_ratings("S", "S") == 600
    assert match.ruleset._initial_coins_for_ratings("D", "D") == 300


def test_official_timed_grant_schedule() -> None:
    match = _match()
    red = match.ruleset._economy_by_team[RED]

    assert red.coins == 400
    for elapsed, expected in (
        (60.0, 450),
        (120.0, 500),
        (180.0, 550),
        (240.0, 600),
        (300.0, 650),
        (360.0, 800),
    ):
        _advance_to(match, elapsed)
        assert red.coins == expected


def test_large_dt_settles_all_crossed_timed_grants() -> None:
    match = _match()
    _advance_to(match, 50.0)
    before = match.ruleset._economy_by_team[RED].coins

    match.update(140.0)

    assert match.elapsed_time == pytest.approx(190.0)
    assert match.ruleset._economy_by_team[RED].coins == before + 150
    assert match.ruleset._next_timed_gold_grant_index == 3


def test_d1_first_and_repeat_increment_periodic_rate_without_history_rebuild() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d1(match, engineer)
    assert match.ruleset._periodic_gold_rate(RED) == (50, 0, 50)

    _complete_d1(match, engineer)
    assert match.ruleset._periodic_gold_rate(RED) == (55, 0, 55)


def test_d2_first_adds_25_and_preserves_cap_seven_unlock() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d2(match, engineer)

    assert match.ruleset._periodic_gold_rate(RED) == (75, 0, 75)
    assert match.ruleset._level_cap_by_team[RED] == 7


def test_official_tech_core_example_reaches_115_per_ten_seconds() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d1(match, engineer)
    _advance_to(match, 60.0)
    _complete(match, engineer, 2)
    _advance_to(match, 120.0)
    _complete(match, engineer, 3)
    _complete(match, engineer, 2)
    _complete(match, engineer, 1)

    assert match.ruleset._periodic_gold_rate(RED) == (115, 0, 115)


def test_d4_success_adds_50_periodic_gold_only_once() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4_without_reward_history(match, engineer)

    _complete_d4(match, engineer)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.completion_count_by_difficulty[4] == 1
    assert match.ruleset._periodic_gold_rate(RED) == (50, 0, 50)


def test_periodic_income_uses_global_ten_second_boundaries() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _advance_to(match, 24.0)
    _complete_d1(match, engineer)
    before = match.ruleset._economy_by_team[RED].coins

    match.update(5.9)
    assert match.elapsed_time == pytest.approx(29.9)
    assert match.ruleset._economy_by_team[RED].coins == before

    match.update(0.1)
    assert match.elapsed_time == pytest.approx(30.0)
    assert match.ruleset._economy_by_team[RED].coins == before + 50


def test_completion_exactly_on_tick_boundary_uses_new_rate() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _advance_to(match, 20.0)
    match.elapsed_time = 30.0
    _complete_d1(match, engineer)
    before = match.ruleset._economy_by_team[RED].coins

    match.update(0.0)

    assert match.ruleset._economy_by_team[RED].coins == before + 50
    assert match.ruleset._next_periodic_gold_tick == pytest.approx(40.0)


def test_large_dt_settles_every_periodic_tick_crossed() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _advance_to(match, 25.0)
    _complete_d1(match, engineer)
    before = match.ruleset._economy_by_team[RED].coins

    match.update(40.0)

    # Periodic ticks 30/40/50/60 = +200; official timed grant at 60 = +50.
    assert match.elapsed_time == pytest.approx(65.0)
    assert match.ruleset._economy_by_team[RED].coins == before + 250
    assert match.ruleset._next_periodic_gold_tick == pytest.approx(70.0)


def test_timed_grant_and_periodic_income_both_settle_at_sixty() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d1(match, engineer)

    _advance_to(match, 50.0)
    before = match.ruleset._economy_by_team[RED].coins
    match.update(10.0)

    assert match.ruleset._economy_by_team[RED].coins == before + 100


def test_priority_failure_penalty_reduces_net_periodic_rate() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d1(match, engineer)
    _start_priority_d4(match, engineer)

    _fail_active_d4_pair_window(match, engineer)

    assert match.ruleset._periodic_gold_rate(RED) == (50, 25, 25)
    state = match.ruleset._tech_core_by_team[RED]
    assert state.permanently_locked_out_of_d4
    assert state.d4_priority_failure_gold_penalty == 25


def test_priority_penalty_does_not_apply_to_ticks_before_midframe_failure() -> None:
    match = _match()
    economy = match.ruleset._economy_by_team[RED]
    tech = match.ruleset._tech_core_by_team[RED]
    economy.coins = 100
    economy.tech_core_periodic_gold_per_10s = 0
    economy.d4_priority_penalty_active_from = 35.0
    tech.d4_priority_failure_gold_penalty = 25

    _advance_to(match, 45.0)

    # Ticks 10/20/30 predate the penalty. Only tick 40 subtracts 25.
    assert economy.coins == 75


def test_negative_net_periodic_rate_floors_wallet_at_zero() -> None:
    match = _match()
    economy = match.ruleset._economy_by_team[RED]
    tech = match.ruleset._tech_core_by_team[RED]
    economy.coins = 40
    economy.d4_priority_penalty_active_from = 0.0
    tech.d4_priority_failure_gold_penalty = 25

    match.update(20.0)

    assert match.ruleset._periodic_gold_rate(RED) == (0, 25, -25)
    assert economy.coins == 0


def test_priority_penalty_persists_until_reset() -> None:
    match = _match()
    economy = match.ruleset._economy_by_team[RED]
    tech = match.ruleset._tech_core_by_team[RED]
    economy.d4_priority_penalty_active_from = 10.0
    tech.d4_priority_failure_gold_penalty = 25

    _advance_to(match, 200.0)

    assert match.ruleset._periodic_gold_rate(RED) == (0, 25, -25)
    assert economy.d4_priority_penalty_active_from == 10.0

    match.reset()

    assert match.ruleset._periodic_gold_rate(RED) == (0, 0, 0)
    assert match.ruleset._economy_by_team[RED].d4_priority_penalty_active_from is None


def test_normal_d4_failure_does_not_create_gold_penalty() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _prepare_d4_without_reward_history(match, engineer)
    assert match.ruleset.start_tech_core_assembly(match, engineer, 4)

    _fail_active_d4_pair_window(match, engineer)

    state = match.ruleset._tech_core_by_team[RED]
    assert state.d4_retry_after > match.elapsed_time
    assert state.d4_priority_failure_gold_penalty == 0
    assert match.ruleset._periodic_gold_rate(RED) == (0, 0, 0)


def test_d3_and_d4_non_gold_rewards_remain_unconsumed() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    target = _robot(match, "tarsgo-infantry-1")

    _complete_d3(match, engineer)
    before = target.hp
    assert match.apply_damage(target, 20, source_team_id=BLUE) == 20
    assert target.hp == before - 20

    _advance_to(match, 180.0)
    _give_credits(match, engineer, 2)
    _complete_d4(match, engineer)

    base = next(
        structure
        for structure in match.structures
        if structure.team == RED and structure.type == "base"
    )
    assert (base.hp, base.max_hp) == (5000, 5000)
    assert not hasattr(base, "shield")


def test_display_state_exposes_coins_gross_penalty_and_net_rate() -> None:
    match = _match()
    economy = match.ruleset._economy_by_team[RED]
    tech = match.ruleset._tech_core_by_team[RED]
    economy.tech_core_periodic_gold_per_10s = 50
    economy.d4_priority_penalty_active_from = 0.0
    tech.d4_priority_failure_gold_penalty = 25

    display = match.ruleset.display_state
    team_economy = {
        team_id: (coins, gross, penalty, net)
        for team_id, coins, gross, penalty, net in display.team_economy
    }

    assert team_economy[RED] == (400, 50, 25, 25)


def test_finished_match_receives_no_further_income() -> None:
    match = _match()
    _advance_to(match, 60.0)
    before = dict(match.ruleset.display_state.coins)

    match.finished = True
    match.update(300.0)

    assert dict(match.ruleset.display_state.coins) == before
