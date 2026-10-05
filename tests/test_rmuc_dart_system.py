from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match(*, spectator_ai: bool = False) -> Match:
    match = Match.from_scenario(SCENARIO, rmuc_spectator_ai=spectator_ai)
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


def _advance_to(match: Match, time: float) -> None:
    assert time >= match.elapsed_time
    match.update(time - match.elapsed_time)


def _destroy_outpost(match: Match, team_id: str) -> None:
    outpost = _structure(match, team_id, "outpost")
    outpost.hp = 0
    outpost.alive = False
    match.ruleset._team_states[team_id].outpost_ever_destroyed = True


def _open_and_fire(
    match: Match,
    team_id: str,
    target_mode: str | None = None,
) -> str:
    rules = match.ruleset
    state = rules._dart_system_by_team[team_id]
    if state.openings_used == 0:
        _advance_to(match, max(match.elapsed_time, 30.0, state.cooldown_until))
    else:
        _advance_to(match, max(match.elapsed_time, 240.0, state.cooldown_until))
    assert rules.open_dart_gate(match, team_id, target_mode)
    assert state.target_structure_id is not None
    _advance_to(match, state.gate_full_open_at)
    assert rules.fire_dart(match, team_id)
    return state.target_structure_id


def test_dart_gate_and_target_eligibility_follow_v140_schedule() -> None:
    match = _match()
    rules = match.ruleset

    _advance_to(match, 29.999)
    assert not rules.open_dart_gate(match, RED)
    _advance_to(match, 30.0)
    assert not rules.open_dart_gate(match, RED, "random-moving")
    assert rules.open_dart_gate(match, RED)
    state = rules._dart_system_by_team[RED]
    assert state.target_structure_id == _structure(match, BLUE, "outpost").id
    assert state.firing_window_ends_at == pytest.approx(67.0)
    assert state.detector_window_ends_at == pytest.approx(77.0)

    _advance_to(match, 36.999)
    assert not rules.fire_dart(match, RED)
    _advance_to(match, 37.0)
    assert rules.fire_dart(match, RED)
    assert not rules.record_dart_hit(
        match,
        RED,
        _structure(match, BLUE, "base").id,
    )
    assert rules.record_dart_hit(match, RED)
    assert _structure(match, BLUE, "outpost").hp == 750


def test_dart_hit_window_reopens_after_two_seconds_and_expires_after_forty() -> None:
    match = _match()
    rules = match.ruleset
    target_id = _open_and_fire(match, RED)
    assert rules.fire_dart(match, RED)
    assert rules.record_dart_hit(match, RED, target_id)
    assert not rules.record_dart_hit(match, RED, target_id)
    _advance_to(match, 39.0)
    assert rules.record_dart_hit(match, RED, target_id)
    assert _structure(match, BLUE, "outpost").hp == 0

    expired = _match()
    expired_target = _open_and_fire(expired, RED)
    _advance_to(expired, 77.0)
    assert not expired.ruleset.record_dart_hit(expired, RED, expired_target)


def test_fixed_target_obstruction_duration_uses_official_hit_count() -> None:
    match = _match()
    rules = match.ruleset
    _destroy_outpost(match, BLUE)
    target_id = _open_and_fire(match, RED, "fixed")
    assert rules.record_dart_hit(match, RED, target_id)
    assert rules._dart_effects_by_team[BLUE].screen_obscured_remaining == 10.0

    for expected_remaining in (5.0, 3.0, 2.0):
        _advance_to(match, match.elapsed_time + 2.0)
        assert rules.fire_dart(match, RED)
        assert rules.record_dart_hit(match, RED, target_id)
        assert (
            rules._dart_effects_by_team[BLUE].screen_obscured_remaining
            == expected_remaining
        )


@pytest.mark.parametrize(
    ("mode", "expected_damage", "expected_experience"),
    [
        ("fixed", 200, 200.0),
        ("random-fixed", 300, 600.0),
        ("random-moving", 625, 2500.0),
        ("terminal-moving", 1000, 2500.0),
    ],
)
def test_base_dart_modes_apply_official_damage_and_split_xp(
    mode: str,
    expected_damage: int,
    expected_experience: float,
) -> None:
    match = _match()
    rules = match.ruleset
    _destroy_outpost(match, BLUE)
    enemy_base = _structure(match, BLUE, "base")
    for robot_id in ("tarsgo-drone",):
        _robot(match, robot_id).alive = True
    for robot in match.robots:
        if robot.team == RED and robot.type in {"hero", "infantry", "drone"}:
            rules._progression_by_robot[robot.id].experience = 0.0
            robot.alive = True
        if robot.team == BLUE and robot.type in {"hero", "infantry", "sentry"}:
            robot.hp = robot.max_hp
            robot.alive = True
        if robot.team == BLUE and robot.type == "drone":
            robot.hp = robot.max_hp
            robot.alive = True

    target_id = _open_and_fire(match, RED, mode)
    assert target_id == enemy_base.id
    assert rules.record_dart_hit(match, RED, target_id)
    assert enemy_base.hp == enemy_base.max_hp - expected_damage
    awarded = sum(
        rules._progression_by_robot[robot.id].experience
        for robot in match.robots
        if robot.team == RED and robot.type in {"hero", "infantry", "drone"}
    )
    assert awarded == pytest.approx(expected_experience)

    if mode in {"random-moving", "terminal-moving"}:
        assert rules._team_states[BLUE].base_armor_deployed
        assert _robot(match, "opponent-infantry-1").hp < _robot(
            match, "opponent-infantry-1"
        ).max_hp
        assert _robot(match, "opponent-drone").hp == 1


def test_random_moving_hp_loss_counts_as_team_damage_without_experience() -> None:
    match = _match()
    rules = match.ruleset
    _destroy_outpost(match, BLUE)
    target = _structure(match, BLUE, "base")
    infantry = _robot(match, "opponent-infantry-1")
    infantry.hp = 1
    infantry.alive = True
    target_id = _open_and_fire(match, RED, "random-moving")
    experience_before = {
        robot.id: rules._progression_by_robot[robot.id].experience
        for robot in match.robots
        if robot.id in rules._progression_by_robot
    }
    assert rules.record_dart_hit(match, RED, target_id)
    match.update(0.0)

    assert not infantry.alive
    assert rules.attack_damage_by_team[RED] >= 625
    eligible_ids = [
        robot.id
        for robot in match.robots
        if robot.team == RED and robot.alive and robot.type in {"hero", "infantry", "drone"}
    ]
    assert all(
        rules._progression_by_robot[robot_id].experience
        == pytest.approx(experience_before[robot_id] + 2500 / len(eligible_ids))
        for robot_id in eligible_ids
    )


def test_fixed_base_hits_deploy_armor_only_after_all_four_darts_hit_base() -> None:
    match = _match()
    rules = match.ruleset
    _destroy_outpost(match, BLUE)
    for hit_index in range(4):
        if hit_index == 0:
            _advance_to(match, 30.0)
            assert rules.open_dart_gate(match, RED, "fixed")
            state = rules._dart_system_by_team[RED]
            _advance_to(match, state.gate_full_open_at)
        elif hit_index == 2:
            _advance_to(match, 240.0)
            assert rules.open_dart_gate(match, RED, "random-fixed")
            state = rules._dart_system_by_team[RED]
            _advance_to(match, state.gate_full_open_at)
        elif hit_index == 1:
            _advance_to(match, match.elapsed_time + 2.0)
        else:
            _advance_to(match, match.elapsed_time + 2.0)
        assert rules.fire_dart(match, RED)
        assert rules.record_dart_hit(match, RED)
        assert rules._team_states[BLUE].base_armor_deployed == (hit_index == 3)


def test_gates_cool_down_ammo_is_shared_and_teams_are_isolated() -> None:
    match = _match()
    rules = match.ruleset
    _advance_to(match, 240.0)
    assert rules.open_dart_gate(match, RED)
    _advance_to(match, 277.0)
    assert not rules.open_dart_gate(match, RED)
    _advance_to(match, 292.0)
    assert rules.open_dart_gate(match, RED)
    assert rules.open_dart_gate(match, BLUE)
    assert not rules.fire_dart(match, RED)
    _advance_to(match, 299.0)
    assert rules.fire_dart(match, RED)
    assert rules.fire_dart(match, BLUE)
    for _ in range(3):
        assert rules.fire_dart(match, RED)
    assert not rules.fire_dart(match, RED)
    assert rules._dart_system_by_team[BLUE].darts_fired == 1


def test_spent_darts_do_not_cancel_a_later_gate_opportunity() -> None:
    match = _match()
    rules = match.ruleset
    _advance_to(match, 30.0)
    assert rules.open_dart_gate(match, RED)
    state = rules._dart_system_by_team[RED]
    _advance_to(match, state.gate_full_open_at)
    for _ in range(4):
        assert rules.fire_dart(match, RED)

    _advance_to(match, 240.0)
    assert rules.open_dart_gate(match, RED)
    assert state.openings_used == 2
    _advance_to(match, state.gate_full_open_at)
    assert not rules.fire_dart(match, RED)


def test_dart_bypasses_attack_defense_but_preserves_base_virtual_shield() -> None:
    match = _match()
    rules = match.ruleset
    _destroy_outpost(match, BLUE)
    target = _structure(match, BLUE, "base")
    rules._team_states[BLUE].base_virtual_shield = 200
    assert rules.activate_large_energy_mechanism_buff(BLUE, 9.5, 10)
    assert rules.activate_large_energy_mechanism_buff(RED, 9.5, 10)
    target_id = _open_and_fire(match, RED, "fixed")
    assert rules.record_dart_hit(match, RED, target_id)
    assert target.hp == target.max_hp
    assert rules._team_states[BLUE].base_virtual_shield == 0
    assert rules._progression_by_robot["tarsgo-hero"].experience > 0


def test_dart_ground_splash_does_not_change_drone_support_or_radar_state() -> None:
    match = _match()
    rules = match.ruleset
    _destroy_outpost(match, BLUE)
    blue_drone = _robot(match, "opponent-drone")

    _advance_to(match, 30.0)
    assert rules.start_drone_air_support(match, blue_drone)
    assert rules.set_radar_anti_drone_laser(RED, blue_drone, True)
    _advance_to(match, 30.25)
    support = rules._drone_air_support_by_robot[blue_drone.id]
    support.active = True
    support.available_seconds = 90.0
    radar = rules._radar_anti_drone_by_robot[blue_drone.id]
    radar.progress = 42.0
    radar.continuous_elapsed = 0.1
    radar.consecutive_ticks = 4
    radar.illuminated_by_team_id = RED
    radar.lock_remaining = 12.0
    radar.activations = 1

    target_id = _open_and_fire(match, RED, "random-moving")
    before = (
        support.active,
        support.available_seconds,
        radar.progress,
        radar.continuous_elapsed,
        radar.consecutive_ticks,
        radar.illuminated_by_team_id,
        radar.lock_remaining,
        radar.activations,
    )
    assert rules.record_dart_hit(match, RED, target_id)
    assert (
        support.active,
        support.available_seconds,
        radar.progress,
        radar.continuous_elapsed,
        radar.consecutive_ticks,
        radar.illuminated_by_team_id,
        radar.lock_remaining,
        radar.activations,
    ) == before
    assert blue_drone.alive and blue_drone.hp == blue_drone.max_hp


def test_random_fixed_base_hit_suppresses_existing_gains_and_resets() -> None:
    match = _match()
    rules = match.ruleset
    _destroy_outpost(match, BLUE)
    assert rules.activate_small_energy_mechanism_buff(
        match,
        _robot(match, "opponent-infantry-1"),
        0.0,
    )
    assert rules.activate_large_energy_mechanism_buff(BLUE, 9.5, 10)
    assert rules._current_small_energy_mechanism_defense(BLUE) == pytest.approx(0.25)

    target_id = _open_and_fire(match, RED, "random-fixed")
    assert rules.record_dart_hit(match, RED, target_id)
    assert rules._current_energy_mechanism_defense(BLUE) == 0.0
    assert rules._current_large_energy_mechanism_cooling_multiplier(BLUE) == 1.0
    base_zone = rules._field_base_zone_by_team[BLUE]
    assert rules._field_buff_zone_disabled(base_zone.id)
    _advance_to(match, 47.0)
    assert rules._current_energy_mechanism_defense(BLUE) == pytest.approx(0.50)
    assert rules._field_buff_zone_disabled(base_zone.id)
    _advance_to(match, 67.0)
    assert not rules._field_buff_zone_disabled(base_zone.id)

    match.reset()
    assert all(state.darts_fired == 0 for state in rules._dart_system_by_team.values())
    assert all(
        effects.screen_obscured_remaining == 0
        and effects.terrain_energy_suppressed_remaining == 0
        for effects in rules._dart_effects_by_team.values()
    )


def test_spectator_ai_uses_both_teams_with_fixed_seed_and_long_match_smoke() -> None:
    first = _match(spectator_ai=True)
    second = _match(spectator_ai=True)
    for _ in range(420):
        first.update(1.0)
        second.update(1.0)

    assert first.finished and second.finished
    assert first.elapsed_time == pytest.approx(second.elapsed_time)
    for team_id in (RED, BLUE):
        left = first.ruleset._dart_system_by_team[team_id]
        right = second.ruleset._dart_system_by_team[team_id]
        assert (left.openings_used, left.darts_fired) == (2, 2)
        assert (left.openings_used, left.darts_fired) == (
            right.openings_used,
            right.darts_fired,
        )
