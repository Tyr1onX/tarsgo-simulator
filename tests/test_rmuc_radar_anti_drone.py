from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RMUC_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)
TRAINING_SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "first-steps.yaml"
RMUL_SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "rmul-2026-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match(*, spectator_ai: bool = False) -> Match:
    match = Match.from_scenario(RMUC_SCENARIO, rmuc_spectator_ai=spectator_ai)
    for robot in match.robots:
        robot.attack_cooldown = 9999.0
        if robot.type != "drone":
            robot.speed = 0.0
            robot.path.clear()
    return match


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _anti_state(match: Match, robot_id: str):
    return match.ruleset._radar_anti_drone_by_robot[robot_id]


def _lock_once(match: Match, source_team_id: str, drone, duration: float) -> None:
    rules = match.ruleset
    assert rules.set_radar_anti_drone_laser(source_team_id, drone, True)
    rules._advance_radar_anti_drone(duration)
    assert rules.set_radar_anti_drone_laser(source_team_id, drone, False)


def test_radar_anti_drone_requires_enemy_active_air_support_and_locks_for_45_seconds() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    state = _anti_state(match, drone.id)

    assert not rules.set_radar_anti_drone_laser(BLUE, drone, True)
    assert not rules.set_radar_anti_drone_laser(RED, drone, True)

    assert rules.start_drone_air_support(match, drone)
    drone.position = (drone.position[0] + 100.0, drone.position[1])
    assert rules.can_attack(drone)
    assert rules.set_radar_anti_drone_laser(BLUE, drone, True)

    rules._advance_radar_anti_drone(0.9)
    assert state.progress == pytest.approx(45.0)
    assert state.activations == 0

    rules._advance_radar_anti_drone(0.1)
    assert state.progress == pytest.approx(0.0)
    assert state.activations == 1
    assert state.lock_remaining == pytest.approx(45.0)
    assert rules.radar_anti_drone_locked(drone.id)
    assert not rules.can_attack(drone)

    assert rules.set_radar_anti_drone_laser(BLUE, drone, False)
    rules._advance_radar_anti_drone(44.9)
    assert state.lock_remaining == pytest.approx(0.1)
    assert not rules.can_attack(drone)
    rules._advance_radar_anti_drone(0.1)
    assert state.lock_remaining == pytest.approx(0.0)
    assert rules.can_attack(drone)


def test_radar_anti_drone_progress_resets_continuous_ticks_and_decays_when_laser_breaks() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    state = _anti_state(match, drone.id)

    assert rules.start_drone_air_support(match, drone)
    assert rules.set_radar_anti_drone_laser(BLUE, drone, True)
    rules._advance_radar_anti_drone(0.5)
    assert state.progress == pytest.approx(15.0)
    assert state.consecutive_ticks == 5

    assert rules.set_radar_anti_drone_laser(BLUE, drone, False)
    rules._advance_radar_anti_drone(2.0)
    assert state.progress == pytest.approx(14.0)
    assert state.consecutive_ticks == 0

    assert rules.set_radar_anti_drone_laser(BLUE, drone, True)
    rules._advance_radar_anti_drone(0.1)
    assert state.progress == pytest.approx(15.0)
    assert state.consecutive_ticks == 1


def test_radar_anti_drone_uses_50_100_100_thresholds_and_caps_at_three_locks() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    state = _anti_state(match, drone.id)

    assert rules.start_drone_air_support(match, drone)

    _lock_once(match, BLUE, drone, 1.0)
    assert state.activations == 1
    assert rules._radar_anti_drone_threshold(state) == pytest.approx(100.0)
    rules._advance_radar_anti_drone(45.0)

    _lock_once(match, BLUE, drone, 1.4)
    assert state.activations == 2
    assert rules._radar_anti_drone_threshold(state) == pytest.approx(100.0)
    rules._advance_radar_anti_drone(45.0)

    _lock_once(match, BLUE, drone, 1.4)
    assert state.activations == 3
    assert state.lock_remaining == pytest.approx(45.0)
    assert not rules.set_radar_anti_drone_laser(BLUE, drone, True)

    display = {
        robot_id: row
        for row in match.ruleset.display_state.radar_anti_drone
        for robot_id in (row[0],)
    }[drone.id]
    assert display[6] == 0


def test_radar_anti_drone_is_team_local_and_symmetric() -> None:
    match = _match()
    rules = match.ruleset
    red_drone = _robot(match, "tarsgo-drone")
    blue_drone = _robot(match, "opponent-drone")

    assert rules.start_drone_air_support(match, red_drone)
    assert rules.start_drone_air_support(match, blue_drone)

    _lock_once(match, BLUE, red_drone, 1.0)

    red_state = _anti_state(match, red_drone.id)
    blue_state = _anti_state(match, blue_drone.id)
    assert red_state.activations == 1
    assert blue_state.activations == 0
    assert blue_state.progress == pytest.approx(0.0)

    _lock_once(match, RED, blue_drone, 1.0)
    assert red_state.activations == 1
    assert blue_state.activations == 1


def test_radar_anti_drone_is_separate_from_ground_vulnerability() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    assert rules.start_drone_air_support(match, drone)
    assert not rules.set_radar_vulnerability(BLUE, drone, 0.15)
    assert rules._current_radar_vulnerability(drone) == 0.0
    assert rules._effective_vulnerability(drone) == 0.0

    _lock_once(match, BLUE, drone, 1.0)
    assert rules.radar_anti_drone_locked(drone.id)
    assert rules._current_radar_vulnerability(drone) == 0.0
    assert rules._effective_vulnerability(drone) == 0.0


def test_radar_lock_does_not_pollute_air_support_progression_or_performance() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    assert rules.start_drone_air_support(match, drone)
    before_support = rules.drone_air_support_available(drone.id)
    before_progression = (
        rules._progression_by_robot[drone.id].level,
        rules._progression_by_robot[drone.id].experience,
    )
    before_heat = rules._effective_heat_parameters(drone.id)

    _lock_once(match, BLUE, drone, 1.0)

    assert rules.drone_air_support_active(drone.id)
    assert rules.drone_air_support_available(drone.id) == pytest.approx(before_support)
    assert rules.can_move(drone)
    assert (
        rules._progression_by_robot[drone.id].level,
        rules._progression_by_robot[drone.id].experience,
    ) == before_progression
    assert rules._effective_heat_parameters(drone.id) == before_heat


def test_radar_anti_drone_reset_restores_round_state() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    assert rules.start_drone_air_support(match, drone)
    _lock_once(match, BLUE, drone, 1.0)
    assert _anti_state(match, drone.id).activations == 1

    match.reset()
    rules = match.ruleset
    state = _anti_state(match, "tarsgo-drone")
    assert state.progress == pytest.approx(0.0)
    assert state.continuous_elapsed == pytest.approx(0.0)
    assert state.consecutive_ticks == 0
    assert state.illuminated_by_team_id is None
    assert state.lock_remaining == pytest.approx(0.0)
    assert state.activations == 0


def test_spectator_radar_ai_is_symmetric_and_fixed_seed_reproducible() -> None:
    snapshots = []
    for _ in range(2):
        match = _match(spectator_ai=True)
        for _step in range(300):
            match.update(0.1)
        snapshots.append(
            tuple(
                (
                    robot_id,
                    round(state.progress, 6),
                    round(state.lock_remaining, 6),
                    state.activations,
                )
                for robot_id, state in sorted(
                    match.ruleset._radar_anti_drone_by_robot.items()
                )
            )
        )

    assert snapshots[0] == snapshots[1]
    states = snapshots[0]
    assert len(states) == 2
    assert states[0][1:] == states[1][1:]
    assert states[0][3] >= 1


def test_rmuc_radar_anti_drone_full_match_smoke_is_bounded() -> None:
    match = _match(spectator_ai=True)

    for _ in range(4200):
        match.update(0.1)
        if match.finished:
            break

    assert match.finished
    for state in match.ruleset._radar_anti_drone_by_robot.values():
        assert 0.0 <= state.progress <= 100.0
        assert 0.0 <= state.lock_remaining <= 45.0
        assert 0 <= state.activations <= 3


def test_training_and_rmul_regression_smoke() -> None:
    for scenario in (TRAINING_SCENARIO, RMUL_SCENARIO):
        match = Match.from_scenario(scenario)
        for _ in range(20):
            match.update(0.1)
        assert match.elapsed_time == pytest.approx(2.0)
