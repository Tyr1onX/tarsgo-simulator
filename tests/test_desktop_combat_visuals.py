import importlib
import math
from pathlib import Path
import sys

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.visuals import (
    CombatVisualState,
    MoveMarker,
    VisualProjectile,
    VisualRobotState,
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


@pytest.fixture(scope="module", autouse=True)
def _cleanup_desktop_imports():
    yield
    pygame = sys.modules.get("pygame")
    if pygame is not None:
        pygame.quit()
    sys.modules.pop("tarsgo_simulator.desktop.app", None)
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
        for robot_type in ("hero", "engineer", "infantry", "sentry")
    }

    assert len(set(profiles.values())) == 4
    assert profiles["hero"].barrel_width > profiles["infantry"].barrel_width
    assert profiles["engineer"].barrel_length == 0
    assert profiles["engineer"].tool_arm_length > 0
    assert profiles["sentry"].body_width > profiles["infantry"].body_width


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
    visuals.after_match_update(
        match,
        projectile_visual_profile("42mm").lifetime,
    )

    assert visuals.projectiles == []
    assert len(visuals.impacts) == 1
    assert visuals.robots[target.id].impact_remaining > 0


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
            visuals.robots[hero.id].muzzle_remaining = 0.05
            visuals.robots[hero.id].muzzle_caliber = "42mm"

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
