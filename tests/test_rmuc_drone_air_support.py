from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match(*, spectator_ai: bool = False) -> Match:
    match = Match.from_scenario(SCENARIO, rmuc_spectator_ai=spectator_ai)
    for robot in match.robots:
        robot.attack_cooldown = 9999.0
        if robot.type != "drone":
            robot.speed = 0.0
            robot.path.clear()
    return match


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def test_paid_air_support_uses_team_coins_after_free_time() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    economy = rules._economy_by_team[RED]

    assert rules.start_drone_air_support(match, drone)

    match.elapsed_time = 60.0
    rules._advance_drone_air_support(match, 60.0)

    assert rules.drone_air_support_active(drone.id)
    assert drone.alive
    assert economy.coins == 370
    assert rules.drone_air_support_available(drone.id) == pytest.approx(20.0)


def test_paid_air_support_starts_from_zero_time_and_preserves_purchased_remainder() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    state = rules._drone_air_support_by_robot[drone.id]
    economy = rules._economy_by_team[RED]
    state.available_seconds = 0.0
    economy.coins = 2

    assert rules.start_drone_air_support(match, drone)
    assert economy.coins == 1
    assert rules.drone_air_support_available(drone.id) == pytest.approx(1.0)

    match.elapsed_time = 0.4
    rules._advance_drone_air_support(match, 0.4)
    assert rules.drone_air_support_available(drone.id) == pytest.approx(0.6)

    assert rules.pause_drone_air_support(drone)
    assert rules.drone_air_support_available(drone.id) == pytest.approx(0.6)

    assert rules.start_drone_air_support(match, drone)
    assert economy.coins == 1


def test_air_support_stops_when_no_time_or_coins_remain() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    helipad = drone.position
    state = rules._drone_air_support_by_robot[drone.id]
    economy = rules._economy_by_team[RED]
    state.available_seconds = 0.5
    economy.coins = 0

    assert rules.start_drone_air_support(match, drone)
    drone.position = (helipad[0] + 100.0, helipad[1])

    match.elapsed_time = 0.5
    rules._advance_drone_air_support(match, 0.5)

    assert not rules.drone_air_support_active(drone.id)
    assert not drone.alive
    assert drone.position == helipad
    assert rules.drone_air_support_available(drone.id) == pytest.approx(0.0)
    assert not rules.can_move(drone)
    assert not rules.can_attack(drone)


def test_air_support_cannot_start_without_time_or_coins() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    state = rules._drone_air_support_by_robot[drone.id]
    state.available_seconds = 0.0
    rules._economy_by_team[RED].coins = 0

    assert not rules.start_drone_air_support(match, drone)
    assert not drone.alive
    assert not rules.drone_air_support_active(drone.id)


def test_air_support_has_no_cooldown_or_activation_count_limit() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    for _ in range(5):
        assert rules.start_drone_air_support(match, drone)
        assert rules.pause_drone_air_support(drone)

    assert rules.drone_air_support_available(drone.id) == pytest.approx(30.0)


def test_periodic_free_grant_is_chronological_and_does_not_auto_restart() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    state = rules._drone_air_support_by_robot[drone.id]
    state.available_seconds = 0.5
    rules._economy_by_team[RED].coins = 0

    assert rules.start_drone_air_support(match, drone)

    match.elapsed_time = 60.0
    rules._advance_drone_air_support(match, 60.0)

    assert not rules.drone_air_support_active(drone.id)
    assert not drone.alive
    assert rules.drone_air_support_available(drone.id) == pytest.approx(20.0)
    assert state.next_grant_at == pytest.approx(120.0)


def test_air_support_spending_is_team_local_and_reset_restores_round_state() -> None:
    match = _match()
    rules = match.ruleset
    red = _robot(match, "tarsgo-drone")
    blue = _robot(match, "opponent-drone")
    red_state = rules._drone_air_support_by_robot[red.id]
    blue_state = rules._drone_air_support_by_robot[blue.id]
    red_state.available_seconds = 0.0
    blue_state.available_seconds = 0.0
    rules._economy_by_team[RED].coins = 1
    rules._economy_by_team[BLUE].coins = 0

    assert rules.start_drone_air_support(match, red)
    assert not rules.start_drone_air_support(match, blue)
    assert rules._economy_by_team[RED].coins == 0
    assert rules._economy_by_team[BLUE].coins == 0

    match.reset()
    rules = match.ruleset
    red = _robot(match, "tarsgo-drone")
    blue = _robot(match, "opponent-drone")

    assert rules._economy_by_team[RED].coins == 400
    assert rules._economy_by_team[BLUE].coins == 400
    assert rules.drone_air_support_available(red.id) == pytest.approx(30.0)
    assert rules.drone_air_support_available(blue.id) == pytest.approx(30.0)
    assert not rules.drone_air_support_active(red.id)
    assert not rules.drone_air_support_active(blue.id)


def test_paid_air_support_does_not_change_drone_progression_or_performance() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    state = rules._drone_air_support_by_robot[drone.id]
    state.available_seconds = 0.0
    before_progression = (
        rules._progression_by_robot[drone.id].level,
        rules._progression_by_robot[drone.id].experience,
    )
    before_heat = rules._effective_heat_parameters(drone.id)

    assert rules.start_drone_air_support(match, drone)

    after_progression = (
        rules._progression_by_robot[drone.id].level,
        rules._progression_by_robot[drone.id].experience,
    )
    after_heat = rules._effective_heat_parameters(drone.id)
    assert after_progression == before_progression
    assert after_heat == before_heat


def test_spectator_ai_can_start_paid_air_support_symmetrically() -> None:
    match = _match(spectator_ai=True)
    rules = match.ruleset
    red = _robot(match, "tarsgo-drone")
    blue = _robot(match, "opponent-drone")

    for drone in (red, blue):
        rules._drone_air_support_by_robot[drone.id].available_seconds = 0.0
        rules._economy_by_team[drone.team].coins = 1

    match.update(0.1)

    assert red.alive and blue.alive
    assert rules._economy_by_team[RED].coins == 0
    assert rules._economy_by_team[BLUE].coins == 0
    assert match.ai_intent(red.id) == "金币续航空中支援"
    assert match.ai_intent(blue.id) == "金币续航空中支援"


def test_rmuc_air_support_full_match_smoke_is_symmetric_and_bounded() -> None:
    match = _match(spectator_ai=True)

    for _ in range(4200):
        match.update(0.1)
        if match.finished:
            break

    rules = match.ruleset
    assert match.finished
    assert 0 <= rules._economy_by_team[RED].coins
    assert 0 <= rules._economy_by_team[BLUE].coins
    for drone_id in ("tarsgo-drone", "opponent-drone"):
        support = rules.drone_air_support_available(drone_id)
        allowance = rules._projectile_allowance_by_robot[drone_id].allowed
        assert support >= 0.0
        assert 0 <= allowance <= 750
