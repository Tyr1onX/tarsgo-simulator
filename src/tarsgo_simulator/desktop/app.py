"""Minimal Pygame front end for training and partial rules-lab matches."""

import argparse
import math
from pathlib import Path

import pygame

from tarsgo_simulator.core.config import default_scenario_path
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.fonts import ui_font
from tarsgo_simulator.desktop.polish import (
    BadgeSpec,
    contextual_controls,
    parse_virtual_shield,
    status_badges,
    structure_visual_profile,
    zone_visual_style,
)
from tarsgo_simulator.desktop.viewport import Viewport
from tarsgo_simulator.desktop.visuals import (
    CombatVisualState,
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
ARENA_GRID = (72, 88, 94)
ARENA_MIDLINE = (112, 130, 134)
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
RMUC_PANEL_GAP = 12
RMUC_FIELD_VIEW_RECT = (
    18,
    92,
    WINDOW_SIZE[0] - RMUC_PANEL_WIDTH - RMUC_PANEL_GAP - 30,
    536,
)
RMUC_PANEL_RECT = (
    WINDOW_SIZE[0] - RMUC_PANEL_WIDTH - 16,
    92,
    RMUC_PANEL_WIDTH,
    WINDOW_SIZE[1] - 108,
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
        pygame.display.set_caption(_window_caption(match))
        font = ui_font(25)
        small_font = ui_font(18)
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
        visual_state = CombatVisualState()
        visual_state.reset(match)
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
                        visual_state.reset(match)
                        selected_robot_ids.clear()
                        selection_start = None
                        selection_current = None
                        selection_shift = False
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
                visual_state=visual_state,
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
        return "TARS-Go RMUC 2026 区域赛规则实验室（实验版）"
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
    type_labels = {"hero": "H", "engineer": "E", "infantry": "I", "sentry": "S"}
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
            f"{labels.get(robot.id, robot.id)}   生命 {robot.hp}/{robot.max_hp}"
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

    title = RMUC_ROBOT_NAMES.get(robot.type, robot.type)
    progression_state = progression.get(robot.id)
    if progression_state is not None:
        title = f"{title} · {progression_state[0]}级"
    lines = [title]
    ai_intent = match.ai_intent(robot.id)
    if ai_intent is not None:
        lines.append(f"当前 AI 意图  {ai_intent}")
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
    coins = dict(display_state.coins)
    lines = [
        "队伍系统",
        f"金币      {coins.get(player_team, 0)}",
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
) -> bool:
    return emphasized or occupied_by_selected or hovered


def _rmuc_hud_rects(
    screen_width: int,
) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
    return (
        pygame.Rect(18, 9, 324, 66),
        pygame.Rect(screen_width // 2 - 62, 7, 124, 68),
        pygame.Rect(screen_width - 342, 9, 324, 66),
    )


def _rmuc_panel_layout(
    panel: pygame.Rect,
    selected_count: int,
) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
    inner_x = panel.x + 4
    inner_width = panel.width - 8
    if selected_count == 0:
        unit_height = 82
    elif selected_count == 1:
        unit_height = 286
    else:
        unit_height = min(166, 52 + min(selected_count, 5) * 20)
    unit_rect = pygame.Rect(inner_x, panel.y + 2, inner_width, unit_height)
    team_rect = pygame.Rect(inner_x, unit_rect.bottom + 8, inner_width, 108)
    controls_rect = pygame.Rect(inner_x, team_rect.bottom + 8, inner_width, 82)
    return unit_rect, team_rect, controls_rect


def _selected_robot_types(
    match: Match,
    selected_robot_ids: set[str],
) -> set[str]:
    return {
        robot.type
        for robot in match.robots
        if robot.id in selected_robot_ids
    }


def _draw_selected_unit_card(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
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
    y += 25

    ai_intent = match.ai_intent(robot.id)
    if ai_intent is not None:
        intent_rect = pygame.Rect(x, y, content_width, 34)
        pygame.draw.rect(screen, PANEL_SECTION_ALT, intent_rect, border_radius=5)
        pygame.draw.rect(screen, team_color, intent_rect, width=1, border_radius=5)
        screen.blit(
            small_font.render("AI", True, team_color),
            (intent_rect.x + 7, intent_rect.y + 7),
        )
        screen.blit(
            small_font.render(ai_intent, True, TEXT_COLOR),
            (intent_rect.x + 32, intent_rect.y + 7),
        )
        y = intent_rect.bottom + 10

    hp_label = small_font.render(
        f"HP  {robot.hp} / {robot.max_hp}",
        True,
        TEXT_COLOR,
    )
    screen.blit(hp_label, (x, y))
    y += 18
    _draw_progress_bar(
        screen,
        rect=pygame.Rect(x, y, content_width, 8),
        value=robot.hp,
        maximum=robot.max_hp,
        fill_color=HP_COLOR,
    )
    y += 17

    projectile_state = projectiles.get(robot.id)
    heat_state = heat.get(robot.id)
    chassis_state = chassis.get(robot.id)
    column_gap = 10
    column_width = (content_width - column_gap) // 2
    right_x = x + column_width + column_gap

    if projectile_state is not None:
        projectile, count = projectile_state
        screen.blit(
            small_font.render(f"弹 {count} · {projectile}", True, TEXT_COLOR),
            (x, y),
        )
    if heat_state is not None:
        current, limit, _locked, _permanent = heat_state
        screen.blit(
            small_font.render(f"热 {current:g}/{limit:g}", True, TEXT_COLOR),
            (right_x, y),
        )
    y += 21

    if heat_state is not None:
        current, limit, _locked, _permanent = heat_state
        _draw_progress_bar(
            screen,
            rect=pygame.Rect(right_x, y - 3, column_width, 5),
            value=current,
            maximum=limit,
            fill_color=WARNING_COLOR,
        )
    if chassis_state is not None:
        buffer, maximum, power, limit, power_off_remaining = chassis_state
        screen.blit(
            small_font.render(f"缓冲 {buffer:g}/{maximum:g}", True, TEXT_COLOR),
            (x, y + 8),
        )
        screen.blit(
            small_font.render(f"功率 {power:g}/{limit:g}W", True, MUTED_COLOR),
            (right_x, y + 8),
        )
        _draw_progress_bar(
            screen,
            rect=pygame.Rect(x, y + 28, column_width, 5),
            value=buffer,
            maximum=maximum,
            fill_color=SHIELD_COLOR,
        )
        y += 42
    else:
        power_off_remaining = 0.0
        y += 11

    extra_parts: list[tuple[str, tuple[int, int, int]]] = []
    if robot.id in engineer_units:
        extra_parts.append((f"能量单元 {engineer_units[robot.id]}", RESOURCE_COLOR))
    if robot.id in reserves:
        extra_parts.append((f"堡垒储备 {reserves[robot.id]}", FORTRESS_COLOR))
    for text_value, text_color in extra_parts:
        screen.blit(small_font.render(text_value, True, text_color), (x, y))
        y += 19

    raw_status = statuses.get(robot.id, "")
    heat_locked = bool(heat_state and heat_state[2])
    permanently_locked = bool(heat_state and heat_state[3])
    invincible = robot.alive and not match.ruleset.can_receive_damage(robot)
    badges = status_badges(
        raw_status,
        invincible=invincible,
        heat_locked=heat_locked,
        permanently_locked=permanently_locked,
        power_off=power_off_remaining > 0,
    )
    if badges:
        _draw_badges(
            screen,
            small_font,
            badges,
            x=x,
            y=min(y + 3, rect.bottom - 30),
            max_width=content_width,
        )


def _draw_team_systems_card(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
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
        if y > rect.bottom - 18:
            break
        color = TEXT_COLOR if line.startswith(("金币", "科技核心")) else MUTED_COLOR
        screen.blit(small_font.render(line, True, color), (x, y))
        y += 17


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
        match,
        selected_robot_ids,
        labels,
        unit_rect,
    )
    _draw_team_systems_card(
        screen,
        small_font,
        match,
        player_team,
        team_rect,
    )
    _draw_context_controls(
        screen,
        small_font,
        _selected_robot_types(match, selected_robot_ids),
        controls_rect,
        debug_geometry=debug_geometry,
    )

def _draw_hud_structure_metric(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    *,
    rect: pygame.Rect,
    label: str,
    hp: int,
    max_hp: int,
    color: tuple[int, int, int],
    align_right: bool = False,
) -> None:
    label_surface = small_font.render(f"{label} {hp}", True, TEXT_COLOR)
    label_x = (
        rect.right - label_surface.get_width()
        if align_right
        else rect.x
    )
    screen.blit(label_surface, (label_x, rect.y))
    _draw_progress_bar(
        screen,
        rect=pygame.Rect(rect.x, rect.y + 18, rect.width, 5),
        value=hp,
        maximum=max_hp,
        fill_color=color,
    )


def _draw_team_hud_card(
    screen: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    *,
    rect: pygame.Rect,
    name: str,
    base_hp: int,
    base_max_hp: int,
    outpost_hp: int,
    outpost_max_hp: int,
    coins: int,
    color: tuple[int, int, int],
    align_right: bool = False,
) -> None:
    pygame.draw.rect(screen, PANEL_BACKGROUND, rect, border_radius=7)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=1, border_radius=7)
    accent = pygame.Rect(rect.x, rect.y, rect.width, 3)
    pygame.draw.rect(screen, color, accent, border_radius=2)

    name_surface = font.render(name, True, color)
    coins_surface = small_font.render(f"金币 {coins}", True, MUTED_COLOR)
    if align_right:
        screen.blit(
            name_surface,
            (rect.right - 10 - name_surface.get_width(), rect.y + 7),
        )
        screen.blit(coins_surface, (rect.x + 10, rect.y + 12))
    else:
        screen.blit(name_surface, (rect.x + 10, rect.y + 7))
        screen.blit(
            coins_surface,
            (rect.right - 10 - coins_surface.get_width(), rect.y + 12),
        )

    gap = 12
    metric_width = (rect.width - 20 - gap) // 2
    first_rect = pygame.Rect(rect.x + 10, rect.y + 35, metric_width, 24)
    second_rect = pygame.Rect(first_rect.right + gap, rect.y + 35, metric_width, 24)
    if align_right:
        _draw_hud_structure_metric(
            screen,
            small_font,
            rect=first_rect,
            label="前哨站",
            hp=outpost_hp,
            max_hp=outpost_max_hp,
            color=color,
            align_right=False,
        )
        _draw_hud_structure_metric(
            screen,
            small_font,
            rect=second_rect,
            label="基地",
            hp=base_hp,
            max_hp=base_max_hp,
            color=color,
            align_right=True,
        )
    else:
        _draw_hud_structure_metric(
            screen,
            small_font,
            rect=first_rect,
            label="基地",
            hp=base_hp,
            max_hp=base_max_hp,
            color=color,
        )
        _draw_hud_structure_metric(
            screen,
            small_font,
            rect=second_rect,
            label="前哨站",
            hp=outpost_hp,
            max_hp=outpost_max_hp,
            color=color,
        )


def _draw_rmuc_hud(
    screen: pygame.Surface,
    font: pygame.font.Font,
    small_font: pygame.font.Font,
    match: Match,
    player_team: str,
    opponent_team: str,
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
    player_rect, timer_rect, opponent_rect = _rmuc_hud_rects(screen.get_width())
    _draw_team_hud_card(
        screen,
        font,
        small_font,
        rect=player_rect,
        name=player_name,
        base_hp=player_base.hp,
        base_max_hp=player_base.max_hp,
        outpost_hp=player_outpost.hp,
        outpost_max_hp=player_outpost.max_hp,
        coins=coins.get(player_team, 0),
        color=player_color,
    )
    _draw_team_hud_card(
        screen,
        font,
        small_font,
        rect=opponent_rect,
        name=opponent_name,
        base_hp=opponent_base.hp,
        base_max_hp=opponent_base.max_hp,
        outpost_hp=opponent_outpost.hp,
        outpost_max_hp=opponent_outpost.max_hp,
        coins=coins.get(opponent_team, 0),
        color=opponent_color,
        align_right=True,
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
        timer_surface.get_rect(center=(timer_rect.centerx, timer_rect.y + 29)),
    )
    match_label = small_font.render("比赛时间", True, MUTED_COLOR)
    screen.blit(
        match_label,
        match_label.get_rect(center=(timer_rect.centerx, timer_rect.y + 53)),
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


def _draw_rmuc_battlefield(
    screen: pygame.Surface,
    field_rect: pygame.Rect,
) -> None:
    pygame.draw.rect(screen, (37, 48, 52), field_rect)
    overlay = pygame.Surface(field_rect.size, pygame.SRCALPHA)
    half = field_rect.width // 2
    pygame.draw.rect(
        overlay,
        (*TEAM_RED_COLOR, 13),
        pygame.Rect(0, 0, half, field_rect.height),
    )
    pygame.draw.rect(
        overlay,
        (*TEAM_BLUE_COLOR, 13),
        pygame.Rect(half, 0, field_rect.width - half, field_rect.height),
    )
    screen.blit(overlay, field_rect.topleft)

    grid_x = max(44, field_rect.width // 12)
    grid_y = max(44, field_rect.height // 8)
    for x in range(field_rect.left + grid_x, field_rect.right, grid_x):
        pygame.draw.line(
            screen,
            ARENA_GRID,
            (x, field_rect.top),
            (x, field_rect.bottom),
            width=1,
        )
    for y in range(field_rect.top + grid_y, field_rect.bottom, grid_y):
        pygame.draw.line(
            screen,
            ARENA_GRID,
            (field_rect.left, y),
            (field_rect.right, y),
            width=1,
        )

    center = field_rect.center
    pygame.draw.line(
        screen,
        ARENA_MIDLINE,
        (center[0], field_rect.top),
        (center[0], field_rect.bottom),
        width=2,
    )
    pygame.draw.circle(
        screen,
        ARENA_MIDLINE,
        center,
        min(52, max(28, field_rect.height // 8)),
        width=1,
    )
    pygame.draw.rect(screen, FIELD_BORDER, field_rect, width=3)


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


def _draw_rmuc_zone(
    screen: pygame.Surface,
    small_font: pygame.font.Font,
    zone_rect: pygame.Rect,
    *,
    zone_id: str,
    selected_types: set[str],
    occupied_by_selected: bool,
    animation_time: float,
) -> None:
    style = zone_visual_style(
        zone_id,
        selected_robot_types=selected_types,
    )
    if style is None:
        return
    emphasized = style.emphasized or occupied_by_selected
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
    fill_alpha = 20 if not emphasized else round(38 + 16 * pulse)
    overlay = pygame.Surface(zone_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(
        overlay,
        (*color, fill_alpha),
        overlay.get_rect(),
        border_radius=5,
    )
    screen.blit(overlay, zone_rect.topleft)

    border_width = 1 if not emphasized else 3
    pygame.draw.rect(
        screen,
        color,
        zone_rect,
        width=border_width,
        border_radius=5,
    )
    if style.family == "fortress":
        inner = zone_rect.inflate(-8, -8)
        if inner.width > 0 and inner.height > 0:
            pygame.draw.rect(screen, color, inner, width=1, border_radius=4)

    symbol_center = (zone_rect.centerx, zone_rect.centery - 7)
    _draw_zone_symbol(
        screen,
        center=symbol_center,
        family=style.family,
        color=color,
    )
    hovered = zone_rect.collidepoint(pygame.mouse.get_pos())
    if _should_show_zone_label(
        emphasized=style.emphasized,
        occupied_by_selected=occupied_by_selected,
        hovered=hovered,
    ):
        label_color = color if emphasized else _blend_color(color, TEXT_COLOR, 0.32)
        label_surface = small_font.render(style.label, True, label_color)
        screen.blit(
            label_surface,
            label_surface.get_rect(
                center=(zone_rect.centerx, zone_rect.centery + 11)
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
    pygame.draw.circle(
        screen,
        SHIELD_COLOR,
        center,
        radius + 7 + pulse,
        width=2,
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
) -> int:
    profile = structure_visual_profile(structure_type)
    draw_color = color if alive else MUTED_COLOR
    size = profile.size

    if structure_type == "base":
        outer = [
            (center[0], center[1] - size),
            (center[0] + size, center[1]),
            (center[0], center[1] + size),
            (center[0] - size, center[1]),
        ]
        pygame.draw.polygon(screen, ROBOT_OUTLINE, outer)
        inner_size = size - 4
        inner = [
            (center[0], center[1] - inner_size),
            (center[0] + inner_size, center[1]),
            (center[0], center[1] + inner_size),
            (center[0] - inner_size, center[1]),
        ]
        pygame.draw.polygon(screen, draw_color, inner, width=3)
        pygame.draw.rect(
            screen,
            draw_color,
            pygame.Rect(
                center[0] - size // 2,
                center[1] - size // 2,
                size,
                size,
            ),
            width=2,
        )
        pygame.draw.circle(screen, draw_color, center, profile.core_radius)
    else:
        pygame.draw.circle(screen, ROBOT_OUTLINE, center, size + 2)
        pygame.draw.circle(screen, draw_color, center, size, width=3)
        pygame.draw.circle(screen, draw_color, center, profile.core_radius)
        for angle in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
            endpoint = (
                center[0] + round(math.cos(angle) * (size - 4)),
                center[1] + round(math.sin(angle) * (size - 4)),
            )
            pygame.draw.line(screen, draw_color, center, endpoint, width=2)

    hovered = pygame.Rect(
        center[0] - size - 8,
        center[1] - size - 8,
        (size + 8) * 2,
        (size + 8) * 2,
    ).collidepoint(pygame.mouse.get_pos())
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

    bar_width = size * 2 + 14
    bar_rect = pygame.Rect(
        center[0] - bar_width // 2,
        center[1] + size + 10,
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
    raw_status: str = "",
    invincible: bool = False,
    hp_ratio: float = 1.0,
) -> int:
    profile = robot_visual_profile(robot_type)
    draw_color = color if alive else MUTED_COLOR
    half_w = profile.body_width / 2
    half_h = profile.body_height / 2
    body_points = [
        _rotate_point(center, (-half_w, -half_h), body_angle),
        _rotate_point(center, (half_w, -half_h), body_angle),
        _rotate_point(center, (half_w, half_h), body_angle),
        _rotate_point(center, (-half_w, half_h), body_angle),
    ]
    pygame.draw.polygon(screen, ROBOT_OUTLINE, body_points)
    inner_points = [
        _rotate_point(center, (-half_w + 2, -half_h + 2), body_angle),
        _rotate_point(center, (half_w - 2, -half_h + 2), body_angle),
        _rotate_point(center, (half_w - 2, half_h - 2), body_angle),
        _rotate_point(center, (-half_w + 2, half_h - 2), body_angle),
    ]
    pygame.draw.polygon(screen, draw_color, inner_points)

    if robot_type == "sentry":
        for side in (-1, 1):
            pod = _rotate_point(
                center,
                (0, side * (half_h + 3)),
                body_angle,
            )
            pygame.draw.rect(
                screen,
                ROBOT_OUTLINE,
                pygame.Rect(pod[0] - 7, pod[1] - 3, 14, 6),
                border_radius=2,
            )
    elif robot_type == "engineer":
        shoulder = _rotate_point(center, (3, 0), body_angle)
        elbow = _rotate_point(
            center,
            (profile.tool_arm_length * 0.55, -8),
            body_angle,
        )
        tool = _rotate_point(
            center,
            (profile.tool_arm_length, -2),
            body_angle,
        )
        pygame.draw.line(screen, TEXT_COLOR, shoulder, elbow, width=3)
        pygame.draw.line(screen, TEXT_COLOR, elbow, tool, width=3)
        pygame.draw.circle(screen, draw_color, tool, 4, width=2)

    muzzle_point = center
    if profile.turret_radius > 0:
        pygame.draw.circle(
            screen,
            ROBOT_OUTLINE,
            center,
            profile.turret_radius + 2,
        )
        pygame.draw.circle(
            screen,
            draw_color,
            center,
            profile.turret_radius,
        )
        muzzle_point = _rotate_point(
            center,
            (profile.barrel_length, 0),
            turret_angle,
        )
        barrel_start = _rotate_point(
            center,
            (profile.turret_radius - 1, 0),
            turret_angle,
        )
        pygame.draw.line(
            screen,
            ROBOT_OUTLINE,
            barrel_start,
            muzzle_point,
            width=profile.barrel_width + 2,
        )
        pygame.draw.line(
            screen,
            TEXT_COLOR if alive else MUTED_COLOR,
            barrel_start,
            muzzle_point,
            width=profile.barrel_width,
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
        pygame.draw.circle(
            screen,
            SHIELD_COLOR,
            center,
            radius + 5 + shield_pulse,
            width=2,
        )
    if "VULN" in raw_status:
        pygame.draw.circle(
            screen,
            DANGER_COLOR,
            center,
            radius + 7,
            width=2,
        )
    if 0 < hp_ratio <= 0.25 and alive:
        warning_pulse = 0.5 + 0.5 * math.sin(animation_time * 5.0)
        warning_radius = radius + 10 + round(2 * warning_pulse)
        pygame.draw.circle(
            screen,
            WARNING_COLOR,
            center,
            warning_radius,
            width=1,
        )
    if impact_remaining > 0:
        pygame.draw.circle(
            screen,
            IMPACT_COLOR,
            center,
            radius + 4,
            width=2,
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
        tail_progress = max(0.0, progress - (0.20 if profile.caliber == "17mm" else 0.14))
        tail_world = (
            projectile.start[0]
            + (projectile.end[0] - projectile.start[0]) * tail_progress,
            projectile.start[1]
            + (projectile.end[1] - projectile.start[1]) * tail_progress,
        )
        tail = viewport.world_to_screen(tail_world)
        start = (round(tail[0]), round(tail[1]))
        end = (round(head[0]), round(head[1]))
        pygame.draw.line(
            screen,
            TRACER_COLOR,
            start,
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
        profile = projectile_visual_profile(impact.caliber)
        radius = round(
            (5 if profile.caliber == "17mm" else 9)
            + impact.progress * (7 if profile.caliber == "17mm" else 13)
        )
        pygame.draw.circle(
            screen,
            IMPACT_COLOR,
            (round(point[0]), round(point[1])),
            radius,
            width=2 if profile.caliber == "17mm" else 3,
        )


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
    visual_state: CombatVisualState | None = None,
) -> None:
    screen.fill(BACKGROUND)
    display_state = match.ruleset.display_state
    is_rmuc = _is_rmuc_rules_lab(match)
    robot_statuses = (
        dict(display_state.robot_statuses)
        if display_state is not None
        else {}
    )

    if is_rmuc:
        _draw_rmuc_hud(
            screen,
            font,
            small_font,
            match,
            player_team,
            opponent_team,
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
        _draw_rmuc_battlefield(screen, field_rect)
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
        pygame.draw.rect(screen, OBSTACLE_COLOR, obstacle_rect, border_radius=3)

    selected_types = _selected_robot_types(match, selected_robot_ids)
    selected_positions = [
        robot.position
        for robot in match.robots
        if robot.id in selected_robot_ids
    ]
    for zone in match.map.zones:
        zone_rect = _world_rect_to_screen(
            viewport,
            zone.x,
            zone.y,
            zone.width,
            zone.height,
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
                selected_types=selected_types,
                occupied_by_selected=any(
                    zone.contains(position)
                    for position in selected_positions
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
        pygame.draw.rect(screen, zone_color, zone_rect, width=2)
        label_surface = small_font.render(zone_label, True, zone_color)
        screen.blit(
            label_surface,
            label_surface.get_rect(center=zone_rect.center),
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
    if is_rmuc and visual_state is not None:
        _draw_selected_paths(
            screen,
            small_font,
            match,
            viewport,
            selected_robot_ids,
        )
        _draw_move_markers(screen, viewport, visual_state)

    for robot in match.robots:
        center = tuple(
            round(value)
            for value in viewport.world_to_screen(robot.position)
        )
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
                raw_status=robot_statuses.get(robot.id, ""),
                invincible=(
                    robot.alive
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

        bar_width, bar_height = 44 if is_rmuc else 48, 6
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
        hp_width = round(bar_width * robot.hp / robot.max_hp)
        if hp_width:
            pygame.draw.rect(
                screen,
                HP_COLOR,
                (bar_x, bar_y, hp_width, bar_height),
            )

        robot_label = labels[robot.id]
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

    if selection_rect is not None:
        pygame.draw.rect(screen, SELECTION_COLOR, selection_rect, width=1)

    if is_rmuc:
        _draw_rmuc_panel(
            screen,
            small_font,
            match,
            player_team,
            selected_robot_ids,
            labels,
            debug_geometry=debug_geometry,
        )


if __name__ == "__main__":
    cli()