import importlib
import math
from pathlib import Path
import sys

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.projectiles import ProjectileImpact
from tarsgo_simulator.desktop.visuals import (
    CombatVisualState,
    DartLauncherVisualState,
    DartVisual,
    ImpactEffect,
    MAX_ACTIVE_DART_VISUALS,
    MAX_ACTIVE_IMPACTS,
    MAX_REBOUND_PROJECTILES,
    MAX_VISIBLE_IMPACT_PARTICLES,
    MAX_SCREEN_SHAKE_AMPLITUDE,
    MAX_SCREEN_SHAKE_DURATION,
    MoveMarker,
    OUTPOST_ROTATION_RETURN_SECONDS,
    OUTPOST_ROTATION_SPEED,
    ReboundProjectileVisual,
    OutpostRotorVisualState,
    VisualProjectile,
    VisualRobotState,
    VisualStructureState,
    low_hp_warning_strength,
    projectile_visual_profile,
    robot_visual_profile,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RMUC_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)
RMUL_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmul-2026-rules-lab.yaml"
)
TRAINING_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "first-steps.yaml"
)
RMUC_RED_TEAM = "tarsgo-rmuc-2026-region"
RMUC_BLUE_TEAM = "opponent-rmuc-2026-region"


@pytest.fixture(scope="module", autouse=True)
def _cleanup_desktop_imports():
    yield
    pygame = sys.modules.get("pygame")
    if pygame is not None:
        pygame.quit()
    sys.modules.pop("tarsgo_simulator.desktop.app", None)
    sys.modules.pop("tarsgo_simulator.desktop.icon", None)
    for module_name in list(sys.modules):
        if module_name == "pygame" or module_name.startswith("pygame."):
            sys.modules.pop(module_name, None)


def _app():
    return importlib.import_module("tarsgo_simulator.desktop.app")


def _match(path: Path = RMUC_SCENARIO) -> Match:
    return Match.from_scenario(path)


def test_robot_types_have_distinct_visual_profiles() -> None:
    profiles = {
        robot_type: robot_visual_profile(robot_type)
        for robot_type in ("hero", "engineer", "infantry", "sentry", "drone")
    }

    assert len(set(profiles.values())) == 5
    assert profiles["hero"].barrel_width > profiles["infantry"].barrel_width
    assert profiles["engineer"].barrel_length == 0
    assert profiles["engineer"].tool_arm_length > 0
    assert profiles["sentry"].body_width > profiles["infantry"].body_width
    assert profiles["drone"].barrel_length == 0


def test_rmuc_robot_silhouettes_are_distinct_without_labels() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.init()
    renderings = []

    for robot_type in ("hero", "engineer", "infantry", "sentry", "drone"):
        surface = pygame.Surface((128, 128))
        surface.fill((18, 24, 32))
        app._draw_rmuc_robot_shape(
            surface,
            center=(64, 64),
            robot_type=robot_type,
            color=app.TEAM_RED_COLOR,
            body_angle=0.23,
            turret_angle=-0.35,
            alive=True,
            selected=False,
            animation_time=0.0,
            muzzle_remaining=0.0,
            muzzle_caliber="42mm" if robot_type == "hero" else "17mm",
            impact_remaining=0.0,
        )
        renderings.append(pygame.image.tostring(surface, "RGB"))

    assert len(set(renderings)) == 5


def test_rmuc_robot_sprite_layers_follow_body_and_turret_angles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.init()
    requested_angles: list[tuple[str, float]] = []
    render_asset = app.ASSET_MANAGER.render

    def record_render(
        relative_path: str,
        *,
        size: tuple[int, int] | None = None,
        angle: float = 0.0,
        tint: tuple[int, int, int] | None = None,
        fallback: pygame.Surface | None = None,
    ) -> pygame.Surface | None:
        requested_angles.append((relative_path, angle))
        return render_asset(
            relative_path,
            size=size,
            angle=angle,
            tint=tint,
            fallback=fallback,
        )

    monkeypatch.setattr(app.ASSET_MANAGER, "render", record_render)
    app._draw_rmuc_robot_shape(
        pygame.Surface((128, 128)),
        center=(64, 64),
        robot_type="hero",
        color=app.TEAM_BLUE_COLOR,
        body_angle=math.pi / 2,
        turret_angle=0.0,
        alive=True,
        selected=False,
        animation_time=0.0,
        muzzle_remaining=0.0,
        muzzle_caliber="42mm",
        impact_remaining=0.0,
    )

    assert requested_angles == [
        ("robots/hero-chassis.png", -90.0),
        ("robots/hero-turret.png", 0.0),
    ]


def test_visual_orientation_update_does_not_mutate_gameplay_position() -> None:
    match = _match()
    robot = next(item for item in match.robots if item.id == "tarsgo-hero")
    original_position = robot.position
    visual = VisualRobotState(
        position=robot.position,
        hp=robot.hp,
        cooldown=robot.attack_cooldown,
    )

    visual.advance_motion((original_position[0], original_position[1] + 100.0), 0.1)

    assert robot.position == original_position
    assert visual.position != original_position
    assert visual.body_angle > 0
    assert visual.body_angle < math.pi / 2
    assert visual.previous_position == original_position
    assert visual.interpolated_position(0.0) == original_position
    assert visual.interpolated_position(1.0) == visual.position
    midpoint = visual.interpolated_position(0.5)
    assert midpoint[0] == pytest.approx(original_position[0])
    assert midpoint[1] == pytest.approx(original_position[1] + 50.0)


def test_physical_projectile_visual_follows_simulation_state() -> None:
    match = _match()
    attacker = next(item for item in match.robots if item.id == "tarsgo-hero")
    target = next(item for item in match.robots if item.id == "opponent-hero")
    attacker.position = (10000.0, 7500.0)
    target.position = (10500.0, 7500.0)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        if robot not in (attacker, target) and robot.type != "drone":
            robot.position = (4000.0 + len(robot.id) * 20.0, 1000.0)
    attacker.attack_cooldown = 0.0
    match.ruleset._projectile_allowance_by_robot[attacker.id].allowed = 1

    visuals = CombatVisualState()
    visuals.reset(match)
    visuals.begin_frame(match)
    match.update(1.0 / 60.0)
    visuals.after_match_update(match, 1.0 / 60.0)

    assert visuals.projectiles == []
    assert len(visuals.physical_projectiles) == 1
    projectile = next(iter(visuals.physical_projectiles.values()))
    assert projectile.caliber == "42mm"
    assert projectile.position == match.projectiles[0].position
    assert visuals.robots[attacker.id].muzzle_remaining > 0
    robot_visual = visuals.robots[attacker.id]
    assert robot_visual.body_angle == pytest.approx(attacker.chassis_angle)
    assert robot_visual.turret_angle == pytest.approx(attacker.turret_angle)
    assert robot_visual.interpolated_body_angle(1.0) == pytest.approx(
        attacker.chassis_angle
    )
    assert robot_visual.interpolated_turret_angle(1.0) == pytest.approx(
        attacker.turret_angle
    )


def test_cosmetic_projectile_expires_without_touching_match_state() -> None:
    projectile = VisualProjectile(
        start=(0.0, 0.0),
        end=(100.0, 0.0),
        caliber="17mm",
        attacker_team_id="red",
        target_id="target",
        damaging=True,
    )

    projectile.advance(projectile.profile.lifetime / 2)
    assert not projectile.expired
    assert projectile.position[0] == pytest.approx(50.0)

    projectile.advance(projectile.profile.lifetime / 2)
    assert projectile.expired
    assert projectile.position == pytest.approx((100.0, 0.0))


def test_17mm_and_42mm_visual_profiles_are_obviously_different() -> None:
    small = projectile_visual_profile("17mm")
    large = projectile_visual_profile("42mm")

    assert large.tracer_width > small.tracer_width
    assert large.head_radius > small.head_radius
    assert large.flash_duration > small.flash_duration
    assert large.impact_duration > small.impact_duration
    assert large.lifetime > small.lifetime


def test_impact_particles_are_deterministic_bounded_and_caliber_specific() -> None:
    small = ImpactEffect(
        (0.0, 0.0), "17mm", 0.12, 0.12, attacker_team_id=RMUC_RED_TEAM
    )
    repeated = ImpactEffect(
        (0.0, 0.0), "17mm", 0.12, 0.12, attacker_team_id=RMUC_RED_TEAM
    )
    large = ImpactEffect(
        (0.0, 0.0), "42mm", 0.22, 0.22, attacker_team_id=RMUC_RED_TEAM
    )
    dart = ImpactEffect(
        (0.0, 0.0), "dart", 0.46, 0.46, attacker_team_id=RMUC_BLUE_TEAM
    )

    assert small.particles == repeated.particles
    assert len(small.particles) < len(large.particles) < len(dart.particles)
    assert {particle.kind for particle in small.particles} >= {"spark", "metal"}
    assert {particle.kind for particle in dart.particles} >= {
        "spark", "metal", "dust"
    }
    assert "smoke" in {particle.kind for particle in large.particles}
    assert max(particle.lifetime for particle in small.particles) < max(
        particle.lifetime for particle in large.particles
    ) < max(particle.lifetime for particle in dart.particles)
    assert len(small.particles) == 4
    assert len(large.particles) == 10
    assert len(dart.particles) == 14
    assert max(particle.lifetime for particle in small.particles) < 0.11
    assert "team" not in {particle.kind for particle in dart.particles}
    assert MAX_ACTIVE_IMPACTS * len(dart.particles) <= MAX_VISIBLE_IMPACT_PARTICLES


def test_immune_and_nonarmor_contacts_use_compact_surface_specific_feedback() -> None:
    damage = ImpactEffect((0.0, 0.0), "42mm", 0.22, 0.22)
    immune = ImpactEffect(
        (0.0, 0.0), "42mm", 0.22, 0.22, surface="armor", outcome="immune"
    )
    chassis = ImpactEffect(
        (0.0, 0.0), "17mm", 0.12, 0.12, surface="chassis", outcome="non_armor"
    )
    obstacle = ImpactEffect(
        (0.0, 0.0), "17mm", 0.12, 0.12, surface="obstacle", outcome="obstacle"
    )

    assert len(immune.particles) < len(damage.particles)
    assert "absorbed" in {particle.kind for particle in immune.particles}
    assert {particle.kind for particle in chassis.particles} == {"metal", "dust"}
    assert {particle.kind for particle in obstacle.particles} == {"debris", "dust"}
    assert len(chassis.particles) < len(
        ImpactEffect((0.0, 0.0), "17mm", 0.12, 0.12).particles
    )
    assert "debris" in {particle.kind for particle in obstacle.particles}


def test_dart_visuals_follow_rule_launch_and_separate_referee_hit() -> None:
    match = _match()
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    visuals = CombatVisualState()
    visuals.reset(match)
    rules = match.ruleset
    target = next(
        structure
        for structure in match.structures
        if structure.team == RMUC_BLUE_TEAM and structure.type == "outpost"
    )
    starting_hp = target.hp

    match.update(30.0)
    assert rules.open_dart_gate(match, RMUC_RED_TEAM)
    visuals.begin_frame(match)
    match.update(1.0 / 60.0)
    visuals.after_match_update(match, 1.0 / 60.0)
    launcher = visuals.dart_launchers[RMUC_RED_TEAM]
    assert launcher.phase == "opening"
    assert 0.0 < launcher.gate_open < 1.0

    opening = rules._dart_system_by_team[RMUC_RED_TEAM].gate_full_open_at
    assert opening is not None
    match.update(opening - match.elapsed_time)
    assert target.hp == starting_hp
    visuals.begin_frame(match)
    assert rules.fire_dart(match, RMUC_RED_TEAM)
    visuals.after_match_update(match, 1.0 / 60.0)

    assert len(visuals.dart_projectiles) == 1
    dart_visual = visuals.dart_projectiles[0]
    assert isinstance(dart_visual, DartVisual)
    assert dart_visual.target_id == target.id
    assert target.hp == starting_hp
    assert launcher.ammo == 3
    assert launcher.launch_pulse_remaining > 0

    attempt = rules._dart_system_by_team[RMUC_RED_TEAM].pending_projectiles[0]
    while match.elapsed_time + 1e-9 < attempt.completes_at:
        flight_dt = min(1.0 / 60.0, attempt.completes_at - match.elapsed_time)
        visuals.begin_frame(match)
        match.update(flight_dt)
        visuals.after_match_update(match, flight_dt)
    dart_impacts = [impact for impact in visuals.impacts if impact.caliber == "dart"]
    assert len(dart_impacts) == 1
    assert dart_impacts[0].position == target.position
    assert target.hp == starting_hp - 750


def test_dart_visuals_detect_same_tick_repeated_hit_from_ammo_drop() -> None:
    match = _match()
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    rules = match.ruleset
    blue_outpost = next(
        structure
        for structure in match.structures
        if structure.team == RMUC_BLUE_TEAM and structure.type == "outpost"
    )
    blue_outpost.hp = 0
    blue_outpost.alive = False
    rules._team_states[RMUC_BLUE_TEAM].outpost_ever_destroyed = True
    blue_base = next(
        structure
        for structure in match.structures
        if structure.team == RMUC_BLUE_TEAM and structure.type == "base"
    )

    visuals = CombatVisualState()
    visuals.reset(match)
    match.update(30.0)
    assert rules.open_dart_gate(match, RMUC_RED_TEAM, "fixed")
    match.update(7.0)

    visuals.begin_frame(match)
    assert rules.fire_dart(match, RMUC_RED_TEAM)
    visuals.after_match_update(match, 0.0)
    visuals.begin_frame(match)
    assert rules.record_dart_hit(match, RMUC_RED_TEAM, blue_base.id)
    visuals.after_match_update(match, 0.0)
    assert len([impact for impact in visuals.impacts if impact.caliber == "dart"]) == 1

    # A repeated hit result still produces a second presentation event.
    match.update(2.0)
    visuals.begin_frame(match)
    assert rules.fire_dart(match, RMUC_RED_TEAM)
    assert rules.record_dart_hit(match, RMUC_RED_TEAM, blue_base.id)
    visuals.after_match_update(match, 0.0)

    assert len([impact for impact in visuals.impacts if impact.caliber == "dart"]) == 2
    assert blue_base.hp == 4600


def test_dart_visual_miss_fades_only_after_rule_report_and_never_changes_hp() -> None:
    match = _match()
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    visuals = CombatVisualState()
    visuals.reset(match)
    rules = match.ruleset
    target = next(
        structure
        for structure in match.structures
        if structure.team == RMUC_BLUE_TEAM and structure.type == "outpost"
    )
    starting_hp = target.hp

    match.update(30.0)
    assert rules.open_dart_gate(match, RMUC_RED_TEAM, "fixed")
    match.update(7.0)
    visuals.begin_frame(match)
    assert rules.fire_dart(match, RMUC_RED_TEAM)
    visuals.after_match_update(match, 0.0)
    assert len(visuals.dart_projectiles) == 1
    assert target.hp == starting_hp

    visuals.begin_frame(match)
    assert rules.record_dart_miss(match, RMUC_RED_TEAM)
    visuals.after_match_update(match, 1.0 / 60.0)
    assert visuals.dart_projectiles[0].missed
    assert target.hp == starting_hp


def test_dart_launcher_open_state_and_effect_budget_are_bounded() -> None:
    launcher = DartLauncherVisualState()
    launcher.sync(4, "opening", 3.5, "前哨站", 1.0 / 60.0)
    assert launcher.gate_open == pytest.approx(0.5)
    launcher.sync(4, "firing", 20.0, "前哨站", 1.0 / 60.0)
    assert launcher.gate_open == 1.0
    launcher.sync(4, "cooldown", 15.0, "前哨站", 1.0 / 60.0)
    assert launcher.gate_open == 0.0

    visuals = CombatVisualState()
    visuals.impacts = [
        ImpactEffect((float(index), 0.0), "dart", 0.46, 0.46)
        for index in range(MAX_ACTIVE_IMPACTS + 1)
    ]
    visuals._cap_impacts()
    assert len(visuals.impacts) == MAX_ACTIVE_IMPACTS

    visuals.dart_projectiles = [
        DartVisual("red", str(index), (0.0, 0.0), (100.0, 0.0), 0.5)
        for index in range(MAX_ACTIVE_DART_VISUALS + 2)
    ]
    visuals.dart_projectiles = visuals.dart_projectiles[-MAX_ACTIVE_DART_VISUALS:]
    assert len(visuals.dart_projectiles) == MAX_ACTIVE_DART_VISUALS


def test_rmuc_dart_launcher_anchors_are_art_only_and_center_symmetric() -> None:
    app = _app()
    match = _match()
    anchors = app._rmuc_dart_launcher_anchors(match)

    assert len(anchors) == 2
    assert {team_id for team_id, _position, _direction in anchors} == {
        RMUC_RED_TEAM,
        RMUC_BLUE_TEAM,
    }
    red = next(item for item in anchors if item[0] == RMUC_RED_TEAM)
    blue = next(item for item in anchors if item[0] == RMUC_BLUE_TEAM)
    assert red[1][0] + blue[1][0] == pytest.approx(match.map.width)
    assert red[1][1] + blue[1][1] == pytest.approx(match.map.height)
    assert red[2] == -blue[2]
    assert not any(structure.type == "dart_launcher" for structure in match.structures)


def test_destroy_and_respawn_visual_lifecycles_are_short_and_local() -> None:
    visual = VisualRobotState(
        position=(0.0, 0.0),
        hp=100,
        cooldown=0.0,
        alive=True,
    )

    visual.register_lifecycle(False)
    assert visual.destroy_remaining > 0
    assert visual.respawn_remaining == 0
    assert visual.destroy_progress == pytest.approx(0.0)
    assert visual.muzzle_remaining == 0
    assert visual.target_hold_remaining == 0
    assert visual.previous_position == visual.position
    assert visual.previous_body_angle == visual.body_angle
    assert visual.previous_turret_angle == visual.turret_angle

    visual.advance_timers(visual.destroy_remaining / 2)
    assert 0 < visual.destroy_progress < 1

    visual.register_lifecycle(True)
    assert visual.destroy_remaining == 0
    assert visual.respawn_remaining > 0
    assert visual.respawn_progress == pytest.approx(0.0)

    visual.advance_timers(visual.respawn_remaining)
    assert visual.respawn_remaining == 0
    assert visual.respawn_progress == pytest.approx(1.0)


@pytest.mark.parametrize("robot_type", ("hero", "drone"))
def test_dead_robot_visual_freezes_pose_and_respawn_snaps_without_interpolation(
    robot_type: str,
) -> None:
    match = _match()
    visual_state = CombatVisualState()
    visual_state.reset(match)
    robot = next(robot for robot in match.robots if robot.type == robot_type)
    state = visual_state.robots[robot.id]
    robot.alive = True
    robot.hp = robot.max_hp
    state.alive = True

    robot.position = (robot.position[0] + 120.0, robot.position[1] + 45.0)
    robot.alive = False
    robot.hp = 0
    visual_state.after_match_update(match, 1.0 / 60.0)
    death_pose = state.position
    death_body = state.body_angle
    death_turret = state.turret_angle
    assert state.destroy_remaining > 0

    robot.position = (robot.position[0] + 500.0, robot.position[1] + 200.0)
    robot.chassis_angle += 1.2
    robot.turret_angle -= 1.4
    visual_state.after_match_update(match, 1.0 / 60.0)
    assert state.position == death_pose
    assert state.body_angle == death_body
    assert state.turret_angle == death_turret

    robot.alive = True
    robot.hp = robot.max_hp
    robot.position = (2400.0, 3100.0)
    robot.chassis_angle = 0.4
    robot.turret_angle = -0.3
    visual_state.after_match_update(match, 1.0 / 60.0)
    assert state.position == robot.position
    assert state.previous_position == robot.position
    assert state.interpolated_position(0.5) == robot.position
    assert state.turret_angle == pytest.approx(robot.turret_angle)
    assert state.respawn_remaining > 0


def test_temporary_chassis_power_off_keeps_live_robot_presentation() -> None:
    match = _match()
    robot = next(robot for robot in match.robots if robot.type == "hero")
    state = CombatVisualState()
    state.reset(match)
    chassis = match.ruleset._chassis_power_by_robot[robot.id]
    chassis.power_off_remaining = 2.0

    state.after_match_update(match, 1.0 / 60.0)

    assert robot.alive
    assert state.robots[robot.id].alive
    assert state.robots[robot.id].destroy_remaining == 0
    assert state.robots[robot.id].respawn_remaining == 0


def test_impact_and_shield_impact_lifecycles_expire() -> None:
    impact = ImpactEffect(
        position=(10.0, 20.0),
        caliber="42mm",
        remaining=0.20,
        duration=0.20,
        shielded=True,
        target_kind="structure",
    )
    structure = VisualStructureState(
        hp=5000,
        shield=400,
        shield_impact_remaining=0.20,
    )

    impact.advance(0.10)
    structure.advance_timers(0.10)
    assert 0 < impact.remaining < impact.duration
    assert 0 < structure.shield_impact_remaining < 0.20

    impact.advance(0.10)
    structure.advance_timers(0.10)
    assert impact.remaining == 0
    assert structure.shield_impact_remaining == 0


def test_low_hp_warning_is_bounded_and_only_active_below_threshold() -> None:
    assert low_hp_warning_strength(0.50, 0.0) == 0
    assert low_hp_warning_strength(0.0, 0.0) == 0

    first = low_hp_warning_strength(0.20, 0.0)
    second = low_hp_warning_strength(0.20, math.pi / 10)
    assert 0 < first <= 1
    assert 0 < second <= 1
    assert first != second


def test_screen_shake_is_capped_rate_limited_and_auto_decays() -> None:
    match = _match()
    visuals = CombatVisualState()
    visuals.reset(match)

    visuals.trigger_screen_shake(99.0, 99.0)
    assert visuals.shake_amplitude == MAX_SCREEN_SHAKE_AMPLITUDE
    assert visuals.shake_duration == MAX_SCREEN_SHAKE_DURATION
    first_amplitude = visuals.shake_amplitude
    visuals.trigger_screen_shake(0.5, 0.05)
    assert visuals.shake_amplitude == first_amplitude

    offset = visuals.screen_shake_offset()
    assert abs(offset[0]) <= math.ceil(MAX_SCREEN_SHAKE_AMPLITUDE)
    assert abs(offset[1]) <= math.ceil(MAX_SCREEN_SHAKE_AMPLITUDE)

    visuals.begin_frame(match)
    visuals.after_match_update(match, MAX_SCREEN_SHAKE_DURATION + 0.01)
    assert visuals.screen_shake_offset() == (0, 0)
    assert visuals.shake_remaining == 0


def test_outpost_rotor_accelerates_and_returns_to_its_initial_pose() -> None:
    rotor = OutpostRotorVisualState(direction=1)

    rotor.advance(2.5, alive=True, opponent_base_armor_deployed=False)
    assert rotor.angle == pytest.approx(math.pi / 2)
    rotor.advance(5.0, alive=True, opponent_base_armor_deployed=False)
    assert rotor.angle == pytest.approx(0.0, abs=1e-9)
    rotor.advance(6.0, alive=True, opponent_base_armor_deployed=False)
    assert rotor.angle == pytest.approx(OUTPOST_ROTATION_SPEED)

    rotor.advance(26.0, alive=True, opponent_base_armor_deployed=True)
    assert rotor.stop_time == pytest.approx(26.0)
    stopped_angle = rotor.angle
    rotor.advance(
        26.0 + OUTPOST_ROTATION_RETURN_SECONDS / 2,
        alive=True,
        opponent_base_armor_deployed=True,
    )
    assert abs(rotor.angle) < abs(stopped_angle)
    rotor.advance(
        26.0 + OUTPOST_ROTATION_RETURN_SECONDS,
        alive=True,
        opponent_base_armor_deployed=False,
    )
    assert rotor.angle == pytest.approx(0.0, abs=1e-9)
    assert rotor.stop_time == pytest.approx(26.0)


def test_outpost_rotor_direction_is_shared_per_match_and_visual_only() -> None:
    match = _match()
    visuals = CombatVisualState()
    visuals.reset(match)
    outposts = [structure for structure in match.structures if structure.type == "outpost"]
    original_positions = {structure.id: structure.position for structure in match.structures}
    original_hp = {structure.id: structure.hp for structure in match.structures}

    assert len(outposts) == 2
    directions = {visuals.outpost_rotors[item.id].direction for item in outposts}
    assert len(directions) == 1
    assert directions <= {-1, 1}

    match.elapsed_time = 31.0
    visuals.after_match_update(match, 0.0)

    assert all(abs(visuals.outpost_rotors[item.id].angle) > 0.1 for item in outposts)
    assert {structure.id: structure.position for structure in match.structures} == original_positions
    assert {structure.id: structure.hp for structure in match.structures} == original_hp


def test_outpost_rotor_stops_on_destruction_and_does_not_restart_after_rebuild() -> None:
    rotor = OutpostRotorVisualState(direction=-1)
    rotor.advance(31.0, alive=True, opponent_base_armor_deployed=False)
    rotor.advance(32.0, alive=False, opponent_base_armor_deployed=False)
    destroyed_pose = rotor.angle

    rotor.advance(40.0, alive=True, opponent_base_armor_deployed=False)

    assert rotor.stop_time == pytest.approx(32.0)
    assert rotor.destroyed_at_stop
    assert rotor.angle == pytest.approx(destroyed_pose)


def test_outpost_rotor_stops_at_three_minutes() -> None:
    rotor = OutpostRotorVisualState(direction=1)
    rotor.advance(179.0, alive=True, opponent_base_armor_deployed=False)
    assert rotor.stop_time is None

    rotor.advance(180.0, alive=True, opponent_base_armor_deployed=False)
    assert rotor.stop_time == pytest.approx(180.0)
    rotor.advance(190.0, alive=True, opponent_base_armor_deployed=False)
    assert rotor.angle == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("armor_source", ["hp", "dart", "enemy_fortress"])
def test_outpost_rotor_stops_for_each_official_base_armor_source(
    armor_source: str,
) -> None:
    match = _match()
    rules = match.ruleset
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    visuals = CombatVisualState()
    visuals.reset(match)

    blue_base = next(
        structure
        for structure in match.structures
        if structure.team == RMUC_BLUE_TEAM and structure.type == "base"
    )

    if armor_source == "hp":
        blue_outpost = next(
            structure
            for structure in match.structures
            if structure.team == RMUC_BLUE_TEAM and structure.type == "outpost"
        )
        match.apply_damage(
            blue_outpost,
            100000,
            source_team_id=RMUC_RED_TEAM,
        )
        match.update(0.0)
        assert match.apply_damage(
            blue_base,
            3000,
            source_team_id=RMUC_RED_TEAM,
        ) == 3000
        match.update(0.0)
        assert blue_base.hp == 2000
    elif armor_source == "dart":
        blue_outpost = next(
            structure
            for structure in match.structures
            if structure.team == RMUC_BLUE_TEAM and structure.type == "outpost"
        )
        match.apply_damage(
            blue_outpost,
            100000,
            source_team_id=RMUC_RED_TEAM,
        )
        match.update(0.0)
        assert not blue_outpost.alive

        dart_state = rules._dart_system_by_team[RMUC_RED_TEAM]
        match.update(30.0)
        assert rules.open_dart_gate(match, RMUC_RED_TEAM, "fixed")
        match.update(dart_state.gate_full_open_at - match.elapsed_time)
        assert rules.fire_dart(match, RMUC_RED_TEAM)
        assert rules.record_dart_hit(match, RMUC_RED_TEAM)

        match.update(240.0 - match.elapsed_time)
        assert rules.open_dart_gate(match, RMUC_RED_TEAM, "random-moving")
        match.update(dart_state.gate_full_open_at - match.elapsed_time)
        assert rules.fire_dart(match, RMUC_RED_TEAM)
        assert rules.record_dart_hit(match, RMUC_RED_TEAM)
        assert blue_base.hp > 2000
    else:
        blue_outpost = next(
            structure
            for structure in match.structures
            if structure.team == RMUC_BLUE_TEAM and structure.type == "outpost"
        )
        match.apply_damage(
            blue_outpost,
            100000,
            source_team_id=RMUC_RED_TEAM,
        )
        match.update(0.0)
        assert not blue_outpost.alive

        infantry = next(
            robot
            for robot in match.robots
            if robot.id == "tarsgo-infantry-1"
        )
        zone = rules._fortress_zone_by_team[RMUC_BLUE_TEAM]
        infantry.position = (zone.x + zone.width / 2, zone.y + zone.height / 2)
        match.elapsed_time = 180.0
        match.update(0.0)
        match.update(20.0)
        assert blue_base.hp > 2000

    assert rules._team_states[RMUC_BLUE_TEAM].base_armor_deployed

    # Run the visual state at a common pre-timeout timestamp so every case
    # exercises the armor flag, including the Fortress route after 180 s.
    match.elapsed_time = 31.0
    visuals.after_match_update(match, 0.0)
    red_outpost = next(
        structure
        for structure in match.structures
        if structure.team == RMUC_RED_TEAM and structure.type == "outpost"
    )
    rotor = visuals.outpost_rotors[red_outpost.id]
    assert red_outpost.alive
    assert rotor.stop_time == pytest.approx(31.0)
    assert not rotor.destroyed_at_stop


def test_move_marker_expires() -> None:
    marker = MoveMarker((10.0, 20.0))
    marker.advance(0.25)
    assert marker.remaining == pytest.approx(0.50)
    assert 0 < marker.progress < 1

    marker.advance(0.50)
    assert marker.remaining == 0
    assert marker.progress == pytest.approx(1.0)


def test_damage_ghost_bar_tracks_recent_hp_loss_locally() -> None:
    visual = VisualRobotState(
        position=(0.0, 0.0),
        hp=100,
        cooldown=0.0,
    )

    visual.register_damage(100, 60)
    assert visual.hp == 60
    assert visual.ghost_hp(60) == pytest.approx(100.0)

    visual.advance_timers(visual.ghost_duration / 2)
    assert visual.ghost_hp(60) == pytest.approx(80.0)

    visual.advance_timers(visual.ghost_duration / 2)
    assert visual.ghost_hp(60) == pytest.approx(60.0)


def test_physical_projectile_impact_feedback_uses_simulated_contact() -> None:
    match = _match()
    attacker = next(item for item in match.robots if item.id == "tarsgo-hero")
    target = next(item for item in match.robots if item.id == "opponent-hero")
    attacker.position = (10000.0, 7500.0)
    target.position = (10500.0, 7500.0)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        if robot not in (attacker, target) and robot.type != "drone":
            robot.position = (4000.0 + len(robot.id) * 20.0, 1000.0)
    attacker.attack_cooldown = 0.0
    match.ruleset._projectile_allowance_by_robot[attacker.id].allowed = 1

    visuals = CombatVisualState()
    visuals.reset(match)
    visuals.begin_frame(match)
    match.update(1.0 / 60.0)
    visuals.after_match_update(match, 1.0 / 60.0)

    assert len(visuals.physical_projectiles) == 1
    assert visuals.impacts == []

    visuals.begin_frame(match)
    match.update(1.0 / 60.0)
    visuals.after_match_update(match, 1.0 / 60.0)

    assert visuals.physical_projectiles == {}
    assert visuals.impacts == []
    assert len(visuals.rebound_projectiles) == 1
    assert visuals.rebound_projectiles[0].caliber == "42mm"
    assert visuals.robots[target.id].impact_remaining == 0
    assert target.hp < target.max_hp


def test_immune_physical_hit_has_absorbed_feedback_without_damage_flash() -> None:
    match = _match()
    attacker = next(item for item in match.robots if item.id == "tarsgo-hero")
    target = next(item for item in match.robots if item.id == "opponent-hero")
    attacker.position = (10000.0, 7500.0)
    target.position = (10500.0, 7500.0)
    match.ruleset._robot_lifecycle_by_robot[target.id].invincible_remaining = 5.0
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        if robot not in (attacker, target) and robot.type != "drone":
            robot.position = (4000.0 + len(robot.id) * 20.0, 1000.0)
    attacker.attack_cooldown = 0.0
    match.ruleset._projectile_allowance_by_robot[attacker.id].allowed = 1

    visuals = CombatVisualState()
    visuals.reset(match)
    for _ in range(3):
        visuals.begin_frame(match)
        match.update(1.0 / 60.0)
        visuals.after_match_update(match, 1.0 / 60.0)

    assert target.hp == target.max_hp
    assert visuals.impacts == []
    assert len(visuals.rebound_projectiles) == 1
    assert visuals.rebound_projectiles[0].caliber == "42mm"
    assert visuals.robots[target.id].impact_remaining == 0.0


@pytest.mark.parametrize("caliber", ("17mm", "42mm"))
@pytest.mark.parametrize("surface", ("armor", "frame", "obstacle"))
def test_rebound_is_deterministic_and_rolls_to_rest(caliber: str, surface: str) -> None:
    contact = ProjectileImpact(
        projectile_id=1,
        shooter_id="shooter",
        shooter_team_id=RMUC_RED_TEAM,
        caliber=caliber,
        position=(12000.0, 6200.0),
        direction=(25000.0, 3000.0),
        target_id=None if surface == "obstacle" else "target",
        target_kind="obstacle" if surface == "obstacle" else "robot",
        applied_damage=0,
        surface=surface,
        normal=(-1.0, 0.0),
    )
    rebound = ReboundProjectileVisual.from_contact(contact)
    repeated = ReboundProjectileVisual.from_contact(contact)
    assert rebound == repeated
    assert rebound.velocity[0] < 0  # Reflected back from the contact plane.
    assert rebound.velocity[1] > 0
    assert rebound.height > 0

    rebound.advance(rebound.flight_duration / 2)
    assert rebound.height > 0
    assert rebound.position[0] < contact.position[0]
    rebound.advance(rebound.flight_duration / 2)
    assert rebound.height == pytest.approx(0.0, abs=1e-8)
    landed = rebound.position
    rebound.advance(rebound.roll_duration)
    assert rebound.position[0] < landed[0]
    at_rest = rebound.position
    rebound.advance(0.12)
    assert rebound.position == pytest.approx(at_rest)
    assert rebound.opacity == pytest.approx(1.0)
    rebound.advance(0.12)
    assert rebound.opacity == pytest.approx(0.5)
    rebound.advance(0.12)
    assert rebound.opacity == pytest.approx(0.0)
    assert rebound.expired


def test_rebound_size_and_motion_are_caliber_specific() -> None:
    payload = dict(
        projectile_id=1, shooter_id="shooter", shooter_team_id=RMUC_RED_TEAM,
        position=(1000.0, 1200.0), direction=(25000.0, 0.0),
        target_id="target", target_kind="robot", applied_damage=20,
        surface="armor", normal=(-1.0, 0.0),
    )
    small = ReboundProjectileVisual.from_contact(ProjectileImpact(caliber="17mm", **payload))
    large = ReboundProjectileVisual.from_contact(ProjectileImpact(caliber="42mm", **payload))
    assert small.flight_duration < large.flight_duration
    assert small.velocity[0] < large.velocity[0]
    assert small.lifetime < large.lifetime


def test_rebound_budget_and_retirement_never_touch_referee() -> None:
    match = _match()
    visuals = CombatVisualState()
    visuals.reset(match)
    original_hp = tuple(robot.hp for robot in match.robots)
    original_ammo = {
        key: value.allowed
        for key, value in match.ruleset._projectile_allowance_by_robot.items()
    }
    original_heat = {
        key: state.heat
        for key, state in match.ruleset._shooting_heat_by_robot.items()
    }
    match.projectile_system.impacts[:] = [
        ProjectileImpact(
            projectile_id=i + 1, shooter_id="shooter",
            shooter_team_id=RMUC_RED_TEAM, caliber="17mm" if i % 2 else "42mm",
            position=(12000.0 + i, 6500.0), direction=(25000.0, 0.0),
            target_id=None, target_kind="obstacle", applied_damage=0,
            surface="obstacle", normal=(-1.0, 0.0),
        )
        for i in range(MAX_REBOUND_PROJECTILES * 3)
    ]
    visuals.begin_frame(match)
    visuals.after_match_update(match, 0.0)
    assert len(visuals.rebound_projectiles) == MAX_REBOUND_PROJECTILES
    assert visuals.impacts == []
    assert tuple(robot.hp for robot in match.robots) == original_hp
    assert {
        key: value.allowed
        for key, value in match.ruleset._projectile_allowance_by_robot.items()
    } == original_ammo

    match.projectile_system.impacts.clear()
    visuals.after_match_update(match, 2.0)
    assert visuals.rebound_projectiles == []
    assert {
        key: state.heat
        for key, state in match.ruleset._shooting_heat_by_robot.items()
    } == original_heat


def test_shielded_structure_impact_is_visual_only() -> None:
    match = _match()
    base = next(
        structure
        for structure in match.structures
        if structure.type == "base"
        and structure.team != match.config.scenario.player_team
    )
    visuals = CombatVisualState()
    visuals.reset(match)
    profile = projectile_visual_profile("42mm")
    before_hp = base.hp

    visuals.projectiles.append(
        VisualProjectile(
            start=base.position,
            end=base.position,
            caliber="42mm",
            attacker_team_id=match.config.scenario.player_team,
            target_id=base.id,
            damaging=False,
            shielded=True,
            age=profile.lifetime - 0.01,
        )
    )
    visuals.begin_frame(match)
    visuals.after_match_update(match, 0.02)

    assert base.hp == before_hp
    assert visuals.impacts
    assert visuals.impacts[-1].shielded
    assert visuals.impacts[-1].target_kind == "structure"
    assert visuals.structures[base.id].shield_impact_remaining > 0
    assert visuals.shake_remaining > 0


@pytest.mark.parametrize(
    ("scenario", "debug_geometry"),
    [
        (RMUC_SCENARIO, False),
        (RMUC_SCENARIO, True),
        (RMUL_SCENARIO, False),
        (TRAINING_SCENARIO, False),
    ],
)
def test_renderer_smoke_with_combat_visual_state(
    scenario: Path,
    debug_geometry: bool,
) -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match(scenario)
    player_team = match.config.scenario.player_team
    opponent_team = next(
        team.team_id
        for team in match.config.scenario.teams.values()
        if team.team_id != player_team
    )
    viewport = app._viewport_for_match(match)
    visuals = CombatVisualState()
    visuals.reset(match)
    if app._is_rmuc_rules_lab(match):
        visuals.add_move_marker((match.map.width / 2, match.map.height / 2))
        hero = next(
            (robot for robot in match.robots if robot.type == "hero"),
            None,
        )
        if hero is not None:
            hero_visual = visuals.robots[hero.id]
            hero_visual.muzzle_remaining = 0.05
            hero_visual.muzzle_caliber = "42mm"
            hero_visual.impact_remaining = 0.08
            hero_visual.impact_caliber = "42mm"
            hero_visual.respawn_remaining = 0.30
        base = next(
            (structure for structure in match.structures if structure.type == "base"),
            None,
        )
        if base is not None:
            visuals.structures[base.id].shield_impact_remaining = 0.10
        visuals.trigger_screen_shake(1.0, 0.08)

    pygame.font.init()
    screen = pygame.Surface(app.WINDOW_SIZE)
    font = pygame.font.Font(None, 25)
    small_font = pygame.font.Font(None, 18)

    app._draw(
        screen,
        font,
        small_font,
        match,
        player_team,
        opponent_team,
        set(),
        None,
        viewport,
        debug_geometry=debug_geometry,
        visual_state=visuals,
    )
