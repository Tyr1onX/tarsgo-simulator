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


def _structure(match: Match, team_id: str, structure_type: str):
    return next(
        structure
        for structure in match.structures
        if structure.team == team_id and structure.type == structure_type
    )


def test_both_drones_are_aerial_entities_and_not_ground_lifecycle_units() -> None:
    match = _match()
    rules = match.ruleset
    drones = [robot for robot in match.robots if robot.type == "drone"]

    assert {robot.id for robot in drones} == {
        "tarsgo-drone",
        "opponent-drone",
    }
    assert all(robot.aerial for robot in drones)
    assert all(not robot.alive for robot in drones)
    assert all(robot.id not in rules._robot_lifecycle_by_robot for robot in drones)
    assert all(robot.id not in rules._chassis_power_by_robot for robot in drones)
    assert all(robot.id not in rules._terrain_crossing_by_robot for robot in drones)
    assert all(robot.id not in rules._fortress_reserved_by_robot for robot in drones)


def test_drone_official_launcher_allowance_and_free_air_support_cycle() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    helipad = drone.position
    allowance = rules._projectile_allowance_by_robot[drone.id]

    assert allowance.projectile_type == "17mm"
    assert allowance.allowed == 750
    assert rules._drone_projectile_muzzle_velocity_limit_mps == 25
    assert rules.drone_air_support_available(drone.id) == pytest.approx(30.0)
    assert not rules.drone_air_support_active(drone.id)
    assert not drone.alive

    assert rules.start_drone_air_support(match, drone)
    assert drone.alive
    assert rules.can_move(drone)
    assert not rules.can_attack(drone)

    drone.position = (helipad[0] + 1.0, helipad[1])
    assert rules.can_attack(drone)

    rules._advance_drone_air_support(match, 10.0)
    assert rules.drone_air_support_available(drone.id) == pytest.approx(20.0)

    assert rules.pause_drone_air_support(drone)
    assert not drone.alive
    assert drone.position == helipad
    assert not rules.can_move(drone)
    assert not rules.can_attack(drone)

    match.elapsed_time = 60.0
    rules._advance_drone_air_support(match, 0.0)
    assert rules.drone_air_support_available(drone.id) == pytest.approx(40.0)


def test_drone_cannot_be_damaged_killed_healed_or_respawned() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    assert rules.start_drone_air_support(match, drone)
    before_hp = drone.hp
    before_events = len(match.current_events)

    assert not rules.can_target(drone)
    assert not rules.can_receive_damage(drone)
    assert match.apply_damage(drone, 100000, source_team_id=BLUE) == 0
    assert drone.hp == before_hp
    assert drone.alive
    assert len(match.current_events) == before_events

    assert not rules.purchase_remote_healing(match, drone)
    assert not rules.purchase_immediate_respawn(match, drone)
    assert drone.id not in rules._robot_lifecycle_by_robot


def test_drone_attack_uses_existing_combat_damage_path() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    target = _robot(match, "opponent-infantry-1")

    assert rules.start_drone_air_support(match, drone)
    drone.position = (1200.0, 420.0)
    target.position = (1320.0, 420.0)
    drone.attack_cooldown = 0.0
    target_before = target.hp
    allowance_before = rules._projectile_allowance_by_robot[drone.id].allowed

    match.update(0.01)

    assert target_before - target.hp == 20
    assert rules._projectile_allowance_by_robot[drone.id].allowed == allowance_before - 1
    assert rules._progression_by_robot[drone.id].experience == pytest.approx(81.0)


def test_drone_progression_and_heat_use_official_level_table_without_hp_growth() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    internal_hp = (drone.hp, drone.max_hp)

    assert rules.start_drone_air_support(match, drone)
    drone.position = (drone.position[0] + 1.0, drone.position[1])
    rules.on_attack_committed(drone)

    progression = rules._progression_by_robot[drone.id]
    heat = rules._shooting_heat_by_robot[drone.id]
    level_one = rules._effective_heat_parameters(drone.id)
    assert progression.experience == pytest.approx(1.0)
    assert heat.heat == pytest.approx(10.0)
    assert (level_one.heat_limit, level_one.cooling_per_second) == (100.0, 20.0)

    rules._grant_experience(drone.id, 549.0)
    assert (progression.level, progression.experience) == (2, 550.0)
    level_two = rules._effective_heat_parameters(drone.id)
    assert (level_two.heat_limit, level_two.cooling_per_second) == (110.0, 30.0)
    assert (drone.hp, drone.max_hp) == internal_hp

    rules._grant_experience(drone.id, 99999.0)
    assert (progression.level, progression.experience) == (5, 2200.0)
    rules._level_cap_by_team[RED] = 7
    rules._grant_experience(drone.id, 99999.0)
    assert (progression.level, progression.experience) == (7, 3300.0)


def test_drone_cannot_acquire_additional_allowance() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    assert rules.start_drone_air_support(match, drone)
    state = rules._projectile_allowance_by_robot[drone.id]
    before = state.allowed
    coins_before = rules._economy_by_team[drone.team].coins

    assert not rules.exchange_projectiles(match, drone)
    assert not rules.remote_exchange_projectiles(match, drone)
    assert state.allowed == before
    assert rules._economy_by_team[drone.team].coins == coins_before


def test_ground_buff_tech_core_and_fortress_do_not_apply_to_drone() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")
    infantry = _robot(match, "tarsgo-infantry-1")

    assert rules.start_drone_air_support(match, drone)
    base_zone = rules._field_base_zone_by_team[RED]
    drone.position = (
        base_zone.x + base_zone.width / 2,
        base_zone.y + base_zone.height / 2,
    )
    rules._advance_field_defense_occupancy(match, 1.0)
    assert not any(key[0] == drone.id for key in rules._field_occupy_remaining)

    rules._team_states[RED].tech_core_defense = 0.50
    assert rules._effective_defense(drone) == 0.0
    assert rules._effective_defense(infantry) == pytest.approx(0.50)
    assert rules._current_fortress_defense(drone) == 0.0
    assert drone.id not in rules._terrain_crossing_by_robot


def test_large_energy_mechanism_applies_team_attack_defense_and_cooling_to_drone() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    assert rules.start_drone_air_support(match, drone)
    assert rules.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    heat = rules._effective_heat_parameters(drone.id)
    assert rules._effective_attack_multiplier(RED) == pytest.approx(3.0)
    assert rules._effective_defense(drone) == pytest.approx(0.50)
    assert heat.cooling_per_second == pytest.approx(100.0)

    # Defense state is official team state, but Drone has no attack-damage HP path.
    assert match.apply_damage(drone, 20, source_team_id=BLUE) == 0


def test_radar_vulnerability_can_mark_drone_but_still_cannot_create_hp_loss() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    assert rules.start_drone_air_support(match, drone)
    assert rules.set_radar_vulnerability(BLUE, drone, 0.15)
    assert rules._current_radar_vulnerability(drone) == pytest.approx(0.15)
    assert rules._effective_vulnerability(drone) == pytest.approx(0.15)
    assert match.apply_damage(drone, 20, source_team_id=BLUE) == 0


def test_drone_utility_ai_uses_air_support_and_non_ground_intents() -> None:
    match = _match(spectator_ai=True)
    red = _robot(match, "tarsgo-drone")
    blue = _robot(match, "opponent-drone")

    match.update(0.75)
    assert red.alive and blue.alive
    assert match.ai_intent(red.id) == "发起空中支援"
    assert match.ai_intent(blue.id) == "发起空中支援"

    match.update(0.75)
    ground_intents = {
        "前往补给区",
        "回撤补给",
        "占领堡垒",
        "前往中央区域",
        "前往防御增益区",
        "获取能量单元",
        "装配科技核心",
    }
    assert match.ai_intent(red.id) not in ground_intents
    assert match.ai_intent(blue.id) not in ground_intents
    assert match.ai_intent(red.id).startswith("空中")
    assert match.ai_intent(blue.id).startswith("空中")
    assert match._ai_target_keys[red.id] is not None
    assert match._ai_target_keys[blue.id] is not None


def test_drone_reset_restores_official_foundation_state() -> None:
    match = _match()
    rules = match.ruleset
    drone = _robot(match, "tarsgo-drone")

    assert rules.start_drone_air_support(match, drone)
    rules.on_attack_committed(drone)
    rules._grant_experience(drone.id, 1000)
    drone.position = (1400.0, 500.0)

    match.reset()
    drone = _robot(match, "tarsgo-drone")
    rules = match.ruleset

    assert drone.aerial
    assert not drone.alive
    assert drone.position == (500.0, 260.0)
    assert rules.drone_air_support_available(drone.id) == pytest.approx(30.0)
    assert not rules.drone_air_support_active(drone.id)
    assert rules._projectile_allowance_by_robot[drone.id].allowed == 750
    assert (rules._progression_by_robot[drone.id].level, rules._progression_by_robot[drone.id].experience) == (1, 0.0)
    assert rules._shooting_heat_by_robot[drone.id].heat == 0.0


def test_drone_internal_sentinel_hp_does_not_enter_match_tiebreak() -> None:
    match = _match()
    red_drone = _robot(match, "tarsgo-drone")
    blue_drone = _robot(match, "opponent-drone")
    match.elapsed_time = match.time_limit
    red_drone.hp = 1
    blue_drone.hp = 0

    result = match.ruleset.evaluate_result(match)

    assert result is not None
    assert result.winner is None


def test_rmuc_drone_long_spectator_smoke_is_stable() -> None:
    match = _match(spectator_ai=True)

    for _ in range(900):
        match.update(0.1)

    assert match.elapsed_time > 0
    for drone_id in ("tarsgo-drone", "opponent-drone"):
        allowance = match.ruleset._projectile_allowance_by_robot[drone_id].allowed
        assert 0 <= allowance <= 750
        assert drone_id in match.ruleset._progression_by_robot