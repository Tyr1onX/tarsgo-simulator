"""Minimal Pygame front end for the infantry training match."""

import math

import pygame

from tarsgo_simulator.core.config import default_scenario_path
from tarsgo_simulator.core.match import Match


BACKGROUND = (18, 24, 32)
FIELD_COLOR = (49, 66, 61)
FIELD_BORDER = (137, 157, 145)
OBSTACLE_COLOR = (112, 119, 126)
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


def main() -> None:
    match = Match.from_scenario(default_scenario_path())
    pygame.init()
    try:
        window_size = (
            round(match.map.width) + WINDOW_MARGIN * 2,
            round(match.map.height) + HUD_HEIGHT + WINDOW_MARGIN,
        )
        screen = pygame.display.set_mode(window_size)
        pygame.display.set_caption("TARS-Go Infantry Training")
        font = pygame.font.Font(None, 25)
        small_font = pygame.font.Font(None, 18)
        clock = pygame.time.Clock()
        player_team = match.config.scenario.player_team
        opponent_team = next(
            team.team_id
            for team in match.config.scenario.teams.values()
            if team.team_id != player_team
        )
        selected_robot_id: str | None = None
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
                        selected_robot_id = None
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    world = _screen_to_world(event.pos, match)
                    if world is None:
                        continue
                    if event.button == 1:
                        selected_robot_id = _select_player_robot(world, match, player_team)
                    elif event.button == 3 and selected_robot_id is not None:
                        match.order_move(selected_robot_id, world)

            match.update(dt)
            _draw(
                screen,
                font,
                small_font,
                match,
                player_team,
                opponent_team,
                selected_robot_id,
            )
            pygame.display.flip()
    finally:
        pygame.quit()


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


def _draw(
    screen: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    match: Match,
    player_team: str,
    opponent_team: str,
    selected_robot_id: str | None,
) -> None:
    screen.fill(BACKGROUND)
    player = next(robot for robot in match.robots if robot.team == player_team)
    opponent = next(robot for robot in match.robots if robot.team == opponent_team)

    left = f"{match.team_name(player_team)}  HP {player.hp}/{player.max_hp}"
    right = f"{match.team_name(opponent_team)}  HP {opponent.hp}/{opponent.max_hp}"
    timer = max(0, math.ceil(match.config.match_duration - match.elapsed_time))
    if match.finished:
        status = f"{match.team_name(match.winner)} WINS" if match.winner else "DRAW"
    else:
        status = f"BATTLE  {timer // 60:02}:{timer % 60:02}"

    screen.blit(font.render(left, True, PLAYER_COLOR), (WINDOW_MARGIN, 22))
    status_surface = font.render(status, True, TEXT_COLOR)
    screen.blit(status_surface, status_surface.get_rect(center=(screen.get_width() // 2, 34)))
    right_surface = font.render(right, True, OPPONENT_COLOR)
    screen.blit(right_surface, (screen.get_width() - WINDOW_MARGIN - right_surface.get_width(), 22))

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

    for robot in match.robots:
        center = (
            round(MAP_ORIGIN[0] + robot.position[0]),
            round(MAP_ORIGIN[1] + robot.position[1]),
        )
        radius = max(9, round(match.map.collision_radius))
        color = PLAYER_COLOR if robot.team == player_team else OPPONENT_COLOR
        if selected_robot_id == robot.id:
            pygame.draw.circle(screen, SELECTION_COLOR, center, radius + 6, width=2)
        pygame.draw.circle(screen, color if robot.alive else MUTED_COLOR, center, radius)

        bar_width, bar_height = 48, 6
        bar_x = center[0] - bar_width // 2
        bar_y = center[1] - radius - 15
        pygame.draw.rect(screen, HP_BACKGROUND, (bar_x, bar_y, bar_width, bar_height))
        hp_width = round(bar_width * robot.hp / robot.max_hp)
        if hp_width:
            pygame.draw.rect(screen, HP_COLOR, (bar_x, bar_y, hp_width, bar_height))
        label = "TARS" if robot.team == player_team else "OPP"
        label_surface = small_font.render(label, True, TEXT_COLOR)
        screen.blit(label_surface, label_surface.get_rect(center=(center[0], center[1] + radius + 11)))


if __name__ == "__main__":
    main()
