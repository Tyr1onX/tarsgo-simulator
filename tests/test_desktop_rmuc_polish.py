import importlib
from pathlib import Path
import sys

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.polish import (
    BadgeSpec,
    contextual_controls,
    parse_virtual_shield,
    status_badges,
    structure_visual_profile,
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


def test_rmuc_panel_and_battlefield_do_not_overlap() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    field = pygame.Rect(*app.RMUC_FIELD_VIEW_RECT)
    panel = pygame.Rect(*app.RMUC_PANEL_RECT)
    window = pygame.Rect((0, 0), app.WINDOW_SIZE)

    assert not field.colliderect(panel)
    assert window.contains(field)
    assert window.contains(panel)


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