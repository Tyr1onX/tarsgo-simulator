"""Single source of truth for the current match state."""

import math
from pathlib import Path
import random

from tarsgo_simulator.core.combat import update_combat
from tarsgo_simulator.core.config import MatchConfig, load_match_config
from tarsgo_simulator.core.events import MatchEvent, MatchEventType
from tarsgo_simulator.core.map import GameMap
from tarsgo_simulator.core.pathfinding import find_path
from tarsgo_simulator.core.robot import MovementProposal, Robot
from tarsgo_simulator.core.structure import Structure
from tarsgo_simulator.rules.protocol import DamageableTarget, MatchResult, RuleSet
from tarsgo_simulator.rules.registry import create_ruleset


_AI_REPLAN_INTERVAL = 0.5
_RMUC_AI_REPLAN_INTERVAL = 1.0
_RMUC_AI_SEED = 2026
_RMUC_RULE_ID = "rmuc-2026-region-v1.4.0"
_RMUC_ROBOT_NAMES = {
    "hero": "英雄",
    "engineer": "工程",
    "infantry": "步兵",
    "sentry": "哨兵",
}


class Match:
    def __init__(
        self,
        config: MatchConfig,
        *,
        rmuc_spectator_ai: bool = False,
    ) -> None:
        self.config = config
        self.ruleset: RuleSet = create_ruleset(config.rule_document)
        self._rmuc_spectator_ai_requested = rmuc_spectator_ai
        self.reset()

    @classmethod
    def from_scenario(
        cls,
        scenario_path: str | Path,
        *,
        rmuc_spectator_ai: bool = False,
    ) -> "Match":
        return cls(
            load_match_config(scenario_path),
            rmuc_spectator_ai=rmuc_spectator_ai,
        )

    def reset(self) -> None:
        scenario = self.config.scenario
        definitions = [
            (scenario.teams[side], definition)
            for side in ("red", "blue")
            for definition in scenario.teams[side].robots
        ]
        initial_parameters = self.ruleset.robot_parameters(definitions[0][1].type)
        self.map = GameMap(
            scenario.map_width,
            scenario.map_height,
            scenario.obstacles,
            initial_parameters.collision_radius,
            scenario.zones,
        )
        self.robots: list[Robot] = []
        for team, definition in definitions:
            parameters = self.ruleset.robot_parameters(definition.type)
            position = scenario.spawns[definition.id]
            if not self.map.is_passable(position):
                raise ValueError(f"机器人出生点不可通行：{definition.id} at {position}")
            self.robots.append(
                Robot(
                    id=definition.id,
                    team=team.team_id,
                    position=position,
                    hp=parameters.max_hp,
                    max_hp=parameters.max_hp,
                    speed=parameters.move_speed,
                    attack_range=parameters.attack_range,
                    attack_interval=parameters.attack_interval,
                    damage=parameters.damage,
                    type=definition.type,
                )
            )
        self.structures: list[Structure] = []
        for definition in scenario.structures:
            parameters = self.ruleset.structure_parameters(definition.type)
            self.structures.append(
                Structure(
                    id=definition.id,
                    team=definition.team,
                    type=definition.type,
                    position=definition.position,
                    hp=parameters.max_hp,
                    max_hp=parameters.max_hp,
                )
            )
        self._validate_spawn_separation()
        self.elapsed_time = 0.0
        self.finished = False
        self.winner: str | None = None
        self.current_events: list[MatchEvent] = []
        self._events_from_last_update = 0
        self._active_update_dt: float | None = None
        self._active_update_start_time: float | None = None
        self._rmuc_spectator_ai = (
            self._rmuc_spectator_ai_requested
            and self.config.rule_document.metadata.id == _RMUC_RULE_ID
        )
        self._ai_replan_elapsed = {
            robot.id: 0.0
            for robot in self.robots
            if self._ai_controls(robot)
        }
        self._ai_intents = {
            robot.id: "等待决策"
            for robot in self.robots
            if self._ai_controls(robot)
        }
        self._rmuc_ai_rng = self._build_rmuc_ai_rng()
        self.ruleset.reset(self)

    @property
    def time_limit(self) -> float:
        return self.ruleset.time_limit

    def is_player_controlled(self, robot_id: str) -> bool:
        return robot_id in self.config.scenario.player_controlled

    def is_ai_controlled(self, robot_id: str) -> bool:
        robot = next((item for item in self.robots if item.id == robot_id), None)
        return robot is not None and self._ai_controls(robot)

    def ai_intent(self, robot_id: str) -> str | None:
        return self._ai_intents.get(robot_id)

    def _ai_controls(self, robot: Robot) -> bool:
        return self._rmuc_spectator_ai or not self.is_player_controlled(robot.id)

    def order_move(self, robot_id: str, goal: tuple[float, float]) -> bool:
        if self.finished:
            return False
        robot = next((item for item in self.robots if item.id == robot_id), None)
        if robot is None or not robot.alive or not self.is_player_controlled(robot.id):
            return False
        return self._set_robot_destination(robot, goal)

    def order_exchange_projectiles(self, robot_id: str) -> bool:
        if self.finished:
            return False
        robot = next((item for item in self.robots if item.id == robot_id), None)
        if robot is None or not robot.alive or not self.is_player_controlled(robot.id):
            return False
        return self.ruleset.exchange_projectiles(self, robot)

    def apply_damage(
        self,
        target: DamageableTarget,
        amount: int,
        *,
        source_robot: Robot | None = None,
        source_team_id: str | None = None,
        bypass_invincibility: bool = False,
    ) -> int:
        """Apply HP loss and emit its damage and destruction facts exactly once."""
        is_robot = any(robot is target for robot in self.robots)
        is_structure = any(structure is target for structure in self.structures)
        if (
            self.finished
            or amount <= 0
            or not (is_robot or is_structure)
            or not target.alive
        ):
            return 0
        if not bypass_invincibility and not self.ruleset.can_receive_damage(target):
            return 0

        if source_robot is not None:
            source_team_id = source_robot.team
        amount = self.ruleset.resolve_damage(target, amount, source_team_id)
        if amount <= 0:
            return 0

        was_alive = target.alive
        previous_hp = max(0, target.hp)
        target.hp = max(0, previous_hp - amount)
        if target.hp == 0:
            target.alive = False
            if isinstance(target, Robot):
                target.path.clear()

        actual_damage = previous_hp - target.hp
        event_time = self.elapsed_time
        if self._active_update_start_time is not None and self._active_update_dt is not None:
            event_time = self._active_update_start_time + self._active_update_dt
        damaged_event = (
            MatchEventType.ROBOT_DAMAGED
            if is_robot
            else MatchEventType.STRUCTURE_DAMAGED
        )
        destroyed_event = (
            MatchEventType.ROBOT_DESTROYED
            if is_robot
            else MatchEventType.STRUCTURE_DESTROYED
        )
        if actual_damage > 0:
            self.current_events.append(
                MatchEvent(
                    type=damaged_event,
                    time=event_time,
                    robot_id=target.id if is_robot else None,
                    structure_id=target.id if is_structure else None,
                    team_id=target.team,
                    attacker_id=source_robot.id if source_robot else None,
                    attacker_team_id=source_team_id,
                    damage=actual_damage,
                )
            )
        if was_alive and not target.alive:
            self.current_events.append(
                MatchEvent(
                    type=destroyed_event,
                    time=event_time,
                    robot_id=target.id if is_robot else None,
                    structure_id=target.id if is_structure else None,
                    team_id=target.team,
                    attacker_id=source_robot.id if source_robot else None,
                    attacker_team_id=source_team_id,
                )
            )
        return actual_damage

    def order_group_move(
        self,
        robot_ids: list[str],
        anchor_goal: tuple[float, float],
    ) -> bool:
        """Keep the selected robots' offsets and commit paths only if all can move."""
        if self.finished or not robot_ids or len(robot_ids) != len(set(robot_ids)):
            return False

        robots_by_id = {robot.id: robot for robot in self.robots}
        selected = [robots_by_id.get(robot_id) for robot_id in robot_ids]
        if any(
            robot is None
            or not robot.alive
            or not self.is_player_controlled(robot.id)
            for robot in selected
        ):
            return False

        ordered_robots = sorted(selected, key=lambda robot: robot.id)
        centroid = (
            math.fsum(robot.position[0] for robot in ordered_robots) / len(ordered_robots),
            math.fsum(robot.position[1] for robot in ordered_robots) / len(ordered_robots),
        )
        planned_paths = []
        for robot in ordered_robots:
            goal = (
                anchor_goal[0] + robot.position[0] - centroid[0],
                anchor_goal[1] + robot.position[1] - centroid[1],
            )
            path = find_path(self.map, robot.position, goal)
            if path is None:
                return False
            planned_paths.append((robot, path))

        for robot, path in planned_paths:
            robot.set_path(path)
        return True

    def _set_robot_destination(self, robot: Robot, goal: tuple[float, float]) -> bool:
        path = find_path(self.map, robot.position, goal)
        if path is None:
            return False
        robot.set_path(path)
        return True

    def update(self, dt: float) -> None:
        if self.finished:
            return
        if dt < 0:
            raise ValueError("dt 不能小于 0")

        if self._events_from_last_update:
            del self.current_events[: self._events_from_last_update]
            self._events_from_last_update = 0
        self._active_update_dt = dt
        self._active_update_start_time = self.elapsed_time
        try:
            self._update_ai(dt)
            for robot in self.robots:
                robot.update_cooldown(dt)
            self.ruleset.prepare_movement(self, dt)
            self._move_robots(dt)
            self.ruleset.prepare_combat(self, dt)
            update_combat(
                self.robots,
                self.map,
                can_attack=self.ruleset.can_attack,
                structures=self.structures,
                can_target=self.ruleset.can_target,
                on_attack_committed=self.ruleset.on_attack_committed,
                apply_damage=lambda target, amount, attacker: self.apply_damage(
                    target, amount, source_robot=attacker
                ),
            )
            self.elapsed_time += dt
            self.ruleset.update(self, dt)
        finally:
            self._active_update_dt = None
            self._active_update_start_time = None
        self._events_from_last_update = len(self.current_events)
        result = self.ruleset.evaluate_result(self)
        if result is not None:
            self._apply_result(result)

    def _validate_spawn_separation(self) -> None:
        minimum_distance = self.map.collision_radius * 2
        for index, first in enumerate(self.robots):
            for second in self.robots[index + 1 :]:
                if math.dist(first.position, second.position) < minimum_distance:
                    raise ValueError(
                        f"机器人出生点冲突：{first.id} 与 {second.id} 的距离小于 "
                        f"{minimum_distance:g}"
                    )

    def _move_robots(self, dt: float) -> None:
        movement_allowed = {
            robot.id: robot.alive and self.ruleset.can_move(robot)
            for robot in self.robots
        }
        proposals: dict[str, MovementProposal] = {}
        for robot in self.robots:
            proposals[robot.id] = (
                robot.propose_movement(dt, self.map)
                if movement_allowed[robot.id]
                else (robot.position, list(robot.path))
            )

        blocked: set[str] = set()
        minimum_distance = self.map.collision_radius * 2
        while True:
            final_positions = {
                robot.id: (
                    robot.position if robot.id in blocked else proposals[robot.id][0]
                )
                for robot in self.robots
            }
            conflicts: set[str] = set()
            for index, first in enumerate(self.robots):
                for second in self.robots[index + 1 :]:
                    if _movement_conflicts(
                        first.position,
                        final_positions[first.id],
                        second.position,
                        final_positions[second.id],
                        minimum_distance,
                    ):
                        conflicts.update((first.id, second.id))

            new_conflicts = conflicts - blocked
            if not new_conflicts:
                break
            blocked.update(new_conflicts)

        for robot in self.robots:
            if movement_allowed[robot.id] and robot.id not in blocked:
                robot.commit_movement(proposals[robot.id])

    def _build_rmuc_ai_rng(self) -> dict[str, random.Random]:
        if not self._rmuc_spectator_ai:
            return {}
        result: dict[str, random.Random] = {}
        for team_id in sorted({robot.team for robot in self.robots}):
            for robot_type in ("hero", "engineer", "infantry", "sentry"):
                role_robots = sorted(
                    (
                        robot
                        for robot in self.robots
                        if robot.team == team_id and robot.type == robot_type
                    ),
                    key=lambda robot: robot.id,
                )
                for index, robot in enumerate(role_robots, start=1):
                    result[robot.id] = random.Random(
                        f"{_RMUC_AI_SEED}:{robot_type}:{index}"
                    )
        return result

    def _team_side(self, team_id: str) -> str:
        for side, team in self.config.scenario.teams.items():
            if team.team_id == team_id:
                return side
        raise KeyError(team_id)

    def _zone(self, zone_id: str):
        return next((zone for zone in self.map.zones if zone.id == zone_id), None)

    @staticmethod
    def _zone_center(zone) -> tuple[float, float]:
        return (zone.x + zone.width / 2, zone.y + zone.height / 2)

    def _zone_goal(self, zone, robot: Robot) -> tuple[float, float]:
        peers = sorted(
            (
                item
                for item in self.robots
                if item.team == robot.team and item.type == robot.type
            ),
            key=lambda item: item.id,
        )
        role_index = peers.index(robot) + 1
        offsets = {
            ("hero", 1): (-0.22, 0.00),
            ("engineer", 1): (0.22, 0.00),
            ("infantry", 1): (-0.12, -0.22),
            ("infantry", 2): (0.12, 0.22),
            ("sentry", 1): (0.00, 0.22),
        }
        dx, dy = offsets.get((robot.type, role_index), (0.0, 0.0))
        if self._team_side(robot.team) == "blue":
            dx, dy = -dx, -dy
        return (
            zone.x + zone.width * (0.5 + dx),
            zone.y + zone.height * (0.5 + dy),
        )

    def _set_ai_goal(
        self,
        robot: Robot,
        intent: str,
        goal: tuple[float, float],
    ) -> None:
        self._ai_intents[robot.id] = intent
        if math.dist(robot.position, goal) <= self.map.collision_radius:
            robot.path.clear()
            return
        self._set_robot_destination(robot, goal)

    def _weighted_ai_choice(
        self,
        robot: Robot,
        candidates: list[tuple[str, tuple[float, float], float]],
    ) -> tuple[str, tuple[float, float]] | None:
        if not candidates:
            return None
        total = math.fsum(weight for _intent, _goal, weight in candidates)
        pick = self._rmuc_ai_rng[robot.id].random() * total
        running = 0.0
        for intent, goal, weight in candidates:
            running += weight
            if pick <= running:
                return intent, goal
        intent, goal, _weight = candidates[-1]
        return intent, goal

    def _rmuc_engineer_step(self, robot: Robot, display_state) -> bool:
        side = self._team_side(robot.team)
        resource_zone = self._zone(f"{side}-resource")
        assembly_zone = self._zone(f"{side}-assembly")
        if resource_zone is None or assembly_zone is None:
            return False

        units = dict(display_state.engineer_energy_units).get(robot.id, 0)
        tech = {
            team_id: (d1, d2, d3, d4, active)
            for team_id, _cap, d1, d2, d3, d4, active, _outside
            in display_state.tech_core_status
        }.get(robot.team)
        d4_state = {
            team_id: (phase, current_step)
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
        }.get(robot.team, ("idle", 0))
        if tech is None:
            return False
        d1, d2, d3, d4, active = tech
        phase, current_step = d4_state

        if phase in {"active", "pending"}:
            self._set_ai_goal(
                robot,
                "装配科技核心",
                self._zone_goal(assembly_zone, robot),
            )
            if phase == "active" and current_step > 0 and assembly_zone.contains(robot.position):
                confirm = getattr(self.ruleset, "confirm_d4_step", None)
                if callable(confirm):
                    confirm(self, robot, "own", current_step)
                    confirm(self, robot, "opponent", current_step)
            return True

        if active is not None:
            self._set_ai_goal(
                robot,
                "装配科技核心",
                self._zone_goal(assembly_zone, robot),
            )
            if assembly_zone.contains(robot.position):
                confirm = getattr(self.ruleset, "confirm_tech_core_assembly", None)
                if callable(confirm):
                    confirm(self, robot)
            return True

        difficulty = 1 if d1 == 0 else 2 if d2 == 0 else 3 if d3 == 0 else 4 if d4 == 0 else None
        if difficulty is None:
            return False
        required_units = 2 if difficulty == 4 else 1
        if units < required_units:
            self._set_ai_goal(
                robot,
                "获取能量单元",
                self._zone_goal(resource_zone, robot),
            )
            if resource_zone.contains(robot.position):
                pickup = getattr(self.ruleset, "pickup_energy_unit", None)
                if callable(pickup):
                    pickup(self, robot)
            return True

        self._set_ai_goal(
            robot,
            "装配科技核心",
            self._zone_goal(assembly_zone, robot),
        )
        if assembly_zone.contains(robot.position):
            start = getattr(self.ruleset, "start_tech_core_assembly", None)
            if callable(start) and start(self, robot, difficulty) and difficulty < 4:
                confirm = getattr(self.ruleset, "confirm_tech_core_assembly", None)
                if callable(confirm):
                    confirm(self, robot)
        return True

    def _rmuc_ai_step(self, robot: Robot, display_state) -> None:
        if not robot.alive:
            robot.path.clear()
            self._ai_intents[robot.id] = "等待复活"
            return

        side = self._team_side(robot.team)
        supply_zone = self._zone(f"{side}-supply-buff")
        if supply_zone is None:
            return
        supply_goal = self._zone_goal(supply_zone, robot)

        if robot.hp / robot.max_hp <= 0.30:
            self._set_ai_goal(robot, "回撤", supply_goal)
            return

        if robot.type == "engineer" and self._rmuc_engineer_step(robot, display_state):
            return

        projectiles = {
            robot_id: count
            for robot_id, _projectile, count in display_state.robot_projectiles
        }
        ammo = projectiles.get(robot.id)
        low_ammo = ammo is not None and ammo <= (0 if robot.type == "hero" else 8)
        if robot.type in {"hero", "infantry", "sentry"} and low_ammo:
            if supply_zone.contains(robot.position):
                exchange = getattr(self.ruleset, "exchange_projectiles", None)
                purchased = bool(callable(exchange) and exchange(self, robot))
                robot.path.clear()
                self._ai_intents[robot.id] = "补充弹量" if purchased else "等待补给"
            else:
                self._set_ai_goal(robot, "前往补给区", supply_goal)
            return

        candidates: list[tuple[str, tuple[float, float], float]] = []
        enemy_robots = sorted(
            (
                target
                for target in self.robots
                if target.alive and target.team != robot.team
            ),
            key=lambda target: (target.type, target.id),
        )
        role_weight = {"hero": 1.35, "engineer": 1.0, "infantry": 1.2, "sentry": 0.9}
        field_scale = max(self.map.width, self.map.height)
        for target in enemy_robots:
            distance = math.dist(robot.position, target.position)
            distance_weight = max(0.45, 1.35 - distance / field_scale)
            name = _RMUC_ROBOT_NAMES.get(target.type, target.type)
            candidates.append(
                (
                    f"追击敌方{name}",
                    target.position,
                    role_weight.get(target.type, 1.0) * distance_weight,
                )
            )

        enemy_structures = sorted(
            (
                structure
                for structure in self.structures
                if structure.alive
                and structure.team != robot.team
                and self.ruleset.can_target(structure)
            ),
            key=lambda structure: (structure.type, structure.id),
        )
        for structure in enemy_structures:
            candidates.append(
                (
                    "进攻敌方前哨站" if structure.type == "outpost" else "进攻敌方基地",
                    structure.position,
                    0.95 if structure.type == "outpost" else 0.55,
                )
            )

        central = self._zone(f"{side}-central-elevated-buff")
        if central is not None:
            candidates.append(("前往中央区域", self._zone_goal(central, robot), 1.1))
        for suffix in ("trapezoid-buff", "outpost-buff"):
            zone = self._zone(f"{side}-{suffix}")
            if zone is not None:
                candidates.append(("前往防御增益区", self._zone_goal(zone, robot), 0.55))

        if robot.type in {"infantry", "sentry"}:
            own_outpost = next(
                (
                    structure
                    for structure in self.structures
                    if structure.team == robot.team and structure.type == "outpost"
                ),
                None,
            )
            structure_status = dict(
                (structure_id, status)
                for structure_id, _hp, _max_hp, status
                in display_state.structure_statuses
            )
            fortress_ready = own_outpost is not None and (
                not own_outpost.alive or "REBUILT" in structure_status.get(own_outpost.id, "")
            )
            fortress = self._zone(f"{side}-fortress-buff")
            if fortress_ready and fortress is not None:
                candidates.append(("占领堡垒", self._zone_goal(fortress, robot), 1.7))

        candidates.append(("前往补给区", supply_goal, 0.25))
        choice = self._weighted_ai_choice(robot, candidates)
        if choice is None:
            robot.path.clear()
            self._ai_intents[robot.id] = "待机"
            return
        intent, goal = choice
        if intent.startswith("追击敌方"):
            distance = math.dist(robot.position, goal)
            if distance <= robot.attack_range and self.map.has_line_of_sight(robot.position, goal):
                robot.path.clear()
                self._ai_intents[robot.id] = intent
                return
        self._set_ai_goal(robot, intent, goal)

    def _update_ai(self, dt: float) -> None:
        if self._rmuc_spectator_ai:
            display_state = self.ruleset.display_state
            if display_state is None:
                return
            for robot in sorted(self.robots, key=lambda item: item.id):
                elapsed = self._ai_replan_elapsed[robot.id] + dt
                if not robot.alive:
                    self._rmuc_ai_step(robot, display_state)
                    self._ai_replan_elapsed[robot.id] = 0.0
                    continue
                if elapsed >= _RMUC_AI_REPLAN_INTERVAL:
                    elapsed %= _RMUC_AI_REPLAN_INTERVAL
                    self._rmuc_ai_step(robot, display_state)
                self._ai_replan_elapsed[robot.id] = elapsed
            return

        for robot in self.robots:
            if self.is_player_controlled(robot.id):
                continue
            targets = [
                target
                for target in self.robots
                if target.alive and target.team != robot.team
            ]
            if not robot.alive or not targets:
                robot.path.clear()
                self._ai_replan_elapsed[robot.id] = 0.0
                continue

            target = min(
                targets,
                key=lambda candidate: (
                    math.dist(robot.position, candidate.position),
                    candidate.id,
                ),
            )
            distance = math.dist(robot.position, target.position)
            if distance <= robot.attack_range and self.map.has_line_of_sight(
                robot.position, target.position
            ):
                robot.path.clear()
                self._ai_replan_elapsed[robot.id] = 0.0
                continue

            elapsed = self._ai_replan_elapsed[robot.id] + dt
            if elapsed >= _AI_REPLAN_INTERVAL:
                elapsed %= _AI_REPLAN_INTERVAL
                self._set_robot_destination(robot, target.position)
            self._ai_replan_elapsed[robot.id] = elapsed

    def _apply_result(self, result: MatchResult) -> None:
        self.finished = True
        self.winner = result.winner

    def team_name(self, team_id: str) -> str:
        for team in self.config.scenario.teams.values():
            if team.team_id == team_id:
                return team.display_name
        return team_id


def _movement_conflicts(
    start_a: tuple[float, float],
    end_a: tuple[float, float],
    start_b: tuple[float, float],
    end_b: tuple[float, float],
    minimum_distance: float,
) -> bool:
    """Check the closest relative separation during this frame's proposed moves."""
    relative_start = (start_a[0] - start_b[0], start_a[1] - start_b[1])
    relative_change = (
        (end_a[0] - start_a[0]) - (end_b[0] - start_b[0]),
        (end_a[1] - start_a[1]) - (end_b[1] - start_b[1]),
    )
    change_squared = relative_change[0] ** 2 + relative_change[1] ** 2
    if change_squared == 0:
        closest = relative_start
    else:
        progress = -(
            relative_start[0] * relative_change[0]
            + relative_start[1] * relative_change[1]
        ) / change_squared
        progress = min(1.0, max(0.0, progress))
        closest = (
            relative_start[0] + relative_change[0] * progress,
            relative_start[1] + relative_change[1] * progress,
        )
    return math.hypot(*closest) < minimum_distance