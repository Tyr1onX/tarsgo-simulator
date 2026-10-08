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
    sys.modules.pop("tarsgo_simulator.desktop.icon", None)
    for module_name in list(sys.modules):
        if module_name == "pygame" or module_name.startswith("pygame."):
            sys.modules.pop(module_name, None)


def _app():
    return importlib.import_module("tarsgo_simulator.desktop.app")


def _match() -> Match:
    return Match.from_scenario(RMUC_SCENARIO)


def test_fixed_step_accumulator_preserves_elapsed_time_and_render_fraction() -> None:
    accumulator = _app()._FixedStepAccumulator()
    accumulator.add(0.05)
    consumed = 0
    while accumulator.consume_step():
        consumed += 1

    assert consumed == 3
    assert accumulator.interpolation_alpha == pytest.approx(0.0)

    accumulator.add(accumulator.step * 0.5)
    assert accumulator.interpolation_alpha == pytest.approx(0.5)
    assert not accumulator.consume_step()


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


def test_rmuc_viewport_expands_beneath_broadcast_hud() -> None:
    app = _app()
    match = _match()
    assert app._is_rmuc_rules_lab(match)

    viewport = app._viewport_for_match(match)
    field_right = viewport.origin[0] + viewport.screen_size[0]

    assert field_right > app.RMUC_PANEL_RECT[0]
    assert viewport.screen_size[0] > 1000
    assert viewport.screen_size[0] / viewport.screen_size[1] == pytest.approx(28 / 15)
    assert viewport.origin[1] + viewport.screen_size[1] <= app.WINDOW_SIZE[1] - 28


def test_rmuc_window_caption_uses_match_presentation() -> None:
    app = _app()
    assert app._window_caption(_match()) == "TARS-Go RMUC 2026 区域赛"


def test_rmuc_inspector_toggle_accepts_key_and_button_click() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    size = app.WINDOW_SIZE
    toggle = app._rmuc_inspector_toggle_rect(size)

    key_event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i)
    click_event = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN,
        button=1,
        pos=toggle.center,
    )
    outside_click = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN,
        button=1,
        pos=(toggle.right + 4, toggle.centery),
    )
    other_key = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d)

    assert app._rmuc_inspector_toggle_requested(key_event, size)
    assert app._rmuc_inspector_toggle_requested(click_event, size)
    assert not app._rmuc_inspector_toggle_requested(outside_click, size)
    assert not app._rmuc_inspector_toggle_requested(other_key, size)


def test_rmuc_default_view_hides_inspector_until_opened(monkeypatch) -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match()
    player_team = match.config.scenario.player_team
    opponent_team = next(
        team.team_id
        for team in match.config.scenario.teams.values()
        if team.team_id != player_team
    )
    calls = []
    monkeypatch.setattr(
        app,
        "_draw_rmuc_panel",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    pygame.font.init()
    draw_args = (
        pygame.Surface(app.WINDOW_SIZE),
        app.ui_font(25),
        app.ui_font(18),
        match,
        player_team,
        opponent_team,
        {"tarsgo-hero"},
        None,
        app._viewport_for_match(match),
    )

    app._draw(*draw_args, inspector_open=False)
    assert calls == []

    app._draw(*draw_args, inspector_open=True)
    assert len(calls) == 1


def test_rmuc_inspector_shows_controls_only_in_debug(monkeypatch) -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    match = _match()
    player_team = match.config.scenario.player_team
    calls = []
    monkeypatch.setattr(
        app,
        "_draw_context_controls",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    pygame.font.init()
    draw_args = (
        pygame.Surface(app.WINDOW_SIZE),
        app.ui_font(18),
        app.ui_font(12),
        match,
        player_team,
        {"tarsgo-hero"},
        app._rmuc_robot_labels(match),
    )

    app._draw_rmuc_panel(*draw_args, debug_geometry=False)
    assert calls == []

    app._draw_rmuc_panel(*draw_args, debug_geometry=True)
    assert len(calls) == 1


def test_rmuc_map_labels_are_minimal_and_number_infantry() -> None:
    app = _app()
    match = _match()
    labels = app._rmuc_robot_labels(match)

    assert labels["tarsgo-hero"] == "H"
    assert labels["tarsgo-engineer"] == "E"
    assert labels["tarsgo-infantry-1"] == "I1"
    assert labels["tarsgo-infantry-2"] == "I2"
    assert labels["tarsgo-sentry"] == "S"

    assert labels["opponent-hero"] == "H"
    assert labels["opponent-infantry-1"] == "I1"
    assert labels["opponent-infantry-2"] == "I2"


def test_rmuc_broadcast_roster_uses_fixed_competition_order() -> None:
    app = _app()
    match = _match()
    labels = app._rmuc_robot_labels(match)

    for team_id in ("tarsgo-rmuc-2026-region", "opponent-rmuc-2026-region"):
        roster = app._rmuc_roster_robots(match, team_id)
        assert [labels[robot.id] for robot in roster] == [
            "H",
            "E",
            "I1",
            "I2",
            "S",
            "D",
        ]


def test_robot_display_names_are_chinese_stable_and_keep_internal_ids() -> None:
    app = _app()
    match = _match()
    names = app._robot_display_names(match)
    compact_names = app._robot_display_names(match, compact=True)

    assert names["tarsgo-hero"] == "英雄"
    assert names["tarsgo-engineer"] == "工程"
    assert names["tarsgo-infantry-1"] == "步兵1"
    assert names["tarsgo-infantry-2"] == "步兵2"
    assert names["tarsgo-sentry"] == "哨兵"
    assert names["tarsgo-drone"] == "空中机器人"
    assert names["opponent-infantry-1"] == "步兵1"
    assert compact_names["tarsgo-drone"] == "空中"
    assert {robot.id for robot in match.robots} >= set(names)

    original = dict(names)
    match.robots.reverse()
    assert app._robot_display_names(match) == original


def test_rmuc_team_hud_rosters_render_compact_chinese_robot_names() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.init()
    match = _match()

    class RecordingFont:
        def __init__(self, font):
            self.font = font
            self.rendered = []

        def __getattr__(self, name):
            return getattr(self.font, name)

        def render(self, text, *args, **kwargs):
            self.rendered.append(text)
            return self.font.render(text, *args, **kwargs)

    player_team = match.config.scenario.player_team
    opponent_team = next(
        team.team_id
        for team in match.config.scenario.teams.values()
        if team.team_id != player_team
    )
    micro_font = RecordingFont(app.ui_font(12))
    app._draw_rmuc_hud(
        pygame.Surface(app.WINDOW_SIZE),
        app.ui_font(25),
        app.ui_font(18),
        micro_font,
        match,
        player_team,
        opponent_team,
    )

    assert {"英雄", "工程", "步兵1", "步兵2", "哨兵", "空中"} <= set(
        micro_font.rendered
    )


def test_energy_mechanism_timers_use_team_scoped_display_state() -> None:
    app = _app()
    match = _match()
    from tarsgo_simulator.rules.rmuc_2026_region import _TimedEnergyMechanismBuff

    player_team = match.config.scenario.player_team
    opponent_team = next(robot.team for robot in match.robots if robot.team != player_team)
    match.ruleset._energy_mechanism_buffs_by_team[player_team].append(
        _TimedEnergyMechanismBuff(
            mechanism="small",
            defense=0.03,
            cooling_multiplier=1.0,
            remaining=2.4,
        )
    )

    assert match.ruleset.display_state.energy_mechanism_effect_timers == (
        (player_team, "small", 2.4),
    )
    assert app._rmuc_energy_timer_labels(match, player_team) == ("小能量 3s",)
    assert app._rmuc_energy_timer_labels(match, opponent_team) == ()


def test_rmuc_map_labels_separate_when_robots_cluster() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.font.init()
    label_surface = app.ui_font(12).render("步兵2 · 3级", True, (255, 255, 255))
    field_rect = pygame.Rect(0, 0, 300, 200)
    centers = [(150, 100)] * 6
    body_rects = []
    for center in centers:
        body = pygame.Rect(0, 0, 54, 54)
        body.center = center
        body_rects.append(body)
    health_bar = pygame.Rect(110, 52, 80, 4)

    placed = []
    for index, center in enumerate(centers):
        label_rect = app._rmuc_map_label_rect(
            label_surface,
            center=center,
            radius=20,
            field_rect=field_rect,
            occupied_labels=placed,
            other_robot_bodies=[
                body
                for body_index, body in enumerate(body_rects)
                if body_index != index
            ] + [health_bar],
        )
        assert not any(label_rect.colliderect(other) for other in placed)
        assert not any(
            label_rect.colliderect(body)
            for body_index, body in enumerate(body_rects)
            if body_index != index
        )
        assert not label_rect.colliderect(health_bar)
        placed.append(label_rect)


def test_rmuc_spectator_map_uses_chinese_names_and_only_real_levels() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.init()
    match = _match()
    display_names = app._robot_display_names(match, compact=True)

    class RecordingFont:
        def __init__(self, font):
            self.font = font
            self.rendered = []

        def __getattr__(self, name):
            return getattr(self.font, name)

        def render(self, text, *args, **kwargs):
            self.rendered.append(text)
            return self.font.render(text, *args, **kwargs)

    player_team = match.config.scenario.player_team
    opponent_team = next(
        team.team_id
        for team in match.config.scenario.teams.values()
        if team.team_id != player_team
    )

    def render_labels(debug_geometry: bool) -> list[str]:
        recorder = RecordingFont(app.ui_font(12))
        visual_state = app.CombatVisualState()
        visual_state.reset(match)
        app._draw(
            pygame.Surface(app.WINDOW_SIZE),
            app.ui_font(25),
            app.ui_font(18),
            match,
            player_team,
            opponent_team,
            set(),
            None,
            app._viewport_for_match(match),
            debug_geometry=debug_geometry,
            visual_state=visual_state,
            hud_font=recorder,
        )
        return recorder.rendered

    normal_labels = render_labels(False)
    debug_labels = render_labels(True)
    for robot_id, name in display_names.items():
        assert any(
            text == name or text.startswith(f"{name} ·")
            for text in normal_labels
        ), (robot_id, name, normal_labels)
    assert any(text.startswith("英雄 · 1级") for text in normal_labels)
    assert "工程" in normal_labels
    assert "哨兵" in normal_labels
    assert "空中" in normal_labels
    assert not any(text.startswith("工程 · ") for text in normal_labels)
    assert not any(text.startswith("哨兵 · ") for text in normal_labels)
    assert all(
        any(text == name or text.startswith(f"{name} ·") for text in debug_labels)
        for name in display_names.values()
    )


def test_team_system_text_is_fitted_to_panel_width() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.font.init()
    font = app.ui_font(12)

    fitted = app._fit_text_to_width(font, "科技核心 上限 10 · 1/1/1/1", 40)

    assert fitted.endswith("…")
    assert font.size(fitted)[0] <= 40


def test_selected_drone_timer_lines_fit_without_truncation() -> None:
    app = _app()
    pygame = importlib.import_module("pygame")
    pygame.font.init()
    font = app.ui_font(12)
    content_width = app.RMUC_PANEL_WIDTH - 30
    details = (
        "空中支援 执行中 · 可用 5.9s",
        "雷达 锁定 22.6s",
        "进度 100/100 · 剩余 2",
        "能量机制 小能量 20s · 大能量 40s",
    )

    for detail in details:
        fitted = app._fit_text_to_width(font, detail, content_width)
        assert fitted == detail
        assert font.size(fitted)[0] <= content_width


def test_broadcast_status_tags_stay_short_and_use_existing_display_state() -> None:
    app = _app()
    match = _match()
    drone = next(robot for robot in match.robots if robot.id == "tarsgo-drone")
    drone.alive = True
    tags = app._rmuc_broadcast_tags(
        match,
        drone,
        "VULN80 FORT DEF50",
        (10.0, 100.0, True, False),
        (True, 8.5),
        (2.0, 3.0, 4.0, 1, True),
        None,
    )

    assert [tag.text for tag in tags] == [
        "易伤",
        "堡垒",
        "禁射",
        "雷达锁定",
        "空支 ON",
    ]

    hero = next(robot for robot in match.robots if robot.id == "tarsgo-hero")
    hero.alive = False
    dead_tags = app._rmuc_broadcast_tags(
        match,
        hero,
        "VULN80 FORT",
        None,
        None,
        None,
        None,
    )
    assert [tag.text for tag in dead_tags] == ["阵亡"]


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
    assert any(line.startswith("冷却      ") for line in lines)
    assert any(line.startswith("缓冲      ") for line in lines)
    assert any(line.startswith("功率      ") for line in lines)
    assert any(line.startswith("状态      ") for line in lines)

    drone_lines = app._selected_unit_lines(
        match,
        {"tarsgo-drone"},
        labels,
    )
    assert any(line.startswith("生命      ") for line in drone_lines)
    assert any(line.startswith("空中支援  ") for line in drone_lines)


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
    assert any(line.startswith("英雄") for line in multi_lines)
    assert any(line.startswith("步兵1") for line in multi_lines)
    assert any(line.startswith("步兵2") for line in multi_lines)


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
        hud_font=app.ui_font(12),
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
        hud_font=app.ui_font(12),
    )
