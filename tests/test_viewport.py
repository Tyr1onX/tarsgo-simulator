import math
from pathlib import Path

import pytest

from tarsgo_simulator.core.config import default_scenario_path, load_match_config
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.viewport import Viewport


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RULES_LAB_PATH = REPOSITORY_ROOT / "configs" / "scenarios" / "rmul-2026-rules-lab.yaml"
RMUC_RULES_LAB_PATH = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)


def test_viewport_round_trip_for_rmul_field_points() -> None:
    viewport = Viewport.fit((1200.0, 800.0), (32.0, 82.0, 1036.0, 666.0))

    for point in ((0.0, 0.0), (600.0, 400.0), (1200.0, 800.0)):
        screen = viewport.world_to_screen(point)
        world = viewport.screen_to_world(screen)
        assert world is not None
        assert world[0] == pytest.approx(point[0])
        assert world[1] == pytest.approx(point[1])


def test_viewport_preserves_field_aspect_ratio_with_uniform_scale() -> None:
    viewport = Viewport.fit((1200.0, 800.0), (32.0, 82.0, 1036.0, 666.0))
    screen_width, screen_height = viewport.screen_size

    assert screen_width / screen_height == pytest.approx(3 / 2)
    assert viewport.scale == pytest.approx(screen_width / 1200.0)
    assert viewport.scale == pytest.approx(screen_height / 800.0)


@pytest.mark.parametrize(
    "window_rect",
    (
        (18.0, 182.0, 1064.0, 568.0),  # RMUC broadcast field in 1100 x 780.
        (18.0, 160.0, 1220.0, 650.0),  # Wider supported desktop window.
    ),
)
def test_rmuc_canonical_field_viewport_stays_proportional(window_rect) -> None:
    match = Match(load_match_config(RMUC_RULES_LAB_PATH))
    viewport = Viewport.fit(
        (match.map.width, match.map.height),
        window_rect,
    )
    screen_width, screen_height = viewport.screen_size
    _left, top, available_width, available_height = window_rect

    assert match.map.width / match.map.height == pytest.approx(28 / 15)
    assert screen_width / screen_height == pytest.approx(28 / 15)
    assert viewport.scale == pytest.approx(screen_width / match.map.width)
    assert viewport.scale == pytest.approx(screen_height / match.map.height)
    assert screen_width <= available_width
    assert screen_height <= available_height
    assert (
        viewport.origin[0] > window_rect[0]
        or viewport.origin[1] > top
    )
    assert (
        viewport.origin[0] + screen_width < window_rect[0] + available_width
        or viewport.origin[1] + screen_height < top + available_height
    )


def test_viewport_rejects_screen_points_outside_rendered_field() -> None:
    viewport = Viewport.fit((1200.0, 800.0), (32.0, 82.0, 1036.0, 666.0))
    left, top = viewport.origin
    width, height = viewport.screen_size

    assert viewport.screen_to_world((left - 1, top)) is None
    assert viewport.screen_to_world((left, top - 1)) is None
    assert viewport.screen_to_world((left + width + 1, top)) is None
    assert viewport.screen_to_world((left, top + height + 1)) is None


def test_scaled_right_click_target_maps_back_to_world_move_goal() -> None:
    from tarsgo_simulator.desktop.app import _screen_to_world, _viewport_for_match

    match = Match(load_match_config(RULES_LAB_PATH))
    viewport = _viewport_for_match(match)
    requested_goal = (700.0, 400.0)
    screen_goal = viewport.world_to_screen(requested_goal)
    world_goal = _screen_to_world(
        (round(screen_goal[0]), round(screen_goal[1])),
        viewport,
    )

    assert world_goal is not None
    assert world_goal[0] == pytest.approx(requested_goal[0], abs=1.0)
    assert world_goal[1] == pytest.approx(requested_goal[1], abs=1.0)
    assert match.order_move("tarsgo-hero", world_goal)
    assert match.robots[0].path


def test_scaled_click_selection_hits_player_robot() -> None:
    from tarsgo_simulator.desktop.app import (
        _screen_to_world,
        _select_player_robot,
        _viewport_for_match,
    )

    match = Match(load_match_config(RULES_LAB_PATH))
    viewport = _viewport_for_match(match)
    hero = next(robot for robot in match.robots if robot.id == "tarsgo-hero")
    screen = viewport.world_to_screen(hero.position)
    world = _screen_to_world((round(screen[0]), round(screen[1])), viewport)

    assert world is not None
    assert _select_player_robot(world, match) == hero.id


def test_scaled_drag_selection_selects_hero_and_infantry_only() -> None:
    pygame = pytest.importorskip("pygame")
    from tarsgo_simulator.desktop.app import (
        _select_player_robots_in_rectangle,
        _viewport_for_match,
    )

    match = Match(load_match_config(RULES_LAB_PATH))
    viewport = _viewport_for_match(match)
    hero = next(robot for robot in match.robots if robot.id == "tarsgo-hero")
    infantry = next(robot for robot in match.robots if robot.id == "tarsgo-infantry")
    hero_screen = viewport.world_to_screen(hero.position)
    infantry_screen = viewport.world_to_screen(infantry.position)
    selection = pygame.Rect(
        round(min(hero_screen[0], infantry_screen[0]) - 12),
        round(min(hero_screen[1], infantry_screen[1]) - 12),
        24,
        round(abs(hero_screen[1] - infantry_screen[1]) + 24),
    )

    assert _select_player_robots_in_rectangle(selection, match, viewport) == {
        "tarsgo-hero",
        "tarsgo-infantry",
    }


def test_training_uses_same_non_pixel_viewport_transform() -> None:
    from tarsgo_simulator.desktop.app import _screen_to_world, _viewport_for_match

    match = Match(load_match_config(default_scenario_path()))
    viewport = _viewport_for_match(match)
    robot = next(robot for robot in match.robots if robot.id == "tarsgo-infantry-1")

    assert not math.isclose(viewport.scale, 1.0)
    screen = viewport.world_to_screen(robot.position)
    world = _screen_to_world((round(screen[0]), round(screen[1])), viewport)
    assert world is not None
    assert world[0] == pytest.approx(robot.position[0], abs=1.0)
    assert world[1] == pytest.approx(robot.position[1], abs=1.0)


def test_desktop_draw_smoke_for_training_and_rmul_field() -> None:
    pygame = pytest.importorskip("pygame")
    from tarsgo_simulator.desktop.app import (
        WINDOW_SIZE,
        _draw,
        _viewport_for_match,
    )

    pygame.font.init()
    try:
        font = pygame.font.Font(None, 25)
        small_font = pygame.font.Font(None, 18)
        for scenario in (default_scenario_path(), RULES_LAB_PATH):
            match = Match(load_match_config(scenario))
            screen = pygame.Surface(WINDOW_SIZE)
            player_team = match.config.scenario.player_team
            opponent_team = next(
                team.team_id
                for team in match.config.scenario.teams.values()
                if team.team_id != player_team
            )
            _draw(
                screen,
                font,
                small_font,
                match,
                player_team,
                opponent_team,
                set(),
                None,
                _viewport_for_match(match),
            )
    finally:
        pygame.font.quit()
