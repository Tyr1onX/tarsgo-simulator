import importlib
import math
from pathlib import Path
import sys

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.polish import (
    BadgeSpec,
    contextual_controls,
    parse_virtual_shield,
    status_badges,
    structure_display_size,
    structure_visual_profile,
    terrain_visual_markers,
    zone_visual_style,
)
from tarsgo_simulator.desktop.visuals import CombatVisualState


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


def _surface_and_fonts():
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.font.init()
    return (
        pygame.Surface(app.WINDOW_SIZE),
        pygame.font.Font(None, 25),
        pygame.font.Font(None, 18),
    )


def test_zone_highlight_helper_is_role_contextual() -> None:
    engineer_resource = zone_visual_style(
        "red-resource",
        selected_robot_types={"engineer"},
    )
    hero_resource = zone_visual_style(
        "red-resource",
        selected_robot_types={"hero"},
    )
    infantry_fortress = zone_visual_style(
        "red-fortress-buff",
        selected_robot_types={"infantry"},
    )

    assert engineer_resource is not None and engineer_resource.emphasized
    assert hero_resource is not None and not hero_resource.emphasized
    assert infantry_fortress is not None and infantry_fortress.emphasized
    assert zone_visual_style("red-terrain-road-lower") is None


def test_shield_visual_helper_parses_existing_structure_status() -> None:
    assert parse_virtual_shield("ARMOR DEF 25% SH:1200") == 1200
    assert parse_virtual_shield("DEF 25%") == 0


def test_badge_helper_uses_existing_display_facts_only() -> None:
    badges = status_badges(
        "DEF 50% TDEF 25% 5.0s FORT VULN100",
        invincible=True,
        heat_locked=True,
        power_off=True,
    )

    texts = {badge.text for badge in badges}
    assert {
        "无敌",
        "防御 50%",
        "易伤 100%",
        "堡垒",
        "地形增益",
        "禁射",
        "底盘断电",
    } <= texts


def test_engineer_controls_are_contextual() -> None:
    engineer = contextual_controls({"engineer"})
    combat = contextual_controls({"hero"})
    none = contextual_controls(set())
    spectator = contextual_controls({"hero"}, spectator=True)

    engineer_labels = {key for key, _action, _enabled in engineer}
    combat_labels = {key for key, _action, _enabled in combat}
    none_labels = {key for key, _action, _enabled in none}
    spectator_rows = {(key, action) for key, action, _enabled in spectator}

    assert {"G", "1-4", "回车", "Q / W"} <= engineer_labels
    assert "G" not in combat_labels
    assert {"E", "F"} <= combat_labels
    assert "E" not in none_labels
    assert ("左键", "查看单位") in spectator_rows
    assert all(key not in {"E", "F", "G", "1-4", "右键"} for key, _action in spectator_rows)


def test_base_and_outpost_have_distinct_structure_profiles() -> None:
    base = structure_visual_profile("base")
    outpost = structure_visual_profile("outpost")

    assert base != outpost
    assert base.size > outpost.size
    assert base.ring_count > outpost.ring_count


def test_outpost_display_minimum_does_not_change_official_blocking_footprint() -> None:
    match = _match()
    outpost = next(item for item in match.structures if item.id == "red-outpost")
    base = next(item for item in match.structures if item.id == "red-base")
    physical_bounds = match.map.structure_bounds(outpost.id)
    base_bounds = match.map.structure_bounds(base.id)
    assert physical_bounds is not None
    assert base_bounds is not None
    viewport = _app()._viewport_for_match(match)
    physical_diameter = round(viewport.world_length_to_screen(outpost.footprint[0]))
    physical_base_size = (
        round(viewport.world_length_to_screen(base_bounds.width)),
        round(viewport.world_length_to_screen(base_bounds.height)),
    )

    display_size = structure_display_size("outpost", (physical_diameter, physical_diameter))

    assert physical_diameter < display_size[0]
    assert display_size == (44, 44)
    assert structure_display_size("base", physical_base_size) == physical_base_size
    assert match.map.structure_bounds(outpost.id) == physical_bounds
    assert outpost.footprint == (550.0, 550.0)


def test_terrain_markers_are_symbolic_and_renderer_does_not_mutate_map_geometry() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match()
    viewport = app._viewport_for_match(match)
    field = pygame.Rect(*app.RMUC_FIELD_VIEW_RECT)
    screen, _font, small_font = _surface_and_fonts()
    original_obstacles = match.map.obstacles
    original_bounds = {
        structure.id: match.map.structure_bounds(structure.id)
        for structure in match.structures
    }
    original_connections = match.map.terrain_connections

    markers = terrain_visual_markers(
        match.map.terrain_features,
        match.map.terrain_connections,
        match.map.zones,
    )
    rendered = app._draw_rmuc_terrain(
        screen,
        small_font,
        field,
        viewport,
        terrain_features=match.map.terrain_features,
        terrain_connections=match.map.terrain_connections,
        zones=match.map.zones,
    )
    road_markings = app._draw_rmuc_terrain(
        screen,
        small_font,
        field,
        viewport,
        terrain_features=match.map.terrain_features,
        terrain_connections=match.map.terrain_connections,
        zones=match.map.zones,
        debug_geometry=False,
    )

    assert {marker.kind for marker in markers} == {
        "surface",
        "elevated",
        "ramp",
        "tunnel",
    }
    assert len(rendered) == len(markers)
    assert road_markings
    assert {kind for kind, _center in road_markings} == {"surface"}
    assert all(field.collidepoint(center) for _kind, center in rendered)
    assert match.map.obstacles == original_obstacles
    assert match.map.terrain_connections == original_connections
    assert {
        structure.id: match.map.structure_bounds(structure.id)
        for structure in match.structures
    } == original_bounds


def test_maps_without_terrain_metadata_render_without_terrain_cues() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match(TRAINING_SCENARIO)
    screen, _font, small_font = _surface_and_fonts()

    rendered = app._draw_rmuc_terrain(
        screen,
        small_font,
        pygame.Rect(*app.FIELD_VIEW_RECT),
        app._viewport_for_match(match),
        terrain_features=match.map.terrain_features,
        terrain_connections=match.map.terrain_connections,
        zones=match.map.zones,
    )

    assert rendered == ()


def test_rmuc_inspector_overlay_and_toggle_stay_inside_1100x780() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    field = pygame.Rect(*app.RMUC_FIELD_VIEW_RECT)
    panel = pygame.Rect(*app.RMUC_PANEL_RECT)
    toggle = app._rmuc_inspector_toggle_rect(app.WINDOW_SIZE)
    window = pygame.Rect((0, 0), app.WINDOW_SIZE)

    assert field.colliderect(panel)
    assert window.contains(field)
    assert window.contains(panel)
    assert window.contains(toggle)
    assert toggle.top >= field.bottom


def test_battlefield_art_helpers_render_inside_1100x780() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    screen, _font, _small_font = _surface_and_fonts()
    field = pygame.Rect(*app.RMUC_FIELD_VIEW_RECT)

    app._draw_rmuc_battlefield(screen, field)
    app._draw_rmuc_obstacle(
        screen,
        pygame.Rect(field.x + 20, field.y + 20, 60, 34),
    )

    assert screen.get_rect().contains(field)
    assert screen.get_at(field.center)[:3] != screen.get_at(
        (field.centerx, field.top + 8)
    )[:3]


def test_zone_art_renders_default_selected_and_targeted_states() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    screen, _font, small_font = _surface_and_fonts()
    rect = pygame.Rect(80, 80, 90, 56)

    app._draw_rmuc_zone(
        screen,
        small_font,
        rect,
        zone_id="red-resource",
        selected_types=set(),
        occupied_by_selected=False,
        targeted_by_selected=False,
        animation_time=0.0,
    )
    app._draw_rmuc_zone(
        screen,
        small_font,
        rect.move(110, 0),
        zone_id="red-fortress-buff",
        selected_types={"infantry"},
        occupied_by_selected=True,
        targeted_by_selected=True,
        animation_time=0.5,
    )


def test_canonical_zone_render_uses_polygon_outline_and_fill() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    screen, _font, small_font = _surface_and_fonts()
    screen.fill((8, 8, 8))
    unchanged = screen.get_at((84, 136))

    app._draw_rmuc_zone(
        screen,
        small_font,
        pygame.Rect(80, 80, 90, 60),
        zone_id="red-resource",
        polygon_points=((80, 80), (170, 80), (125, 140)),
        selected_types=set(),
        occupied_by_selected=True,
        targeted_by_selected=False,
        animation_time=0.0,
    )

    assert screen.get_at((125, 100)) != pygame.Color(8, 8, 8, 255)
    assert screen.get_at((84, 136)) == unchanged


def test_buff_zone_is_quiet_by_default_and_clearer_when_contextual() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    _screen, _font, small_font = _surface_and_fonts()
    rect = pygame.Rect(80, 90, 90, 60)
    polygon = ((80, 90), (170, 90), (170, 150), (80, 150))
    idle = pygame.Surface((260, 220))
    emphasized = pygame.Surface((260, 220))
    floor = app.ARENA_FLOOR
    idle.fill(floor)
    emphasized.fill(floor)

    for target, selected in ((idle, set()), (emphasized, {"hero"})):
        app._draw_rmuc_zone(
            target,
            small_font,
            rect,
            zone_id="red-base-buff",
            polygon_points=polygon,
            selected_types=selected,
            occupied_by_selected=False,
            targeted_by_selected=False,
            animation_time=0.0,
        )

    def visual_energy(surface):
        return sum(
            sum(
                abs(channel - baseline)
                for channel, baseline in zip(surface.get_at((x, y))[:3], floor)
            )
            for x in range(rect.left, rect.right)
            for y in range(rect.top, rect.bottom)
        )

    assert visual_energy(idle) == 0
    assert visual_energy(emphasized) > visual_energy(idle)


def test_selected_ai_target_positions_use_existing_path_endpoint() -> None:
    app = _app()
    match = Match.from_scenario(RMUC_SCENARIO, rmuc_spectator_ai=True)
    hero = next(robot for robot in match.robots if robot.id == "tarsgo-hero")
    target = (match.map.width / 2, match.map.height / 2)
    hero.path = [target]

    assert app._selected_ai_target_positions(match, {hero.id}) == (target,)
    assert app._selected_ai_target_positions(match, set()) == ()


def test_structure_and_shield_rendering_helpers_do_not_crash() -> None:
    app = _app()
    screen, _font, small_font = _surface_and_fonts()

    base_size = app._draw_rmuc_structure(
        screen,
        small_font,
        structure_type="base",
        center=(180, 180),
        color=app.PLAYER_COLOR,
        alive=True,
        hp=5000,
        max_hp=5000,
        status="DEF 25% SH:1200",
        animation_time=0.5,
        debug_geometry=False,
    )
    outpost_size = app._draw_rmuc_structure(
        screen,
        small_font,
        structure_type="outpost",
        center=(320, 180),
        color=app.OPPONENT_COLOR,
        alive=False,
        hp=0,
        max_hp=1500,
        status="DESTROYED",
        animation_time=0.5,
        debug_geometry=False,
    )

    assert base_size > outpost_size


@pytest.mark.parametrize(("alive", "expected_lit"), ((True, True), (False, False)))
def test_robot_team_leds_follow_life_state_and_dead_muzzle_flash_is_suppressed(
    monkeypatch: pytest.MonkeyPatch,
    alive: bool,
    expected_lit: bool,
) -> None:
    app = _app()
    screen, _font, _small_font = _surface_and_fonts()
    rendered: dict[str, bool] = {}

    monkeypatch.setattr(app, "_rmuc_robot_sprites_available", lambda _robot_type: True)

    def capture_sprites(*_args: object, lit: bool, **_kwargs: object) -> bool:
        rendered["lit"] = lit
        return True

    monkeypatch.setattr(app, "_draw_rmuc_robot_sprites", capture_sprites)
    app._draw_rmuc_robot_shape(
        screen,
        center=(64, 64),
        robot_type="hero",
        color=app.TEAM_RED_COLOR,
        body_angle=0.0,
        turret_angle=0.0,
        alive=alive,
        selected=False,
        animation_time=0.0,
        muzzle_remaining=0.08,
        muzzle_caliber="42mm",
        impact_remaining=0.0,
    )

    assert rendered["lit"] is expected_lit
    if not alive:
        assert screen.get_at((99, 64))[:3] != app.IMPACT_COLOR


def test_outpost_middle_armor_rotates_without_rotating_its_outer_platform() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    screen_a, _font, small_font = _surface_and_fonts()
    screen_b = pygame.Surface(screen_a.get_size(), pygame.SRCALPHA)
    screen_b.fill((0, 0, 0, 0))
    screen_a.fill((0, 0, 0, 0))

    for screen, angle in ((screen_a, 0.0), (screen_b, math.pi / 3)):
        app._draw_rmuc_structure(
            screen,
            small_font,
            structure_type="outpost",
            center=(180, 180),
            color=app.TEAM_RED_COLOR,
            alive=True,
            hp=1500,
            max_hp=1500,
            status="",
            animation_time=0.0,
            debug_geometry=False,
            rotor_angle=angle,
        )

    assert pygame.image.tostring(screen_a, "RGBA") != pygame.image.tostring(screen_b, "RGBA")


def test_badge_rendering_helper_stays_inside_width() -> None:
    app = _app()
    screen, _font, small_font = _surface_and_fonts()
    end_y = app._draw_badges(
        screen,
        small_font,
        (
            BadgeSpec("INV", "shield"),
            BadgeSpec("DEF 50", "defense"),
            BadgeSpec("PWR OFF", "warning"),
        ),
        x=20,
        y=20,
        max_width=180,
    )
    assert end_y > 20
    assert end_y < 80


def test_observer_hud_layout_is_mirrored_and_clear_of_battlefield() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    left, timer, right = app._rmuc_hud_rects(app.WINDOW_SIZE[0])
    window = pygame.Rect((0, 0), app.WINDOW_SIZE)
    field = pygame.Rect(*app.RMUC_FIELD_VIEW_RECT)

    assert window.contains(left)
    assert window.contains(timer)
    assert window.contains(right)
    assert not left.colliderect(timer)
    assert not timer.colliderect(right)
    assert left.width == right.width
    assert left.x == app.WINDOW_SIZE[0] - right.right
    assert max(left.bottom, timer.bottom, right.bottom) < field.top


def test_observer_panel_cards_are_compact_and_non_overlapping() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    panel = pygame.Rect(*app.RMUC_PANEL_RECT)

    empty = app._rmuc_panel_layout(panel, 0)
    single = app._rmuc_panel_layout(panel, 1)
    multi = app._rmuc_panel_layout(panel, 4)

    assert empty[0].height < single[0].height
    assert multi[0].height < single[0].height
    for layout in (empty, single, multi):
        unit, team, controls = layout
        assert panel.contains(unit)
        assert panel.contains(team)
        assert panel.contains(controls)
        assert unit.bottom < team.top
        assert team.bottom < controls.top


def test_hover_helper_is_safe_without_video_system() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.display.quit()

    assert not app._screen_rect_is_hovered(pygame.Rect(0, 0, 20, 20))


def test_zone_labels_are_contextual_in_observer_view() -> None:
    app = _app()

    assert not app._should_show_zone_label(
        emphasized=False,
        occupied_by_selected=False,
        hovered=False,
    )
    assert app._should_show_zone_label(
        emphasized=True,
        occupied_by_selected=False,
        hovered=False,
    )
    assert app._should_show_zone_label(
        emphasized=False,
        occupied_by_selected=True,
        hovered=False,
    )
    assert app._should_show_zone_label(
        emphasized=False,
        occupied_by_selected=False,
        hovered=True,
    )
    assert app._should_show_zone_label(
        emphasized=False,
        occupied_by_selected=False,
        hovered=False,
        targeted_by_selected=True,
    )


def test_rmuc_team_colors_follow_red_blue_sides() -> None:
    app = _app()
    match = _match()
    red = match.config.scenario.teams["red"].team_id
    blue = match.config.scenario.teams["blue"].team_id

    assert app._rmuc_team_color(match, red) == app.TEAM_RED_COLOR
    assert app._rmuc_team_color(match, blue) == app.TEAM_BLUE_COLOR


def test_selected_ai_path_overlay_supports_opponent_units(monkeypatch) -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = Match.from_scenario(RMUC_SCENARIO, rmuc_spectator_ai=True)
    opponent = next(robot for robot in match.robots if robot.id == "opponent-hero")
    opponent.path = [(match.map.width / 2, match.map.height / 2)]
    viewport = app._viewport_for_match(match)
    screen, _font, small_font = _surface_and_fonts()
    calls = []
    original_lines = pygame.draw.lines

    def capture_lines(*args, **kwargs):
        calls.append((args, kwargs))
        return original_lines(*args, **kwargs)

    monkeypatch.setattr(pygame.draw, "lines", capture_lines)
    app._draw_selected_paths(
        screen,
        small_font,
        match,
        viewport,
        {opponent.id},
    )

    assert match.is_ai_controlled(opponent.id)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("robot_type", "expected_action"),
    [
        ("hero", "E"),
        ("engineer", "G"),
    ],
)
def test_selected_single_unit_panel_renders_context(
    robot_type: str,
    expected_action: str,
) -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match()
    robot = next(item for item in match.robots if item.type == robot_type)
    labels = app._rmuc_robot_labels(match)
    screen, _font, small_font = _surface_and_fonts()
    rect = pygame.Rect(20, 20, 232, 332)

    app._draw_selected_unit_card(
        screen,
        small_font,
        app.ui_font(12),
        match,
        {robot.id},
        labels,
        rect,
    )
    actions = {
        key
        for key, _action, _enabled
        in contextual_controls({robot_type})
    }
    assert expected_action in actions


def test_multi_select_panel_renders_without_squad_state() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match()
    selected = {
        robot.id
        for robot in match.robots
        if match.is_player_controlled(robot.id)
    }
    labels = app._rmuc_robot_labels(match)
    screen, _font, small_font = _surface_and_fonts()

    app._draw_selected_unit_card(
        screen,
        small_font,
        app.ui_font(12),
        match,
        selected,
        labels,
        pygame.Rect(20, 20, 232, 332),
    )


@pytest.mark.parametrize(
    ("scenario", "debug_geometry", "select_type"),
    [
        (RMUC_SCENARIO, False, "hero"),
        (RMUC_SCENARIO, True, "engineer"),
        (RMUL_SCENARIO, False, None),
        (TRAINING_SCENARIO, False, None),
    ],
)
def test_polished_renderer_smoke(
    scenario: Path,
    debug_geometry: bool,
    select_type: str | None,
) -> None:
    app = _app()
    match = _match(scenario)
    player_team = match.config.scenario.player_team
    opponent_team = next(
        team.team_id
        for team in match.config.scenario.teams.values()
        if team.team_id != player_team
    )
    selected = set()
    if select_type is not None:
        selected.add(
            next(
                robot.id
                for robot in match.robots
                if robot.type == select_type
                and match.is_player_controlled(robot.id)
            )
        )

    viewport = app._viewport_for_match(match)
    visuals = CombatVisualState()
    visuals.reset(match)
    screen, font, small_font = _surface_and_fonts()

    app._draw(
        screen,
        font,
        small_font,
        match,
        player_team,
        opponent_team,
        selected,
        None,
        viewport,
        debug_geometry=debug_geometry,
        visual_state=visuals,
    )
