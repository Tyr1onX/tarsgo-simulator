Warning: truncated output (original token count: 44811)
Total output lines: 5168

"""Minimal Pygame front end for training and partial rules-lab matches."""

import argparse
from collections import OrderedDict
from functools import lru_cache
import math
from pathlib import Path

import pygame

from tarsgo_simulator.core.config import default_scenario_path
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.assets import (
    ASSET_MANAGER,
    quantize_transform_angle,
)
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
    DEATH_SPARK_DURATION,
    DEATH_VIBRATION_DURATION,
    DESTROY_VISUAL_DURATION,
    MAX_VISIBLE_IMPACT_PARTICLES,
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
SIMULATION_HZ = 60
SIMULATION_DT = 1.0 / SIMULATION_HZ
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


class _FixedStepAccumulator:
    """Track wall time while advancing simulation in fixed-size steps."""

    def __init__(self, step: float = SIMULATION_DT) -> None:
        self.step = step
        self.accumulated = 0.0

    def add(self, elapsed: float) -> None:
        self.accumulated += max(0.0, elapsed)

    def consume_step(self) -> bool:
        if self.accumulated + 1e-12 < self.step:
            return False
        self.accumulated = max(0.0, self.accumulated - self.step)
        return True

    def reset(self) -> None:
        self.accumulated = 0.0

    @property
    def interpolation_alpha(self) -> float:
        return min(1.0, self.accumulated / self.step)
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
        static_field_cache = RMUCStaticFieldCache()
        simulation_clock = _FixedStepAccumulator()
        running = True

        while running:
            frame_dt = clock.tick(SIMULATION_HZ) / 1000.0
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
                        simulation_clock.reset()
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

            simulation_clock.add(frame_dt)
            while simulation_clock.consume_step():
                visual_state.begin_frame(match)
                match.update(SIMULATION_DT)
                visual_state.after_match_update(match, SIMULATION_DT)
            interpolation_alpha = simulation_clock.interpolation_alpha
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
                interpolation_alpha=interpolation_alpha,
                static_field_cache=static_field_cache,
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
    re…24811 tokens truncated…31, 36), deck, border_radius=3)
    pygame.draw.rect(screen, (143, 153, 158), deck, width=1, border_radius=3)

    rail_offset = max(4, length(205))
    rail_start = along(-710)
    rail_end = along(710)
    for side in (-1, 1):
        rail_y = center[1] + side * rail_offset
        pygame.draw.line(
            screen,
            (67, 78, 85),
            (rail_start[0], rail_y),
            (rail_end[0], rail_y),
            width=max(2, length(58)),
        )
        pygame.draw.line(
            screen,
            (191, 200, 203),
            (rail_start[0], rail_y - 1),
            (rail_end[0], rail_y - 1),
            width=1,
        )
        for hole_mm in (-560, -300, -40, 220, 480, 660):
            hole = along(hole_mm)
            point = (hole[0], rail_y)
            pygame.draw.circle(screen, (18, 23, 27), point, max(1, length(34)))

    # Open CNC carrier plate and its cross-members leave the rails visible.
    inner = pygame.Rect(0, 0, length(820, 18), length(350, 10))
    inner.center = center
    pygame.draw.rect(screen, (47, 56, 62), inner, border_radius=2)
    pygame.draw.rect(screen, (116, 128, 134), inner, width=1, border_radius=2)
    for s in (-570, -225, 120, 465):
        left = along(s)
        pygame.draw.line(
            screen,
            (124, 136, 141),
            (left[0], center[1] - half_h + 3),
            (left[0], center[1] + half_h - 3),
            width=max(1, length(34)),
        )

    motor_center = along(-615)
    motor = pygame.Rect(0, 0, length(250, 8), length(310, 10))
    motor.center = motor_center
    pygame.draw.rect(screen, (16, 21, 25), motor, border_radius=2)
    pygame.draw.rect(screen, (158, 168, 171), motor, width=1, border_radius=2)
    pygame.draw.line(
        screen,
        (205, 211, 211),
        (motor.left + 2, motor.centery),
        (motor.right - 2, motor.centery),
        width=1,
    )

    # The carriage accelerates down the rails only after a rule-reported launch.
    carriage_s = -250 + round(520 * state.launch_progress)
    carriage_center = along(carriage_s)
    carriage = pygame.Rect(0, 0, length(285, 9), length(480, 13))
    carriage.center = carriage_center
    pygame.draw.rect(screen, (31, 38, 43), carriage, border_radius=2)
    pygame.draw.rect(screen, (196, 204, 207), carriage, width=1, border_radius=2)
    for dy in (-length(150), length(150)):
        wheel = (carriage_center[0], carriage_center[1] + dy)
        pygame.draw.circle(screen, (15, 20, 24), wheel, max(2, length(92)))
        pygame.draw.circle(screen, (136, 148, 153), wheel, max(1, length(42)))

    # Gate leaves slide apart during the seven-second opening phase.
    gate_s = 640
    gate_center = along(gate_s)
    gate_offset = round(length(195) * state.gate_open)
    gate_color = (179, 190, 193) if state.gate_open > 0.5 else (93, 105, 111)
    gate_leaf = max(2, length(58))
    for sign in (-1, 1):
        end_y = gate_center[1] + sign * (length(100) + gate_offset)
        pygame.draw.line(
            screen,
            gate_color,
            (gate_center[0], gate_center[1] + sign * length(38)),
            (gate_center[0], end_y),
            width=gate_leaf,
        )

    if state.ammo > 0:
        dart_start = along(310)
        dart_end = along(575)
        pygame.draw.line(screen, (208, 214, 211), dart_start, dart_end, width=max(2, length(40)))
        pygame.draw.line(screen, team_color, along(500), dart_end, width=1)

    # Exposed power/data loom and a restrained team referee/status LED.
    cable_points = [along(-650), across(half_h - 3), along(-160)]
    pygame.draw.lines(screen, (13, 18, 22), False, cable_points, width=max(2, length(42)))
    pygame.draw.lines(screen, (156, 77, 67), False, [cable_points[0], cable_points[1]], width=1)
    led_color = _blend_color(team_color, (24, 31, 36), 0.88)
    if state.phase in {"opening", "firing"}:
        led_color = _blend_color(team_color, (231, 238, 240), 0.22)
    led_y = center[1] + half_h - max(2, length(60))
    pygame.draw.line(
        screen,
        led_color,
        (deck.left + 5, led_y),
        (deck.right - 5, led_y),
        width=max(1, length(36)),
    )
    if state.launch_pulse_remaining > 0:
        pulse = along(745)
        pygame.draw.circle(screen, (223, 233, 235), pulse, max(2, length(92)))


def _draw_rmuc_dart_launchers(
    screen: pygame.Surface,
    viewport: Viewport,
    match: Match,
    visual_state: CombatVisualState,
) -> None:
    for team_id, position, direction in _rmuc_dart_launcher_anchors(match):
        state = visual_state.dart_launchers.get(team_id)
        if state is None:
            continue
        _draw_rmuc_dart_launcher(
            screen,
            viewport,
            position,
            direction,
            _rmuc_team_color(match, team_id),
            state,
        )


def _draw_visual_projectiles(
    screen: pygame.Surface,
    viewport: Viewport,
    visual_state: CombatVisualState,
    match: Match | None = None,
) -> None:
    for projectile in visual_state.physical_projectiles.values():
        start = viewport.world_to_screen(projectile.previous_position)
        end = viewport.world_to_screen(projectile.position)
        team_color = (
            _rmuc_team_color(match, projectile.attacker_team_id)
            if match
            else TEAM_RED_COLOR
        )
        pygame.draw.line(
            screen,
            _blend_color(team_color, ARENA_FLOOR, 0.36),
            (round(start[0]), round(start[1])),
            (round(end[0]), round(end[1])),
            width=1 if projectile.caliber == "17mm" else 2,
        )
        pygame.draw.circle(
            screen,
            (230, 236, 231),
            (round(end[0]), round(end[1])),
            2 if projectile.caliber == "17mm" else 3,
        )

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

    for dart in visual_state.dart_projectiles:
        progress = dart.progress
        direction_x = dart.end[0] - dart.start[0]
        direction_y = dart.end[1] - dart.start[1]
        distance = max(1.0, math.hypot(direction_x, direction_y))
        direction_x /= distance
        direction_y /= distance
        head_world = dart.position
        head = viewport.world_to_screen(head_world)
        arc_lift = math.sin(math.pi * progress) * 170.0
        head = (head[0], head[1] - viewport.world_length_to_screen(arc_lift))
        perpendicular = (-direction_y, direction_x)
        tail_fraction = max(0.0, progress - 0.075)
        tail_world = (
            dart.start[0] + (dart.end[0] - dart.start[0]) * tail_fraction,
            dart.start[1] + (dart.end[1] - dart.start[1]) * tail_fraction,
        )
        tail = viewport.world_to_screen(tail_world)
        tail = (tail[0], tail[1] - viewport.world_length_to_screen(math.sin(math.pi * tail_fraction) * 170.0))
        team_color = _rmuc_team_color(match, dart.team_id) if match is not None else TEAM_RED_COLOR
        pygame.draw.line(
            screen,
            _blend_color(team_color, ARENA_FLOOR, 0.45),
            (round(tail[0]), round(tail[1])),
            (round(head[0]), round(head[1])),
            width=3,
        )
        pygame.draw.line(
            screen,
            (221, 229, 230),
            (round(tail[0]), round(tail[1])),
            (round(head[0]), round(head[1])),
            width=1,
        )
        head_point = (round(head[0]), round(head[1]))
        rear = (round(head[0] - direction_x * 8), round(head[1] - direction_y * 8))
        fin_a = (
            round(rear[0] - direction_x * 3 + perpendicular[0] * 2),
            round(rear[1] - direction_y * 3 + perpendicular[1] * 2),
        )
        fin_b = (
            round(rear[0] - direction_x * 3 - perpendicular[0] * 2),
            round(rear[1] - direction_y * 3 - perpendicular[1] * 2),
        )
        pygame.draw.line(screen, (23, 29, 34), rear, head_point, width=4)
        pygame.draw.line(screen, (194, 204, 207), rear, head_point, width=2)
        pygame.draw.line(screen, team_color, rear, fin_a, width=2)
        pygame.draw.line(screen, team_color, rear, fin_b, width=2)
        pygame.draw.circle(screen, (238, 242, 239), head_point, 2)

    particle_budget = MAX_VISIBLE_IMPACT_PARTICLES
    for impact in visual_state.impacts:
        point = viewport.world_to_screen(impact.position)
        center = (round(point[0]), round(point[1]))
        elapsed = max(0.0, impact.duration - impact.remaining)
        if impact.shielded:
            radius = round(5 + impact.progress * 6)
            pygame.draw.circle(
                screen,
                _blend_color(SHIELD_COLOR, ARENA_FLOOR, 0.24),
                center,
                radius,
                width=1,
            )
        impact_strength = {"17mm": 0.45, "42mm": 0.72, "dart": 0.95}.get(
            impact.caliber,
            0.45,
        )
        if impact.outcome in {"immune", "absorbed"}:
            # Referee absorption has a cool, compact contact mark; it never
            # receives the warm damage flash used for a valid hit.
            radius = 3 + round(impact.progress * 4)
            immune_color = _blend_color((155, 220, 235), ARENA_FLOOR, 0.48)
            box = pygame.Rect(center[0] - radius, center[1] - radius, radius * 2, radius * 2)
            pygame.draw.arc(screen, immune_color, box, 0.12, 1.18, width=1)
            pygame.draw.arc(screen, immune_color, box, 3.28, 4.34, width=1)
        else:
            if impact.surface == "armor":
                flash_color = (230, 236, 234)
            elif impact.surface in {"chassis", "frame"}:
                flash_color = (189, 198, 198)
            elif impact.surface in {"structure", "dart-target"}:
                flash_color = (216, 222, 218)
            elif impact.surface == "wheel":
                flash_color = (167, 174, 171)
            else:
                # Obstacles and arena edges produce a duller, dustier mark.
                flash_color = (153, 162, 159)
            flash_strength = 0.10 + 0.62 * impact.progress
            flash_radius = {"17mm": 2, "42mm": 3, "dart": 4}.get(
                impact.caliber,
                1,
            )
            flash_radius = max(1, round(flash_radius * (1.0 - 0.45 * impact.progress)))
            pygame.draw.circle(
                screen,
                _blend_color(flash_color, ARENA_FLOOR, flash_strength),
                center,
                flash_radius,
            )
            if impact.surface == "armor" and impact.caliber != "17mm":
                # Short, interrupted steel glint; it collapses into the
                # contact point instead of expanding as a glowing shockwave.
                base_radius = 4 if impact.caliber == "42mm" else 5
                radius = max(
                    2,
                    round(base_radius * (1.0 - 0.45 * impact.progress)),
                )
                box = pygame.Rect(
                    center[0] - radius,
                    center[1] - radius,
                    radius * 2,
                    radius * 2,
                )
                glint = _blend_color((228, 234, 228), ARENA_FLOOR, 0.08 + 0.58 * impact.progress)
                pygame.draw.arc(screen, glint, box, 0.18, 0.88, width=1)
                pygame.draw.arc(screen, glint, box, 3.35, 4.05, width=1)
        for particle in impact.particles:
            if particle_budget <= 0:
                break
            if elapsed >= particle.lifetime:
                continue
            particle_budget -= 1
            progress = min(1.0, elapsed / particle.lifetime)
            travel = particle.speed * elapsed * (1.0 - 0.32 * progress)
            world_x = impact.position[0] + particle.direction_x * travel
            world_y = impact.position[1] + particle.direction_y * travel
            if particle.kind in {"dust", "smoke"}:
                world_y += 5.0 * progress / max(1e-6, viewport.scale)
                base_color = (130, 139, 143) if particle.kind == "smoke" else (142, 150, 151)
                color = _blend_color(base_color, ARENA_FLOOR, 0.52 + 0.28 * progress)
                radius = max(
                    1,
                    round(
                        (1.1 + impact_strength * (1.25 if particle.kind == "smoke" else 1.0))
                        * (1.0 - 0.45 * progress)
                    ),
                )
                dust = viewport.world_to_screen((world_x, world_y))
                pygame.draw.circle(screen, color, (round(dust[0]), round(dust[1])), radius)
                continue

            base_color = (
                (166, 195, 202)
                if particle.kind == "absorbed"
                else (155, 161, 160)
                if particle.kind == "debris"
                else (188, 201, 203)
                if particle.kind == "metal"
                else (222, 222, 204)
            )
            fade = (
                0.32 + 0.58 * progress
                if particle.kind == "absorbed"
                else 0.25 + 0.52 * progress
                if particle.kind == "metal"
                else 0.18 + 0.48 * progress
            )
            color = _blend_color(
                base_color,
                ARENA_FLOOR,
                min(0.92, fade),
            )
            particle_point = viewport.world_to_screen((world_x, world_y))
            point = (round(particle_point[0]), round(particle_point[1]))
            length_px = max(
                1,
                round(viewport.world_length_to_screen(particle.length * (1.0 - 0.72 * progress))),
            )
            tail = (
                round(point[0] - particle.direction_x * length_px),
                round(point[1] - particle.direction_y * length_px),
            )
            if particle.kind in {"team", "absorbed"}:
                pygame.draw.circle(screen, color, point, 1 if impact.caliber != "dart" else 2)
            else:
                pygame.draw.line(screen, color, tail, point, width=1)


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
    interpolation_alpha: float = 1.0,
    static_field_cache: RMUCStaticFieldCache | None = None,
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
        if static_field_cache is None:
            _draw_rmuc_battlefield(screen, field_rect)
            if not debug_geometry:
                _draw_rmuc_field_regions(
                    screen,
                    field_rect,
                    viewport,
                    match.map.zones,
                )
        else:
            static_field_cache.draw(
                screen,
                hud_font,
                match,
                field_rect,
                viewport,
                debug_geometry=debug_geometry,
            )
    else:
        pygame.draw.rect(screen, FIELD_COLOR, field_rect)
        pygame.draw.rect(screen, FIELD_BORDER, field_rect, width=2)

    if not (is_rmuc and static_field_cache is not None):
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
        if static_field_cache is None:
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
        else:
            static_field_cache.draw_terrain(screen)

        if visual_state is not None:
            _draw_rmuc_dart_launchers(screen, viewport, match, visual_state)

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
                rotor_angle=(
                    visual_state.outpost_rotors[structure.id].angle
                    if visual_state is not None
                    and structure.id in visual_state.outpost_rotors
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
            for value in viewport.world_to_screen(
                visual_state.robots[robot.id].interpolated_position(
                    interpolation_alpha
                )
                if is_rmuc
                and visual_state is not None
                and robot.id in visual_state.robots
                else robot.position
            )
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
                body_angle=visual_robot.interpolated_body_angle(
                    interpolation_alpha
                ),
                turret_angle=visual_robot.interpolated_turret_angle(
                    interpolation_alpha
                ),
                alive=robot.alive,
                selected=robot.id in selected_robot_ids,
                animation_time=animation_time,
                muzzle_remaining=visual_robot.muzzle_remaining,
                muzzle_caliber=visual_robot.muzzle_caliber,
                impact_remaining=visual_robot.impact_remaining,
                impact_caliber=visual_robot.impact_caliber,
                destroy_remaining=visual_robot.destroy_remaining,
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
        _draw_visual_projectiles(screen, viewport, visual_state, match)
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
