import importlib
import math
from pathlib import Path
import sys

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.visuals import (
    CombatVisualState,
    ImpactEffect,
    MAX_SCREEN_SHAKE_AMPLITUDE,
    MAX_SCREEN_SHAKE_DURATION,
    MoveMarker,
    OUTPOST_ROTATION_RETURN_SECONDS,
    OUTPOST_ROTATION_SPEED,
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


def test_cosmetic_projectile_creation_from_committed_shot_observation() -> None:
    match = _match()
    attacker = next(item for item in match.robots if item.id == "tarsgo-hero")
    target = next(item for item in match.robots if item.id == "opponent-hero")
    target.position = (attacker.position[0] + 100.0, attacker.position[1])

    visuals = CombatVisualState()
    visuals.reset(match)
    visuals.begin_frame(match)
    attacker.attack_cooldown = attacker.attack_interval

    visuals.after_match_update(match, 0.016)

    assert len(visuals.projectiles) == 1
    projectile = visuals.projectiles[0]
    assert projectile.caliber == "42mm"
    assert projectile.start == attacker.position
    assert projectile.end == target.position
    assert not projectile.damaging
    assert visuals.robots[attacker.id].muzzle_remaining > 0


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

    visual.advance_timers(visual.destroy_remaining / 2)
    assert 0 < visual.destroy_progress < 1

    visual.register_lifecycle(True)
    assert visual.destroy_remaining == 0
    assert visual.respawn_remaining > 0
    assert visual.respawn_progress == pytest.approx(0.0)

    visual.advance_timers(visual.respawn_remaining)
    assert visual.respawn_remaining == 0
    assert visual.respawn_progress == pytest.approx(1.0)


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


def test_damaging_projectile_delays_impact_feedback_until_visual_arrival() -> None:
    match = _match()
    attacker = next(item for item in match.robots if item.id == "tarsgo-hero")
    target = next(item for item in match.robots if item.id == "opponent-hero")
    target.position = (attacker.position[0] + 100.0, attacker.position[1])

    visuals = CombatVisualState()
    visuals.reset(match)
    visuals.begin_frame(match)
    attacker.attack_cooldown = attacker.attack_interval
    match.apply_damage(target, 10, source_robot=attacker)

    visuals.after_match_update(match, 0.01)

    assert len(visuals.projectiles) == 1
    assert visuals.projectiles[0].damaging
    assert visuals.impacts == []

    visuals.begin_frame(match)
    attacker.attack_cooldown = max(
        0.0,
        attacker.attack_cooldown - projectile_visual_profile("42mm").lifetime,
    )
    visuals.after_match_update(
        match,
        projectile_visual_profile("42mm").lifetime,
    )

    assert visuals.projectiles == []
    assert len(visuals.impacts) == 1
    assert visuals.robots[target.id].impact_remaining > 0


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
