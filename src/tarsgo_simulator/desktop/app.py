"""Minimal Pygame front end for training and partial rules-lab matches."""

import argparse
from functools import lru_cache
import math
from pathlib import Path

import pygame

from tarsgo_simulator.core.config import default_scenario_path
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.assets import ASSET_MANAGER
from tarsgo_simulator.desktop.fonts import ui_font
from tarsgo_simulator.desktop.icon import render_app_icon
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
from tarsgo_simulator.desktop.viewport import Viewport
from tarsgo_simulator.desktop.visuals import (
    CombatVisualState,
    low_hp_warning_strength,
    projectile_visual_profile,
    robot_visual_profile,
)


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
DAMAGE_GHOST_COLOR = (224, 176, 92)
TRACER_COLOR = (245, 239, 197)
IMPACT_COLOR = (255, 218, 132)
ROBOT_OUTLINE = (27, 35, 42)
ARENA_FLOOR = (34, 44, 48)
ARENA_FLOOR_DARK = (28, 37, 41)
ARENA_FLOOR_LIGHT = (42, 53, 57)
ARENA_GRID = (58, 72, 77)
ARENA_MIDLINE = (94, 112, 117)
ARENA_LANE = (76, 92, 97)
ARENA_EDGE = (126, 144, 145)
ARENA_SHADOW = (8, 12, 16)
PANEL_BACKGROUND = (23, 30, 38)
PANEL_SECTION = (31, 40, 49)
PANEL_SECTION_ALT = (27, 35, 43)
PANEL_BORDER = (67, 82, 94)
TEAM_RED_COLOR = (213, 83, 78)
TEAM_BLUE_COLOR = (80, 137, 211)
SHIELD_COLOR = (91, 178, 235)
WARNING_COLOR = (240, 187, 92)
DANGER_COLOR = (234, 104, 96)
RESOURCE_COLOR = (142, 188, 128)
ASSEMBLY_COLOR = (188, 154, 96)
FORTRESS_COLOR = (173, 141, 207)
DEFENSE_ZONE_COLOR = (100, 159, 185)
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
RMUC_PANEL_WIDTH = 236
RMUC_BROADCAST_HUD_HEIGHT = 164
RMUC_FIELD_VIEW_RECT = (
    18,
    182,
    WINDOW_SIZE[0] - WINDOW_MARGIN * 2,
    WINDOW_SIZE[1] - 212,
)
RMUC_PANEL_RECT = (
    WINDOW_SIZE[0] - RMUC_PANEL_WIDTH - 16,
    182,
    RMUC_PANEL_WIDTH,
    WINDOW_SIZE[1] - 200,
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
    "red-resource": (RED_SUPPLY_COLOR, "资源区"),
    "blue-resource": (BLUE_SUPPLY_COLOR, "资源区"),
    "red-assembly": (HIGH_GROUND_COLOR, "装配区"),
    "blue-assembly": (HIGH_GROUND_COLOR, "装配区"),
    "red-outpost-rebuild": (RED_SUPPLY_COLOR, "重建区"),
    "blue-outpost-rebuild": (BLUE_SUPPLY_COLOR, "重建区"),
    "red-supply-buff": (RED_SUPPLY_COLOR, "补给区"),
    "blue-supply-buff": (BLUE_SUPPLY_COLOR, "补给区"),
    "red-base-buff": (RED_SUPPLY_COLOR, "基地区"),
    "blue-base-buff": (BLUE_SUPPLY_COLOR, "基地区"),
    "red-outpost-buff": (RED_SUPPLY_COLOR, "前哨站区"),
    "blue-outpost-buff": (BLUE_SUPPLY_COLOR, "前哨站区"),
    "red-central-elevated-buff": (HIGH_GROUND_COLOR, "中央区"),
    "blue-central-elevated-buff": (HIGH_GROUND_COLOR, "中央区"),
    "red-trapezoid-buff": (RED_SUPPLY_COLOR, "梯形区"),
    "blue-trapezoid-buff": (BLUE_SUPPLY_COLOR, "梯形区"),
    "red-fortress-buff": (HIGH_GROUND_COLOR, "堡垒区"),
    "blue-fortress-buff": (HIGH_GROUND_COLOR, "堡垒区"),
}
RMUC_DEFAULT_ZONE_IDS = frozenset(RMUC_ZONE_STYLE)
RMUC_DEBUG_ZONE_PREFIXES = ("red-terrain-", "blue-terrain-")
RMUC_ROBOT_NAMES = {
    "hero": "英雄",
    "engineer": "工程",
    "infantry": "步兵",
    "sentry": "哨兵",
    "drone": "空中机器人",
}
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
    match = Match.from_scenario(
        scenario_path or default_scenario_path(),
        rmuc_spectator_ai=True,
    )
    pygame.init()
    try:
        viewport = _viewport_for_match(match)
        screen = pygame.display.set_mode(WINDOW_SIZE)
        pygame.display.set_icon(render_app_icon(128))
        pygame.display.set_caption(_window_caption(match))
        font = ui_font(25)
        small_font = ui_font(18)
        hud_font = ui_font(12)
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
        inspector_open = False
        visual_state = CombatVisualState()
        visual_state.reset(match)
        running = True

        while running:
            dt = clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if (
                    _is_rmuc_rules_lab(match)
                    and _rmuc_inspector_toggle_requested(event, screen.get_size())
                ):
                    inspector_open = not inspector_open
                    continue
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if inspector_open:
                            inspector_open = False
                        else:
                            running = False
                    elif event.key == pygame.K_d:
                        debug_geometry = not debug_geometry
                    elif event.key == pygame.K_r:
                        match.reset()
                        visual_state.reset(match)
                        selected_robot_ids.clear()
                        selection_start = None
                        selection_current = None
                        selection_shift = False
                        inspector_open = False
                    elif len(selected_robot_ids) == 1 and not _is_rmuc_rules_lab(match):
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
                        if _is_rmuc_rules_lab(match):
                            continue
                        world = _screen_to_world(event.pos, viewport)
                        if world is None:
                            continue
                        moved = False
                        if len(selected_robot_ids) == 1:
                            moved = match.order_move(
                                next(iter(selected_robot_ids)),
                                world,
                            )
                        elif len(selected_robot_ids) > 1:
                            moved = match.order_group_move(
                                sorted(selected_robot_ids),
                                world,
                            )
                        if moved and _is_rmuc_rules_lab(match):
                            visual_state.add_move_marker(world)
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

            visual_state.begin_frame(match)
            match.update(dt)
            visual_state.after_match_update(match, dt)
            live_selectable_ids = {
                robot.id
                for robot in match.robots
                if robot.alive
                and (
                    _is_rmuc_rules_lab(match)
                    or match.is_player_controlled(robot.id)
                )
            }
            selected_robot_ids.intersection_update(live_selectable_ids)
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
                inspector_open=inspector_open,
                visual_state=visual_state,
                hud_font=hud_font,
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
        return "TARS-Go RMUC 2026 区域赛"
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
        if not robot.alive or (
            not _is_rmuc_rules_lab(match)
            and not match.is_player_controlled(robot.id)
        ):
            continue
        distance = math.hypot(robot.position[0] - point[0], robot.position[1] - point[1])
        if distance <= match.map.collision_radius + 9 * match.map.unit_scale:
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
        if not robot.alive or (
            not _is_rmuc_rules_lab(match)
            and not match.is_player_controlled(robot.id)
        ):
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


def _rmuc_zone_style(
    zone_id: str,
    *,
    debug_geometry: bool,
) -> tuple[tuple[int, int, int], str] | None:
    if debug_geometry:
        color = ZONE_STYLE.get(zone_id, (ZONE_COLOR, ""))[0]
        return color, zone_id.upper()
    return RMUC_ZONE_STYLE.get(zone_id)


def _rmuc_robot_labels(match: Match) -> dict[str, str]:
    labels: dict[str, str] = {}
    team_ids = sorted({robot.team for robot in match.robots})
    for team_id in team_ids:
        team_robots = sorted(
            (robot for robot in match.robots if robot.team == team_id),
            key=lambda robot: robot.id,
        )
        infantry_ids = [
            robot.id for robot in team_robots if robot.type == "infantry"
        ]
        infantry_index = {
            robot_id: index + 1 for index, robot_id in enumerate(infantry_ids)
        }
        for robot in team_robots:
            if robot.type == "hero":
                label = "H"
            elif robot.type == "engineer":
                label = "E"
            elif robot.type == "infantry":
                label = f"I{infantry_index[robot.id]}"
            elif robot.type == "sentry":
                label = "S"
            elif robot.type == "drone":
                label = "D"
            else:
                label = robot.type[:1].upper()
            labels[robot.id] = label
    return labels


def _default_robot_labels(
    match: Match,
    player_team: str,
    opponent_team: str,
) -> dict[str, str]:
    if all(robot.type == "infantry" for robot in match.robots):
        labels: dict[str, str] = {}
        for team_id, prefix in ((player_team, "T"), (opponent_team, "O")):
            for index, robot in enumerate(
                item for item in match.robots if item.team == team_id
            ):
                labels[robot.id] = f"{prefix}{index + 1}"
        return labels
    type_labels = {
        "hero": "H",
        "engineer": "E",
        "infantry": "I",
        "sentry": "S",
        "drone": "D",
    }
    return {
        robot.id: type_labels.get(robot.type, robot.type[:1].upper())
        for robot in match.robots
    }


def _status_without_defense(status: str) -> str:
    words = status.split()
    if len(words) >= 2 and words[0] == "DEF" and words[1].endswith("%"):
        return " ".join(words[2:])
    return status


def _defense_from_status(status: str) -> str | None:
    words = status.split()
    for index, word in enumerate(words[:-1]):
        if word == "DEF" and words[index + 1].endswith("%"):
            return words[index + 1]
    return None


def _selected_unit_lines(
    match: Match,
    selected_robot_ids: set[str],
    labels: dict[str, str],
) -> list[str]:
    if not selected_robot_ids:
        return ["已选单位", "请选择一个单位"]
    robots_by_id = {robot.id: robot for robot in match.robots}
    selected = [
        robots_by_id[robot_id]
        for robot_id in sorted(selected_robot_ids)
        if robot_id in robots_by_id
    ]
    if len(selected) != 1:
        lines = [f"已选择 {len(selected)} 个单位"]
        lines.extend(
            (
                f"{labels.get(robot.id, robot.id)}   空中单位"
                if robot.type == "drone"
                else f"{labels.get(robot.id, robot.id)}   生命 {robot.hp}/{robot.max_hp}"
            )
            for robot in selected
        )
        return lines

    robot = selected[0]
    display_state = match.ruleset.display_state
    statuses = dict(display_state.robot_statuses) if display_state is not None else {}
    progression = (
        {
            robot_id: (level, experience, level_cap)
            for robot_id, level, experience, level_cap
            in display_state.robot_progression
        }
        if display_state is not None
        else {}
    )
    projectiles = (
        {
            robot_id: (projectile, count)
            for robot_id, projectile, count in display_state.robot_projectiles
        }
        if display_state is not None
        else {}
    )
    reserves = (
        dict(display_state.robot_projectile_reserves)
        if display_state is not None
        else {}
    )
    heat = (
        {
            robot_id: (current, limit, locked, permanently_locked)
            for robot_id, current, limit, locked, permanently_locked
            in display_state.robot_shooting_heat
        }
        if display_state is not None
        else {}
    )
    chassis = (
        {
            robot_id: (buffer, maximum, power, limit, power_off_remaining)
            for (
                robot_id,
                buffer,
                maximum,
                power,
                limit,
                power_off_remaining,
            ) in display_state.robot_chassis_power
        }
        if display_state is not None
        else {}
    )
    engineer_units = (
        dict(display_state.engineer_energy_units)
        if display_state is not None
        else {}
    )
    drone_support = (
        {
            robot_id: (active, remaining)
            for robot_id, active, remaining in display_state.drone_air_support
        }
        if display_state is not None
        else {}
    )
    radar_anti_drone = (
        {
            robot_id: (progress, threshold, lock_remaining, remaining_uses, illuminated)
            for (
                robot_id,
                _source_team_id,
                progress,
                threshold,
                lock_remaining,
                _activations,
                remaining_uses,
                illuminated,
            ) in display_state.radar_anti_drone
        }
        if display_state is not None
        else {}
    )

    title = RMUC_ROBOT_NAMES.get(robot.type, robot.type)
    progression_state = progression.get(robot.id)
    if progression_state is not None:
        title = f"{title} · {progression_state[0]}级"
    lines = [title]
    ai_intent = match.ai_intent(robot.id)
    if ai_intent is not None:
        lines.append(f"当前 AI 意图  {ai_intent}")
    if robot.type == "drone":
        support = drone_support.get(robot.id)
        if support is not None:
            active, remaining = support
            lines.append(
                f"空中支援  {'执行中' if active else '停机坪'} · 可用 {remaining:.1f}s"
            )
        anti_drone = radar_anti_drone.get(robot.id)
        if anti_drone is not None:
            progress, threshold, lock_remaining, remaining_uses, illuminated = anti_drone
            lock_text = (
                f"锁定 {lock_remaining:.1f}s"
                if lock_remaining > 0
                else "瞄准中"
                if illuminated
                else "待机"
            )
            lines.append(
                f"雷达反制  {lock_text} · P {progress:g}/{threshold:g} · 剩余 {remaining_uses}"
            )
    lines.append(f"生命      {robot.hp} / {robot.max_hp}")
    if progression_state is not None:
        _level, experience, _level_cap = progression_state
        lines.append(f"经验      {experience:g}")
    projectile_state = projectiles.get(robot.id)
    if projectile_state is not None:
        projectile, count = projectile_state
        lines.append(f"弹量      {projectile}: {count}")
    heat_state = heat.get(robot.id)
    if heat_state is not None:
        current, limit, locked, permanently_locked = heat_state
        suffix = " 永久禁射" if permanently_locked else " 禁射" if locked else ""
        lines.append(f"热量      {current:g} / {limit:g}{suffix}")
        effective_heat = getattr(match.ruleset, "_effective_heat_parameters", None)
        if callable(effective_heat):
            try:
                cooling = effective_heat(robot.id).cooling_per_second
            except KeyError:
                cooling = None
            if cooling is not None:
                lines.append(f"冷却      {cooling:g} / 秒")
    chassis_state = chassis.get(robot.id)
    if chassis_state is not None:
        buffer, maximum, power, limit, power_off_remaining = chassis_state
        lines.append(f"缓冲      {buffer:g} / {maximum:g}")
        lines.append(f"功率      {power:g} / {limit:g} W")
        if power_off_remaining > 0:
            lines.append(f"底盘断电  {power_off_remaining:.1f}s")
    if robot.id in engineer_units:
        lines.append(f"能量单元  {engineer_units[robot.id]}")
    if robot.id in reserves:
        lines.append(f"堡垒储备  {reserves[robot.id]}")

    raw_status = statuses.get(robot.id, "")
    defense = _defense_from_status(raw_status)
    if defense is not None:
        lines.append(f"防御      {defense}")
    status = _status_without_defense(raw_status)
    lines.append(f"状态      {status or '—'}")
    return lines


def _rmuc_team_detail_lines(
    match: Match,
    player_team: str,
) -> list[str]:
    display_state = match.ruleset.display_state
    if display_state is None:
        return []
    attack_damage = dict(display_state.attack_damage)
    rebuild = dict(display_state.rebuild_opportunities)
    economy = {
        team_id: (gross, penalty, net)
        for team_id, _coins, gross, penalty, net in display_state.team_economy
    }
    gross, penalty, net = economy.get(player_team, (0, 0, 0))
    income = (
        f"收入      {gross:+d}-{penalty}={net:+d} / 10s"
        if penalty
        else f"收入      {net:+d} / 10s"
    )
    lines = [
        "队伍系统",
        income,
        f"重建机会  {rebuild.get(player_team, 0)}",
        f"累计伤害  {attack_damage.get(player_team, 0)}",
    ]
    tech_core = {
        team_id: (cap, d1, d2, d3, d4, active, outside)
        for team_id, cap, d1, d2, d3, d4, active, outside
        in display_state.tech_core_status
    }.get(player_team)
    if tech_core is not None:
        cap, d1, d2, d3, d4, active, outside = tech_core
        lines.append(f"科技核心  上限 {cap} · {d1}/{d2}/{d3}/{d4}")
        if active is not None:
            detail = f"D{active} 已激活"
            if outside > 0:
                detail += f" · 离区 {outside:.1f}/15s"
            lines.append(detail)
    d4 = {
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
    }.get(player_team)
    if d4 is not None:
        (
            phase,
            current_step,
            activated_at,
            first_core_at,
            pending_remaining,
            retry_after,
            permanent,
            penalty,
        ) = d4
        if phase == "pending":
            lines.append(f"D4 等待   {max(0.0, 15.0 - pending_remaining):.1f}/15s")
        elif phase == "active":
            remaining = max(0.0, 45.0 - (match.elapsed_time - activated_at))
            detail = f"D4 步骤 {current_step} · {remaining:.1f}s"
            if first_core_at >= 0:
                pair_remaining = max(
                    0.0,
                    5.0 - (match.elapsed_time - first_core_at),
                )
                detail += f" · 配对 {pair_remaining:.1f}s"
            lines.append(detail)
        elif phase == "complete":
            lines.append("D4 已完成")
        elif permanent:
            detail = "D4 已锁定"
            if penalty > 0:
                detail += f" · -{penalty}/10s"
            lines.append(detail)
        elif retry_after > match.elapsed_time:
            lines.append(f"D4 锁定   {math.ceil(retry_after - match.elapsed_time)}s")
    return lines


def _wrap_words(text: str, max_chars: int = 30) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_panel_lines(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    lines: list[str],
    *,
    x: int,
    y: int,
    max_chars: int = 30,
    title_color: tuple[int, int, int] = TEXT_COLOR,
) -> int:
    cursor_y = y
    for index, line in enumerate(lines):
        wrapped = _wrap_words(line, max_chars=max_chars)
        for piece in wrapped:
            color = title_color if index == 0 else TEXT_COLOR
            surface = small_font.render(piece, True, color)
            screen.blit(surface, (x, cursor_y))
            cursor_y += 17
        if index == 0:
            cursor_y += 4
    return cursor_y


def _badge_color(tone: str) -> tuple[int, int, int]:
    return {
        "shield": SHIELD_COLOR,
        "defense": DEFENSE_ZONE_COLOR,
        "danger": DANGER_COLOR,
        "warning": WARNING_COLOR,
        "fortress": FORTRESS_COLOR,
        "terrain": RESOURCE_COLOR,
    }.get(tone, MUTED_COLOR)


def _draw_badges(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    badges: tuple[BadgeSpec, ...],
    *,
    x: int,
    y: int,
    max_width: int,
) -> int:
    cursor_x = x
    cursor_y = y
    row_height = 23
    for badge in badges:
        text_surface = small_font.render(badge.text, True, TEXT_COLOR)
        width = text_surface.get_width() + 14
        if cursor_x != x and cursor_x + width > x + max_width:
            cursor_x = x
            cursor_y += row_height
        rect = pygame.Rect(cursor_x, cursor_y, width, 19)
        color = _badge_color(badge.tone)
        pygame.draw.rect(screen, PANEL_SECTION, rect, border_radius=5)
        pygame.draw.rect(screen, color, rect, width=1, border_radius=5)
        screen.blit(
            text_surface,
            text_surface.get_rect(center=rect.center),
        )
        cursor_x += width + 6
    return cursor_y + (row_height if badges else 0)


def _draw_progress_bar(
    screen: pygame.Surface,
    *,
    rect: pygame.Rect,
    value: float,
    maximum: float,
    fill_color: tuple[int, int, int],
) -> None:
    pygame.draw.rect(screen, HP_BACKGROUND, rect, border_radius=3)
    ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
    width = round(rect.width * ratio)
    if width > 0:
        pygame.draw.rect(
            screen,
            fill_color,
            pygame.Rect(rect.x, rect.y, width, rect.height),
            border_radius=3,
        )


def _rmuc_team_color(match: Match, team_id: str) -> tuple[int, int, int]:
    for side, team in match.config.scenario.teams.items():
        if team.team_id == team_id:
            return TEAM_RED_COLOR if side == "red" else TEAM_BLUE_COLOR
    return MUTED_COLOR


def _should_show_zone_label(
    *,
    emphasized: bool,
    occupied_by_selected: bool,
    hovered: bool,
    targeted_by_selected: bool = False,
) -> bool:
    return (
        emphasized
        or occupied_by_selected
        or hovered
        or targeted_by_selected
    )


def _screen_rect_is_hovered(rect: pygame.Rect) -> bool:
    if not pygame.display.get_init() or pygame.display.get_surface() is None:
        return False
    try:
        return rect.collidepoint(pygame.mouse.get_pos())
    except pygame.error:
        return False


def _rmuc_hud_rects(
    screen_width: int,
) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
    margin = 18
    gap = 12
    timer_width = 164
    team_width = (screen_width - margin * 2 - gap * 2 - timer_width) // 2
    return (
        pygame.Rect(margin, 8, team_width, RMUC_BROADCAST_HUD_HEIGHT),
        pygame.Rect(screen_width // 2 - timer_width // 2, 8, timer_width, RMUC_BROADCAST_HUD_HEIGHT),
        pygame.Rect(screen_width - margin - team_width, 8, team_width, RMUC_BROADCAST_HUD_HEIGHT),
    )


def _rmuc_inspector_toggle_rect(
    screen_size: tuple[int, int],
) -> pygame.Rect:
    screen_width, screen_height = screen_size
    return pygame.Rect(18, screen_height - 28, 92, 22).clamp(
        pygame.Rect(0, 0, screen_width, screen_height)
    )


def _rmuc_inspector_toggle_requested(
    event: pygame.event.Event,
    screen_size: tuple[int, int],
) -> bool:
    if event.type == pygame.KEYDOWN:
        return event.key == pygame.K_i
    return (
        event.type == pygame.MOUSEBUTTONDOWN
        and event.button == 1
        and _rmuc_inspector_toggle_rect(screen_size).collidepoint(event.pos)
    )


def _draw_rmuc_inspector_toggle(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    *,
    inspector_open: bool,
) -> None:
    rect = _rmuc_inspector_toggle_rect(screen.get_size())
    color = SELECTION_COLOR if inspector_open else MUTED_COLOR
    pygame.draw.rect(screen, PANEL_BACKGROUND, rect, border_radius=5)
    pygame.draw.rect(
        screen,
        color if inspector_open else PANEL_BORDER,
        rect,
        width=1,
        border_radius=5,
    )
    label = small_font.render("单位详情", True, color)
    screen.blit(label, label.get_rect(center=rect.center))


def _rmuc_panel_layout(
    panel: pygame.Rect,
    selected_count: int,
) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
    inner_x = panel.x + 4
    inner_width = panel.width - 8
    if selected_count == 0:
        unit_height = 82
    elif selected_count == 1:
        unit_height = 344
    else:
        unit_height = min(166, 52 + min(selected_count, 5) * 20)
    unit_rect = pygame.Rect(inner_x, panel.y + 2, inner_width, unit_height)
    team_rect = pygame.Rect(inner_x, unit_rect.bottom + 8, inner_width, 132)
    controls_rect = pygame.Rect(inner_x, team_rect.bottom + 8, inner_width, 82)
    return unit_rect, team_rect, controls_rect


def _selected_robot_types(
    match: Match,
    selected_robot_ids: set[str],
) -> set[str]:
    return {        robot.type
        for robot in match.robots
        if robot.id in selected_robot_ids
    }


def _selected_ai_target_positions(
    match: Match,
    selected_robot_ids: set[str],
) -> tuple[tuple[float, float], ...]:
    return tuple(
        robot.path[-1]
        for robot in match.robots
        if (
            robot.id in selected_robot_ids
            and match.is_ai_controlled(robot.id)
            and robot.path
        )
    )


def _draw_selected_unit_card(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    micro_font: pygame.font.Font,
    match: Match,
    selected_robot_ids: set[str],
    labels: dict[str, str],
    rect: pygame.Rect,
) -> None:
    pygame.draw.rect(screen, PANEL_SECTION, rect, border_radius=7)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=1, border_radius=7)
    x = rect.x + 11
    y = rect.y + 9
    content_width = rect.width - 22
    robots_by_id = {robot.id: robot for robot in match.robots}
    selected = [
        robots_by_id[robot_id]
        for robot_id in sorted(selected_robot_ids)
        if robot_id in robots_by_id
    ]

    if not selected:
        screen.blit(small_font.render("观察单位", True, TEXT_COLOR), (x, y))
        screen.blit(
            small_font.render("点击战场单位查看状态", True, MUTED_COLOR),
            (x, y + 26),
        )
        return

    if len(selected) != 1:
        screen.blit(
            small_font.render(
                f"多单位观察 · {len(selected)}",
                True,
                TEXT_COLOR,
            ),
            (x, y),
        )
        y += 28
        for robot in selected[:5]:
            label = labels.get(robot.id, robot.id)
            team_color = _rmuc_team_color(match, robot.team)
            pygame.draw.circle(screen, team_color, (x + 5, y + 7), 4)
            screen.blit(
                small_font.render(label, True, TEXT_COLOR if robot.alive else MUTED_COLOR),
                (x + 14, y),
            )
            if robot.type == "drone":
                screen.blit(
                    small_font.render("AIR", True, team_color),
                    (x + 46, y),
                )
            else:
                _draw_progress_bar(
                    screen,
                    rect=pygame.Rect(x + 46, y + 4, content_width - 48, 7),
                    value=robot.hp,
                    maximum=robot.max_hp,
                    fill_color=HP_COLOR if robot.alive else MUTED_COLOR,
                )
            y += 20
        return

    robot = selected[0]
    display_state = match.ruleset.display_state
    if display_state is None:
        return
    statuses = dict(display_state.robot_statuses)
    progression = {
        robot_id: (level, experience, level_cap)
        for robot_id, level, experience, level_cap
        in display_state.robot_progression
    }
    projectiles = {
        robot_id: (projectile, count)
        for robot_id, projectile, count in display_state.robot_projectiles
    }
    reserves = dict(display_state.robot_projectile_reserves)
    heat = {
        robot_id: (current, limit, locked, permanently_locked)
        for robot_id, current, limit, locked, permanently_locked
        in display_state.robot_shooting_heat
    }
    chassis = {
        robot_id: (buffer, maximum, power, limit, power_off_remaining)
        for (
            robot_id,
            buffer,
            maximum,
            power,
            limit,
            power_off_remaining,
        ) in display_state.robot_chassis_power
    }
    engineer_units = dict(display_state.engineer_energy_units)
    drone_support = {
        robot_id: (active, remaining)
        for robot_id, active, remaining in display_state.drone_air_support
    }
    radar_anti_drone = {
        robot_id: (progress, threshold, lock_remaining, remaining_uses, illuminated)
        for (
            robot_id,
            _source_team_id,
            progress,
            threshold,
            lock_remaining,
            _activations,
            remaining_uses,
            illuminated,
        ) in display_state.radar_anti_drone
    }

    team_color = _rmuc_team_color(match, robot.team)
    pygame.draw.rect(
        screen,
        team_color,
        pygame.Rect(rect.x, rect.y, 4, rect.height),
        border_top_left_radius=7,
        border_bottom_left_radius=7,
    )

    level_state = progression.get(robot.id)
    level = level_state[0] if level_state is not None else None
    role = RMUC_ROBOT_NAMES.get(robot.type, robot.type)
    title = f"{role} · {level}级" if level is not None else role
    label = labels.get(robot.id, robot.id)
    screen.blit(small_font.render(title, True, TEXT_COLOR), (x, y))
    label_surface = small_font.render(label, True, team_color)
    screen.blit(label_surface, (rect.right - 11 - label_surface.get_width(), y))
    y += 23

    ai_intent = match.ai_intent(robot.id)
    if ai_intent is not None:
        intent_rect = pygame.Rect(x, y, content_width, 31)
        pygame.draw.rect(screen, PANEL_SECTION_ALT, intent_rect, border_radius=5)
        pygame.draw.rect(screen, team_color, intent_rect, width=1, border_radius=5)
        screen.blit(small_font.render("AI", True, team_color), (intent_rect.x + 7, intent_rect.y + 5))
        screen.blit(small_font.render(ai_intent, True, TEXT_COLOR), (intent_rect.x + 32, intent_rect.y + 5))
        y = intent_rect.bottom + 5

    hp_label = small_font.render(
        f"生命 {robot.hp}/{robot.max_hp}",
        True,
        TEXT_COLOR if robot.alive else MUTED_COLOR,
    )
    screen.blit(hp_label, (x, y))
    y += 17
    _draw_progress_bar(
        screen,
        rect=pygame.Rect(x, y, content_width, 6),
        value=robot.hp if robot.alive else 0,
        maximum=robot.max_hp,
        fill_color=team_color if robot.alive else MUTED_COLOR,
    )
    y += 12

    if level_state is not None:
        current_level, experience, level_cap = level_state
        text_value = f"经验 {experience:g} · 等级 {current_level}/{level_cap}"
        screen.blit(small_font.render(text_value, True, TEXT_COLOR), (x, y))
        y += 19

    projectile_state = projectiles.get(robot.id)
    if projectile_state is not None:
        projectile, allowance = projectile_state
        screen.blit(
            small_font.render(f"发弹额度 {allowance} · {projectile}", True, TEXT_COLOR),
            (x, y),
        )
        y += 19

    heat_state = heat.get(robot.id)
    cooling_per_second = None
    effective_heat = getattr(match.ruleset, "_effective_heat_parameters", None)
    if callable(effective_heat):
        try:
            cooling_per_second = effective_heat(robot.id).cooling_per_second
        except KeyError:
            cooling_per_second = None
    if heat_state is not None:
        current, limit, locked, permanently_locked = heat_state
        lock_text = " · 永久禁射" if permanently_locked else " · 禁射" if locked else ""
        screen.blit(
            small_font.render(f"热量 {current:g}/{limit:g}{lock_text}", True, TEXT_COLOR),
            (x, y),
        )
        y += 17
        _draw_progress_bar(
            screen,
            rect=pygame.Rect(x, y, content_width, 5),
            value=current,
            maximum=limit,
            fill_color=WARNING_COLOR,
        )
        y += 9
    if cooling_per_second is not None:
        screen.blit(
            small_font.render(f"冷却 {cooling_per_second:g}/秒", True, MUTED_COLOR),
            (x, y),
        )
        y += 19

    chassis_state = chassis.get(robot.id)
    power_off_remaining = 0.0
    if chassis_state is not None:
        buffer, maximum, power, limit, power_off_remaining = chassis_state
        buffer_surface = small_font.render(
            f"缓冲 {buffer:g}/{maximum:g}",
            True,
            TEXT_COLOR,
        )
        power_surface = small_font.render(
            f"功率 {power:g}/{limit:g}W",
            True,
            MUTED_COLOR,
        )
        if buffer_surface.get_width() + power_surface.get_width() + 8 <= content_width:
            screen.blit(buffer_surface, (x, y))
            screen.blit(power_surface, (x + buffer_surface.get_width() + 8, y))
            y += 16
        else:
            screen.blit(buffer_surface, (x, y))
            y += 18
            screen.blit(power_surface, (x, y))
            y += 18
        _draw_progress_bar(
            screen,
            rect=pygame.Rect(x, y, content_width, 5),
            value=buffer,
            maximum=maximum,
            fill_color=SHIELD_COLOR,
        )
        y += 10
        if power_off_remaining > 0:
            screen.blit(
                small_font.render(f"底盘断电 {power_off_remaining:.1f}s", True, WARNING_COLOR),
                (x, y),
            )
            y += 19

    if robot.type == "drone":
        active, remaining = drone_support.get(robot.id, (False, 0.0))
        support_text = f"空中支援 {'执行中' if active else '停机坪'} · 可用 {remaining:.1f}s"
        screen.blit(
            micro_font.render(
                _fit_text_to_width(micro_font, support_text, content_width),
                True,
                SHIELD_COLOR if active else MUTED_COLOR,
            ),
            (x, y),
        )
        y += 17
        anti_drone = radar_anti_drone.get(robot.id)
        if anti_drone is not None:
            progress, threshold, lock_remaining, remaining_uses, illuminated = anti_drone
            state_text = (
                f"锁定 {lock_remaining:.1f}s"
                if lock_remaining > 0
                else "瞄准中"
                if illuminated
                else "待机"
            )
            radar_state_text = f"雷达 {state_text}"
            radar_detail_text = f"进度 {progress:g}/{threshold:g} · 剩余 {remaining_uses}"
            screen.blit(
                micro_font.render(radar_state_text, True, MUTED_COLOR),
                (x, y),
            )
            y += 15
            screen.blit(
                micro_font.render(
                    _fit_text_to_width(micro_font, radar_detail_text, content_width),
                    True,
                    MUTED_COLOR,
                ),
                (x, y),
            )
            y += 17

    energy_timers = _rmuc_energy_timer_labels(match, robot.team)
    if energy_timers:
        screen.blit(
            micro_font.render(
                _fit_text_to_width(
                    micro_font,
                    f"能量机制 {' · '.join(energy_timers)}",
                    content_width,
                ),
                True,
                SHIELD_COLOR,
            ),
            (x, y),
        )
        y += 17

    if robot.id in engineer_units:
        screen.blit(
            small_font.render(f"能量单元 {engineer_units[robot.id]}", True, RESOURCE_COLOR),
            (x, y),
        )
        y += 19
    if robot.id in reserves:
        screen.blit(
            small_font.render(f"堡垒储备 {reserves[robot.id]}", True, FORTRESS_COLOR),
            (x, y),
        )
        y += 19

    raw_status = statuses.get(robot.id, "")
    heat_locked = bool(heat_state and heat_state[2])
    permanently_locked = bool(heat_state and heat_state[3])
    invincible = robot.type != "drone" and robot.alive and not match.ruleset.can_receive_damage(robot)
    badges = status_badges(
        raw_status,
        invincible=invincible,
        heat_locked=heat_locked,
        permanently_locked=permanently_locked,
        power_off=power_off_remaining > 0,
    )
    if raw_status:
        raw_status_surface = small_font.render(f"状态 {raw_status}", True, MUTED_COLOR)
        if raw_status_surface.get_width() <= content_width:
            screen.blit(raw_status_surface, (x, min(y, rect.bottom - 20)))
            y += 19
    if badges and y < rect.bottom - 18:
        _draw_badges(
            screen,
            small_font,
            badges,
            x=x,
            y=y,
            max_width=content_width,
        )


def _draw_team_systems_card(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    micro_font: pygame.font.Font,
    match: Match,
    player_team: str,
    rect: pygame.Rect,
) -> None:
    pygame.draw.rect(screen, PANEL_SECTION, rect, border_radius=7)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=1, border_radius=7)
    lines = _rmuc_team_detail_lines(match, player_team)
    x = rect.x + 12
    y = rect.y + 10
    if not lines:
        return
    screen.blit(small_font.render("队伍态势", True, TEXT_COLOR), (x, y))
    y += 22
    for line in lines[1:]:
        if y > rect.bottom - 13:
            break
        color = TEXT_COLOR if line.startswith("科技核心") else MUTED_COLOR
        fitted_line = _fit_text_to_width(
            micro_font,
            line,
            rect.right - x - 10,
        )
        screen.blit(micro_font.render(fitted_line, True, color), (x, y))
        y += 14


def _fit_text_to_width(
    font: pygame.font.Font,
    text: str,
    max_width: int,
) -> str:
    if font.size(text)[0] <= max_width:
        return text
    suffix = "…"
    fitted = text
    while fitted and font.size(fitted + suffix)[0] > max_width:
        fitted = fitted[:-1]
    return f"{fitted}{suffix}" if fitted else suffix


def _draw_context_controls(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    selected_types: set[str],
    rect: pygame.Rect,
    *,
    debug_geometry: bool,
) -> None:
    pygame.draw.rect(screen, PANEL_SECTION, rect, border_radius=7)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=1, border_radius=7)
    x = rect.x + 11
    y = rect.y + 8
    title = "调试几何：开启" if debug_geometry else "观战操作"
    title_color = SELECTION_COLOR if debug_geometry else MUTED_COLOR
    screen.blit(small_font.render(title, True, title_color), (x, y))
    y += 23
    rows = contextual_controls(selected_types, spectator=True)
    compact_keys = {"Shift+左键": "Shift"}
    compact_actions = {
        "查看单位": "查看",
        "多选查看": "多选",
        "框选查看": "框选",
        "调试几何": "调试",
        "重新开始": "重开",
    }
    column_width = (rect.width - 22) // 2
    for index, (key, action, enabled) in enumerate(rows[:6]):
        column = index % 2
        row = index // 2
        color = TEXT_COLOR if enabled else MUTED_COLOR
        item_x = x + column * column_width
        item_y = y + row * 16
        key_text = compact_keys.get(key, key)
        action_text = compact_actions.get(action, action)
        screen.blit(
            small_font.render(f"{key_text} {action_text}", True, color),
            (item_x, item_y),
        )


def _draw_rmuc_panel(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    micro_font: pygame.font.Font,
    match: Match,
    player_team: str,
    selected_robot_ids: set[str],
    labels: dict[str, str],
    *,
    debug_geometry: bool,
) -> None:
    panel = pygame.Rect(*RMUC_PANEL_RECT)
    selected_count = sum(
        robot.id in selected_robot_ids
        for robot in match.robots
    )
    unit_rect, team_rect, controls_rect = _rmuc_panel_layout(
        panel,
        selected_count,
    )
    _draw_selected_unit_card(
        screen,
        small_font,
        micro_font,
        match,
        selected_robot_ids,
        labels,
        unit_rect,
    )
    _draw_team_systems_card(
        screen,
        small_font,
        micro_font,
        match,
        player_team,
        team_rect,
    )
    if debug_geometry:
        _draw_context_controls(
            screen,
            small_font,
            _selected_robot_types(match, selected_robot_ids),
            controls_rect,
            debug_geometry=True,
        )


def _draw_hud_structure_metric(
    screen: pygame.Surface,
    micro_font: pygame.font.Font,
    *,
    rect: pygame.Rect,
    label: str,
    hp: int,
    max_hp: int,
    color: tuple[int, int, int],
    status: str = "",
) -> None:
    label_surface = micro_font.render(
        f"{label} {hp}/{max_hp}",
        True,
        TEXT_COLOR,
    )
    screen.blit(label_surface, (rect.x + 10, rect.y))
    details: list[str] = []
    if "ARMOR" in status:
        details.append("装甲")
    shield = parse_virtual_shield(status)
    if shield > 0:
        details.append(f"盾 {shield}")
    defense = _defense_from_status(status)
    if defense is not None:
        details.append(f"防御 {defense}")
    if details:
        details_surface = micro_font.render(
            " · ".join(details),
            True,
            SHIELD_COLOR if shield > 0 or "ARMOR" in status else DEFENSE_ZONE_COLOR,
        )
        if details_surface.get_width() <= rect.width - label_surface.get_width() - 30:
            screen.blit(
                details_surface,
                (rect.right - 10 - details_surface.get_width(), rect.y),
            )
    _draw_progress_bar(
        screen,
        rect=pygame.Rect(rect.x + 10, rect.y + 14, rect.width - 20, 4),
        value=hp,
        maximum=max_hp,
        fill_color=color,
    )


def _rmuc_roster_robots(match: Match, team_id: str) -> list[object]:
    labels = _rmuc_robot_labels(match)
    order = {"hero": 0, "engineer": 1, "infantry": 2, "sentry": 3, "drone": 4}
    return sorted(
        (robot for robot in match.robots if robot.team == team_id),
        key=lambda robot: (
            order.get(robot.type, len(order)),
            labels.get(robot.id, robot.id),
        ),
    )


def _rmuc_energy_timer_labels(match: Match, team_id: str) -> tuple[str, ...]:
    display_state = match.ruleset.display_state
    if display_state is None:
        return ()
    names = {"small": "小能量", "large": "大能量"}
    return tuple(
        f"{names.get(mechanism, '能量')} {math.ceil(remaining)}s"
        for effect_team, mechanism, remaining
        in display_state.energy_mechanism_effect_timers
        if effect_team == team_id and remaining > 0
    )


def _rmuc_broadcast_tags(
    match: Match,
    robot,
    raw_status: str,
    heat_state: tuple[float, float, bool, bool] | None,
    drone_support: tuple[bool, float] | None,
    radar_state: tuple[float, float, float, int, bool] | None,
    visual_robot,
) -> tuple[BadgeSpec, ...]:
    if not robot.alive:
        return (BadgeSpec("阵亡", "danger"),)
    if visual_robot is not None and visual_robot.respawn_remaining > 0:
        return (BadgeSpec("复活", "shield"),)

    badges: list[BadgeSpec] = []
    if robot.type != "drone" and not match.ruleset.can_receive_damage(robot):
        badges.append(BadgeSpec("无敌", "shield"))
    if "VULN" in raw_status:
        badges.append(BadgeSpec("易伤", "danger"))
    if "FORT" in raw_status:
        badges.append(BadgeSpec("堡垒", "fortress"))
    if heat_state is not None and (heat_state[2] or heat_state[3]):
        badges.append(
            BadgeSpec(
                "永久禁射" if heat_state[3] else "禁射",
                "danger" if heat_state[3] else "warning",
            )
        )
    if radar_state is not None:
        progress, _threshold, lock_remaining, _remaining_uses, illuminated = radar_state
        if lock_remaining > 0:
            badges.append(BadgeSpec("雷达锁定", "warning"))
        elif illuminated or progress > 0:
            badges.append(BadgeSpec("雷达", "warning"))
    if robot.type == "drone" and drone_support is not None:
        badges.append(
            BadgeSpec(
                "空支 ON" if drone_support[0] else "空支待命",
                "shield" if drone_support[0] else "neutral",
            )
        )
    return tuple(badges)


def _draw_compact_badges(
    screen: pygame.Surface,
    micro_font: pygame.font.Font,
    badges: tuple[BadgeSpec, ...],
    *,
    x: int,
    y: int,
    max_width: int,
) -> None:
    cursor_x = x
    for index, badge in enumerate(badges):
        text_surface = micro_font.render(badge.text, True, TEXT_COLOR)
        width = text_surface.get_width() + 8
        if cursor_x + width > x + max_width:
            remaining = len(badges) - index
            overflow = micro_font.render(f"+{remaining}", True, MUTED_COLOR)
            if cursor_x + overflow.get_width() + 6 <= x + max_width:
                screen.blit(overflow, (cursor_x + 3, y + 1))
            break
        rect = pygame.Rect(cursor_x, y, width, 15)
        tone_color = _badge_color(badge.tone)
        pygame.draw.rect(screen, PANEL_SECTION, rect, border_radius=4)
        pygame.draw.rect(screen, tone_color, rect, width=1, border_radius=4)
        screen.blit(text_surface, text_surface.get_rect(center=rect.center))
        cursor_x += width + 3


def _rmuc_map_label_rect(
    label_surface: pygame.Surface,
    *,
    center: tuple[int, int],
    radius: int,
    field_rect: pygame.Rect,
    occupied_labels: list[pygame.Rect],
    other_robot_bodies: list[pygame.Rect],
) -> pygame.Rect:
    width = label_surface.get_width() + 10
    height = label_surface.get_height() + 4
    x, y = center
    gap = radius + 9
    candidates = (
        pygame.Rect(x - width // 2, y + gap, width, height),
        pygame.Rect(x - width // 2, y - gap - height, width, height),
        pygame.Rect(x + gap, y - height // 2, width, height),
        pygame.Rect(x - gap - width, y - height // 2, width, height),
        pygame.Rect(x + gap, y + gap, width, height),
        pygame.Rect(x - gap - width, y + gap, width, height),
        pygame.Rect(x + gap, y - gap - height, width, height),
        pygame.Rect(x - gap - width, y - gap - height, width, height),
    )
    default_center = candidates[0].center
    best_rect = candidates[0].copy()
    best_score: tuple[int, int, int] | None = None
    for index, candidate in enumerate(candidates):
        candidate = candidate.copy()
        candidate.clamp_ip(field_rect)
        label_collisions = sum(
            candidate.colliderect(occupied)
            for occupied in occupied_labels
        )
        body_collisions = sum(
            candidate.colliderect(body)
            for body in other_robot_bodies
        )
        displacement = (
            abs(candidate.centerx - default_center[0])
            + abs(candidate.centery - default_center[1])
        )
        score = (label_collisions, body_collisions, displacement + index)
        if best_score is None or score < best_score:
            best_rect = candidate
            best_score = score
    return best_rect


def _draw_rmuc_roster_tile(
    screen: pygame.Surface,
    micro_font: pygame.font.Font,
    match: Match,
    robot,
    label: str,
    rect: pygame.Rect,
    *,
    raw_status: str,
    heat_state: tuple[float, float, bool, bool] | None,
    drone_support: tuple[bool, float] | None,
    radar_state: tuple[float, float, float, int, bool] | None,
    visual_robot,
) -> None:
    color = _rmuc_team_color(match, robot.team)
    pygame.draw.rect(screen, PANEL_SECTION_ALT, rect, border_radius=4)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=1, border_radius=4)
    label_surface = micro_font.render(label, True, color)
    screen.blit(label_surface, (rect.x + 6, rect.y + 2))
    hp_text = (
        f"{robot.hp}/{robot.max_hp}"
        if robot.alive
        else f"0/{robot.max_hp}"
    )
    hp_surface = micro_font.render(hp_text, True, TEXT_COLOR if robot.alive else MUTED_COLOR)
    hp_x = rect.x + 6 + label_surface.get_width() + 5
    screen.blit(hp_surface, (hp_x, rect.y + 2))

    tags = _rmuc_broadcast_tags(
        match,
        robot,
        raw_status,
        heat_state,
        drone_support,
        radar_state,
        visual_robot,
    )
    tags_x = hp_x + hp_surface.get_width() + 5
    _draw_compact_badges(
        screen,
        micro_font,
        tags,
        x=tags_x,
        y=rect.y + 2,
        max_width=rect.right - 5 - tags_x,
    )

    bar_color = color if robot.alive else MUTED_COLOR
    _draw_progress_bar(
        screen,
        rect=pygame.Rect(rect.x + 6, rect.y + 18, rect.width - 12, 3),
        value=robot.hp if robot.alive else 0,
        maximum=robot.max_hp,
        fill_color=bar_color,
    )


def _draw_team_hud_card(
    screen: pygame.Surface,
    font: pygame.font.Font,
    micro_font: pygame.font.Font,
    *,
    rect: pygame.Rect,
    match: Match,
    team_id: str,
    name: str,
    base,
    outpost,
    structure_statuses: dict[str, tuple[int, int, str]],
    coins: int,
    color: tuple[int, int, int],
    align_right: bool = False,
    visual_state: CombatVisualState | None = None,
) -> None:
    pygame.draw.rect(screen, PANEL_BACKGROUND, rect, border_radius=7)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=1, border_radius=7)
    accent = pygame.Rect(rect.x, rect.y, rect.width, 3)
    pygame.draw.rect(screen, color, accent, border_radius=2)

    name_surface = font.render(name, True, color)
    resource_items = [f"金币 {coins}", *_rmuc_energy_timer_labels(match, team_id)]
    strategy = match.ai_team_strategy(team_id)
    if strategy is not None:
        resource_items.append(f"策略 {strategy}")
    resources = " · ".join(resource_items)
    resources_surface = micro_font.render(
        _fit_text_to_width(
            micro_font,
            resources,
            max(40, rect.width - name_surface.get_width() - 30),
        ),
        True,
        MUTED_COLOR,
    )
    if align_right:
        screen.blit(
            name_surface,
            (rect.right - 10 - name_surface.get_width(), rect.y + 5),
        )
        screen.blit(resources_surface, (rect.x + 10, rect.y + 8))
    else:
        screen.blit(name_surface, (rect.x + 10, rect.y + 5))
        screen.blit(resources_surface, (rect.right - 10 - resources_surface.get_width(), rect.y + 8))

    status_by_structure = {
        structure_id: status
        for structure_id, (_hp, _maximum, status) in structure_statuses.items()
    }
    base_hp, base_max_hp, _base_status = structure_statuses.get(
        base.id,
        (base.hp, base.max_hp, ""),
    )
    outpost_hp, outpost_max_hp, _outpost_status = structure_statuses.get(
        outpost.id,
        (outpost.hp, outpost.max_hp, ""),
    )
    _draw_hud_structure_metric(
        screen,
        micro_font,
        rect=pygame.Rect(rect.x, rect.y + 28, rect.width, 21),
        label="基地",
        hp=base_hp,
        max_hp=base_max_hp,
        color=color,
        status=status_by_structure.get(base.id, ""),
    )
    _draw_hud_structure_metric(
        screen,
        micro_font,
        rect=pygame.Rect(rect.x, rect.y + 50, rect.width, 21),
        label="前哨站",
        hp=outpost_hp,
        max_hp=outpost_max_hp,
        color=color,
        status=status_by_structure.get(outpost.id, ""),
    )

    display_state = match.ruleset.display_state
    statuses = dict(display_state.robot_statuses) if display_state is not None else {}
    heat_by_robot = {
        robot_id: (current, limit, locked, permanently_locked)
        for robot_id, current, limit, locked, permanently_locked
        in display_state.robot_shooting_heat
    } if display_state is not None else {}
    support_by_robot = {
        robot_id: (active, remaining)
        for robot_id, active, remaining in display_state.drone_air_support
    } if display_state is not None else {}
    radar_by_robot = {
        robot_id: (progress, threshold, lock_remaining, uses, illuminated)
        for (
            robot_id,
            _source_team,
            progress,
            threshold,
            lock_remaining,
            _activations,
            uses,
            illuminated,
        ) in display_state.radar_anti_drone
    } if display_state is not None else {}
    visual_robots = visual_state.robots if visual_state is not None else {}
    roster = _rmuc_roster_robots(match, team_id)
    labels = _rmuc_robot_labels(match)
    tile_gap = 6
    tile_width = (rect.width - 20 - tile_gap) // 2
    for index, robot in enumerate(roster[:6]):
        column = index % 2
        row = index // 2
        tile_rect = pygame.Rect(
            rect.x + 10 + column * (tile_width + tile_gap),
            rect.y + 74 + row * 27,
            tile_width,
            24,
        )
        _draw_rmuc_roster_tile(
            screen,
            micro_font,
            match,
            robot,
            labels.get(robot.id, robot.type[:1].upper()),
            tile_rect,
            raw_status=statuses.get(robot.id, ""),
            heat_state=heat_by_robot.get(robot.id),
            drone_support=support_by_robot.get(robot.id),
            radar_state=radar_by_robot.get(robot.id),
            visual_robot=visual_robots.get(robot.id),
        )


def _draw_rmuc_hud(
    screen: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    micro_font: pygame.font.Font,
    match: Match,
    player_team: str,
    opponent_team: str,
    *,
    visual_state: CombatVisualState | None = None,
) -> None:
    display_state = match.ruleset.display_state
    assert display_state is not None
    structures = {
        (structure.team, structure.type): structure for structure in match.structures
    }
    coins = dict(display_state.coins)
    player_base = structures[(player_team, "base")]
    player_outpost = structures[(player_team, "outpost")]
    opponent_base = structures[(opponent_team, "base")]
    opponent_outpost = structures[(opponent_team, "outpost")]

    player_name = (
        "TARS-Go"
        if player_team.startswith("tarsgo")
        else match.team_name(player_team)
    )
    opponent_name = (
        "对手"
        if opponent_team.startswith("opponent")
        else match.team_name(opponent_team)
    )
    player_color = _rmuc_team_color(match, player_team)
    opponent_color = _rmuc_team_color(match, opponent_team)
    structure_statuses = {
        structure_id: (hp, max_hp, status)
        for structure_id, hp, max_hp, status in display_state.structure_statuses
    }
    player_rect, timer_rect, opponent_rect = _rmuc_hud_rects(screen.get_width())
    _draw_team_hud_card(
        screen,
        small_font,
        micro_font,
        rect=player_rect,
        match=match,
        team_id=player_team,
        name=player_name,
        base=player_base,
        outpost=player_outpost,
        structure_statuses=structure_statuses,
        coins=coins.get(player_team, 0),
        color=player_color,
        visual_state=visual_state,
    )
    _draw_team_hud_card(
        screen,
        small_font,
        micro_font,
        rect=opponent_rect,
        match=match,
        team_id=opponent_team,
        name=opponent_name,
        base=opponent_base,
        outpost=opponent_outpost,
        structure_statuses=structure_statuses,
        coins=coins.get(opponent_team, 0),
        color=opponent_color,
        align_right=True,
        visual_state=visual_state,
    )

    timer = max(0, math.ceil(match.time_limit - match.elapsed_time))
    if match.finished:
        status = (
            f"{match.team_name(match.winner)} 获胜"
            if match.winner
            else "平局"
        )
    else:
        status = f"{timer // 60:02}:{timer % 60:02}"
    pygame.draw.rect(screen, PANEL_SECTION_ALT, timer_rect, border_radius=8)
    pygame.draw.rect(screen, PANEL_BORDER, timer_rect, width=1, border_radius=8)
    timer_surface = font.render(status, True, TEXT_COLOR)
    screen.blit(
        timer_surface,
        timer_surface.get_rect(center=(timer_rect.centerx, timer_rect.y + 72)),
    )
    match_label = small_font.render("比赛时间", True, MUTED_COLOR)
    screen.blit(
        match_label,
        match_label.get_rect(center=(timer_rect.centerx, timer_rect.y + 103)),
    )

    dart_by_team = {
        team_id: (ammo, _openings, phase, remaining, _target, result)
        for team_id, ammo, _openings, phase, remaining, _target, result
        in display_state.dart_system_statuses
    }
    dart_effects = {
        team_id: (obscured, _buff_suppression)
        for team_id, obscured, _buff_suppression
        in display_state.dart_effect_statuses
    }
    phase_labels = {
        "locked": "待解锁",
        "ready": "可开闸",
        "opening": "开闸",
        "firing": "发射期",
        "cooldown": "冷却",
        "closed": "机会用尽",
        "spent": "弹药耗尽",
    }
    for index, team_id in enumerate((player_team, opponent_team)):
        state = dart_by_team.get(team_id)
        if state is None:
            continue
        ammo, _openings, phase, remaining, _target, result = state
        obscured = dart_effects.get(team_id, (0.0, 0.0))[0]
        detail = result or (
            f"遮挡 {math.ceil(obscured)}s"
            if obscured > 0
            else f"{phase_labels.get(phase, phase)}"
            + (f" {math.ceil(remaining)}s" if remaining > 0 else "")
        )
        text = _fit_text_to_width(
            micro_font,
            f"飞镖 {ammo}/4 · {detail}",
            timer_rect.width - 12,
        )
        surface = micro_font.render(text, True, _rmuc_team_color(match, team_id))
        screen.blit(
            surface,
            surface.get_rect(
                center=(timer_rect.centerx, timer_rect.y + 127 + index * 17)
            ),
        )


def _blend_color(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    ratio = max(0.0, min(1.0, amount))
    return tuple(
        round(a + (b - a) * ratio)
        for a, b in zip(first, second)
    )


@lru_cache(maxsize=4)
def _rmuc_field_material(size: tuple[int, int]) -> pygame.Surface:
    """Build a subtle light falloff; it carries no field geometry semantics."""
    width, height = size
    material = pygame.Surface(size)
    denominator = max(1, height - 1)
    for y in range(height):
        lift = round(3 * math.sin(math.pi * y / denominator))
        color = tuple(min(255, channel + lift) for channel in ARENA_FLOOR)
        pygame.draw.line(material, color, (0, y), (width - 1, y))
    return material


def _draw_rmuc_battlefield(
    screen: pygame.Surface,
    field_rect: pygame.Rect,
) -> None:
    shadow_rect = field_rect.inflate(10, 10).move(0, 3)
    pygame.draw.rect(screen, ARENA_SHADOW, shadow_rect)
    floor = ASSET_MANAGER.render("field/floor-surface.png", size=field_rect.size)
    if floor is None:
        floor = _rmuc_field_material(field_rect.size)
    screen.blit(floor, field_rect.topleft)
    screen.fill(
        (148, 154, 158),
        field_rect,
        special_flags=pygame.BLEND_RGB_MULT,
    )
    pygame.draw.rect(screen, ARENA_EDGE, field_rect, width=2)
    inner_rect = field_rect.inflate(-5, -5)
    if inner_rect.width > 0 and inner_rect.height > 0:
        pygame.draw.rect(
            screen,
            _blend_color(ARENA_FLOOR_LIGHT, ARENA_FLOOR, 0.42),
            inner_rect,
            width=1,
        )


def _draw_rmuc_field_regions(
    screen: pygame.Surface,
    field_rect: pygame.Rect,
    viewport: Viewport,
    zones: tuple,
) -> tuple[str, ...]:
    """Tint confirmed region polygons as floor treatment, never as debug wireframes."""
    suffix_styles = {
        "start": ("start", 38, 12),
        "resource": ("resource", 24, 10),
        "assembly": ("assembly", 24, 10),
        "base-buff": ("base", 20, 32),
        "outpost-buff": ("outpost", 18, 24),
    }
    rendered: list[str] = []
    for zone in zones:
        suffix = zone.id.removeprefix("red-").removeprefix("blue-")
        spec = suffix_styles.get(suffix)
        if spec is None or len(zone.vertices) < 3:
            continue
        family, fill_alpha, edge_alpha = spec
        team_color = TEAM_RED_COLOR if zone.id.startswith("red-") else TEAM_BLUE_COLOR
        family_color = {
            "resource": RESOURCE_COLOR,
            "assembly": ASSEMBLY_COLOR,
        }.get(family, team_color)
        color = _blend_color(family_color, team_color, 0.5)
        points = tuple(
            tuple(round(value) for value in viewport.world_to_screen(point))
            for point in zone.vertices
        )
        left = min(point[0] for point in points)
        top = min(point[1] for point in points)
        right = max(point[0] for point in points)
        bottom = max(point[1] for point in points)
        bounds = pygame.Rect(
            left,
            top,
            max(1, right - left + 1),
            max(1, bottom - top + 1),
        )
        if not bounds.colliderect(field_rect):
            continue
        local_points = tuple((x - left, y - top) for x, y in points)
        layer = pygame.Surface(bounds.size, pygame.SRCALPHA)
        pygame.draw.polygon(layer, (*color, fill_alpha), local_points)

        if family in {"start", "resource"}:
            pattern = pygame.Surface(bounds.size, pygame.SRCALPHA)
            step = 22 if family == "start" else 26
            for offset in range(-bounds.height, bounds.width + bounds.height, step):
                pygame.draw.line(
                    pattern,
                    (*_blend_color(color, TEXT_COLOR, 0.28), 9),
                    (offset, bounds.height),
                    (offset + bounds.height, 0),
                    width=1,
                )
            mask = pygame.mask.from_surface(layer, threshold=0)
            pattern.blit(
                mask.to_surface(
                    setcolor=(255, 255, 255, 255),
                    unsetcolor=(255, 255, 255, 0),
                ),
                (0, 0),
                special_flags=pygame.BLEND_RGBA_MULT,
            )
            layer.blit(pattern, (0, 0))
        elif family == "assembly":
            center = (bounds.width // 2, bounds.height // 2)
            radius = max(4, min(bounds.width, bounds.height) // 4)
            pygame.draw.circle(layer, (*color, 16), center, radius, width=1)

        if edge_alpha:
            pygame.draw.polygon(layer, (*color, edge_alpha), local_points, width=1)
        old_clip = screen.get_clip()
        screen.set_clip(field_rect)
        screen.blit(layer, bounds.topleft)
        screen.set_clip(old_clip)
        rendered.append(zone.id)
    return tuple(rendered)


def _draw_rmuc_terrain(
    screen: pygame.Surface,
    legend_font: pygame.font.Font,
    field_rect: pygame.Rect,
    viewport: Viewport,
    *,
    terrain_features: tuple,
    terrain_connections: tuple,
    zones: tuple,
    debug_geometry: bool = True,
) -> tuple[tuple[str, tuple[int, int]], ...]:
    """Draw symbolic terrain cues only; never render their anchor as a footprint."""
    markers = terrain_visual_markers(
        terrain_features,
        terrain_connections,
        zones,
    )
    palette = {
        "surface": (115, 133, 137),
        "elevated": (137, 147, 121),
        "ramp": (151, 132, 108),
        "tunnel": (118, 137, 153),
    }
    rendered: list[tuple[str, tuple[int, int]]] = []
    for marker in markers:
        center = tuple(
            round(value)
            for value in viewport.world_to_screen(marker.center)
        )
        if not field_rect.collidepoint(center):
            continue
        color = palette[marker.kind]
        if not debug_geometry:
            if marker.kind == "surface":
                # A restrained road-lane stamp at the confirmed symbolic
                # anchor. It intentionally does not imply a road footprint.
                marking = pygame.Surface((18, 12), pygame.SRCALPHA)
                road_color = _blend_color(color, TEXT_COLOR, 0.15)
                pygame.draw.line(
                    marking,
                    (*road_color, 88),
                    (1, 3),
                    (16, 3),
                    width=1,
                )
                pygame.draw.line(
                    marking,
                    (*road_color, 88),
                    (1, 8),
                    (16, 8),
                    width=1,
                )
                screen.blit(marking, (center[0] - 9, center[1] - 6))
                rendered.append((marker.kind, center))
            continue
        if debug_geometry:
            pygame.draw.circle(screen, ARENA_SHADOW, (center[0] + 1, center[1] + 2), 13)
            pygame.draw.circle(screen, ARENA_FLOOR_DARK, center, 12)
            pygame.draw.circle(screen, color, center, 12, width=1)
        if marker.kind == "surface":
            pygame.draw.line(
                screen,
                color,
                (center[0] - 5, center[1] - 2),
                (center[0] + 5, center[1] - 2),
                width=2,
            )
            pygame.draw.line(
                screen,
                color,
                (center[0] - 5, center[1] + 3),
                (center[0] + 5, center[1] + 3),
                width=2 if debug_geometry else 1,
            )
        elif marker.kind == "elevated":
            pygame.draw.polygon(
                screen,
                color,
                (
                    (center[0] - 6, center[1]),
                    (center[0] - 3, center[1] - 4),
                    (center[0] + 3, center[1] - 4),
                    (center[0] + 6, center[1]),
                    (center[0] + 3, center[1] + 4),
                    (center[0] - 3, center[1] + 4),
                ),
                width=1,
            )
            pygame.draw.line(
                screen,
                color,
                (center[0] - 3, center[1]),
                (center[0] + 3, center[1]),
                width=1,
            )
        elif marker.kind == "ramp":
            pygame.draw.line(
                screen,
                color,
                (center[0] - 5, center[1] + 3),
                (center[0] + 4, center[1] - 3),
                width=2,
            )
            pygame.draw.line(
                screen,
                color,
                (center[0] - 5, center[1] + 5),
                (center[0] + 4, center[1] - 1),
                width=1,
            )
        else:
            arch = pygame.Rect(center[0] - 5, center[1] - 5, 10, 11)
            pygame.draw.arc(screen, color, arch, 0.0, math.pi, width=2)
            pygame.draw.line(
                screen,
                color,
                (center[0] - 5, center[1]),
                (center[0] - 5, center[1] + 4),
                width=2,
            )
            pygame.draw.line(
                screen,
                color,
                (center[0] + 5, center[1]),
                (center[0] + 5, center[1] + 4),
                width=2,
            )
        rendered.append((marker.kind, center))

    if rendered and debug_geometry:
        labels = {
            "surface": "路面",
            "elevated": "高地",
            "ramp": "坡面",
            "tunnel": "隧道",
        }
        kinds = {kind for kind, _center in rendered}
        x = field_rect.left + 11
        y = field_rect.bottom - 22
        for kind in ("surface", "elevated", "ramp", "tunnel"):
            if kind not in kinds:
                continue
            color = palette[kind]
            pygame.draw.circle(screen, color, (x + 3, y + 8), 3)
            text = legend_font.render(
                labels[kind],
                True,
                _blend_color(color, ARENA_FLOOR, 0.25),
            )
            screen.blit(text, (x + 10, y))
            x += text.get_width() + 27
    return tuple(rendered)


def _draw_rmuc_obstacle(
    screen: pygame.Surface,
    rect: pygame.Rect,
) -> None:
    shadow = rect.move(3, 4)
    pygame.draw.rect(screen, ARENA_SHADOW, shadow, border_radius=4)
    pygame.draw.rect(screen, (63, 74, 79), rect, border_radius=4)
    pygame.draw.rect(screen, (92, 104, 108), rect, width=1, border_radius=4)
    highlight = pygame.Rect(rect.x + 3, rect.y + 3, max(0, rect.width - 6), 2)
    if highlight.width > 0:
        pygame.draw.rect(screen, (118, 129, 131), highlight, border_radius=1)
    if rect.width >= 18 and rect.height >= 18:
        inset = rect.inflate(-10, -10)
        pygame.draw.rect(screen, (48, 59, 64), inset, width=1, border_radius=3)


def _zone_family_color(family: str) -> tuple[int, int, int]:
    return {
        "resource": RESOURCE_COLOR,
        "assembly": ASSEMBLY_COLOR,
        "supply": PLAYER_COLOR,
        "fortress": FORTRESS_COLOR,
        "defense": DEFENSE_ZONE_COLOR,
        "central": DEFENSE_ZONE_COLOR,
        "rebuild": WARNING_COLOR,
    }.get(family, ZONE_COLOR)


def _draw_zone_symbol(
    screen: pygame.Surface,
    *,
    center: tuple[int, int],
    family: str,
    color: tuple[int, int, int],
) -> None:
    if family == "supply":
        pygame.draw.line(
            screen,
            color,
            (center[0] - 6, center[1]),
            (center[0] + 6, center[1]),
            width=2,
        )
        pygame.draw.line(
            screen,
            color,
            (center[0], center[1] - 6),
            (center[0], center[1] + 6),
            width=2,
        )
    elif family == "resource":
        pygame.draw.polygon(
            screen,
            color,
            [
                (center[0], center[1] - 7),
                (center[0] + 7, center[1]),
                (center[0], center[1] + 7),
                (center[0] - 7, center[1]),
            ],
            width=2,
        )
    elif family == "assembly":
        pygame.draw.circle(screen, color, center, 6, width=2)
        for angle in (0, math.pi / 2):
            dx = round(math.cos(angle) * 10)
            dy = round(math.sin(angle) * 10)
            pygame.draw.line(
                screen,
                color,
                (center[0] - dx, center[1] - dy),
                (center[0] + dx, center[1] + dy),
                width=2,
            )
    elif family == "fortress":
        pygame.draw.rect(
            screen,
            color,
            pygame.Rect(center[0] - 8, center[1] - 7, 16, 14),
            width=2,
        )
        pygame.draw.line(
            screen,
            color,
            (center[0] - 5, center[1]),
            (center[0] + 5, center[1]),
            width=2,
        )
    elif family in {"defense", "central"}:
        pygame.draw.polygon(
            screen,
            color,
            [
                (center[0], center[1] - 8),
                (center[0] + 7, center[1] - 4),
                (center[0] + 5, center[1] + 6),
                (center[0], center[1] + 9),
                (center[0] - 5, center[1] + 6),
                (center[0] - 7, center[1] - 4),
            ],
            width=2,
        )
    elif family == "rebuild":
        pygame.draw.circle(screen, color, center, 7, width=2)


def _draw_zone_corner_frame(
    screen: pygame.Surface,
    rect: pygame.Rect,
    color: tuple[int, int, int],
    *,
    active: bool,
) -> None:
    length = min(12, max(5, min(rect.width, rect.height) // 4))
    width = 2 if active else 1
    corners = (
        (rect.left, rect.top, 1, 1),
        (rect.right - 1, rect.top, -1, 1),
        (rect.left, rect.bottom - 1, 1, -1),
        (rect.right - 1, rect.bottom - 1, -1, -1),
    )
    for x, y, sx, sy in corners:
        pygame.draw.line(screen, color, (x, y), (x + sx * length, y), width=width)
        pygame.draw.line(screen, color, (x, y), (x, y + sy * length), width=width)


def _draw_zone_pattern(
    screen: pygame.Surface,
    rect: pygame.Rect,
    *,
    family: str,
    color: tuple[int, int, int],
    active: bool,
) -> None:
    if rect.width < 12 or rect.height < 12:
        return
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    alpha = 26 if active else 8
    local = layer.get_rect()
    if family == "resource":
        step = 14
        for offset in range(-local.height, local.width, step):
            pygame.draw.line(
                layer,
                (*color, alpha),
                (offset, local.bottom),
                (offset + local.height, local.top),
                width=1,
            )
    elif family == "assembly":
        radius = max(5, min(local.width, local.height) // 4)
        pygame.draw.circle(layer, (*color, alpha + 16), local.center, radius, width=1)
        pygame.draw.circle(layer, (*color, alpha), local.center, max(3, radius // 2), width=1)
    elif family == "supply":
        arm = max(5, min(local.width, local.height) // 5)
        cx, cy = local.center
        pygame.draw.rect(
            layer,
            (*color, alpha),
            pygame.Rect(cx - arm, cy - 2, arm * 2, 4),
            border_radius=2,
        )
        pygame.draw.rect(
            layer,
            (*color, alpha),
            pygame.Rect(cx - 2, cy - arm, 4, arm * 2),
            border_radius=2,
        )
    elif family == "fortress":
        block = max(4, min(9, local.width // 6))
        for x in range(5, max(6, local.width - block), block * 2):
            pygame.draw.rect(
                layer,
                (*color, alpha),
                pygame.Rect(x, 4, block, 4),
            )
            pygame.draw.rect(
                layer,
                (*color, alpha),
                pygame.Rect(x, max(4, local.height - 8), block, 4),
            )
    elif family == "central":
        radius = max(8, min(local.width, local.height) // 3)
        pygame.draw.circle(layer, (*color, alpha), local.center, radius, width=1)
        pygame.draw.line(
            layer,
            (*color, alpha),
            (local.centerx - radius, local.centery),
            (local.centerx + radius, local.centery),
        )
    elif family in {"defense", "rebuild"}:
        inset = local.inflate(-10, -10)
        if inset.width > 0 and inset.height > 0:
            pygame.draw.rect(layer, (*color, alpha), inset, width=1, border_radius=4)
    screen.blit(layer, rect.topleft)


def _draw_rmuc_zone(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    zone_rect: pygame.Rect,
    *,
    zone_id: str,
    polygon_points: tuple[tuple[int, int], ...] = (),
    selected_types: set[str],
    occupied_by_selected: bool,
    targeted_by_selected: bool,
    animation_time: float,
) -> None:
    style = zone_visual_style(
        zone_id,
        selected_robot_types=selected_types,
    )
    if style is None:
        return
    hovered = _screen_rect_is_hovered(zone_rect)
    emphasized = (
        style.emphasized
        or occupied_by_selected
        or targeted_by_selected
        or hovered
    )
    if not emphasized:
        return
    family_color = _zone_family_color(style.family)
    team_color = (
        TEAM_RED_COLOR
        if zone_id.startswith("red-")
        else TEAM_BLUE_COLOR
        if zone_id.startswith("blue-")
        else family_color
    )
    color = _blend_color(family_color, team_color, 0.32)
    pulse = 0.5 + 0.5 * math.sin(animation_time * 3.4)
    fill_alpha = 5 if not emphasized else round(18 + 6 * pulse)
    overlay = pygame.Surface(zone_rect.size, pygame.SRCALPHA)
    if polygon_points:
        local_points = tuple(
            (x - zone_rect.x, y - zone_rect.y)
            for x, y in polygon_points
        )
        pygame.draw.polygon(overlay, (*color, fill_alpha), local_points)
        screen.blit(overlay, zone_rect.topleft)
        pygame.draw.polygon(
            screen,
            (
                _blend_color(color, TEXT_COLOR, 0.20)
                if emphasized
                else _blend_color(color, ARENA_FLOOR, 0.40)
            ),
            polygon_points,
            width=2 if emphasized else 1,
        )
    else:
        pygame.draw.rect(
            overlay,
            (*color, fill_alpha),
            overlay.get_rect(),
            border_radius=5,
        )
        screen.blit(overlay, zone_rect.topleft)
        _draw_zone_pattern(
            screen,
            zone_rect,
            family=style.family,
            color=(color if emphasized else _blend_color(color, ARENA_FLOOR, 0.40)),
            active=emphasized,
        )
        _draw_zone_corner_frame(
            screen,
            zone_rect,
            color if emphasized else _blend_color(color, ARENA_FLOOR, 0.40),
            active=emphasized,
        )
        if emphasized:
            pygame.draw.rect(
                screen,
                _blend_color(color, TEXT_COLOR, 0.20),
                zone_rect.inflate(-3, -3),
                width=1,
                border_radius=4,
            )

    symbol_center = (
        zone_rect.centerx,
        zone_rect.centery - (7 if emphasized else 2),
    )
    _draw_zone_symbol(
        screen,
        center=symbol_center,
        family=style.family,
        color=color if emphasized else _blend_color(color, ARENA_FLOOR, 0.40),
    )
    if _should_show_zone_label(
        emphasized=style.emphasized,
        occupied_by_selected=occupied_by_selected,
        hovered=hovered,
        targeted_by_selected=targeted_by_selected,
    ):
        label_color = (
            _blend_color(color, TEXT_COLOR, 0.20)
            if emphasized
            else _blend_color(color, TEXT_COLOR, 0.32)
        )
        label_surface = small_font.render(style.label, True, label_color)
        screen.blit(
            label_surface,
            label_surface.get_rect(
                center=(zone_rect.centerx, zone_rect.centery + 12)
            ),
        )


def _draw_virtual_shield(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    *,
    center: tuple[int, int],
    radius: int,
    shield: int,
    animation_time: float,
    show_label: bool = False,
) -> None:
    if shield <= 0:
        return
    pulse = 1 + round(2 * (0.5 + 0.5 * math.sin(animation_time * 2.8)))
    glow_radius = radius + 10 + pulse
    glow = pygame.Surface((glow_radius * 2 + 8, glow_radius * 2 + 8), pygame.SRCALPHA)
    glow_center = (glow.get_width() // 2, glow.get_height() // 2)
    pygame.draw.circle(
        glow,
        (*SHIELD_COLOR, 22),
        glow_center,
        glow_radius + 2,
    )
    pygame.draw.circle(
        glow,
        (*SHIELD_COLOR, 86),
        glow_center,
        glow_radius,
        width=2,
    )
    screen.blit(        glow,
        (
            center[0] - glow_center[0],
            center[1] - glow_center[1],
        ),
    )
    if show_label:
        label = small_font.render(f"护盾 {shield}", True, SHIELD_COLOR)
        screen.blit(
            label,
            label.get_rect(center=(center[0], center[1] - radius - 19)),
        )


def _draw_rmuc_structure(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    *,
    structure_type: str,
    center: tuple[int, int],
    color: tuple[int, int, int],
    alive: bool,
    hp: int,
    max_hp: int,
    status: str,
    animation_time: float,
    debug_geometry: bool,
    footprint_size: tuple[int, int] | None = None,
    footprint_points: tuple[tuple[int, int], ...] = (),
    impact_remaining: float = 0.0,
    impact_caliber: str = "17mm",
    shield_impact_remaining: float = 0.0,
) -> int:
    profile = structure_visual_profile(structure_type)
    draw_color = color if alive else _blend_color(MUTED_COLOR, ARENA_FLOOR_DARK, 0.38)
    if alive and impact_remaining > 0:
        flash_mix = 0.68 if impact_caliber == "42mm" else 0.38
        draw_color = _blend_color(draw_color, IMPACT_COLOR, flash_mix)
    body_color = _blend_color(draw_color, ARENA_FLOOR_DARK, 0.58)
    edge_color = draw_color if alive else _blend_color(MUTED_COLOR, ARENA_GRID, 0.35)
    body_width, body_height = structure_display_size(
        structure_type,
        footprint_size,
    )
    half_width = max(1, body_width // 2)
    half_height = max(1, body_height // 2)
    size = max(half_width, half_height)

    structure_asset = {
        "base": "structures/base.png",
        "outpost": "structures/outpost.png",
    }.get(structure_type)
    sprite = (
        ASSET_MANAGER.render(
            structure_asset,
            size=(body_width, body_height),
        )
        if structure_asset is not None
        else None
    )
    if sprite is None:
        shadow = pygame.Surface((body_width + 16, body_height + 16), pygame.SRCALPHA)
        shadow_center = (shadow.get_width() // 2 + 2, shadow.get_height() // 2 + 3)
        pygame.draw.ellipse(
            shadow,
            (*ARENA_SHADOW, 118),
            pygame.Rect(
                shadow_center[0] - half_width - 3,
                shadow_center[1] - half_height - 3,
                body_width + 6,
                body_height + 6,
            ),
        )
        screen.blit(
            shadow,
            (
                center[0] - shadow.get_width() // 2,
                center[1] - shadow.get_height() // 2,
            ),
        )

        if structure_type == "base":
            diagonal_x = round(half_width * 0.68)
            diagonal_y = round(half_height * 0.68)
            outer = list(footprint_points) or [
                (center[0], center[1] - half_height),
                (center[0] + diagonal_x, center[1] - diagonal_y),
                (center[0] + half_width, center[1]),
                (center[0] + diagonal_x, center[1] + diagonal_y),
                (center[0], center[1] + half_height),
                (center[0] - diagonal_x, center[1] + diagonal_y),
                (center[0] - half_width, center[1]),
                (center[0] - diagonal_x, center[1] - diagonal_y),
            ]
            inset = max(0.0, min(0.45, 6 / max(1, size)))
            inner = [
                (
                    round(center[0] + (x - center[0]) * (1 - inset)),
                    round(center[1] + (y - center[1]) * (1 - inset)),
                )
                for x, y in outer
            ]
            pygame.draw.polygon(screen, ROBOT_OUTLINE, outer)
            pygame.draw.polygon(screen, body_color, inner)
            pygame.draw.polygon(screen, edge_color, inner, width=2)
            for angle in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
                start = (
                    center[0] + round(math.cos(angle) * (profile.core_radius + 4)),
                    center[1] + round(math.sin(angle) * (profile.core_radius + 4)),
                )
                end = (
                    center[0] + round(math.cos(angle) * (half_width - 9)),
                    center[1] + round(math.sin(angle) * (half_height - 9)),
                )
                pygame.draw.line(screen, edge_color, start, end, width=2)
            pygame.draw.circle(screen, ROBOT_OUTLINE, center, profile.core_radius + 3)
            pygame.draw.circle(screen, body_color, center, profile.core_radius)
            pygame.draw.circle(
                screen,
                _blend_color(body_color, TEXT_COLOR, 0.14),
                (center[0] - 2, center[1] - 2),
                max(2, profile.core_radius // 3),
            )
        else:
            body_rect = pygame.Rect(
                center[0] - half_width,
                center[1] - half_height,
                body_width,
                body_height,
            )
            pygame.draw.ellipse(screen, ROBOT_OUTLINE, body_rect)
            inner_rect = body_rect.inflate(-4, -4)
            if inner_rect.width > 0 and inner_rect.height > 0:
                pygame.draw.ellipse(screen, body_color, inner_rect)
            pygame.draw.ellipse(screen, edge_color, body_rect, width=2)
            inner_rect = body_rect.inflate(-12, -12)
            if inner_rect.width > 0 and inner_rect.height > 0:
                pygame.draw.ellipse(screen, ARENA_FLOOR_DARK, inner_rect, width=2)
            for angle in (
                0,
                math.pi / 4,
                math.pi / 2,
                3 * math.pi / 4,
                math.pi,
                5 * math.pi / 4,
                3 * math.pi / 2,
                7 * math.pi / 4,
            ):
                inner = (
                    center[0] + round(math.cos(angle) * (profile.core_radius + 3)),
                    center[1] + round(math.sin(angle) * (profile.core_radius + 3)),
                )
                outer = (
                    center[0] + round(math.cos(angle) * (half_width - 5)),
                    center[1] + round(math.sin(angle) * (half_height - 5)),
                )
                pygame.draw.line(screen, edge_color, inner, outer, width=1)
            pygame.draw.circle(screen, ROBOT_OUTLINE, center, profile.core_radius + 2)
            pygame.draw.circle(
                screen,
                _blend_color(body_color, edge_color, 0.12),
                center,
                profile.core_radius,
            )
            sensor_offset = max(2, profile.core_radius // 3)
            for side in (-1, 1):
                lens_center = (center[0] + side * sensor_offset, center[1])
                pygame.draw.circle(screen, ROBOT_OUTLINE, lens_center, 2)
                pygame.draw.circle(screen, ARENA_GRID, lens_center, 1)
    else:
        screen.blit(sprite, sprite.get_rect(center=center))
        if debug_geometry:
            if footprint_points:
                pygame.draw.polygon(
                    screen,
                    SELECTION_COLOR,
                    footprint_points,
                    width=1,
                )
            elif footprint_size is not None:
                geometry_rect = pygame.Rect(
                    center[0] - footprint_size[0] // 2,
                    center[1] - footprint_size[1] // 2,
                    footprint_size[0],
                    footprint_size[1],
                )
                pygame.draw.ellipse(
                    screen,
                    SELECTION_COLOR,
                    geometry_rect,
                    width=1,
                )

    if alive:
        structure_lights = {
            "base": (
                (-0.34, -0.37, "v"),
                (0.34, -0.37, "v"),
                (-0.34, 0.37, "v"),
                (0.34, 0.37, "v"),
            ),
            "outpost": (
                (0.0, -0.40, "h"),
                (0.40, 0.0, "v"),
                (0.0, 0.40, "h"),
                (-0.40, 0.0, "v"),
            ),
        }.get(structure_type, ())
        _draw_rmuc_team_led_overlay(
            screen,
            center=center,
            size=(body_width, body_height),
            angle=0.0,
            lights=structure_lights,
            color=color,
        )

    if not alive:
        crack = max(6, profile.core_radius + 3)
        pygame.draw.line(
            screen,
            ARENA_SHADOW,
            (center[0] - crack, center[1] - crack),
            (center[0] + crack, center[1] + crack),
            width=2,
        )
        pygame.draw.line(
            screen,
            ARENA_SHADOW,
            (center[0] + crack, center[1] - crack),
            (center[0] - crack, center[1] + crack),
            width=2,
        )

    hovered = _screen_rect_is_hovered(
        pygame.Rect(
            center[0] - half_width - 8,
            center[1] - half_height - 8,
            body_width + 16,
            body_height + 16,
        )
    )
    shield = parse_virtual_shield(status) if structure_type == "base" else 0
    _draw_virtual_shield(
        screen,
        small_font,
        center=center,
        radius=size,
        shield=shield,
        animation_time=animation_time,
        show_label=hovered or debug_geometry,
    )
    if structure_type == "base" and shield_impact_remaining > 0:
        progress = 1.0 - min(1.0, shield_impact_remaining / 0.20)
        impact_radius = size + 9 + round(progress * 8)
        pygame.draw.circle(
            screen,
            SHIELD_COLOR,
            center,
            impact_radius,
            width=3,
        )
        for angle in (-0.55, -0.18, 0.22, 0.58):
            start = (
                center[0] + round(math.cos(angle) * (size + 4)),
                center[1] + round(math.sin(angle) * (size + 4)),
            )
            end = (
                center[0] + round(math.cos(angle) * (impact_radius + 5)),
                center[1] + round(math.sin(angle) * (impact_radius + 5)),
            )
            pygame.draw.line(screen, SHIELD_COLOR, start, end, width=2)
    elif impact_remaining > 0:
        ring_radius = size + (7 if impact_caliber == "42mm" else 4)
        pygame.draw.circle(
            screen,
            IMPACT_COLOR,
            center,
            ring_radius,
            width=3 if impact_caliber == "42mm" else 2,
        )

    bar_width = body_width + 14
    bar_rect = pygame.Rect(
        center[0] - bar_width // 2,
        center[1] + half_height + 10,
        bar_width,
        7,
    )
    _draw_progress_bar(
        screen,
        rect=bar_rect,
        value=hp,
        maximum=max_hp,
        fill_color=HP_COLOR if alive else MUTED_COLOR,
    )
    if hovered or debug_geometry:
        label = "基地" if structure_type == "base" else "前哨站"
        label_surface = small_font.render(
            f"{label} {hp}",
            True,
            TEXT_COLOR if alive else MUTED_COLOR,
        )
        screen.blit(
            label_surface,
            label_surface.get_rect(
                center=(center[0], bar_rect.bottom + 10)
            ),
        )
    if debug_geometry and status:
        debug_surface = small_font.render(status, True, MUTED_COLOR)
        screen.blit(
            debug_surface,
            debug_surface.get_rect(
                center=(center[0], bar_rect.bottom + 26)
            ),
        )
    return size


def _rotate_point(
    center: tuple[int, int],
    local: tuple[float, float],
    angle: float,
) -> tuple[int, int]:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        round(center[0] + local[0] * cosine - local[1] * sine),
        round(center[1] + local[0] * sine + local[1] * cosine),
    )


def _draw_selection_feedback(
    screen: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    animation_time: float,
) -> None:
    pulse = round(2.0 * math.sin(animation_time * 6.0))
    ring_radius = radius + 8 + pulse
    pygame.draw.circle(screen, SELECTION_COLOR, center, ring_radius, width=2)
    bracket = 7
    offset = ring_radius + 3
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        corner = (center[0] + sx * offset, center[1] + sy * offset)
        pygame.draw.line(
            screen,
            SELECTION_COLOR,
            corner,
            (corner[0] - sx * bracket, corner[1]),
            width=2,
        )
        pygame.draw.line(
            screen,
            SELECTION_COLOR,
            corner,
            (corner[0], corner[1] - sy * bracket),
            width=2,
        )


def _draw_robot_lifecycle_effects(
    screen: pygame.Surface,
    *,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    alive: bool,
    destroy_remaining: float,
    destroy_progress: float,
    respawn_remaining: float,
    respawn_progress: float,
) -> None:
    if destroy_remaining > 0:
        burst = radius + 6 + round(18 * destroy_progress)
        for index in range(8):
            angle = index * math.tau / 8 + 0.22
            inner = radius * (0.45 + 0.10 * (index % 2))
            start = (
                center[0] + round(math.cos(angle) * inner),
                center[1] + round(math.sin(angle) * inner),
            )
            end = (
                center[0] + round(math.cos(angle) * burst),
                center[1] + round(math.sin(angle) * burst),
            )
            spark_color = IMPACT_COLOR if index % 2 == 0 else WARNING_COLOR
            pygame.draw.line(screen, spark_color, start, end, width=2)
        core_radius = max(2, round(8 * (1.0 - destroy_progress)))
        pygame.draw.circle(screen, IMPACT_COLOR, center, core_radius)
    elif not alive:
        wreck = max(5, radius // 2)
        pygame.draw.line(
            screen,
            ROBOT_OUTLINE,
            (center[0] - wreck, center[1] - wreck),
            (center[0] + wreck, center[1] + wreck),
            width=2,
        )
        pygame.draw.line(
            screen,
            ROBOT_OUTLINE,
            (center[0] + wreck, center[1] - wreck),
            (center[0] - wreck, center[1] + wreck),
            width=2,
        )

    if respawn_remaining > 0 and alive:
        layer_radius = radius + 16
        layer = pygame.Surface(
            (layer_radius * 2 + 6, layer_radius * 2 + 6),
            pygame.SRCALPHA,
        )
        local_center = (layer.get_width() // 2, layer.get_height() // 2)
        alpha = round(55 + 70 * (1.0 - respawn_progress))
        pygame.draw.circle(
            layer,
            (*SHIELD_COLOR, alpha),
            local_center,
            radius + 7,
            width=2,
        )
        outer = radius + 13 - round(5 * respawn_progress)
        pygame.draw.circle(
            layer,
            (*color, max(35, alpha - 25)),
            local_center,
            outer,
            width=1,
        )
        scan_y = round(
            local_center[1] - radius
            + min(1.0, respawn_progress) * radius * 2
        )
        pygame.draw.line(
            layer,
            (*SHIELD_COLOR, 150),
            (local_center[0] - radius, scan_y),
            (local_center[0] + radius, scan_y),
            width=2,
        )
        screen.blit(
            layer,
            (
                center[0] - local_center[0],
                center[1] - local_center[1],
            ),
        )


_RMUC_ROBOT_SPRITE_PARTS = {
    "hero": ("hero-chassis.png", "hero-turret.png"),
    "engineer": ("engineer.png",),
    "infantry": ("infantry-chassis.png", "infantry-turret.png"),
    "sentry": ("sentry-chassis.png", "sentry-turret.png"),
    "drone": ("drone.png",),
}
_RMUC_ROBOT_SPRITE_SIZES = {
    "hero": ((50, 34), (66, 38)),
    "engineer": ((70, 36),),
    "infantry": ((34, 26), (42, 28)),
    "sentry": ((58, 38), (68, 40)),
    "drone": ((48, 48),),
}
_RMUC_ROBOT_LED_LAYOUTS = {
    "hero": (
        ((-0.36, 0.0, "v"), (0.36, 0.0, "v")),
        ((-0.28, -0.08, "v"), (0.28, -0.08, "v")),
    ),
    "engineer": (
        ((-0.39, 0.0, "v"), (0.39, 0.0, "v")),
    ),
    "infantry": (
        ((-0.38, 0.0, "v"), (0.38, 0.0, "v")),
        ((0.0, -0.34, "h"),),
    ),
    "sentry": (
        ((-0.36, 0.0, "v"), (0.36, 0.0, "v")),
        ((-0.31, -0.08, "v"), (0.31, -0.08, "v")),
    ),
    "drone": (
        (
            (-0.31, -0.31, "dot"),
            (0.31, -0.31, "dot"),
            (-0.31, 0.31, "dot"),
            (0.31, 0.31, "dot"),
        ),
    ),
}


def _rmuc_led_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    if color == TEAM_RED_COLOR:
        return (250, 63, 71)
    if color == TEAM_BLUE_COLOR:
        return (72, 157, 255)
    return color


def _draw_rmuc_team_led_overlay(
    screen: pygame.Surface,
    *,
    center: tuple[int, int],
    size: tuple[int, int],
    angle: float,
    lights: tuple[tuple[float, float, str], ...],
    color: tuple[int, int, int],
) -> None:
    """Draw low-energy team LEDs and local bloom on presentation-only layers."""
    if not lights or size[0] <= 0 or size[1] <= 0:
        return
    led_color = _rmuc_led_color(color)
    span = max(1, min(size))
    overlay = pygame.Surface(size, pygame.SRCALPHA)
    for x_fraction, y_fraction, orientation in lights:
        x = round(size[0] * (0.5 + x_fraction))
        y = round(size[1] * (0.5 + y_fraction))
        if not (0 <= x < size[0] and 0 <= y < size[1]):
            continue
        if orientation == "dot":
            diameter = max(2, round(span * 0.085))
            lamp = pygame.Rect(0, 0, diameter, diameter)
            lamp.center = (x, y)
        elif orientation == "v":
            lamp = pygame.Rect(
                0,
                0,
                max(2, round(span * 0.055)),
                max(3, round(span * 0.14)),
            )
            lamp.center = (x, y)
        else:
            lamp = pygame.Rect(
                0,
                0,
                max(3, round(span * 0.14)),
                max(2, round(span * 0.055)),
            )
            lamp.center = (x, y)
        glow = lamp.inflate(max(3, round(span * 0.08)), max(3, round(span * 0.08)))
        pygame.draw.ellipse(overlay, (*led_color, 16), glow)
        pygame.draw.rect(
            overlay,
            (*led_color, 204),
            lamp,
            border_radius=max(1, min(lamp.width, lamp.height) // 2),
        )
        if orientation != "dot":
            highlight = _blend_color(led_color, TEXT_COLOR, 0.32)
            if orientation == "v":
                pygame.draw.line(
                    overlay,
                    (*highlight, 116),
                    (x, lamp.top + 1),
                    (x, lamp.bottom - 2),
                    width=1,
                )
            else:
                pygame.draw.line(
                    overlay,
                    (*highlight, 116),
                    (lamp.left + 1, y),
                    (lamp.right - 2, y),
                    width=1,
                )
    if angle:
        overlay = pygame.transform.rotate(overlay, angle)
    screen.blit(overlay, overlay.get_rect(center=center))


def _rmuc_robot_sprites_available(robot_type: str) -> bool:
    parts = _RMUC_ROBOT_SPRITE_PARTS.get(robot_type)
    return bool(parts) and all(
        ASSET_MANAGER.load(f"robots/{part}") is not None for part in parts
    )


def _draw_rmuc_robot_sprites(
    screen: pygame.Surface,
    *,
    center: tuple[int, int],
    robot_type: str,
    color: tuple[int, int, int],
    body_angle: float,
    turret_angle: float,
    lit: bool = True,
) -> bool:
    """Draw presentation-only robot art; sprite pixels never define geometry."""
    parts = _RMUC_ROBOT_SPRITE_PARTS.get(robot_type)
    sizes = _RMUC_ROBOT_SPRITE_SIZES.get(robot_type)
    led_layouts = _RMUC_ROBOT_LED_LAYOUTS.get(robot_type)
    if (
        not parts
        or not sizes
        or not led_layouts
        or not _rmuc_robot_sprites_available(robot_type)
    ):
        return False

    angles = (-math.degrees(body_angle), -math.degrees(turret_angle))
    for index, (part, size) in enumerate(zip(parts, sizes)):
        rendered = ASSET_MANAGER.render(
            f"robots/{part}",
            size=size,
            angle=angles[index],
        )
        if rendered is None:
            return False
        screen.blit(rendered, rendered.get_rect(center=center))
        _draw_rmuc_team_led_overlay(
            screen,
            center=center,
            size=size,
            angle=angles[index],
            lights=led_layouts[index] if lit else (),
            color=color,
        )
    return True


def _draw_rmuc_robot_shape(
    screen: pygame.Surface,
    *,
    center: tuple[int, int],
    robot_type: str,
    color: tuple[int, int, int],
    body_angle: float,
    turret_angle: float,
    alive: bool,
    selected: bool,
    animation_time: float,
    muzzle_remaining: float,
    muzzle_caliber: str,
    impact_remaining: float,
    impact_caliber: str = "17mm",
    destroy_remaining: float = 0.0,
    destroy_progress: float = 1.0,
    respawn_remaining: float = 0.0,
    respawn_progress: float = 1.0,
    raw_status: str = "",
    invincible: bool = False,
    hp_ratio: float = 1.0,
) -> int:
    profile = robot_visual_profile(robot_type)
    draw_color = color if alive else MUTED_COLOR
    if alive and impact_remaining > 0:
        flash_mix = 0.72 if impact_caliber == "42mm" else 0.44
        draw_color = _blend_color(draw_color, IMPACT_COLOR, flash_mix)
    if alive and respawn_remaining > 0:
        draw_color = _blend_color(draw_color, SHIELD_COLOR, 0.28)
    robot_sprites_available = _rmuc_robot_sprites_available(robot_type)
    if robot_type == "drone":
        hover = round(2 * math.sin(animation_time * 3.2))
        center = (center[0], center[1] + hover)

    light_color = _blend_color(draw_color, TEXT_COLOR, 0.58)
    armor_color = _blend_color(draw_color, ROBOT_OUTLINE, 0.25)

    def body_point(local: tuple[float, float]) -> tuple[int, int]:
        return _rotate_point(center, local, body_angle)

    def body_polygon(
        points: tuple[tuple[float, float], ...],
        fill: tuple[int, int, int],
        *,
        outline: tuple[int, int, int] = ROBOT_OUTLINE,
        width: int = 2,
    ) -> None:
        transformed = [body_point(point) for point in points]
        pygame.draw.polygon(screen, fill, transformed)
        pygame.draw.polygon(screen, outline, transformed, width=width)

    def body_line(
        start: tuple[float, float],
        end: tuple[float, float],
        color: tuple[int, int, int],
        width: int,
    ) -> None:
        pygame.draw.line(screen, color, body_point(start), body_point(end), width)

    if not robot_sprites_available:
        shadow_extent = max(
            profile.body_width,
            profile.body_height,
            profile.tool_arm_length + 14,
            46 if robot_type == "drone" else 0,
        )
        shadow = pygame.Surface(
            (shadow_extent + 14, max(28, round(shadow_extent * 0.56))),
            pygame.SRCALPHA,
        )
        pygame.draw.ellipse(shadow, (*ARENA_SHADOW, 105), shadow.get_rect())
        screen.blit(
            shadow,
            (center[0] - shadow.get_width() // 2 + 3, center[1] + 8),
        )

    if robot_type == "hero" and not robot_sprites_available:
        body_polygon(
            (
                (-22, -10), (-17, -14), (14, -14), (23, -8),
                (23, 8), (14, 14), (-17, 14), (-22, 10),
            ),
            armor_color,
            width=3,
        )
        body_polygon(
            ((-16, -9), (11, -9), (18, -5), (18, 5), (11, 9), (-16, 9)),
            draw_color,
            outline=light_color,
            width=1,
        )
        body_polygon(
            ((13, -5), (20, -4), (20, 4), (13, 5)),
            light_color,
            width=1,
        )
        body_line((-14, -11), (9, -11), light_color, 2)
        body_line((-14, 11), (9, 11), armor_color, 2)
        body_line((-9, 0), (8, 0), light_color, 3)
    elif robot_type == "engineer" and not robot_sprites_available:
        body_polygon(
            (
                (-18, -10), (-13, -14), (11, -14), (18, -9),
                (18, 9), (11, 14), (-13, 14), (-18, 10),
            ),
            armor_color,
            width=3,
        )
        body_polygon(
            ((-12, -8), (8, -8), (13, -5), (13, 5), (8, 8), (-12, 8)),
            draw_color,
            outline=light_color,
            width=1,
        )
        for side in (-1, 1):
            body_polygon(
                ((-11, side * 11), (9, side * 11), (11, side * 14), (-13, side * 14)),
                ROBOT_OUTLINE,
                outline=armor_color,
                width=1,
            )
            body_line((-7, side * 12), (5, side * 12), light_color, 2)
        body_line((-9, 0), (7, 0), light_color, 3)
        shoulder = body_point((12, 0))
        elbow = body_point((profile.tool_arm_length * 0.68, -7))
        tool = body_point((profile.tool_arm_length, -3))
        pygame.draw.line(screen, ROBOT_OUTLINE, shoulder, elbow, width=7)
        pygame.draw.line(screen, ASSEMBLY_COLOR, shoulder, elbow, width=4)
        pygame.draw.circle(screen, ROBOT_OUTLINE, elbow, 5)
        pygame.draw.circle(screen, light_color, elbow, 2)
        pygame.draw.line(screen, ROBOT_OUTLINE, elbow, tool, width=6)
        pygame.draw.line(screen, ASSEMBLY_COLOR, elbow, tool, width=3)
        pygame.draw.line(
            screen,
            ASSEMBLY_COLOR,
            body_point((profile.tool_arm_length - 1, -8)),
            body_point((profile.tool_arm_length + 5, -11)),
            width=3,
        )
        pygame.draw.line(
            screen,
            ASSEMBLY_COLOR,
            body_point((profile.tool_arm_length - 1, 2)),
            body_point((profile.tool_arm_length + 5, 5)),
            width=3,
        )
    elif robot_type == "sentry" and not robot_sprites_available:
        body_polygon(
            (
                (-26, -9), (-21, -14), (19, -14), (26, -9),
                (26, 9), (19, 14), (-21, 14), (-26, 9),
            ),
            armor_color,
            width=3,
        )
        body_polygon(
            ((-19, -9), (15, -9), (22, -5), (22, 5), (15, 9), (-19, 9)),
            draw_color,
            outline=light_color,
            width=1,
        )
        for side in (-1, 1):
            body_polygon(
                ((-17, side * 10), (17, side * 10), (20, side * 13), (-20, side * 13)),
                ROBOT_OUTLINE,
                outline=armor_color,
                width=1,
            )
            body_line((-12, side * 11), (13, side * 11), light_color, 2)
        body_polygon(
            ((16, -5), (23, -4), (23, 4), (16, 5)),
            light_color,
            width=1,
        )
        body_line((-9, 0), (10, 0), light_color, 3)
    elif robot_type == "drone" and not robot_sprites_available:
        rotors = ((-18, -9), (18, -9), (-18, 9), (18, 9))
        for local_rotor in rotors:
            rotor = body_point(local_rotor)
            pygame.draw.line(screen, ROBOT_OUTLINE, center, rotor, width=6)
            pygame.draw.line(screen, armor_color, center, rotor, width=3)
            pygame.draw.circle(screen, ROBOT_OUTLINE, rotor, 7)
            pygame.draw.circle(screen, armor_color, rotor, 5)
            pygame.draw.circle(screen, light_color, rotor, 2)
            blade = body_point((local_rotor[0] + 4, local_rotor[1] - 1))
            pygame.draw.line(screen, TEXT_COLOR, rotor, blade, width=2)
        body_polygon(
            ((-13, -7), (-8, -12), (8, -12), (13, -7),
             (13, 7), (8, 12), (-8, 12), (-13, 7)),
            armor_color,
            width=3,
        )
        body_polygon(
            ((-9, -5), (-5, -8), (7, -8), (10, -5),
             (10, 5), (5, 8), (-9, 6)),
            draw_color,
            outline=light_color,
            width=1,
        )
        pygame.draw.circle(screen, TEXT_COLOR, center, 3)
    elif not robot_sprites_available:
        body_polygon(
            (
                (-14, -7), (-10, -10), (10, -10), (14, -6),
                (14, 6), (10, 10), (-10, 10), (-14, 7),
            ),
            armor_color,
            width=3,
        )
        body_polygon(
            ((-9, -6), (7, -6), (11, -4), (11, 4), (7, 6), (-9, 6)),
            draw_color,
            outline=light_color,
            width=1,
        )
        for x in (-8, 9):
            for y in (-9, 9):
                wheel = body_point((x, y))
                pygame.draw.circle(screen, ROBOT_OUTLINE, wheel, 4)
                pygame.draw.circle(screen, armor_color, wheel, 2)
        body_polygon(
            ((9, -3), (13, -2), (13, 2), (9, 3)),
            light_color,
            width=1,
        )
        body_line((-6, 0), (6, 0), light_color, 2)
    turret_center = body_point((4, 0))
    muzzle_point = center
    if profile.turret_radius > 0:
        muzzle_point = _rotate_point(
            turret_center,
            (profile.barrel_length, 0),
            turret_angle,
        )
        if not robot_sprites_available:
            pygame.draw.circle(
                screen,
                ROBOT_OUTLINE,
                turret_center,
                profile.turret_radius + 3,
            )
            pygame.draw.circle(
                screen,
                armor_color,
                turret_center,
                profile.turret_radius,
            )
            pygame.draw.circle(
                screen,
                light_color,
                _rotate_point(turret_center, (-3, -3), turret_angle),
                max(2, profile.turret_radius // 3),
            )
            barrel_start = _rotate_point(
                turret_center,
                (profile.turret_radius - 1, 0),
                turret_angle,
            )
            if robot_type == "sentry":
                for side in (-1, 1):
                    rail_start = _rotate_point(
                        turret_center,
                        (profile.turret_radius, side * 4),
                        turret_angle,
                    )
                    rail_end = _rotate_point(
                        turret_center,
                        (profile.barrel_length - 3, side * 4),
                        turret_angle,
                    )
                    pygame.draw.line(screen, ROBOT_OUTLINE, rail_start, rail_end, width=4)
                    pygame.draw.line(screen, light_color, rail_start, rail_end, width=2)
            pygame.draw.line(
                screen,
                ROBOT_OUTLINE,
                barrel_start,
                muzzle_point,
                width=profile.barrel_width + 2,
            )
            pygame.draw.line(
                screen,
                light_color if alive else MUTED_COLOR,
                barrel_start,
                muzzle_point,
                width=profile.barrel_width,
            )

    if robot_sprites_available:
        _draw_rmuc_robot_sprites(
            screen,
            center=center,
            robot_type=robot_type,
            color=color,
            body_angle=body_angle,
            turret_angle=turret_angle,
            lit=alive,
        )

    if muzzle_remaining > 0 and profile.turret_radius > 0:
        projectile = projectile_visual_profile(muzzle_caliber)
        flash_radius = (
            8 if projectile.caliber == "42mm" else 5
        )
        pygame.draw.circle(
            screen,
            IMPACT_COLOR,
            muzzle_point,
            flash_radius,
        )
        flash_tip = _rotate_point(
            muzzle_point,
            (flash_radius + 5, 0),
            turret_angle,
        )
        pygame.draw.line(
            screen,
            IMPACT_COLOR,
            muzzle_point,
            flash_tip,
            width=max(2, projectile.tracer_width),
        )

    radius = max(profile.body_width, profile.body_height) // 2
    if invincible:
        shield_pulse = 1 + round(
            2 * (0.5 + 0.5 * math.sin(animation_time * 3.0))
        )
        shield_radius = radius + 5 + shield_pulse
        layer = pygame.Surface(
            (shield_radius * 2 + 8, shield_radius * 2 + 8),
            pygame.SRCALPHA,
        )
        local_center = (layer.get_width() // 2, layer.get_height() // 2)
        pygame.draw.circle(
            layer,
            (*SHIELD_COLOR, 22),
            local_center,
            shield_radius + 2,
        )
        pygame.draw.circle(
            layer,
            (*SHIELD_COLOR, 105),
            local_center,
            shield_radius,
            width=2,
        )
        screen.blit(
            layer,
            (
                center[0] - local_center[0],
                center[1] - local_center[1],
            ),
        )
    if "VULN" in raw_status:
        pygame.draw.circle(
            screen,
            DANGER_COLOR,
            center,
            radius + 7,
            width=2,
        )
    warning_strength = (
        0.0
        if robot_type == "drone"
        else low_hp_warning_strength(hp_ratio, animation_time)
    )
    if warning_strength > 0 and alive:
        warning_radius = radius + 9 + round(3 * warning_strength)
        warning_color = _blend_color(WARNING_COLOR, DANGER_COLOR, warning_strength * 0.45)
        pygame.draw.circle(
            screen,
            warning_color,
            center,
            warning_radius,
            width=1,
        )
    if impact_remaining > 0:
        impact_radius = radius + (7 if impact_caliber == "42mm" else 4)
        pygame.draw.circle(
            screen,
            IMPACT_COLOR,
            center,
            impact_radius,
            width=3 if impact_caliber == "42mm" else 2,
        )
    if robot_type != "drone":
        _draw_robot_lifecycle_effects(
            screen,
            center=center,
            radius=radius,
            color=color,
            alive=alive,
            destroy_remaining=destroy_remaining,
            destroy_progress=destroy_progress,
            respawn_remaining=respawn_remaining,
            respawn_progress=respawn_progress,
        )
    if selected:
        _draw_selection_feedback(
            screen,
            center,
            radius,
            animation_time,
        )
    return radius


def _draw_visual_projectiles(
    screen: pygame.Surface,
    viewport: Viewport,
    visual_state: CombatVisualState,
) -> None:
    for projectile in visual_state.projectiles:
        profile = projectile.profile
        progress = projectile.progress
        head = viewport.world_to_screen(projectile.position)
        trail_fraction = 0.24 if profile.caliber == "17mm" else 0.18
        tail_progress = max(0.0, progress - trail_fraction)
        mid_progress = max(0.0, progress - trail_fraction * 0.42)

        def _point_at(value: float) -> tuple[int, int]:
            world = (
                projectile.start[0]
                + (projectile.end[0] - projectile.start[0]) * value,
                projectile.start[1]
                + (projectile.end[1] - projectile.start[1]) * value,
            )
            point = viewport.world_to_screen(world)
            return (round(point[0]), round(point[1]))

        tail = _point_at(tail_progress)
        mid = _point_at(mid_progress)
        end = (round(head[0]), round(head[1]))
        faded = _blend_color(TRACER_COLOR, ARENA_FLOOR, 0.58)
        pygame.draw.line(
            screen,
            faded,
            tail,
            mid,
            width=max(1, profile.tracer_width - 1),
        )
        if profile.caliber == "42mm":
            pygame.draw.line(
                screen,
                _blend_color(IMPACT_COLOR, ARENA_FLOOR, 0.30),
                mid,
                end,
                width=profile.tracer_width + 2,
            )
        pygame.draw.line(
            screen,
            TRACER_COLOR,
            mid,
            end,
            width=profile.tracer_width,
        )
        pygame.draw.circle(
            screen,
            IMPACT_COLOR,
            end,
            profile.head_radius,
        )

    for impact in visual_state.impacts:
        point = viewport.world_to_screen(impact.position)
        center = (round(point[0]), round(point[1]))
        profile = projectile_visual_profile(impact.caliber)
        if impact.shielded:
            radius = round(9 + impact.progress * 13)
            pygame.draw.circle(
                screen,
                SHIELD_COLOR,
                center,
                radius,
                width=3,
            )
            pygame.draw.circle(
                screen,
                _blend_color(SHIELD_COLOR, TEXT_COLOR, 0.35),
                center,
                max(3, radius // 3),
                width=1,
            )
            continue

        radius = round(
            (5 if profile.caliber == "17mm" else 9)
            + impact.progress * (7 if profile.caliber == "17mm" else 14)
        )
        pygame.draw.circle(
            screen,
            IMPACT_COLOR,
            center,
            radius,
            width=2 if profile.caliber == "17mm" else 3,
        )
        if profile.caliber == "42mm":
            inner = max(3, round(radius * 0.35))
            pygame.draw.circle(screen, WARNING_COLOR, center, inner)
            ray = radius + 5
            for angle in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
                start = (
                    center[0] + round(math.cos(angle) * (radius - 2)),
                    center[1] + round(math.sin(angle) * (radius - 2)),
                )
                end = (
                    center[0] + round(math.cos(angle) * ray),
                    center[1] + round(math.sin(angle) * ray),
                )
                pygame.draw.line(screen, IMPACT_COLOR, start, end, width=2)


def _draw_move_markers(
    screen: pygame.Surface,
    viewport: Viewport,
    visual_state: CombatVisualState,
) -> None:
    for marker in visual_state.move_markers:
        point = viewport.world_to_screen(marker.position)
        center = (round(point[0]), round(point[1]))
        radius = round(8 + marker.progress * 12)
        pygame.draw.circle(
            screen,
            SELECTION_COLOR,
            center,
            radius,
            width=2,
        )
        arm = 8
        pygame.draw.line(
            screen,
            SELECTION_COLOR,
            (center[0] - arm, center[1]),
            (center[0] + arm, center[1]),
            width=1,
        )
        pygame.draw.line(
            screen,
            SELECTION_COLOR,
            (center[0], center[1] - arm),
            (center[0], center[1] + arm),
            width=1,
        )


def _draw_selected_paths(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    match: Match,
    viewport: Viewport,
    selected_robot_ids: set[str],
) -> None:
    for robot in match.robots:
        if (
            robot.id not in selected_robot_ids
            or not match.is_ai_controlled(robot.id)
            or not robot.path
        ):
            continue
        world_points = [robot.position, *robot.path]
        screen_points = [
            tuple(round(value) for value in viewport.world_to_screen(point))
            for point in world_points
        ]
        if len(screen_points) < 2:
            continue

        team_color = _rmuc_team_color(match, robot.team)
        path_color = _blend_color(team_color, TEXT_COLOR, 0.28)
        pygame.draw.lines(
            screen,
            path_color,
            False,
            screen_points,
            width=2,
        )
        start = screen_points[-2]
        end = screen_points[-1]
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        arrow_length = 10
        for offset in (-0.55, 0.55):
            arrow_end = (
                end[0] - round(math.cos(angle + offset) * arrow_length),
                end[1] - round(math.sin(angle + offset) * arrow_length),
            )
            pygame.draw.line(screen, path_color, end, arrow_end, width=2)
        pygame.draw.circle(screen, team_color, end, 4, width=1)

        intent = match.ai_intent(robot.id)
        if intent:
            label_surface = small_font.render(intent, True, TEXT_COLOR)
            label_rect = label_surface.get_rect(
                midbottom=(end[0], end[1] - 9)
            )
            label_rect.clamp_ip(screen.get_rect().inflate(-8, -8))
            pill = label_rect.inflate(10, 6)
            pygame.draw.rect(screen, PANEL_BACKGROUND, pill, border_radius=5)
            pygame.draw.rect(screen, team_color, pill, width=1, border_radius=5)
            screen.blit(label_surface, label_rect)


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
    inspector_open: bool = False,
    visual_state: CombatVisualState | None = None,
    hud_font: pygame.font.Font | None = None,
) -> None:
    screen.fill(BACKGROUND)
    hud_font = hud_font or small_font
    display_state = match.ruleset.display_state
    is_rmuc = _is_rmuc_rules_lab(match)
    robot_statuses = (
        dict(display_state.robot_statuses)
        if display_state is not None
        else {}
    )
    if is_rmuc and visual_state is not None:
        shake_x, shake_y = visual_state.screen_shake_offset()
        if shake_x or shake_y:
            viewport = Viewport(
                origin=(
                    viewport.origin[0] + shake_x,
                    viewport.origin[1] + shake_y,
                ),
                scale=viewport.scale,
                world_size=viewport.world_size,
            )

    if is_rmuc:
        _draw_rmuc_hud(
            screen,
            font,
            small_font,
            hud_font,
            match,
            player_team,
            opponent_team,
            visual_state=visual_state,
        )
    else:
        player_robots = [
            robot for robot in match.robots if robot.team == player_team
        ]
        opponent_robots = [
            robot for robot in match.robots if robot.team == opponent_team
        ]
        player_alive = sum(robot.alive for robot in player_robots)
        opponent_alive = sum(robot.alive for robot in opponent_robots)
        player_hp = sum(robot.hp for robot in player_robots)
        opponent_hp = sum(robot.hp for robot in opponent_robots)
        player_max_hp = sum(robot.max_hp for robot in player_robots)
        opponent_max_hp = sum(robot.max_hp for robot in opponent_robots)

        if display_state is None:
            left = (
                f"{match.team_name(player_team)}  "
                f"{player_alive}/{len(player_robots)} alive  "
                f"HP {player_hp}/{player_max_hp}"
            )
            right = (
                f"{match.team_name(opponent_team)}  "
                f"{opponent_alive}/{len(opponent_robots)} alive  "
                f"HP {opponent_hp}/{opponent_max_hp}"
            )
        else:
            victory_points = dict(display_state.victory_points)
            attack_damage = dict(display_state.attack_damage)
            coins = dict(display_state.coins)
            left = (
                f"{match.team_name(player_team)} "
                f"VP {victory_points[player_team]} "
                f"C {coins.get(player_team, 0)} "
                f"DMG {attack_damage.get(player_team, 0)}"
            )
            right = (
                f"{match.team_name(opponent_team)} "
                f"VP {victory_points[opponent_team]} "
                f"C {coins.get(opponent_team, 0)} "
                f"DMG {attack_damage.get(opponent_team, 0)}"
            )
        timer = max(0, math.ceil(match.time_limit - match.elapsed_time))
        if match.finished:
            status = (
                f"{match.team_name(match.winner)} WINS"
                if match.winner
                else "DRAW"
            )
        else:
            status = f"BATTLE  {timer // 60:02}:{timer % 60:02}"

        screen.blit(font.render(left, True, PLAYER_COLOR), (WINDOW_MARGIN, 22))
        status_surface = font.render(status, True, TEXT_COLOR)
        screen.blit(
            status_surface,
            status_surface.get_rect(
                center=(screen.get_width() // 2, 34)
            ),
        )
        right_surface = font.render(right, True, OPPONENT_COLOR)
        screen.blit(
            right_surface,
            (
                screen.get_width() - WINDOW_MARGIN - right_surface.get_width(),
                22,
            ),
        )
        if display_state is not None:
            control_owner = (
                match.team_name(display_state.control_owner)
                if display_state.control_owner is not None
                else "Neutral"
            )
            detail = f"Control: {control_owner}"
            detail_surface = small_font.render(detail, True, TEXT_COLOR)
            screen.blit(
                detail_surface,
                detail_surface.get_rect(
                    center=(screen.get_width() // 2, 54)
                ),
            )

    field_left, field_top = viewport.origin
    field_width, field_height = viewport.screen_size
    field_rect = pygame.Rect(
        round(field_left),
        round(field_top),
        round(field_width),
        round(field_height),
    )
    animation_time = pygame.time.get_ticks() / 1000.0
    if is_rmuc:
        _draw_rmuc_battlefield(
            screen,
            field_rect,
        )
        if not debug_geometry:
            _draw_rmuc_field_regions(
                screen,
                field_rect,
                viewport,
                match.map.zones,
            )
    else:
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
        if is_rmuc and not debug_geometry:
            _draw_rmuc_obstacle(screen, obstacle_rect)
        else:
            pygame.draw.rect(screen, OBSTACLE_COLOR, obstacle_rect, border_radius=3)

    selected_types = _selected_robot_types(match, selected_robot_ids)
    selected_positions = [
        robot.position
        for robot in match.robots
        if robot.id in selected_robot_ids
    ]
    selected_targets = _selected_ai_target_positions(
        match,
        selected_robot_ids,
    )
    for zone in match.map.zones:
        zone_rect = _world_rect_to_screen(
            viewport,
            zone.x,
            zone.y,
            zone.width,
            zone.height,
        )
        zone_points = tuple(
            tuple(round(value) for value in viewport.world_to_screen(point))
            for point in zone.vertices
        )
        if is_rmuc and not debug_geometry:
            if zone_visual_style(
                zone.id,
                selected_robot_types=selected_types,
            ) is None:
                continue
            _draw_rmuc_zone(
                screen,
                small_font,
                zone_rect,
                zone_id=zone.id,
                polygon_points=zone_points,
                selected_types=selected_types,
                occupied_by_selected=any(
                    zone.contains(position)                    for position in selected_positions
                ),
                targeted_by_selected=any(
                    zone.contains(position)
                    for position in selected_targets
                ),
                animation_time=animation_time,
            )
            continue

        if is_rmuc:
            style = _rmuc_zone_style(zone.id, debug_geometry=True)
            if style is None:
                continue
            zone_color, zone_label = style
        else:
            zone_color, zone_label = ZONE_STYLE.get(
                zone.id,
                (ZONE_COLOR, zone.id.upper()),
            )
        if zone_points:
            pygame.draw.polygon(screen, zone_color, zone_points, width=2)
        else:
            pygame.draw.rect(screen, zone_color, zone_rect, width=2)
        label_surface = small_font.render(zone_label, True, zone_color)
        screen.blit(
            label_surface,
            label_surface.get_rect(center=zone_rect.center),
        )

    if is_rmuc:
        _draw_rmuc_terrain(
            screen,
            hud_font,
            field_rect,
            viewport,
            terrain_features=match.map.terrain_features,
            terrain_connections=match.map.terrain_connections,
            zones=match.map.zones,
            debug_geometry=debug_geometry,
        )

    structure_statuses = (
        {
            structure_id: (hp, max_hp, status)
            for structure_id, hp, max_hp, status
            in display_state.structure_statuses
        }
        if display_state is not None
        else {}
    )
    for structure in match.structures:
        center = tuple(
            round(value)
            for value in viewport.world_to_screen(structure.position)
        )
        color = (
            _rmuc_team_color(match, structure.team)
            if is_rmuc
            else PLAYER_COLOR if structure.team == player_team else OPPONENT_COLOR
        )
        hp, max_hp, structure_status = structure_statuses.get(
            structure.id,
            (structure.hp, structure.max_hp, ""),
        )
        if is_rmuc:
            visual_structure = (
                visual_state.structures.get(structure.id)
                if visual_state is not None
                else None
            )
            structure_bounds = match.map.structure_bounds(structure.id)
            footprint_size = (
                (
                    max(1, round(viewport.world_length_to_screen(structure_bounds.width))),
                    max(1, round(viewport.world_length_to_screen(structure_bounds.height))),
                )
                if structure_bounds is not None
                else None
            )
            footprint_points = tuple(
                tuple(
                    round(value)
                    for value in viewport.world_to_screen(
                        (structure.position[0] + x, structure.position[1] + y)
                    )
                )
                for x, y in structure.footprint_vertices
            )
            _draw_rmuc_structure(
                screen,
                small_font,
                structure_type=structure.type,
                center=center,
                color=color,
                alive=structure.alive,
                hp=hp,
                max_hp=max_hp,
                status=structure_status,
                animation_time=animation_time,
                debug_geometry=debug_geometry,
                footprint_size=footprint_size,
                footprint_points=footprint_points,
                impact_remaining=(
                    visual_structure.impact_remaining
                    if visual_structure is not None
                    else 0.0
                ),
                impact_caliber=(
                    visual_structure.impact_caliber
                    if visual_structure is not None
                    else "17mm"
                ),
                shield_impact_remaining=(
                    visual_structure.shield_impact_remaining
                    if visual_structure is not None
                    else 0.0
                ),
            )
        else:
            size = max(13, round(viewport.world_length_to_screen(34)))
            rect = pygame.Rect(
                center[0] - size,
                center[1] - size,
                size * 2,
                size * 2,
            )
            pygame.draw.rect(
                screen,
                color if structure.alive else MUTED_COLOR,
                rect,
                width=3,
            )
            label = f"{'B' if structure.type == 'base' else 'O'} {hp}/{max_hp}"
            label_surface = small_font.render(label, True, TEXT_COLOR)
            screen.blit(
                label_surface,
                label_surface.get_rect(
                    center=(center[0], center[1] + size + 12)
                ),
            )

    labels = (
        _rmuc_robot_labels(match)
        if is_rmuc
        else _default_robot_labels(match, player_team, opponent_team)
    )
    map_centers = {
        robot.id: tuple(
            round(value)
            for value in viewport.world_to_screen(robot.position)
        )
        for robot in match.robots
    }
    robot_body_rects: dict[str, pygame.Rect] = {}
    if is_rmuc:
        for robot in match.robots:
            profile = robot_visual_profile(robot.type)
            body_extent = max(
                profile.body_width,
                profile.body_height,
                profile.barrel_length + profile.body_width // 2,
                profile.tool_arm_length + profile.body_width // 2,
                50 if robot.type == "drone" else 0,
            )
            radius = max(9, body_extent // 2 + 7)
            body_rect = pygame.Rect(0, 0, radius * 2, radius * 2)
            body_rect.center = map_centers[robot.id]
            robot_body_rects[robot.id] = body_rect
    occupied_map_labels: list[pygame.Rect] = []
    for robot in match.robots:
        center = map_centers[robot.id]
        color = (
            _rmuc_team_color(match, robot.team)
            if is_rmuc
            else PLAYER_COLOR if robot.team == player_team else OPPONENT_COLOR
        )
        visual_robot = (
            visual_state.robots.get(robot.id)
            if is_rmuc and visual_state is not None
            else None
        )
        if visual_robot is not None:
            radius = _draw_rmuc_robot_shape(
                screen,
                center=center,
                robot_type=robot.type,
                color=color,
                body_angle=visual_robot.body_angle,
                turret_angle=visual_robot.turret_angle,
                alive=robot.alive,
                selected=robot.id in selected_robot_ids,
                animation_time=animation_time,
                muzzle_remaining=visual_robot.muzzle_remaining,
                muzzle_caliber=visual_robot.muzzle_caliber,
                impact_remaining=visual_robot.impact_remaining,
                impact_caliber=visual_robot.impact_caliber,
                destroy_remaining=visual_robot.destroy_remaining,
                destroy_progress=visual_robot.destroy_progress,
                respawn_remaining=visual_robot.respawn_remaining,
                respawn_progress=visual_robot.respawn_progress,
                raw_status=robot_statuses.get(robot.id, ""),
                invincible=(
                    robot.type != "drone"
                    and robot.alive
                    and not match.ruleset.can_receive_damage(robot)
                ),
                hp_ratio=(robot.hp / robot.max_hp if robot.max_hp else 0.0),
            )
        else:
            radius = max(
                9,
                round(viewport.world_length_to_screen(match.map.collision_radius)),
            )
            if robot.id in selected_robot_ids:
                pygame.draw.circle(
                    screen,
                    SELECTION_COLOR,
                    center,
                    radius + 6,
                    width=2,
                )
            pygame.draw.circle(
                screen,
                color if robot.alive else MUTED_COLOR,
                center,
                radius,
            )

        if is_rmuc or robot.type != "drone":
            bar_width = 44 if is_rmuc else 48
            bar_height = 4 if is_rmuc else 6
            bar_x = center[0] - bar_width // 2
            bar_y = center[1] - radius - 15
            pygame.draw.rect(
                screen,
                HP_BACKGROUND,
                (bar_x, bar_y, bar_width, bar_height),
            )
            if visual_robot is not None:
                ghost_hp = min(
                    float(robot.max_hp),
                    visual_robot.ghost_hp(robot.hp),
                )
                ghost_width = round(bar_width * ghost_hp / robot.max_hp)
                if ghost_width:
                    pygame.draw.rect(
                        screen,
                        DAMAGE_GHOST_COLOR,
                        (bar_x, bar_y, ghost_width, bar_height),
                    )
            hp_width = round(bar_width * robot.hp / robot.max_hp) if robot.alive else 0
            if hp_width:
                hp_fill = color if is_rmuc else HP_COLOR
                if is_rmuc and robot.alive and robot.max_hp:
                    warning = low_hp_warning_strength(
                        robot.hp / robot.max_hp,
                        animation_time,
                    )
                    if warning > 0:
                        hp_fill = _blend_color(
                            color,
                            DANGER_COLOR,
                            min(0.72, warning * 0.72),
                        )
                pygame.draw.rect(
                    screen,
                    hp_fill,
                    (bar_x, bar_y, hp_width, bar_height),
                )

        robot_label = labels[robot.id]
        if is_rmuc and debug_geometry:
            map_label = robot_label
            if not robot.alive:
                map_label = f"{robot_label} · 亡"
            elif visual_robot is not None and visual_robot.respawn_remaining > 0:
                map_label = f"{robot_label} · 复活"
            label_surface = hud_font.render(
                map_label,
                True,
                TEXT_COLOR if robot.alive else MUTED_COLOR,
            )
            label_rect = _rmuc_map_label_rect(
                label_surface,
                center=center,
                radius=radius,
                field_rect=field_rect,
                occupied_labels=occupied_map_labels,
                other_robot_bodies=[
                    body_rect
                    for robot_id, body_rect in robot_body_rects.items()
                    if robot_id != robot.id
                ],
            )
            occupied_map_labels.append(label_rect)
            pygame.draw.rect(screen, PANEL_BACKGROUND, label_rect, border_radius=4)
            pygame.draw.rect(
                screen,
                color if robot.alive else MUTED_COLOR,
                label_rect,
                width=1,
                border_radius=4,
            )
            screen.blit(label_surface, label_surface.get_rect(center=label_rect.center))
        elif not is_rmuc:
            label_surface = small_font.render(
                robot_label,
                True,
                TEXT_COLOR if robot.alive else MUTED_COLOR,
            )
            screen.blit(
                label_surface,
                label_surface.get_rect(
                    center=(center[0], center[1] + radius + 11)
                ),
            )
        if debug_geometry:
            robot_status = robot_statuses.get(robot.id)
            if robot_status:
                status_surface = small_font.render(
                    robot_status,
                    True,
                    MUTED_COLOR,
                )
                screen.blit(
                    status_surface,
                    status_surface.get_rect(
                        center=(center[0], center[1] + radius + 27)
                    ),
                )

    if is_rmuc and visual_state is not None:
        _draw_visual_projectiles(screen, viewport, visual_state)
        _draw_move_markers(screen, viewport, visual_state)
        if debug_geometry:
            _draw_selected_paths(
                screen,
                small_font,
                match,
                viewport,
                selected_robot_ids,
            )

    if selection_rect is not None:
        pygame.draw.rect(screen, SELECTION_COLOR, selection_rect, width=1)

    if is_rmuc and inspector_open:
        _draw_rmuc_panel(
            screen,
            small_font,
            hud_font,
            match,
            player_team,
            selected_robot_ids,
            labels,
            debug_geometry=debug_geometry,
        )

    if is_rmuc:
        _draw_rmuc_inspector_toggle(
            screen,
            small_font,
            inspector_open=inspector_open,
        )


if __name__ == "__main__":
    cli()
