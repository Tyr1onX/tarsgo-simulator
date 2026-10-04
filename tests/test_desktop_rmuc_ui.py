import importlib
from pathlib import Path
import sys

import pytest

from tarsgo_simulator.core.match import Match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RMUC_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
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


def _match() -> Match:
    return Match.from_scenario(RMUC_SCENARIO)


def test_rmuc_default_zone_rendering_hides_internal_debug_geometry() -> None:
    app = _app()
    assert app._rmuc_zone_style(
        "red-terrain-road-lower",
        debug_geometry=False,
    ) is None
    assert app._rmuc_zone_style(
        "blue-terrain-tunnel-middle",
        debug_geometry=False,
    ) is None
    assert app._rmuc_zone_style(
        "red-start",
        debug_geometry=False,
    ) is None

    color, label = app._rmuc_zone_style(
        "red-supply-buff",
        debug_geometry=False,
    )
    assert color is not None
    assert label == "补给区"

    _color, label = app._rmuc_zone_style(
        "red-central-elevated-buff",
        debug_geometry=False,
    )
    assert label == "中央区"


def test_rmuc_debug_zone_rendering_restores_original_zone_ids() -> None:
    app = _app()
    _color, label = app._rmuc_zone_style(
        "red-terrain-elevated-lower",
        debug_geometry=True,
    )
    assert label == "RED-TERRAIN-ELEVATED-LOWER"

    _color, label = app._rmuc_zone_style(
        "red-base-buff",
        debug_geometry=True,
    )
    assert label == "RED-BASE-BUFF"


def test_rmuc_viewport_leaves_room_for_right_side_panel() -> None:
    app = _app()
    match = _match()
    assert app._is_rmuc_rules_lab(match)

    viewport = app._viewport_for_match(match)
    field_right = viewport.origin[0] + viewport.screen_size[0]

    assert field_right < app.RMUC_PANEL_RECT[0]


def test_rmuc_map_labels_are_minimal_and_number_infantry() -> None:
    app = _app()
    match = _match()
    labels = app._rmuc_robot_labels(match)

    assert labels["tarsgo-hero"] == "英 1级"
    assert labels["tarsgo-engineer"] == "工"
    assert labels["tarsgo-infantry-1"] == "步1 1级"
    assert labels["tarsgo-infantry-2"] == "步2 1级"
    assert labels["tarsgo-sentry"] == "哨"

    assert labels["opponent-hero"] == "英 1级"
    assert labels["opponent-infantry-1"] == "步1 1级"
    assert labels["opponent-infantry-2"] == "步2 1级"


def test_selected_unit_panel_moves_detailed_robot_state_off_map_label() -> None:
    app = _app()
    match = _match()
    labels = app._rmuc_robot_labels(match)

    lines = app._selected_unit_lines(
        match,
        {"tarsgo-hero"},
        labels,
    )

    assert lines[0] == "英雄 · 1级"
    assert any(line.startswith("生命      ") for line in lines)
    assert any(line.startswith("经验      ") for line in lines)
    assert any(line.startswith("弹量      42mm:") for line in lines)
    assert any(line.startswith("热量      ") for line in lines)
    assert any(line.startswith("缓冲      ") for line in lines)
    assert any(line.startswith("功率      ") for line in lines)
    assert any(line.startswith("状态      ") for line in lines)


def test_selected_unit_panel_has_engineer_and_multi_select_views() -> None:
    app = _app()
    match = _match()
    labels = app._rmuc_robot_labels(match)

    engineer_lines = app._selected_unit_lines(
        match,
        {"tarsgo-engineer"},
        labels,
    )
    assert engineer_lines[0] == "工程"
    assert any(line.startswith("能量单元  ") for line in engineer_lines)

    multi_lines = app._selected_unit_lines(
        match,
        {"tarsgo-hero", "tarsgo-infantry-1", "tarsgo-infantry-2"},
        labels,
    )
    assert multi_lines[0] == "已选择 3 个单位"
    assert any(line.startswith("英 1级") for line in multi_lines)
    assert any(line.startswith("步1 1级") for line in multi_lines)
    assert any(line.startswith("步2 1级") for line in multi_lines)


def test_rmuc_renderer_smoke_default_and_debug_modes() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match()
    player_team = match.config.scenario.player_team
    opponent_team = next(
        team.team_id
        for team in match.config.scenario.teams.values()
        if team.team_id != player_team
    )
    viewport = app._viewport_for_match(match)

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
        {"tarsgo-hero"},
        None,
        viewport,
        debug_geometry=False,
    )
    app._draw(
        screen,
        font,
        small_font,
        match,
        player_team,
        opponent_team,
        {"tarsgo-hero"},
        None,
        viewport,
        debug_geometry=True,
    )