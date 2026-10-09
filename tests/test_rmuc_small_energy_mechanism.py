import math
from pathlib import Path
import random

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.energy_mechanism import SmallEnergyMechanism
from tarsgo_simulator.core.projectiles import Projectile
from tarsgo_simulator.core.projectile_targets import ProjectileSpecialHitbox
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure
from rmuc_test_support import move_ground_robots_to_unbuffed_region


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
    move_ground_robots_to_unbuffed_region(match)
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


def _quiet_physical_match(match: Match) -> None:
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    move_ground_robots_to_unbuffed_region(match)


def _projectile_for_rule_contact(
    robot: Robot,
    *,
    caliber: str = "17mm",
    speed: float = 25_000.0,
) -> Projectile:
    return Projectile(
        id=9900,
        shooter_id=robot.id,
        shooter_team_id=robot.team,
        caliber=caliber,
        damage=20,
        radius=8.4,
        speed=speed,
        effective_range=2400.0,
        position=(0.0, 0.0),
        previous_position=(0.0, 0.0),
        velocity=(speed, 0.0),
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


def test_small_energy_live_command_eligibility_and_accumulated_chances() -> None:
    match = _match()
    rules = match.ruleset
    red_hero = _robot(match, "tarsgo-hero")
    red_engineer = _robot(match, "tarsgo-engineer")
    red_infantry = _robot(match, "tarsgo-infantry-1")
    red_sentry = _robot(match, "tarsgo-sentry")

    assert not rules.request_small_energy_mechanism_activation(match, red_hero)
    assert not rules.request_small_energy_mechanism_activation(match, red_engineer)
    red_infantry.alive = False
    assert not rules.request_small_energy_mechanism_activation(match, red_infantry)
    red_infantry.alive = True
    assert rules.request_small_energy_mechanism_activation(match, red_infantry)
    assert not rules.request_small_energy_mechanism_activation(match, red_sentry)

    # A missed first lit window fails and resets the active state. The manual
    # does not specify chance refunds; Rules Lab consumes one at command start.
    match.update(2.5)
    state = rules._small_energy_mechanism_by_team[RED]
    assert state.status == "inactive"
    assert state.failure_count == 1
    assert state.opportunities_used == 1
    assert not rules.small_energy_mechanism_activation_available(RED)

    match.update(87.499)
    assert not rules.request_small_energy_mechanism_activation(match, red_sentry)
    match.update(0.001)
    assert match.elapsed_time == pytest.approx(90.0)
    assert rules.request_small_energy_mechanism_activation(match, red_sentry)
    assert state.opportunities_used == 2

    late = _match()
    late.update(180.0)
    assert not late.ruleset.request_small_energy_mechanism_activation(
        late,
        _robot(late, "tarsgo-sentry"),
    )


def test_match_activation_command_allows_eligible_player_infantry_and_sentry() -> None:
    infantry_match = Match.from_scenario(SCENARIO)
    assert infantry_match.order_activate_small_energy_mechanism("tarsgo-infantry-1")
    assert not infantry_match.order_activate_small_energy_mechanism("tarsgo-hero")

    sentry_match = Match.from_scenario(SCENARIO)
    assert sentry_match.order_activate_small_energy_mechanism("tarsgo-sentry")
    assert not sentry_match.order_activate_small_energy_mechanism(
        "opponent-sentry"
    )


def test_small_energy_real_projectiles_complete_five_lit_modules_and_reward() -> None:
    match = _match()
    _quiet_physical_match(match)
    rules = match.ruleset
    sentry = _robot(match, "tarsgo-sentry")
    assert rules.request_small_energy_mechanism_activation(match, sentry)
    state = rules._small_energy_mechanism_by_team[RED]
    contacts = []

    for _ in range(60 * 5):
        target = rules.small_energy_mechanism_aim_targets().get(sentry.id)
        if target is not None and target.approach_position is not None:
            # Keep this physical-collision fixture on the current clear radial
            # side; the separate spectator-AI test covers actual navigation.
            sentry.position = target.approach_position
            sentry.velocity = (0.0, 0.0)
        sentry.attack_cooldown = 0.0
        match.update(1.0 / 60.0)
        contacts.extend(
            impact
            for impact in match.projectile_system.impacts
            if impact.target_kind == "energy_mechanism"
        )
        if state.status == "activated":
            break

    progression = [
        impact
        for impact in contacts
        if impact.outcome in {"energy_module_activated", "energy_activated"}
    ]
    assert [impact.outcome for impact in progression] == [
        "energy_module_activated",
        "energy_module_activated",
        "energy_module_activated",
        "energy_module_activated",
        "energy_activated",
    ]
    assert len({impact.armor_face for impact in progression}) == 5
    assert all(impact.caliber == "17mm" for impact in contacts)
    assert rules._small_energy_mechanism_activation_times_by_team[RED] == [0.0]
    assert rules._current_small_energy_mechanism_defense(RED) == pytest.approx(0.25)
    assert rules._current_small_energy_mechanism_defense(BLUE) == 0.0
    assert rules._energy_mechanism_buffs_by_team[RED][0].experience_bonus_remaining == 1200.0


def test_spectator_ai_activates_small_energy_through_real_projectiles() -> None:
    match = Match.from_scenario(SCENARIO, rmuc_spectator_ai=True)
    rules = match.ruleset
    sentry = _robot(match, "tarsgo-sentry")
    sentry.position = rules.small_energy_mechanism_activation_position(sentry.team)
    sentry.path.clear()
    match.robots = [sentry]
    # Fixed Rules Lab sequence/rotation seeds make autonomous movement and
    # physical projectile contacts reproducible without teleporting in flight.
    rules._small_energy_rng_by_team[sentry.team] = random.Random(0)
    rules._small_energy_mechanism_entity = SmallEnergyMechanism(
        center=(match.map.width / 2.0, match.map.height / 2.0),
        rotation_direction=1,
    )
    state = rules._small_energy_mechanism_by_team[sentry.team]
    impacts = []

    for _ in range(60 * 10):
        match.update(1.0 / 60.0)
        impacts.extend(
            impact
            for impact in match.projectile_system.impacts
            if impact.target_kind == "energy_mechanism"
        )
        if state.status == "activated":
            break

    successful_hits = [
        impact
        for impact in impacts
        if impact.outcome in {"energy_module_activated", "energy_activated"}
    ]
    assert state.status == "activated"
    assert state.failure_count == 0
    assert [impact.outcome for impact in successful_hits] == [
        "energy_module_activated",
        "energy_module_activated",
        "energy_module_activated",
        "energy_module_activated",
        "energy_activated",
    ]
    assert len({impact.armor_face for impact in successful_hits}) == 5
    assert all(impact.shooter_id == sentry.id for impact in successful_hits)
    assert rules._current_small_energy_mechanism_defense(sentry.team) == pytest.approx(
        0.25
    )


def test_small_energy_real_unlit_module_contact_resets_only_its_team() -> None:
    match = _match()
    _quiet_physical_match(match)
    rules = match.ruleset
    red_sentry = _robot(match, "tarsgo-sentry")
    blue_sentry = _robot(match, "opponent-sentry")
    assert rules.request_small_energy_mechanism_activation(match, red_sentry)
    assert rules.request_small_energy_mechanism_activation(match, blue_sentry)
    red_state = rules._small_energy_mechanism_by_team[RED]
    blue_state = rules._small_energy_mechanism_by_team[BLUE]
    wrong_index = next(
        index for index in range(5) if index != red_state.lit_module_index
    )
    entity = rules._small_energy_mechanism_entity
    assert entity is not None
    panel = next(
        panel
        for panel in entity.panels_at(match.elapsed_time)
        if panel.module_index == wrong_index
    )
    dx = panel.center[0] - entity.center[0]
    dy = panel.center[1] - entity.center[1]
    radial_length = math.hypot(dx, dy)
    radial = (dx / radial_length, dy / radial_length)
    start_radius = entity.panel_outer_radius_mm + 100.0
    start = (
        entity.center[0] + radial[0] * start_radius,
        entity.center[1] + radial[1] * start_radius,
    )
    speed = 25_000.0
    wrong_projectile = Projectile(
        id=9901,
        shooter_id=red_sentry.id,
        shooter_team_id=RED,
        caliber="17mm",
        damage=20,
        radius=8.4,
        speed=speed,
        effective_range=2400.0,
        position=start,
        previous_position=start,
        velocity=(-radial[0] * speed, -radial[1] * speed),
        height_mm=match.map.terrain_height_at(start),
        target_id=f"manual-test:{wrong_index}",
    )
    match.projectile_system.projectiles.append(wrong_projectile)

    for _ in range(3):
        match.update(1.0 / 60.0)
        if match.projectile_system.impacts:
            break

    contact = next(
        impact
        for impact in match.projectile_system.impacts
        if impact.target_kind == "energy_mechanism"
    )
    assert contact.armor_face == str(wrong_index)
    assert contact.outcome == "energy_activation_failed"
    assert red_state.status == "inactive"
    assert red_state.failure_count == 1
    assert blue_state.status == "activating"
    assert blue_state.completed_modules == set()


def test_small_energy_projectile_speed_caliber_and_lit_window_boundaries() -> None:
    match = _match()
    rules = match.ruleset
    sentry = _robot(match, "tarsgo-sentry")
    assert rules.request_small_energy_mechanism_activation(match, sentry)
    state = rules._small_energy_mechanism_by_team[RED]
    entity = rules._small_energy_mechanism_entity
    assert entity is not None

    def lit_contact(*, caliber: str, speed: float, impact_time: float) -> str:
        assert state.lit_module_index is not None
        panel = next(
            item
            for item in entity.panels_at(impact_time)
            if item.module_index == state.lit_module_index
        )
        projectile = _projectile_for_rule_contact(
            sentry,
            caliber=caliber,
            speed=speed,
        )
        hitbox = ProjectileSpecialHitbox(
            id=entity.id,
            target_kind="energy_mechanism",
            module_id=str(panel.module_index),
            vertices=panel.vertices,
        )
        return rules.on_small_energy_mechanism_projectile_hit(
            projectile,
            hitbox,
            panel.center,
            speed,
            impact_time,
        )

    assert lit_contact(caliber="42mm", speed=20_000.0, impact_time=0.1) == (
        "energy_mechanism_illegal_projectile"
    )
    assert lit_contact(caliber="17mm", speed=12_000.0, impact_time=0.1) == (
        "energy_mechanism_ineffective"
    )
    assert state.status == "activating"
    assert not state.completed_modules

    # An impact at the inclusive 2.5-second limit is valid. Just beyond the
    # next lamp's deadline, the same target contact resets the attempt.
    assert (
        lit_contact(caliber="17mm", speed=12_000.001, impact_time=2.5)
        == "energy_module_activated"
    )
    assert state.status == "activating"
    next_deadline = state.lit_module_deadline
    assert next_deadline == pytest.approx(5.0)
    assert (
        lit_contact(
            caliber="17mm",
            speed=12_000.001,
            impact_time=next_deadline + 1e-6,
        )
        == "energy_activation_failed"
    )
    assert state.status == "inactive"
    assert state.failure_count == 1


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
