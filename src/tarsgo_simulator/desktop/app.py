"""Minimal Pygame front end for training and partial rules-lab matches."""

import argparse
import math
from pathlib import Path

import pygame

from tarsgo_simulator.core.config import default_scenario_path
from tarsgo_simulator.core.match import Match


BACKGROUND = (18, 24, 32)
FIELD_COLOR = (49, 66, 61)
FIELD_BORDER = (137, 157, 145)
OBSTACLE_COLOR = (112, 119, 126)
ZONE_COLOR = (79, 156, 166)
TEXT_COLOR = (236, 240, 244)
MUTED_COLOR = (166, 178, 187)
PLAYER_COLOR = (66, 190, 167)
OPPONENT_COLOR = (225, 105, 92)
SELECTION_COLOR = (255, 225, 126)
HP_COLOR = (105, 214, 133)
HP_BACKGROUND = (65, 72, 78)
MAP_ORIGIN = (32, 82)
HUD_HEIGHT = 68
WINDOW_MARGIN = 32


def main(scenario_path: str | Path | None = None) -> None:
    match = Match.from_scenario(scenario_path or default_scenario_path())
    pygame.init()
    try:
        window_size = (
            round(match.map.width) + WINDOW_MARGIN * 2,
            round(match.map.height) + HUD_HEIGHT + WINDOW_MARGIN,
        )
        screen = pygame.display.set_mode(window_size)
        pygame.display.set_caption(_window_caption(match))
        font = pygame.font.Font(None, 25)
        small_font = pygame.font.Font(None, 18)
        clock = pygame.time.Clock()
        player_team = match.config.scenario.player_team
        opponent_team = next(
            team.team_id
            for team in match.config.scenario.teams.values()
            if team.team_id != player_team
        )
        selected_robot_ids: set[str] = set()
        selection_start: tuple[int, int] | None = None
        selection_current: tuple[int, int] | None = None
        selection_shift = False
        running = True

        while running:
            dt = clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_r:
                        match.reset()
                        selected_robot_ids.clear()
                        selection_start = None
                        selection_current = None
                        selection_shift = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        if _screen_to_world(event.pos, match) is not None:
                            selection_start = event.pos
                            selection_current = event.pos
                            modifiers = getattr(event, "mod", 0) | pygame.key.get_mods()
                            selection_shift = bool(modifiers & pygame.KMOD_SHIFT)
                    elif event.button == 3:
                        world = _screen_to_world(event.pos, match)
                        if world is None:
                            continue
                        if len(selected_robot_ids) == 1:
                            match.order_move(next(iter(selected_robot_ids)), world)
                        elif len(selected_robot_ids) > 1:
                            match.order_group_move(sorted(selected_robot_ids), world)
                elif event.type == pygame.MOUSEMOTION and selection_start is not None:
                    selection_current = event.pos
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if selection_start is None:
                        continue
                    selection_current = event.pos
                    if math.dist(selection_start, selection_current) > 5:
                        selection_rect = _selection_rectangle(selection_start, selection_current)
                        selected_robot_ids = _select_player_robots_in_rectangle(
                            selection_rect, match, player_team
                        )
                    else:
                        world = _screen_to_world(event.pos, match)
                        _apply_click_selection(
                            world,
                            match,
                            player_team,
                            selected_robot_ids,
                            shift=selection_shift,
                        )
                    selection_start = None
                    selection_current = None
                    selection_shift = False

            match.update(dt)
            live_player_ids = {
                robot.id
                for robot in match.robots
                if robot.alive and robot.team == player_team
            }
            selected_robot_ids.intersection_update(live_player_ids)
            selection_rect = (
                _selection_rectangle(selection_start, selection_current)
                if selection_start is not None and selection_current is not None
                else None
            )
            _draw(
                screen,
                font,
                small_font,
                match,
                player_team,
                opponent_team,
                selected_robot_ids,
                selection_rect,
            )
            pygame.display.flip()
    finally:
        pygame.quit()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run a TARS-Go simulator scenario.")
    parser.add_argument(
        "--scenario",
        type=Path,
        help="YAML scenario path (defaults to the training-v0 tutorial)",
    )
    arguments = parser.parse_args()
    main(arguments.scenario)


def _window_caption(match: Match) -> str:
    if match.ruleset.display_state is not None:
        return "TARS-Go RMUL 2026 Rules Lab (Partial / Experimental)"
    return "TARS-Go Infantry Training"


def _screen_to_world(position: tuple[int, int], match: Match) -> tuple[float, float] | None:
    x = position[0] - MAP_ORIGIN[0]
    y = position[1] - MAP_ORIGIN[1]
    point = (float(x), float(y))
    return point if match.map.contains(point) else None


def _select_player_robot(
    point: tuple[float, float],
    match: Match,
    player_team: str,
) -> str | None:
    for robot in match.robots:
        if not robot.alive or robot.team != player_team:
            continue
        distance = math.hypot(robot.position[0] - point[0], robot.position[1] - point[1])
        if distance <= match.map.collision_radius + 9:
            return robot.id
    return None


def _apply_click_selection(
    point: tuple[float, float] | None,
    match: Match,
    player_team: str,
    selected_robot_ids: set[str],
    *,
    shift: bool,
) -> None:
    robot_id = (
        _select_player_robot(point, match, player_team) if point is not None else None
    )
    if shift:
        if robot_id is not None:
            if robot_id in selected_robot_ids:
                selected_robot_ids.remove(robot_id)
            else:
                selected_robot_ids.add(robot_id)
        return

    selected_robot_ids.clear()
    if robot_id is not None:
        selected_robot_ids.add(robot_id)


def _selection_rectangle(
    start: tuple[int, int], end: tuple[int, int]
) -> pygame.Rect:
    return pygame.Rect(
        min(start[0], end[0]),
        min(start[1], end[1]),
        abs(end[0] - start[0]),
        abs(end[1] - start[1]),
    )


def _select_player_robots_in_rectangle(
    selection_rect: pygame.Rect,
    match: Match,
    player_team: str,
) -> set[str]:
    selected = set()
    for robot in match.robots:
        if not robot.alive or robot.team != player_team:
            continue
        center = (
            round(MAP_ORIGIN[0] + robot.position[0]),
            round(MAP_ORIGIN[1] + robot.position[1]),
        )
        if selection_rect.collidepoint(center):
            selected.add(robot.id)
    return selected


def _draw(
    screen: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    match: Match,
    player_team: str,
    opponent_team: str,
    selected_robot_ids: set[str],
    selection_rect: pygame.Rect | None,
) -> None:
    screen.fill(BACKGROUND)
    player_robots = [robot for robot in match.robots if robot.team == player_team]
    opponent_robots = [robot for robot in match.robots if robot.team == opponent_team]

    player_alive = sum(robot.alive for robot in player_robots)
    opponent_alive = sum(robot.alive for robot in opponent_robots)
    player_hp = sum(robot.hp for robot in player_robots)
    opponent_hp = sum(robot.hp for robot in opponent_robots)
    player_max_hp = sum(robot.max_hp for robot in player_robots)
    opponent_max_hp = sum(robot.max_hp for robot in opponent_robots)
    display_state = match.ruleset.display_state
    if display_state is None:
        left = f"{match.team_name(player_team)}  {player_alive}/{len(player_robots)} alive  HP {player_hp}/{player_max_hp}"
        right = f"{match.team_name(opponent_team)}  {opponent_alive}/{len(opponent_robots)} alive  HP {opponent_hp}/{opponent_max_hp}"
    else:
        victory_points = dict(display_state.victory_points)
        left = f"{match.team_name(player_team)} VP {victory_points[player_team]}"
        right = f"{match.team_name(opponent_team)} VP {victory_points[opponent_team]}"
    timer = max(0, math.ceil(match.time_limit - match.elapsed_time))
    if match.finished:
        status = f"{match.team_name(match.winner)} WINS" if match.winner else "DRAW"
    else:
        status = f"BATTLE  {timer // 60:02}:{timer % 60:02}"

    screen.blit(font.render(left, True, PLAYER_COLOR), (WINDOW_MARGIN, 22))
    status_surface = font.render(status, True, TEXT_COLOR)
    status_y = 26 if display_state is not None else 34
    screen.blit(status_surface, status_surface.get_rect(center=(screen.get_width() // 2, status_y)))
    right_surface = font.render(right, True, OPPONENT_COLOR)
    screen.blit(right_surface, (screen.get_width() - WINDOW_MARGIN - right_surface.get_width(), 22))
    if display_state is not None:
        control_owner = (
            match.team_name(display_state.control_owner)
            if display_state.control_owner is not None
            else "Neutral"
        )
        control_surface = small_font.render(f"Control: {control_owner}", True, TEXT_COLOR)
        screen.blit(
            control_surface,
            control_surface.get_rect(center=(screen.get_width() // 2, 52)),
        )

    field_rect = pygame.Rect(MAP_ORIGIN, (round(match.map.width), round(match.map.height)))
    pygame.draw.rect(screen, FIELD_COLOR, field_rect)
    pygame.draw.rect(screen, FIELD_BORDER, field_rect, width=2)
    for obstacle in match.map.obstacles:
        obstacle_rect = pygame.Rect(
            round(MAP_ORIGIN[0] + obstacle.x),
            round(MAP_ORIGIN[1] + obstacle.y),
            round(obstacle.width),
            round(obstacle.height),
        )
        pygame.draw.rect(screen, OBSTACLE_COLOR, obstacle_rect, border_radius=3)
    for zone in match.map.zones:
        zone_rect = pygame.Rect(
            round(MAP_ORIGIN[0] + zone.x),
            round(MAP_ORIGIN[1] + zone.y),
            round(zone.width),
            round(zone.height),
        )
        pygame.draw.rect(screen, ZONE_COLOR, zone_rect, width=2)

    labels = {}
    for team_id, prefix in ((player_team, "T"), (opponent_team, "O")):
        for index, robot in enumerate(item for item in match.robots if item.team == team_id):
            labels[robot.id] = f"{prefix}{index + 1}"

    for robot in match.robots:
        center = (
            round(MAP_ORIGIN[0] + robot.position[0]),
            round(MAP_ORIGIN[1] + robot.position[1]),
        )
        radius = max(9, round(match.map.collision_radius))
        color = PLAYER_COLOR if robot.team == player_team else OPPONENT_COLOR
        if robot.id in selected_robot_ids:
            pygame.draw.circle(screen, SELECTION_COLOR, center, radius + 6, width=2)
        pygame.draw.circle(screen, color if robot.alive else MUTED_COLOR, center, radius)

        bar_width, bar_height = 48, 6
        bar_x = center[0] - bar_width // 2
        bar_y = center[1] - radius - 15
        pygame.draw.rect(screen, HP_BACKGROUND, (bar_x, bar_y, bar_width, bar_height))
        hp_width = round(bar_width * robot.hp / robot.max_hp)
        if hp_width:
            pygame.draw.rect(screen, HP_COLOR, (bar_x, bar_y, hp_width, bar_height))
        label_surface = small_font.render(labels[robot.id], True, TEXT_COLOR)
        screen.blit(label_surface, label_surface.get_rect(center=(center[0], center[1] + radius + 11)))

    if selection_rect is not None:
        pygame.draw.rect(screen, SELECTION_COLOR, selection_rect, width=1)


if __name__ == "__main__":
    cli()
