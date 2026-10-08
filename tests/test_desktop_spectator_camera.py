import importlib
from pathlib import Path
import sys

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.projectiles import ProjectileImpact
from tarsgo_simulator.desktop.camera import MAX_CAMERA_ZOOM, SpectatorCamera


@pytest.fixture(scope="module", autouse=True)
def _cleanup_desktop_imports():
    yield
    pygame = sys.modules.get("pygame")
    if pygame is not None:
        pygame.quit()
    sys.modules.pop("tarsgo_simulator.desktop.app", None)
    sys.modules.pop("tarsgo_simulator.desktop.icon", None)
    for name in list(sys.modules):
        if name == "pygame" or name.startswith("pygame."):
            sys.modules.pop(name, None)


def _app():
    return importlib.import_module("tarsgo_simulator.desktop.app")


SCENARIO = Path(__file__).resolve().parents[1] / "configs/scenarios/rmuc-2026-region-rules-lab.yaml"


def _camera():
    match = Match.from_scenario(SCENARIO)
    return SpectatorCamera(_app()._viewport_for_match(match)), match


def _settle(camera, match, duration=1.5):
    for _ in range(round(duration * 60)):
        camera.update(1 / 60, match)


def test_default_full_field_view_and_reset_are_smooth():
    camera, match = _camera()
    assert camera.mode == "full"
    assert camera.viewport() == camera.base
    camera.zoom_at(4, (530, 360))
    camera.update(1 / 60, match)
    assert 1 < camera.zoom < camera.target_zoom
    camera.reset()
    assert camera.zoom > 1
    _settle(camera, match, 2)
    assert camera.zoom == pytest.approx(1, abs=0.001)
    assert camera.viewport().origin == pytest.approx(camera.base.origin, abs=0.2)


def test_zoom_preserves_cursor_world_and_is_bounded():
    camera, match = _camera()
    pointer = tuple(round(x) for x in camera.base.world_to_screen((10000, 6500)))
    world = camera.viewport().screen_to_world(pointer)
    assert world is not None
    camera.zoom_at(40, pointer)
    assert camera.target_zoom == MAX_CAMERA_ZOOM
    _settle(camera, match)
    assert camera.viewport().screen_to_world(pointer) == pytest.approx(world, abs=40)
    camera.zoom_at(-50, pointer)
    assert camera.target_zoom == 1


def test_manual_pan_clamps_camera_and_world_geometry_is_unchanged():
    camera, match = _camera()
    original_map = (match.map.width, match.map.height)
    original_positions = tuple(r.position for r in match.robots)
    camera.zoom_at(10, tuple(round(x) for x in camera.base.world_to_screen((14000, 7500))))
    _settle(camera, match)
    camera.pan((200000, 200000))
    _settle(camera, match)
    view = camera.viewport()
    bounds = camera.frame_rect
    assert view.screen_to_world((bounds[0] + 2, bounds[1] + 2)) is not None
    assert tuple(r.position for r in match.robots) == original_positions
    assert (match.map.width, match.map.height) == original_map


def test_follow_dead_robot_freezes_and_respawn_resumes():
    camera, match = _camera()
    robot = next(r for r in match.robots if r.id == "tarsgo-hero")
    robot.position = (13000.0, 7100.0)
    camera.follow(robot.id)
    camera.update(1 / 60, match)
    assert camera.mode == "follow"
    _settle(camera, match)
    assert camera.center == pytest.approx(robot.position, abs=2)
    robot.alive = False
    robot.position = (16000, 8200)
    _settle(camera, match)
    assert camera.center != pytest.approx(robot.position, abs=2)
    robot.alive = True
    _settle(camera, match)
    assert camera.center == pytest.approx(robot.position, abs=2)
    assert camera.follow_id == robot.id


def _contact(attacker, target, *, pid=1, surface="armor", damage=20):
    return ProjectileImpact(
        projectile_id=pid, shooter_id=attacker.id, shooter_team_id=attacker.team,
        caliber="17mm", position=target.position, direction=(25000.0, 0.0),
        target_id=target.id, target_kind="robot",
        applied_damage=damage, surface=surface, normal=(-1.0, 0.0),
    )


def test_auto_picks_opposing_armor_hits_and_avoids_rapid_switches():
    camera, match = _camera()
    red = next(r for r in match.robots if r.id == "tarsgo-infantry-1")
    blue = next(r for r in match.robots if r.id == "opponent-infantry-1")
    blue2 = next(r for r in match.robots if r.id == "opponent-hero")
    camera.auto()
    match.projectile_system.impacts = [_contact(red, blue)]
    camera.observe(match)
    assert camera.auto_pair == (red.id, blue.id)
    camera.update(1/60, match)
    match.projectile_system.impacts = [_contact(red, blue2, pid=2)]
    camera.observe(match)
    assert camera.auto_pair == (red.id, blue.id)
    camera.update(3, match)
    camera.observe(match)
    assert camera.auto_pair == (red.id, blue2.id)
    camera.update(6, match)
    assert camera.auto_pair is None
    assert camera.target_zoom == 1


def test_auto_ignores_same_team_and_manual_input_takes_priority():
    camera, match = _camera()
    red = next(r for r in match.robots if r.id == "tarsgo-infantry-1")
    friend = next(r for r in match.robots if r.id == "tarsgo-hero")
    blue = next(r for r in match.robots if r.id == "opponent-infantry-1")
    camera.auto()
    match.projectile_system.impacts = [_contact(red, friend)]
    camera.observe(match)
    assert camera.auto_pair is None
    match.projectile_system.impacts = [_contact(red, blue)]
    camera.observe(match)
    assert camera.auto_pair is not None
    camera.pan((20, 30))
    assert camera.mode == "manual"
    assert camera.auto_pair is None
    camera.observe(match)
    assert camera.mode == "manual"
    camera.follow(red.id)
    assert camera.mode == "follow"
    camera.zoom_at(1, tuple(round(x) for x in camera.viewport().world_to_screen(red.position)))
    assert camera.mode == "manual"


def test_auto_frame_contains_both_participants():
    camera, match = _camera()
    red = next(r for r in match.robots if r.id == "tarsgo-infantry-1")
    blue = next(r for r in match.robots if r.id == "opponent-infantry-1")
    red.position = (11500, 7100)
    blue.position = (12800, 7400)
    camera.auto()
    match.projectile_system.impacts = [_contact(red, blue)]
    camera.observe(match)
    _settle(camera, match)
    view = camera.viewport()
    frame = camera.frame_rect
    for robot in (red, blue):
        x, y = view.world_to_screen(robot.position)
        assert frame[0] < x < frame[0] + frame[2]
        assert frame[1] < y < frame[1] + frame[3]
    assert camera.zoom > 1.5

def test_zoomed_game_draw_preserves_hud_and_reuses_static_art(monkeypatch):
    app = _app()
    from tarsgo_simulator.desktop.visuals import CombatVisualState

    pygame = pytest.importorskip("pygame")
    pygame.init()
    match = Match.from_scenario(SCENARIO)
    hero = next(robot for robot in match.robots if robot.id == "tarsgo-hero")
    hero.position = (10800.0, 7100.0)
    cam = SpectatorCamera(app._viewport_for_match(match))
    visuals = CombatVisualState()
    visuals.reset(match)
    cache = app.RMUCStaticFieldCache()
    screen = pygame.Surface(app.WINDOW_SIZE)
    font, small, hud = app.ui_font(25), app.ui_font(18), app.ui_font(12)
    red = match.config.scenario.player_team
    blue = next(team.team_id for team in match.config.scenario.teams.values()
                if team.team_id != red)

    drawn_sizes = []
    original = app.ASSET_MANAGER.render

    def record(path, *, size=None, angle=0.0, tint=None, fallback=None):
        if path == "robots/hero-chassis.png":
            drawn_sizes.append(size)
        return original(path, size=size, angle=angle, tint=tint, fallback=fallback)

    monkeypatch.setattr(app.ASSET_MANAGER, "render", record)

    def draw():
        app._draw(screen, font, small, match, red, blue, set(), None, cam.viewport(),
                  visual_state=visuals, hud_font=hud, static_field_cache=cache,
                  spectator=cam)

    draw()
    baseline_hud = pygame.image.tostring(screen.subsurface((0, 0, 1100, 164)), "RGB")
    assert (50, 34) in drawn_sizes
    cam.manual()
    cam.target_center = hero.position
    cam.target_zoom = 3.2
    _settle(cam, match)
    draw()
    zoom_hud = pygame.image.tostring(screen.subsurface((0, 0, 1100, 164)), "RGB")
    assert zoom_hud == baseline_hud
    assert any(size[0] >= 145 for size in drawn_sizes if size is not None)
    assert cache._zoom_floor is not None
    before_floor = cache._zoom_floor
    before_buffer = cache._zoom_scratch_floor
    cam.pan((40, -15))
    _settle(cam, match, 0.2)
    draw()
    assert cache._zoom_floor is before_floor
    assert cache._zoom_scratch_floor is before_buffer

def test_auto_prefers_actual_armor_damage_over_undamaging_contacts():
    camera, match = _camera()
    red = next(r for r in match.robots if r.id == "tarsgo-infantry-1")
    red2 = next(r for r in match.robots if r.id == "tarsgo-hero")
    blue = next(r for r in match.robots if r.id == "opponent-infantry-1")
    blue2 = next(r for r in match.robots if r.id == "opponent-hero")
    camera.auto()
    match.projectile_system.impacts = [
        _contact(red, blue, pid=500, surface="frame", damage=0),
        _contact(red2, blue2, pid=1, surface="armor", damage=80),
    ]
    camera.observe(match)
    assert camera.auto_pair == (red2.id, blue2.id)


def test_camera_update_cannot_affect_referee_or_projectiles():
    camera, match = _camera()
    robots_before = tuple((r.id, r.position, r.hp) for r in match.robots)
    ammo_before = tuple(
        (key, value.allowed)
        for key, value in match.ruleset._projectile_allowance_by_robot.items()
    )
    heat_before = tuple(
        (key, value.heat)
        for key, value in match.ruleset._shooting_heat_by_robot.items()
    )
    shots_before = tuple(match.projectiles)
    camera.follow("tarsgo-hero")
    _settle(camera, match, .5)
    camera.auto()
    _settle(camera, match, .5)
    camera.reset()
    _settle(camera, match, 1.0)
    assert tuple((r.id, r.position, r.hp) for r in match.robots) == robots_before
    assert tuple(
        (key, value.allowed)
        for key, value in match.ruleset._projectile_allowance_by_robot.items()
    ) == ammo_before
    assert tuple(
        (key, value.heat)
        for key, value in match.ruleset._shooting_heat_by_robot.items()
    ) == heat_before
    assert tuple(match.projectiles) == shots_before

def test_zoomed_click_maps_back_to_the_selected_robot():
    app = _app()

    camera, match = _camera()
    robot = next(robot for robot in match.robots if robot.id == "tarsgo-infantry-1")
    robot.position = (11000.0, 7400.0)
    camera.manual()
    camera.target_center = robot.position
    camera.target_zoom = 3.6
    _settle(camera, match)
    click = tuple(round(x) for x in camera.viewport().world_to_screen(robot.position))
    world = app._screen_to_world(click, camera.viewport())
    selection = set()
    app._apply_click_selection(world, match, selection, shift=False)
    assert selection == {robot.id}
