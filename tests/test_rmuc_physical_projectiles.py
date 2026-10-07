import math
from dataclasses import replace
from pathlib import Path

import pytest

from tarsgo_simulator.core.map import Rectangle
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.projectiles import (
    Projectile,
    ProjectileImpact,
    ProjectileSystem,
    predictive_intercept_point,
)
from rmuc_test_support import move_ground_robots_to_unbuffed_region


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"
TICK = 1.0 / 60.0


def _match() -> Match:
    match = Match.from_scenario(SCENARIO)
    move_ground_robots_to_unbuffed_region(match)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        if robot.type == "drone":
            robot.position = (1000.0, 1000.0)
    return match


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _prepare_duel(match: Match, *, distance: float = 2000.0):
    shooter = _robot(match, "tarsgo-infantry-1")
    target = _robot(match, "opponent-infantry-1")
    shooter.position = (12000.0, 7500.0)
    target.position = (shooter.position[0] + distance, shooter.position[1])
    for robot in match.robots:
        if robot not in (shooter, target) and robot.type != "drone":
            robot.position = (5000.0 + len(robot.id) * 17.0, 1200.0)
    shooter.attack_cooldown = 0.0
    target.attack_cooldown = 9999.0
    match.ruleset._projectile_allowance_by_robot[shooter.id].allowed = 100
    return shooter, target


def _ticks(match: Match, count: int) -> None:
    for _ in range(count):
        match.update(TICK)


def test_17mm_continuous_fire_keeps_multiple_independent_projectiles_in_flight() -> None:
    match = _match()
    shooter, target = _prepare_duel(match)
    target_hp = target.hp

    match.update(TICK)
    assert target.hp == target_hp  # Launch itself is not a damage event.
    _ticks(match, 3)

    assert len(match.projectiles) == 2
    assert len({projectile.id for projectile in match.projectiles}) == 2
    assert all(projectile.shooter_id == shooter.id for projectile in match.projectiles)
    assert all(projectile.caliber == "17mm" for projectile in match.projectiles)
    assert match.ruleset._projectile_allowance_by_robot[shooter.id].allowed == 98
    assert match.ruleset._shooting_heat_by_robot[shooter.id].heat == 20


def test_swept_collision_catches_a_projectile_crossing_a_robot_in_one_large_step() -> None:
    match = _match()
    shooter, target = _prepare_duel(match, distance=1000.0)
    target_hp = target.hp

    match.update(TICK)
    shooter.attack_cooldown = 9999.0
    match.update(0.5)

    assert target.hp == target_hp - shooter.damage
    assert match.projectile_impacts
    assert match.projectile_impacts[0].target_id == target.id
    assert match.projectiles == []


def test_projectile_aims_at_current_target_position_and_can_miss_a_moving_robot() -> None:
    match = _match()
    shooter, target = _prepare_duel(match, distance=2200.0)
    target_hp = target.hp

    match.update(TICK)  # Commit one shot.
    shooter.attack_cooldown = 9999.0
    target.position = (target.position[0], target.position[1] + 700.0)
    _ticks(match, 20)

    assert target.hp == target_hp
    assert match.projectiles == []  # The missed shot expires at simulated range.
    assert match.projectile_diagnostics["launched"] == 1
    assert match.projectile_diagnostics["misses"] == 1


def test_obstacle_added_in_front_of_live_shot_consumes_it_without_target_damage() -> None:
    match = _match()
    _shooter, target = _prepare_duel(match)
    target_hp = target.hp
    match.update(TICK)
    match.map.obstacles = (*match.map.obstacles, Rectangle(12400.0, 7400.0, 120.0, 200.0))

    match.update(TICK)

    assert target.hp == target_hp
    assert match.projectiles == []
    assert match.projectile_impacts
    assert match.projectile_impacts[0].target_kind == "obstacle"
    assert match.projectile_impacts[0].applied_damage == 0


def test_projectile_can_damage_an_enemy_structure_through_the_damage_pipeline() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    outpost = next(
        structure
        for structure in match.structures
        if structure.type == "outpost" and structure.team == BLUE
    )
    hero.position = (outpost.position[0] - 2400.0, outpost.position[1])
    hero.attack_cooldown = 0.0
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 5
    for robot in match.robots:
        if robot is not hero and robot.type != "drone":
            robot.position = (14000.0 + len(robot.id) * 20.0, 13000.0)
            robot.attack_cooldown = 9999.0
    original_hp = outpost.hp

    match.update(TICK)
    for _ in range(20):
        match.update(TICK)
        if outpost.hp < original_hp:
            break

    assert outpost.hp == original_hp - hero.damage
    assert any(
        impact.target_id == outpost.id and impact.applied_damage == hero.damage
        for impact in match.projectile_impacts
    )


def test_invincible_robot_is_physically_hit_but_referee_applies_zero_damage() -> None:
    match = _match()
    shooter, target = _prepare_duel(match, distance=1000.0)
    match.ruleset._robot_lifecycle_by_robot[target.id].invincible_remaining = 5.0
    original_hp = target.hp

    match.update(TICK)
    for _ in range(12):
        match.update(TICK)
        if match.projectile_impacts:
            break

    assert target.hp == original_hp
    assert match.projectile_impacts
    assert match.projectile_impacts[0].target_id == target.id
    assert match.projectile_impacts[0].applied_damage == 0
    assert match.projectile_impacts[0].surface == "armor"
    assert match.projectile_impacts[0].outcome == "immune"
    assert match.ruleset._projectile_allowance_by_robot[shooter.id].allowed == 99
    diagnostics = match.projectile_diagnostics
    assert diagnostics["shots_fired"] == 1
    assert diagnostics["robot_contacts"] == 1
    assert diagnostics["armor_hits"] == 1
    assert diagnostics["applied_damage"] == 0
    assert diagnostics["per_robot_hit_rate"][shooter.id]["hit_rate_pct"] == 100.0


def _swept_robot_contact(
    chassis_angle: float,
    *,
    invincible: bool = False,
    lateral_offset: float = 0.0,
):
    match = _match()
    shooter, target = _prepare_duel(match, distance=1000.0)
    target.chassis_angle = chassis_angle
    if invincible:
        match.ruleset._robot_lifecycle_by_robot[target.id].invincible_remaining = 5.0
    target_hp = target.hp
    system = ProjectileSystem()
    system.projectiles.append(
        Projectile(
            id=1,
            shooter_id=shooter.id,
            shooter_team_id=shooter.team,
            caliber="17mm",
            damage=shooter.damage,
            radius=8.4,
            speed=25_000.0,
            effective_range=1000.0,
            position=(target.position[0] - 500.0, target.position[1] + lateral_offset),
            previous_position=(target.position[0] - 500.0, target.position[1] + lateral_offset),
            velocity=(25_000.0, 0.0),
        )
    )
    system.advance(
        0.04,
        match.robots,
        match.structures,
        match.map,
        robot_hitboxes=match.ruleset.projectile_robot_hitbox_parameters(),
        apply_damage=lambda victim, amount, attacker: match.apply_damage(
            victim,
            amount,
            source_robot=attacker,
        ),
    )
    return match, target, target_hp, system


def test_robot_damage_requires_swept_contact_with_rotating_armor_plate() -> None:
    aligned_match, aligned_target, aligned_hp, aligned_system = _swept_robot_contact(0.0)
    assert aligned_target.hp == aligned_hp - 20
    assert aligned_system.impacts[0].surface == "armor"
    assert aligned_system.impacts[0].armor_face == "rear"
    assert aligned_system.impacts[0].outcome == "damage"

    spun_match, spun_target, spun_hp, spun_system = _swept_robot_contact(math.pi / 4)
    assert spun_target.hp == spun_hp
    assert spun_system.impacts[0].surface == "wheel"
    assert spun_system.impacts[0].outcome == "non_armor"
    assert spun_system.robot_contacts == 1
    assert spun_system.nonarmor_contacts == 1
    assert spun_system.armor_hits == 0
    assert aligned_match.map.collision_radius == spun_match.map.collision_radius


def test_invincible_armor_contact_is_counted_as_absorbed_not_damage() -> None:
    _match_state, target, target_hp, system = _swept_robot_contact(0.0, invincible=True)
    assert target.hp == target_hp
    assert system.impacts[0].surface == "armor"
    assert system.impacts[0].outcome == "immune"
    assert system.armor_hits == 1
    assert system.applied_damage == 0


def test_wheel_contact_consumes_shot_without_armor_damage() -> None:
    _match_state, target, target_hp, system = _swept_robot_contact(
        0.0,
        lateral_offset=95.0,
    )
    assert target.hp == target_hp
    assert system.impacts[0].surface == "wheel"
    assert system.impacts[0].outcome == "non_armor"
    assert system.nonarmor_contacts == 1


def test_42mm_uses_official_speed_ceiling_but_slower_lab_cadence() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    target = _robot(match, "opponent-infantry-1")
    hero.position = (12000.0, 7500.0)
    target.position = (14000.0, 7500.0)
    target.hp = target.max_hp = 1000
    hero.attack_cooldown = 0.0
    target.attack_cooldown = 9999.0
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 10
    for robot in match.robots:
        if robot is not hero and robot is not target and robot.type != "drone":
            robot.position = (5000.0 + len(robot.id) * 17.0, 1200.0)
            robot.attack_cooldown = 9999.0
    infantry = _robot(match, "tarsgo-infantry-1")
    hero_parameters = match.ruleset.projectile_parameters_for(hero)
    infantry_parameters = match.ruleset.projectile_parameters_for(infantry)

    assert hero_parameters is not None and infantry_parameters is not None
    assert hero_parameters.speed == 12_000.0
    assert hero_parameters.firing_interval > infantry_parameters.firing_interval

    _ticks(match, 20)
    assert match.projectile_diagnostics["launched"] == 1
    _ticks(match, 12)
    assert match.projectile_diagnostics["launched"] == 2


def test_predictive_aim_leads_from_observed_velocity_and_fires_on_turret_heading() -> None:
    match = _match()
    shooter, target = _prepare_duel(match, distance=2000.0)
    target.speed = 1200.0
    target.path = [(target.position[0], target.position[1] + 1200.0)]
    match.config = replace(
        match.config,
        scenario=replace(
            match.config.scenario,
            player_controlled=frozenset(
                {*match.config.scenario.player_controlled, shooter.id, target.id}
            ),
        ),
    )

    match.update(TICK)

    assert target.velocity[1] == pytest.approx(1200.0)
    assert shooter.aim_target_id == target.id
    assert shooter.aim_point is not None
    assert shooter.aim_point[1] > target.position[1] + 60.0
    assert len(match.projectiles) == 1
    projectile = match.projectiles[0]
    fired_angle = math.atan2(projectile.velocity[1], projectile.velocity[0])
    assert fired_angle == pytest.approx(shooter.turret_angle)
    assert fired_angle > 0.02


def test_intercept_uses_caliber_speed_and_falls_back_if_target_is_too_fast() -> None:
    shooter = (1000.0, 1000.0)
    target = (2000.0, 1000.0)
    lateral_velocity = (0.0, 1500.0)
    aim_17 = predictive_intercept_point(
        shooter,
        target,
        lateral_velocity,
        projectile_speed=25_000.0,
        maximum_range=2400.0,
    )
    aim_42 = predictive_intercept_point(
        shooter,
        target,
        lateral_velocity,
        projectile_speed=12_000.0,
        maximum_range=2400.0,
    )
    assert aim_42[1] - target[1] > aim_17[1] - target[1]

    moving_away = predictive_intercept_point(
        shooter,
        target,
        (30_000.0, 0.0),
        projectile_speed=25_000.0,
        maximum_range=2400.0,
    )
    assert moving_away == target


def test_chassis_spin_is_repeatable_while_turret_keeps_tracking_target() -> None:
    first = _match()
    second = _match()
    first_shooter, first_target = _prepare_duel(first)
    second_shooter, _second_target = _prepare_duel(second)
    first_shooter.attack_cooldown = 9999.0
    second_shooter.attack_cooldown = 9999.0
    initial_angle = first_shooter.chassis_angle

    for _ in range(60):
        first.update(TICK)
        second.update(TICK)

    assert first_shooter.chassis_spin_direction == second_shooter.chassis_spin_direction
    assert first_shooter.chassis_angle == pytest.approx(second_shooter.chassis_angle)
    assert abs(first_shooter.chassis_angle - initial_angle) > 2.5
    assert first_shooter.aim_target_id == first_target.id
    assert abs(first_shooter.turret_angle) < 0.05
    assert abs(first_shooter.chassis_angular_velocity) == pytest.approx(3.0)


def test_engineer_does_not_chassis_spin() -> None:
    match = _match()
    engineer = next(robot for robot in match.robots if robot.type == "engineer")
    target = _robot(match, "opponent-infantry-1")
    engineer.position = (12000.0, 7500.0)
    target.position = (14000.0, 7500.0)

    match.update(TICK)

    assert engineer.chassis_angle == 0.0
    assert engineer.chassis_angular_velocity == 0.0


def test_live_projectile_pressure_has_bounded_deterministic_state() -> None:
    system = ProjectileSystem()
    system.projectiles = [
        Projectile(
            id=index + 1,
            shooter_id=f"shooter-{index % 12}",
            shooter_team_id=RED,
            caliber="17mm",
            damage=20,
            radius=8.4,
            speed=25_000.0,
            effective_range=2400.0,
            position=(1000.0, 1000.0 + index),
            previous_position=(1000.0, 1000.0 + index),
            velocity=(25_000.0, 0.0),
        )
        for index in range(1000)
    ]
    empty_map = Match.from_scenario(SCENARIO).map
    robots = []
    structures = []

    system.advance(
        TICK,
        robots,
        structures,
        empty_map,
        apply_damage=lambda _target, _amount, _shooter: 0,
    )

    assert len(system.projectiles) == 1000
    assert all(projectile.position[0] == pytest.approx(1416.6666667) for projectile in system.projectiles)


def test_finished_match_clears_stale_projectile_contact_snapshots() -> None:
    match = _match()
    match.projectile_system.impacts.append(
        ProjectileImpact(
            projectile_id=1,
            shooter_id="tarsgo-infantry-1",
            shooter_team_id=RED,
            caliber="17mm",
            position=(1000.0, 1000.0),
            direction=(25_000.0, 0.0),
            target_id="opponent-infantry-1",
            target_kind="robot",
            applied_damage=20,
        )
    )
    match.finished = True

    match.update(TICK)

    assert match.projectile_impacts == ()
