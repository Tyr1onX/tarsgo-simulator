"""Minimal Pygame front end for training and partial rules-lab matches."""

import argparse
import math
from pathlib import Path

import pygame

from tarsgo_simulator.core.config import default_scenario_path
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.viewport import Viewport


BACKGROUND = (18, 24, 32)
FIELD_COLOR = (49, 66, 61)
FIELD_BORDER = (137, 157, 145)
OBSTACLE_COLOR = (112, 119, 126)
ZONE_COLOR = (79, 156, 166)
RED_SUPPLY_COLOR = (196, 102, 96)
BLUE_SUPPLY_COLOR = (94, 132, 196)
CONTROL_ZONE_COLOR = (79, 156, 166)
HIGH_GROUND_COLOR = (180, 162, 105)
TEXT_COLOR = (236, 240, 244)
MUTED_COLOR = (166, 178, 187)
PLAYER_COLOR = (66, 190, 167)
OPPONENT_COLOR = (225, 105, 92)
SELECTION_COLOR = (255, 225, 126)
HP_COLOR = (105, 214, 133)
HP_BACKGROUND = (65, 72, 78)
HUD_HEIGHT = 68
WINDOW_MARGIN = 32
WINDOW_SIZE = (1100, 780)
FIELD_TOP = 82
FIELD_VIEW_RECT = (
    WINDOW_MARGIN,
    FIELD_TOP,
    WINDOW_SIZE[0] - WINDOW_MARGIN * 2,
    WINDOW_SIZE[1] - FIELD_TOP - WINDOW_MARGIN,
)
RMUC_PANEL_WIDTH = 250
RMUC_PANEL_GAP = 14
RMUC_FIELD_VIEW_RECT = (
    20,
    96,
    WINDOW_SIZE[0] - RMUC_PANEL_WIDTH - RMUC_PANEL_GAP - 34,
    WINDOW_SIZE[1] - 112,
)
RMUC_PANEL_RECT = (
    WINDOW_SIZE[0] - RMUC_PANEL_WIDTH - 18,
    92,
    RMUC_PANEL_WIDTH,
    WINDOW_SIZE[1] - 110,
)
ZONE_STYLE = {
    "red-supply": (RED_SUPPLY_COLOR, "RED SUPPLY"),
    "blue-supply": (BLUE_SUPPLY_COLOR, "BLUE SUPPLY"),
    "center-control": (CONTROL_ZONE_COLOR, "CONTROL"),
    "red-high-ground": (HIGH_GROUND_COLOR, "HIGH GROUND"),
    "blue-high-ground": (HIGH_GROUND_COLOR, "HIGH GROUND"),
    "red-start": (RED_SUPPLY_COLOR, "RED START"),
    "blue-start": (BLUE_SUPPLY_COLOR, "BLUE START"),
    "red-outpost-rebuild": (RED_SUPPLY_COLOR, "OUTPOST REBUILD"),
    "blue-outpost-rebuild": (BLUE_SUPPLY_COLOR, "OUTPOST REBUILD"),
    "red-resource": (RED_SUPPLY_COLOR, "RESOURCE"),
    "blue-resource": (BLUE_SUPPLY_COLOR, "RESOURCE"),
    "red-assembly": (HIGH_GROUND_COLOR, "ASSEMBLY"),
    "blue-assembly": (HIGH_GROUND_COLOR, "ASSEMBLY"),
    "red-supply-buff": (RED_SUPPLY_COLOR, "SUPPLY BUFF"),
    "blue-supply-buff": (BLUE_SUPPLY_COLOR, "SUPPLY BUFF"),
    "red-base-buff": (RED_SUPPLY_COLOR, "BASE BUFF"),
    "blue-base-buff": (BLUE_SUPPLY_COLOR, "BASE BUFF"),
    "red-outpost-buff": (RED_SUPPLY_COLOR, "OUTPOST BUFF"),
    "blue-outpost-buff": (BLUE_SUPPLY_COLOR, "OUTPOST BUFF"),
    "red-central-elevated-buff": (HIGH_GROUND_COLOR, "CENTRAL DEF"),
    "blue-central-elevated-buff": (HIGH_GROUND_COLOR, "CENTRAL DEF"),
    "red-trapezoid-buff": (RED_SUPPLY_COLOR, "TRAPEZOID DEF"),
    "blue-trapezoid-buff": (BLUE_SUPPLY_COLOR, "TRAPEZOID DEF"),
    "red-fortress-buff": (HIGH_GROUND_COLOR, "FORTRESS"),
    "blue-fortress-buff": (HIGH_GROUND_COLOR, "FORTRESS"),
}
RMUC_ZONE_STYLE = {
    "red-resource": (RED_SUPPLY_COLOR, "RESOURCE"),
    "blue-resource": (BLUE_SUPPLY_COLOR, "RESOURCE"),
    "red-assembly": (HIGH_GROUND_COLOR, "ASSEMBLY"),
    "blue-assembly": (HIGH_GROUND_COLOR, "ASSEMBLY"),
    "red-outpost-rebuild": (RED_SUPPLY_COLOR, "REBUILD"),
    "blue-outpost-rebuild": (BLUE_SUPPLY_COLOR, "REBUILD"),
    "red-supply-buff": (RED_SUPPLY_COLOR, "SUPPLY"),
    "blue-supply-buff": (BLUE_SUPPLY_COLOR, "SUPPLY"),
    "red-base-buff": (RED_SUPPLY_COLOR, "BASE"),
    "blue-base-buff": (BLUE_SUPPLY_COLOR, "BASE"),
    "red-outpost-buff": (RED_SUPPLY_COLOR, "OUTPOST"),
    "blue-outpost-buff": (BLUE_SUPPLY_COLOR, "OUTPOST"),
    "red-central-elevated-buff": (HIGH_GROUND_COLOR, "CENTRAL"),
    "blue-central-elevated-buff": (HIGH_GROUND_COLOR, "CENTRAL"),
    "red-trapezoid-buff": (RED_SUPPLY_COLOR, "TRAPEZOID"),
    "blue-trapezoid-buff": (BLUE_SUPPLY_COLOR, "TRAPEZOID"),
    "red-fortress-buff": (HIGH_GROUND_COLOR, "FORTRESS"),
    "blue-fortress-buff": (HIGH_GROUND_COLOR, "FORTRESS"),
}
RMUC_DEFAULT_ZONE_IDS = frozenset(RMUC_ZONE_STYLE)
RMUC_DEBUG_ZONE_PREFIXES = ("red-terrain-", "blue-terrain-")
CONTROLS = (
    ("LMB", "Select"),
    ("Shift/LMB", "Multi-select"),
    ("Drag", "Box select"),
    ("RMB", "Move"),
    ("E", "Local ammo"),
    ("F", "Remote ammo"),
    ("G", "Energy Unit"),
    ("1-4", "Tech Core"),
    ("Enter", "Confirm"),
    ("Q / W", "D4 Core"),
    ("D", "Debug view"),
    ("R", "Restart"),
    ("Esc", "Quit"),
)


def main(scenario_path: str | Path | None = None) -> None:
    match = Match.from_scenario(scenario_path or default_scenario_path())
    pygame.init()
    try:
        viewport = _viewport_for_match(match)
        screen = pygame.display.set_mode(WINDOW_SIZE)
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
        debug_geometry = False
        running = True

        while running:
            dt = clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_d:
                        debug_geometry = not debug_geometry
                    elif event.key == pygame.K_r:
                        match.reset()
                        selected_robot_ids.clear()
                        selection_start = None
                        selection_current = None
                        selection_shift = False
                    elif len(selected_robot_ids) == 1:
                        robot_id = next(iter(selected_robot_ids))
                        robot = next(
                            (
                                item
                                for item in match.robots
                                if item.id == robot_id
                            ),
                            None,
                        )
                        if event.key == pygame.K_e:
                            match.order_exchange_projectiles(robot_id)
                        elif robot is not None and event.key == pygame.K_f:
                            action = getattr(
                                match.ruleset,
                                "remote_exchange_projectiles",
                                None,
                            )
                            if callable(action):
                                action(match, robot)
                        elif robot is not None and event.key == pygame.K_g:
                            action = getattr(
                                match.ruleset,
                                "pickup_energy_unit",
                                None,
                            )
                            if callable(action):
                                action(match, robot)
                        elif robot is not None and event.key in {
                            pygame.K_1,
                            pygame.K_2,
                            pygame.K_3,
                            pygame.K_4,
                        }:
                            action = getattr(
                                match.ruleset,
                                "start_tech_core_assembly",
                                None,
                            )
                            if callable(action):
                                difficulty = {
                                    pygame.K_1: 1,
                                    pygame.K_2: 2,
                                    pygame.K_3: 3,
                                    pygame.K_4: 4,
                                }[event.key]
                                action(match, robot, difficulty)
                        elif robot is not None and event.key in {
                            pygame.K_q,
                            pygame.K_w,
                        }:
                            action = getattr(
                                match.ruleset,
                                "confirm_d4_step",
                                None,
                            )
                            display_state = match.ruleset.display_state
                            if callable(action) and display_state is not None:
                                d4_by_team = {
                                    team_id: (
                                        phase,
                                        current_step,
                                    )
                                    for (
                                        team_id,
                                        phase,
                                        current_step,
                                        _activated_at,
                                        _first_core_at,
                                        _pending_remaining,
                                        _retry_after,
                                        _permanent,
                                        _penalty,
                                    ) in display_state.d4_status
                                }
                                phase_step = d4_by_team.get(robot.team)
                                if (
                                    phase_step is not None
                                    and phase_step[0] == "active"
                                    and phase_step[1] > 0
                                ):
                                    action(
                                        match,
                                        robot,
                                        "own" if event.key == pygame.K_q else "opponent",
                                        phase_step[1],
                                    )
                        elif robot is not None and event.key in {
                            pygame.K_RETURN,
                            pygame.K_KP_ENTER,
                        }:
                            action = getattr(
                                match.ruleset,
                                "confirm_tech_core_assembly",
                                None,
                            )
                            if callable(action):
                                action(match, robot)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        if _screen_to_world(event.pos, viewport) is not None:
                            selection_start = event.pos
                            selection_current = event.pos
                            modifiers = getattr(event, "mod", 0) | pygame.key.get_mods()
                            selection_shift = bool(modifiers & pygame.KMOD_SHIFT)
                    elif event.button == 3:
                        world = _screen_to_world(event.pos, viewport)
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
                            selection_rect, match, viewport
                        )
                    else:
                        world = _screen_to_world(event.pos, viewport)
                        _apply_click_selection(
                            world,
                            match,
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
                if robot.alive and match.is_player_controlled(robot.id)
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
                viewport,
                debug_geometry=debug_geometry,
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
    display_state = match.ruleset.display_state
    if display_state is not None and display_state.structure_statuses:
        return "TARS-Go RMUC 2026 Regional Rules Lab (Partial / Experimental)"
    if display_state is not None:
        return "TARS-Go RMUL 2026 Rules Lab (Partial / Experimental)"
    return "TARS-Go Infantry Training"


def _is_rmuc_rules_lab(match: Match) -> bool:
    display_state = match.ruleset.display_state
    return display_state is not None and bool(display_state.structure_statuses)


def _viewport_for_match(match: Match) -> Viewport:
    screen_rect = RMUC_FIELD_VIEW_RECT if _is_rmuc_rules_lab(match) else FIELD_VIEW_RECT
    return Viewport.fit(
        (match.map.width, match.map.height),
        screen_rect,
    )


def _screen_to_world(
    position: tuple[int, int],
    viewport: Viewport,
) -> tuple[float, float] | None:
    return viewport.screen_to_world((float(position[0]), float(position[1])))


def _select_player_robot(
    point: tuple[float, float],
    match: Match,
) -> str | None:
    for robot in match.robots:
        if not robot.alive or not match.is_player_controlled(robot.id):
            continue
        distance = math.hypot(robot.position[0] - point[0], robot.position[1] - point[1])
        if distance <= match.map.collision_radius + 9:
            return robot.id
    return None


def _apply_click_selection(
    point: tuple[float, float] | None,
    match: Match,
    selected_robot_ids: set[str],
    *,
    shift: bool,
) -> None:
    robot_id = _select_player_robot(point, match) if point is not None else None
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
    viewport: Viewport,
) -> set[str]:
    selected = set()
    for robot in match.robots:
        if not robot.alive or not match.is_player_controlled(robot.id):
            continue
        center = tuple(round(value) for value in viewport.world_to_screen(robot.position))
        if selection_rect.collidepoint(center):
            selected.add(robot.id)
    return selected


def _world_rect_to_screen(
    viewport: Viewport,
    x: float,
    y: float,
    width: float,
    height: float,
) -> pygame.Rect:
    left, top = viewport.world_to_screen((x, y))
    return pygame.Rect(
        round(left),
        round(top),
        max(1, round(viewport.world_length_to_screen(width))),
        max(1, round(viewport.world_length_to_screen(height))),
    )


def _draw(
    screen: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    match: Match,
    player_team: str,
    opponent_team: str,
    selected_robot_ids: set[str],
    selection_rect: pygame.Rect | None,
    viewport: Viewport,
    *,
    debug_geometry: bool = False,
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
    robot_statuses = dict(display_state.robot_statuses) if display_state is not None else {}
    if display_state is None:
        left = f"{match.team_name(player_team)}  {player_alive}/{len(player_robots)} alive  HP {player_hp}/{player_max_hp}"
        right = f"{match.team_name(opponent_team)}  {opponent_alive}/{len(opponent_robots)} alive  HP {opponent_hp}/{opponent_max_hp}"
    elif display_state.structure_statuses:
        attack_damage = dict(display_state.attack_damage)
        coins = dict(display_state.coins)
        economy = {
            team_id: (gross, penalty, net)
            for team_id, _coins, gross, penalty, net
            in display_state.team_economy
        }
        rebuild_opportunities = dict(display_state.rebuild_opportunities)
        structures = {
            (structure.team, structure.type): structure
            for structure in match.structures
        }
        player_base = structures[(player_team, "base")]
        player_outpost = structures[(player_team, "outpost")]
        opponent_base = structures[(opponent_team, "base")]
        opponent_outpost = structures[(opponent_team, "outpost")]
        player_gross, player_penalty, player_net = economy.get(
            player_team, (0, 0, 0)
        )
        opponent_gross, opponent_penalty, opponent_net = economy.get(
            opponent_team, (0, 0, 0)
        )
        player_rate = (
            f"CORE {player_gross:+d}-{player_penalty}={player_net:+d}/10s"
            if player_penalty
            else f"CORE {player_net:+d}/10s"
        )
        opponent_rate = (
            f"CORE {opponent_gross:+d}-{opponent_penalty}={opponent_net:+d}/10s"
            if opponent_penalty
            else f"CORE {opponent_net:+d}/10s"
        )
        left = (
            f"{match.team_name(player_team)} B {player_base.hp} O {player_outpost.hp} "
            f"C {coins.get(player_team, 0)} {player_rate} "
            f"R {rebuild_opportunities.get(player_team, 0)} "
            f"DMG {attack_damage.get(player_team, 0)}"
        )
        right = (
            f"{match.team_name(opponent_team)} B {opponent_base.hp} O {opponent_outpost.hp} "
            f"C {coins.get(opponent_team, 0)} {opponent_rate} "
            f"R {rebuild_opportunities.get(opponent_team, 0)} "
            f"DMG {attack_damage.get(opponent_team, 0)}"
        )
    else:
        victory_points = dict(display_state.victory_points)
        attack_damage = dict(display_state.attack_damage)
        coins = dict(display_state.coins)
        left = (
            f"{match.team_name(player_team)} VP {victory_points[player_team]} "
            f"C {coins.get(player_team, 0)} DMG {attack_damage.get(player_team, 0)}"
        )
        right = (
            f"{match.team_name(opponent_team)} VP {victory_points[opponent_team]} "
            f"C {coins.get(opponent_team, 0)} DMG {attack_damage.get(opponent_team, 0)}"
        )
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
        if display_state.structure_statuses:
            tech_core_status = {
                team_id: (cap, d1, d2, d3, d4, active, outside)
                for team_id, cap, d1, d2, d3, d4, active, outside
                in display_state.tech_core_status
            }
            d4_status = {
                team_id: (
                    phase,
                    current_step,
                    activated_at,
                    first_core_at,
                    pending_remaining,
                    retry_after,
                    permanent,
                    penalty,
                )
                for (
                    team_id,
                    phase,
                    current_step,
                    activated_at,
                    first_core_at,
                    pending_remaining,
                    retry_after,
                    permanent,
                    penalty,
                ) in display_state.d4_status
            }
            core_state = tech_core_status.get(player_team)
            if core_state is not None:
                cap, d1, d2, d3, d4, active, outside = core_state
                detail = f"CORE CAP:{cap} D1:{d1} D2:{d2} D3:{d3} D4:{d4}"
                d4_state = d4_status.get(player_team)
                if d4_state is not None:
                    (
                        phase,
                        current_step,
                        activated_at,
                        first_core_at,
                        pending_remaining,
                        retry_after,
                        permanent,
                        penalty,
                    ) = d4_state
                    if phase == "pending":
                        detail = (
                            f"{detail} | D4 WAIT "
                            f"{max(0.0, 15.0 - pending_remaining):.1f}/15"
                        )
                    elif phase == "active":
                        remaining = max(
                            0.0,
                            45.0 - (match.elapsed_time - activated_at),
                        )
                        detail = (
                            f"{detail} | D4 STEP{current_step} "
                            f"45:{remaining:.1f}"
                        )
                        if first_core_at >= 0:
                            pair_remaining = max(
                                0.0,
                                5.0 - (match.elapsed_time - first_core_at),
                            )
                            detail = f"{detail} PAIR:{pair_remaining:.1f}"
                    elif phase == "complete":
                        detail = f"{detail} | D4 COMPLETE"
                    elif permanent:
                        detail = f"{detail} | D4 LOCKED"
                        if penalty > 0:
                            detail = f"{detail} PENALTY -{penalty}/10s"
                    elif retry_after > match.elapsed_time:
                        detail = (
                            f"{detail} | D4 LOCK "
                            f"{math.ceil(retry_after - match.elapsed_time)}s"
                        )
                if active is not None:
                    detail = f"{detail} | D{active} ACTIVE"
                    if outside > 0:
                        detail = f"{detail} OUT {outside:.1f}/15"
            else:
                detail = "CORE unavailable"
            progress_parts = [
                f"{robot_id} {progress:.1f}/{required:g}s"
                for _team_id, robot_id, progress, required
                in display_state.rebuild_progress
            ]
            if progress_parts:
                detail = f"{detail} | Rebuild: " + ", ".join(progress_parts)
        else:
            control_owner = (
                match.team_name(display_state.control_owner)
                if display_state.control_owner is not None
                else "Neutral"
            )
            detail = f"Control: {control_owner}"
        detail_surface = small_font.render(detail, True, TEXT_COLOR)
        screen.blit(
            detail_surface,
            detail_surface.get_rect(center=(screen.get_width() // 2, 52)),
        )

    field_left, field_top = viewport.origin
    field_width, field_height = viewport.screen_size
    field_rect = pygame.Rect(
        round(field_left),
        round(field_top),
        round(field_width),
        round(field_height),
    )
    pygame.draw.rect(screen, FIELD_COLOR, field_rect)
    pygame.draw.rect(screen, FIELD_BORDER, field_rect, width=2)
    for obstacle in match.map.obstacles:
        obstacle_rect = _world_rect_to_screen(
            viewport,
            obstacle.x,
            obstacle.y,
            obstacle.width,
            obstacle.height,
        )
        pygame.draw.rect(screen, OBSTACLE_COLOR, obstacle_rect, border_radius=3)
    for zone in match.map.zones:
        zone_rect = _world_rect_to_screen(
            viewport,
            zone.x,
            zone.y,
            zone.width,
            zone.height,
        )
        zone_color, zone_label = ZONE_STYLE.get(zone.id, (ZONE_COLOR, zone.id.upper()))
        pygame.draw.rect(screen, zone_color, zone_rect, width=2)
        label_surface = small_font.render(zone_label, True, zone_color)
        screen.blit(label_surface, label_surface.get_rect(center=zone_rect.center))

    structure_statuses = (
        {
            structure_id: (hp, max_hp, status)
            for structure_id, hp, max_hp, status in display_state.structure_statuses
        }
        if display_state is not None
        else {}
    )
    for structure in match.structures:
        center = tuple(round(value) for value in viewport.world_to_screen(structure.position))
        size = max(13, round(viewport.world_length_to_screen(34)))
        color = PLAYER_COLOR if structure.team == player_team else OPPONENT_COLOR
        rect = pygame.Rect(center[0] - size, center[1] - size, size * 2, size * 2)
        pygame.draw.rect(screen, color if structure.alive else MUTED_COLOR, rect, width=3)
        hp, max_hp, structure_status = structure_statuses.get(
            structure.id, (structure.hp, structure.max_hp, "")
        )
        label = f"{'B' if structure.type == 'base' else 'O'} {hp}/{max_hp}"
        if structure_status:
            label = f"{label} {structure_status}"
        label_surface = small_font.render(label, True, TEXT_COLOR)
        screen.blit(
            label_surface,
            label_surface.get_rect(center=(center[0], center[1] + size + 12)),
        )

    if all(robot.type == "infantry" for robot in match.robots):
        labels = {}
        for team_id, prefix in ((player_team, "T"), (opponent_team, "O")):
            for index, robot in enumerate(
                item for item in match.robots if item.team == team_id
            ):
                labels[robot.id] = f"{prefix}{index + 1}"
    else:
        type_labels = {"hero": "H", "engineer": "E", "infantry": "I", "sentry": "S"}
        labels = {
            robot.id: type_labels.get(robot.type, robot.type[:1].upper())
            for robot in match.robots
        }
    projectile_counts = (
        {
            robot_id: f"{projectile.removesuffix('mm')}:{count}"
            for robot_id, projectile, count in display_state.robot_projectiles
        }
        if display_state is not None
        else {}
    )
    fortress_reserves = (
        dict(display_state.robot_projectile_reserves)
        if display_state is not None
        else {}
    )
    shooting_heat = (
        {
            robot_id: (heat, limit, locked, permanently_locked)
            for robot_id, heat, limit, locked, permanently_locked
            in display_state.robot_shooting_heat
        }
        if display_state is not None
        else {}
    )
    chassis_power = (
        {
            robot_id: (buffer, maximum, power, limit, power_off_remaining)
            for robot_id, buffer, maximum, power, limit, power_off_remaining
            in display_state.robot_chassis_power
        }
        if display_state is not None
        else {}
    )
    progression = (
        {
            robot_id: (level, experience, level_cap)
            for robot_id, level, experience, level_cap
            in display_state.robot_progression
        }
        if display_state is not None
        else {}
    )
    engineer_energy_units = (
        dict(display_state.engineer_energy_units)
        if display_state is not None
        else {}
    )

    for robot in match.robots:
        center = tuple(round(value) for value in viewport.world_to_screen(robot.position))
        radius = max(
            9,
            round(viewport.world_length_to_screen(match.map.collision_radius)),
        )
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
        robot_label = labels[robot.id]
        progression_state = progression.get(robot.id)
        if progression_state is not None:
            level, experience, level_cap = progression_state
            if level >= level_cap:
                robot_label = f"{robot_label} L{level} MAX"
            else:
                robot_label = f"{robot_label} L{level} XP:{experience:g}"
        energy_unit_credits = engineer_energy_units.get(robot.id, 0)
        if energy_unit_credits > 0:
            robot_label = f"{robot_label} EU:{energy_unit_credits}"
        if robot.id in projectile_counts:
            robot_label = f"{robot_label} {projectile_counts[robot.id]}"
        if robot.id in fortress_reserves:
            robot_label = f"{robot_label} FR:{fortress_reserves[robot.id]}"
        heat_state = shooting_heat.get(robot.id)
        if heat_state is not None:
            heat, limit, locked, permanently_locked = heat_state
            lock_label = " PERM" if permanently_locked else " LOCK" if locked else ""
            robot_label = f"{robot_label} H:{heat:g}/{limit:g}{lock_label}"
        chassis_state = chassis_power.get(robot.id)
        if chassis_state is not None:
            buffer, maximum, _power, _limit, power_off_remaining = chassis_state
            robot_label = f"{robot_label} B:{buffer:g}/{maximum:g}"
            if power_off_remaining > 0:
                robot_label = f"{robot_label} PWR {power_off_remaining:.1f}s"
        label_surface = small_font.render(robot_label, True, TEXT_COLOR)
        screen.blit(label_surface, label_surface.get_rect(center=(center[0], center[1] + radius + 11)))
        robot_status = robot_statuses.get(robot.id)
        if robot_status:
            status_surface = small_font.render(robot_status, True, MUTED_COLOR)
            screen.blit(
                status_surface,
                status_surface.get_rect(center=(center[0], center[1] + radius + 27)),
            )

    if selection_rect is not None:
        pygame.draw.rect(screen, SELECTION_COLOR, selection_rect, width=1)


if __name__ == "__main__":
    cli()
