"""Single source of truth for the current match state."""

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import math
from pathlib import Path
import random

from tarsgo_simulator.core.combat import update_combat
from tarsgo_simulator.core.config import MatchConfig, load_match_config
from tarsgo_simulator.core.events import MatchEvent, MatchEventType
from tarsgo_simulator.core.map import GameMap
from tarsgo_simulator.core.pathfinding import IncrementalAStar, find_path
from tarsgo_simulator.core.projectiles import Projectile, ProjectileImpact, ProjectileSystem
from tarsgo_simulator.core.robot import MovementProposal, Robot
from tarsgo_simulator.core.structure import Structure
from tarsgo_simulator.rules.protocol import DamageableTarget, MatchResult, RuleSet
from tarsgo_simulator.rules.registry import create_ruleset


_AI_REPLAN_INTERVAL = 0.5
_RMUC_AI_REPLAN_INTERVAL = 0.75
_RMUC_AI_SEED = 2026
_RMUC_AI_SCORE_JITTER = 0.07
_RMUC_AI_STICKY_SECONDS = 2.25
_RMUC_AI_SWITCH_MARGIN = 0.45
_RMUC_AI_STRATEGY_STICKY_SECONDS = 4.0
_RMUC_RULE_ID = "rmuc-2026-region-v1.4.0"
_RMUC_ROBOT_NAMES = {
    "hero": "英雄",
    "engineer": "工程",
    "infantry": "步兵",
    "sentry": "哨兵",
    "drone": "空中机器人",
}
_PATHFINDING_WORK_BUDGET_PER_TICK = 512
_PATHFINDING_WORK_QUANTUM = 16
_PATH_CACHE_MAX_ENTRIES = 512
_LOCAL_AVOIDANCE_DISTANCE = 2.2
_STUCK_RECOVERY_AFTER_SECONDS = 0.75
_STUCK_REPATH_AFTER_SECONDS = 1.75
_STUCK_REPATH_COOLDOWN_SECONDS = 1.5
_STUCK_PROGRESS_EPSILON = 0.05


def _stable_spin_direction(robot_id: str, team_id: str) -> int:
    """Assign a repeatable spin direction without Python's randomized hash."""
    key = f"{team_id}:{robot_id}"
    value = sum((index + 1) * ord(char) for index, char in enumerate(key))
    return 1 if value % 2 == 0 else -1


@dataclass(slots=True)
class _AIPathPlan:
    robot_id: str
    target_key: str | None
    goal: tuple[float, float]
    pending_searches: int = 0
    structure_id: str | None = None
    preferred_approach_index: int | None = None
    candidates: list[
        tuple[int, bool, float, int, list[tuple[float, float]]]
    ] = field(default_factory=list)


@dataclass(slots=True)
class _AIPathSearchJob:
    plan: _AIPathPlan
    index: int
    start: tuple[float, float]
    goal: tuple[float, float]
    clear_shot: bool
    search: IncrementalAStar
    reported_expansions: int = 0


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
                    footprint=definition.footprint,
                    footprint_shape=definition.footprint_shape,
                    footprint_vertices=definition.footprint_vertices,
                )
            )
        self.map = GameMap(
            scenario.map_width,
            scenario.map_height,
            scenario.obstacles,
            initial_parameters.collision_radius,
            scenario.zones,
            self.structures,
            scenario.path_grid_size,
            scenario.terrain_features,
            scenario.terrain_connections,
        )
        self.robots: list[Robot] = []
        for team, definition in definitions:
            parameters = self.ruleset.robot_parameters(definition.type)
            position = scenario.spawns[definition.id]
            aerial = definition.type == "drone"
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
                    aerial=aerial,
                    chassis_spin_direction=_stable_spin_direction(
                        definition.id,
                        team.team_id,
                    ),
                )
            )
        self._validate_spawn_separation()
        self.elapsed_time = 0.0
        if hasattr(self, "projectile_system"):
            self.projectile_system.reset()
        else:
            self.projectile_system = ProjectileSystem()
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
        ai_robots = [robot for robot in self.robots if self._ai_controls(robot)]
        if self._rmuc_spectator_ai:
            ai_robots.sort(key=lambda robot: robot.id)
        replan_phase = (
            _RMUC_AI_REPLAN_INTERVAL / len(ai_robots)
            if self._rmuc_spectator_ai and ai_robots
            else 0.0
        )
        self._ai_replan_elapsed = {
            robot.id: index * replan_phase
            for index, robot in enumerate(ai_robots)
        }
        self._ai_intents = {
            robot.id: "等待决策"
            for robot in self.robots
            if self._ai_controls(robot)
        }
        self._ai_target_keys = {
            robot.id: None
            for robot in self.robots
            if self._ai_controls(robot)
        }
        self._ai_path_targets: dict[
            str,
            tuple[str | None, tuple[float, float]],
        ] = {}
        self._ai_assigned_approach_slots: dict[str, tuple[str, int]] = {}
        self._pending_ai_paths: dict[str, _AIPathPlan] = {}
        self._path_work_queue: deque[_AIPathSearchJob] = deque()
        self._path_cache: OrderedDict[
            tuple[tuple[int, int], tuple[int, int]],
            tuple[tuple[float, float], ...],
        ] = OrderedDict()
        self._pathfinding_counters = {
            "requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "searches_started": 0,
            "searches_completed": 0,
            "searches_failed": 0,
            "node_pops": 0,
            "node_expansions": 0,
            "max_queue_length": 0,
        }
        self._movement_counters = {
            "blocked_ticks": 0,
            "blocked_events": 0,
            "yield_decisions": 0,
            "local_avoidance_attempts": 0,
            "local_avoidance_moves": 0,
            "stuck_recovery_attempts": 0,
            "stuck_recovery_successes": 0,
            "stuck_path_replans": 0,
        }
        self._blocked_seconds_by_robot = {robot.id: 0.0 for robot in self.robots}
        self._stuck_seconds_by_robot = {robot.id: 0.0 for robot in self.robots}
        self._stuck_goal_by_robot: dict[str, tuple[float, float]] = {}
        self._best_goal_distance_by_robot: dict[str, float] = {}
        self._was_blocked = {robot.id: False for robot in self.robots}
        self._stuck_recovery_after = {robot.id: 0.0 for robot in self.robots}
        self._stuck_repath_after = {robot.id: 0.0 for robot in self.robots}
        self._local_detour_by_robot: dict[str, tuple[float, float]] = {}
        self._local_avoidance_side_by_robot: dict[str, int] = {}
        self._ai_sticky_until = {
            robot.id: 0.0
            for robot in self.robots
            if self._ai_controls(robot)
        }
        self._rmuc_ai_rng = self._build_rmuc_ai_rng()
        self._rmuc_ai_team_strategies = (
            {
                team_id: (
                    "assault" if self._team_side(team_id) == "red" else "control"
                )
                for team_id in sorted({robot.team for robot in self.robots})
            }
            if self._rmuc_spectator_ai
            else {}
        )
        self._rmuc_ai_strategy_changed_at = {
            team_id: self.elapsed_time
            for team_id in self._rmuc_ai_team_strategies
        }
        self._rmuc_radar_ai_elapsed = {
            team_id: 0.0 for team_id in sorted({robot.team for robot in self.robots})
        }
        self._rmuc_radar_ai_laser_active = {
            team_id: False for team_id in self._rmuc_radar_ai_elapsed
        }
        self.ruleset.reset(self)

    @property
    def time_limit(self) -> float:
        return self.ruleset.time_limit

    @property
    def uses_physical_projectiles(self) -> bool:
        return self.config.rule_document.metadata.id == _RMUC_RULE_ID

    @property
    def projectiles(self) -> list[Projectile]:
        """Current simulation projectiles; the desktop renderer treats these as input only."""
        return self.projectile_system.projectiles

    @property
    def projectile_impacts(self) -> tuple[ProjectileImpact, ...]:
        """Contacts recorded during the most recent simulation update."""
        return tuple(self.projectile_system.impacts)

    @property
    def projectile_diagnostics(self) -> dict[str, object]:
        shooters = {}
        for robot_id, values in sorted(self.projectile_system._shooter_stats.items()):
            shots = values["shots_fired"]
            shooters[robot_id] = {
                **values,
                "hit_rate_pct": round(100.0 * values["armor_hits"] / shots, 2)
                if shots
                else 0.0,
            }
        return {
            "active": len(self.projectile_system.projectiles),
            "max_active": self.projectile_system.max_active_projectiles,
            "launched": self.projectile_system.total_launched,
            "impacts": self.projectile_system.total_impacts,
            "shots_fired": self.projectile_system.total_launched,
            "robot_contacts": self.projectile_system.robot_contacts,
            "armor_hits": self.projectile_system.armor_hits,
            "friendly_armor_contacts": self.projectile_system.friendly_armor_contacts,
            "nonarmor_contacts": self.projectile_system.nonarmor_contacts,
            "misses": self.projectile_system.misses,
            "applied_damage": self.projectile_system.applied_damage,
            "per_robot_hit_rate": shooters,
        }

    def is_player_controlled(self, robot_id: str) -> bool:
        return robot_id in self.config.scenario.player_controlled

    def is_ai_controlled(self, robot_id: str) -> bool:
        robot = next((item for item in self.robots if item.id == robot_id), None)
        return robot is not None and self._ai_controls(robot)

    def ai_intent(self, robot_id: str) -> str | None:
        return self._ai_intents.get(robot_id)

    @property
    def movement_diagnostics(self) -> dict[str, int]:
        """Return a snapshot of deterministic local-movement counters."""
        return dict(self._movement_counters)

    def ai_team_strategy(self, team_id: str) -> str | None:
        """Return the spectator AI's current team-level strategy label."""
        if not self._rmuc_spectator_ai:
            return None
        strategy = self._rmuc_ai_team_strategies.get(team_id)
        if strategy is None:
            return None
        flavor = "主攻" if self._team_side(team_id) == "red" else "控场"
        labels = {
            "assault": "快速主攻",
            "control": "区域控制",
            "tech": f"科技推进 · {flavor}",
            "focus": f"集火 · {flavor}",
            "defend": f"防守 · {flavor}",
            "return": "紧急回防",
        }
        return labels.get(strategy, labels["assault"])

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
        bypass_attack_defense: bool = False,
        award_experience: bool = True,
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
        if bypass_attack_defense:
            amount = self.ruleset.resolve_damage(
                target,
                amount,
                source_team_id,
                bypass_attack_defense=True,
            )
        else:
            amount = self.ruleset.resolve_damage(target, amount, source_team_id)
        if amount <= 0:
            return 0

        was_alive = target.alive
        previous_hp = max(0, target.hp)
        target.hp = max(0, previous_hp - amount)
        if target.hp == 0:
            target.alive = False
            if isinstance(target, Robot):
                self._clear_ai_path(target)

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
                    award_experience=award_experience,
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
                    award_experience=award_experience,
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

    def _advance_path_requests(self) -> None:
        """Spend a bounded, fair slice of A* work once per simulation tick."""
        budget = _PATHFINDING_WORK_BUDGET_PER_TICK
        while budget > 0 and self._path_work_queue:
            job = self._path_work_queue.popleft()
            if self._pending_ai_paths.get(job.plan.robot_id) is not job.plan:
                continue
            used = job.search.advance(min(_PATHFINDING_WORK_QUANTUM, budget))
            budget -= used
            self._pathfinding_counters["node_pops"] += used
            self._pathfinding_counters["node_expansions"] += (
                job.search.expanded_nodes - job.reported_expansions
            )
            job.reported_expansions = job.search.expanded_nodes
            if job.search.done:
                self._finish_ai_path_search(job)
            else:
                self._path_work_queue.append(job)
            if used == 0 and not job.search.done:
                break

    def _finish_ai_path_search(self, job: _AIPathSearchJob) -> None:
        plan = job.plan
        if self._pending_ai_paths.get(plan.robot_id) is not plan:
            return
        self._pathfinding_counters["searches_completed"] += 1
        path = job.search.result
        if path is None:
            self._pathfinding_counters["searches_failed"] += 1
        else:
            self._store_cached_path(job.start, job.goal, path)
            self._add_ai_path_candidate(
                plan,
                job.index,
                job.clear_shot,
                path,
            )
        plan.pending_searches -= 1
        if plan.pending_searches == 0:
            self._commit_ai_path_plan(plan)

    def _add_ai_path_candidate(
        self,
        plan: _AIPathPlan,
        index: int,
        clear_shot: bool,
        path: list[tuple[float, float]],
    ) -> None:
        path_length = math.fsum(
            math.dist(first, second)
            for first, second in zip(path, path[1:])
        )
        slot_penalty = int(
            plan.preferred_approach_index is not None
            and index != plan.preferred_approach_index
        )
        plan.candidates.append((slot_penalty, not clear_shot, path_length, index, path))

    def _commit_ai_path_plan(self, plan: _AIPathPlan) -> None:
        robot = next(
            (item for item in self.robots if item.id == plan.robot_id),
            None,
        )
        if (
            self._pending_ai_paths.get(plan.robot_id) is not plan
            or robot is None
            or not robot.alive
            or self._ai_target_keys.get(plan.robot_id) != plan.target_key
        ):
            return
        self._pending_ai_paths.pop(plan.robot_id, None)
        valid_candidates = []
        occupied_approaches = {
            index
            for other_id, (other_target, index)
            in self._ai_assigned_approach_slots.items()
            if (
                other_id != robot.id
                and other_target == plan.target_key
                and any(
                    teammate.id == other_id
                    and teammate.team == robot.team
                    and teammate.alive
                    for teammate in self.robots
                )
            )
        }
        for (
            slot_penalty,
            no_clear_shot,
            _old_length,
            index,
            path,
        ) in plan.candidates:
            if not path:
                continue
            rebased = [robot.position, *path[1:]]
            if all(
                self.map.can_traverse(first, second)
                for first, second in zip(rebased, rebased[1:])
            ):
                path_length = math.fsum(
                    math.dist(first, second)
                    for first, second in zip(rebased, rebased[1:])
                )
                occupied_penalty = int(index in occupied_approaches)
                valid_candidates.append(
                    (
                        occupied_penalty,
                        slot_penalty,
                        no_clear_shot,
                        path_length,
                        index,
                        rebased,
                    )
                )
        if valid_candidates:
            chosen = min(valid_candidates, key=lambda item: item[:5])
            path = chosen[5]
            robot.set_path(path)
            self._ai_path_targets[plan.robot_id] = (plan.target_key, plan.goal)
            if plan.structure_id is not None and plan.target_key is not None:
                self._ai_assigned_approach_slots[robot.id] = (
                    plan.target_key,
                    chosen[4],
                )
        elif plan.candidates:
            self._request_ai_path(
                robot,
                plan.goal,
                target_key=plan.target_key,
                structure_id=plan.structure_id,
            )
        else:
            self._clear_ai_path(robot)

    def _cancel_ai_path_request(self, robot_id: str) -> None:
        plan = self._pending_ai_paths.pop(robot_id, None)
        if plan is not None:
            self._path_work_queue = deque(
                job for job in self._path_work_queue if job.plan is not plan
            )
        self._ai_path_targets.pop(robot_id, None)

    def _clear_ai_path(self, robot: Robot) -> None:
        self._cancel_ai_path_request(robot.id)
        robot.path.clear()

    def _path_cache_key(
        self,
        start: tuple[float, float],
        goal: tuple[float, float],
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        grid = self.map.path_grid_size
        return (
            (math.floor(start[0] / grid), math.floor(start[1] / grid)),
            (math.floor(goal[0] / grid), math.floor(goal[1] / grid)),
        )

    def _cached_path(
        self,
        start: tuple[float, float],
        goal: tuple[float, float],
    ) -> list[tuple[float, float]] | None:
        if not self.map.is_passable(start) or not self.map.is_passable(goal):
            self._pathfinding_counters["cache_misses"] += 1
            return None
        key = self._path_cache_key(start, goal)
        cached = self._path_cache.get(key)
        if cached is None:
            self._pathfinding_counters["cache_misses"] += 1
            return None
        rebased = [start, *cached[1:-1], goal]
        if len(rebased) == 2 and start == goal:
            rebased = [start]
        if not all(
            self.map.can_traverse(first, second)
            for first, second in zip(rebased, rebased[1:])
        ):
            self._pathfinding_counters["cache_misses"] += 1
            return None
        self._path_cache.move_to_end(key)
        self._pathfinding_counters["cache_hits"] += 1
        return rebased

    def _store_cached_path(
        self,
        start: tuple[float, float],
        goal: tuple[float, float],
        path: list[tuple[float, float]],
    ) -> None:
        key = self._path_cache_key(start, goal)
        self._path_cache[key] = tuple(path)
        self._path_cache.move_to_end(key)
        while len(self._path_cache) > _PATH_CACHE_MAX_ENTRIES:
            self._path_cache.popitem(last=False)

    def _request_ai_path(
        self,
        robot: Robot,
        goal: tuple[float, float],
        *,
        target_key: str | None,
        structure_id: str | None = None,
    ) -> None:
        self._pathfinding_counters["requests"] += 1
        tolerance = self.map.path_grid_size / 2
        tracked = self._ai_path_targets.get(robot.id)
        if (
            tracked is not None
            and tracked[0] == target_key
            and math.dist(tracked[1], goal) <= tolerance
            and self._existing_ai_path_is_usable(robot)
        ):
            return
        pending = self._pending_ai_paths.get(robot.id)
        if (
            pending is not None
            and pending.target_key == target_key
            and math.dist(pending.goal, goal) <= tolerance
        ):
            return

        self._cancel_ai_path_request(robot.id)
        plan = _AIPathPlan(
            robot_id=robot.id,
            target_key=target_key,
            goal=goal,
            structure_id=structure_id,
        )
        self._pending_ai_paths[robot.id] = plan
        approaches: list[tuple[int, tuple[float, float], bool]]
        if structure_id is not None:
            approaches = [
                (
                    index,
                    point,
                    self.map.has_line_of_sight(
                        point,
                        next(
                            item.position
                            for item in self.structures
                            if item.id == structure_id
                        ),
                        structure_id,
                    ),
                )
                for index, point in enumerate(
                    self.map.structure_approach_points(structure_id)
                )
            ]
            if approaches:
                teammates = sorted(
                    (
                        item
                        for item in self.robots
                        if item.team == robot.team
                        and item.alive
                        and not item.aerial
                    ),
                    key=lambda item: item.id,
                )
                if robot in teammates:
                    plan.preferred_approach_index = (
                        teammates.index(robot) % len(approaches)
                    )
        else:
            approaches = [(0, goal, False)]

        for index, endpoint, clear_shot in approaches:
            start = robot.position
            cached = self._cached_path(start, endpoint)
            if cached is not None:
                self._add_ai_path_candidate(
                    plan,
                    index,
                    clear_shot,
                    cached,
                )
                continue
            self._pathfinding_counters["searches_started"] += 1
            search = IncrementalAStar(self.map, start, endpoint)
            job = _AIPathSearchJob(
                plan=plan,
                index=index,
                start=start,
                goal=endpoint,
                clear_shot=clear_shot,
                search=search,
            )
            if search.done:
                if search.result is None:
                    self._pathfinding_counters["searches_failed"] += 1
                else:
                    self._store_cached_path(start, endpoint, search.result)
                    self._add_ai_path_candidate(
                        plan,
                        index,
                        clear_shot,
                        search.result,
                    )
                self._pathfinding_counters["searches_completed"] += 1
                continue
            plan.pending_searches += 1
            self._path_work_queue.append(job)
        self._pathfinding_counters["max_queue_length"] = max(
            self._pathfinding_counters["max_queue_length"],
            len(self._path_work_queue),
        )
        if plan.pending_searches == 0:
            self._commit_ai_path_plan(plan)

    def _existing_ai_path_is_usable(self, robot: Robot) -> bool:
        if not robot.path:
            return False
        points = [robot.position, *robot.path]
        return all(
            self.map.can_traverse(first, second)
            for first, second in zip(points, points[1:])
        )

    def update(self, dt: float) -> None:
        if self.finished:
            # Contact snapshots are consumed by presentation once per fixed
            # simulation tick. Do not replay the last hit on later render ticks.
            self.projectile_system.impacts.clear()
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
            self._advance_path_requests()
            for robot in self.robots:
                robot.update_cooldown(dt)
            self.ruleset.prepare_movement(self, dt)
            self._move_robots(dt)
            self.ruleset.prepare_combat(self, dt)
            if self.uses_physical_projectiles:
                existing_projectile_ids = tuple(
                    projectile.id for projectile in self.projectiles
                )
                parameters_for = getattr(self.ruleset, "projectile_parameters_for")
                aim_parameters_for = getattr(
                    self.ruleset,
                    "aim_motion_parameters_for",
                )
                self.projectile_system.update_aim(
                    dt,
                    self.robots,
                    self.structures,
                    self.map,
                    can_target=self.ruleset.can_target,
                    parameters_for=parameters_for,
                    aim_parameters_for=aim_parameters_for,
                )
                self.projectile_system.launch_ready_shots(
                    self.robots,
                    self.structures,
                    self.map,
                    can_attack=self.ruleset.can_attack,
                    can_target=self.ruleset.can_target,
                    parameters_for=parameters_for,
                    on_attack_committed=self.ruleset.on_attack_committed,
                )
                self.projectile_system.advance(
                    dt,
                    self.robots,
                    self.structures,
                    self.map,
                    projectile_ids=existing_projectile_ids,
                    robot_hitboxes=getattr(
                        self.ruleset,
                        "projectile_robot_hitbox_parameters",
                        lambda: None,
                    )(),
                    apply_damage=lambda target, amount, attacker: self.apply_damage(
                        target,
                        amount,
                        source_robot=attacker,
                    ),
                )
            else:
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
                if first.aerial or second.aerial:
                    continue
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
        intended_to_move = {
            robot.id: (
                movement_allowed[robot.id]
                and math.dist(robot.position, proposals[robot.id][0]) > 1e-8
            )
            for robot in self.robots
        }
        minimum_distance = self.map.collision_radius * 2
        priority = sorted(
            self.robots,
            key=lambda robot: (
                int(
                    math.dist(robot.position, proposals[robot.id][0]) > 1e-8
                    and movement_allowed[robot.id]
                ),
                robot.id,
            ),
        )
        active_detours = dict(self._local_detour_by_robot)
        avoidance_sides = dict(self._local_avoidance_side_by_robot)
        avoidance_moves: set[str] = set()

        # Resolve one conflict at a time in a stable order. The lower-priority
        # mover first tries a deterministic side-step; if the pair is still too
        # close during the first sidestep tick, the right-of-way robot waits for
        # that tick instead of permanently freezing both paths.
        iteration_limit = max(1, len(priority) * len(priority) * 2)
        for _ in range(iteration_limit):
            conflict_pair = None
            for index, first in enumerate(priority):
                if first.aerial:
                    continue
                for second in priority[index + 1 :]:
                    if second.aerial:
                        continue
                    if _movement_conflicts(
                        first.position,
                        proposals[first.id][0],
                        second.position,
                        proposals[second.id][0],
                        minimum_distance,
                    ):
                        conflict_pair = first, second
                        break
                if conflict_pair is not None:
                    break
            if conflict_pair is None:
                break

            winner, yielding = conflict_pair
            self._movement_counters["yield_decisions"] += 1
            changed = False
            candidates = self._local_avoidance_proposals(
                yielding,
                winner,
                proposals[yielding.id],
                active_detours.get(yielding.id),
                avoidance_sides.get(yielding.id),
                dt,
                minimum_distance,
            )
            if candidates:
                self._movement_counters["local_avoidance_attempts"] += 1
            for proposal, detour_goal, side in candidates:
                conflicts = [
                    other
                    for other in priority
                    if other.id != yielding.id
                    and not other.aerial
                    and _movement_conflicts(
                        yielding.position,
                        proposal[0],
                        other.position,
                        proposals[other.id][0],
                        minimum_distance,
                    )
                ]
                if not conflicts:
                    proposals[yielding.id] = proposal
                    active_detours[yielding.id] = detour_goal
                    avoidance_sides[yielding.id] = side
                    avoidance_moves.add(yielding.id)
                    changed = True
                    break
                if conflicts == [winner] and not _movement_conflicts(
                    yielding.position,
                    proposal[0],
                    winner.position,
                    winner.position,
                    minimum_distance,
                ):
                    proposals[yielding.id] = proposal
                    proposals[winner.id] = (winner.position, list(winner.path))
                    active_detours[yielding.id] = detour_goal
                    avoidance_sides[yielding.id] = side
                    avoidance_moves.add(yielding.id)
                    changed = True
                    break

            if not changed:
                # Keep the requested route intact while yielding. A second
                # stable pass will also stop the conflicting right-of-way move
                # if neither a side-step nor the original route is safe.
                if math.dist(yielding.position, proposals[yielding.id][0]) > 1e-8:
                    proposals[yielding.id] = (
                        yielding.position,
                        list(yielding.path),
                    )
                    changed = True
                elif math.dist(winner.position, proposals[winner.id][0]) > 1e-8:
                    proposals[winner.id] = (winner.position, list(winner.path))
                    changed = True
            if not changed:
                break

        # A dense knot can create new crossings as one robot yields. If bounded
        # local resolution cannot settle it, pause only the remaining conflict
        # participants for this tick; their old paths remain available.
        for _ in range(len(priority)):
            conflicts = [
                (first, second)
                for index, first in enumerate(priority)
                if not first.aerial
                for second in priority[index + 1 :]
                if not second.aerial
                and _movement_conflicts(
                    first.position,
                    proposals[first.id][0],
                    second.position,
                    proposals[second.id][0],
                    minimum_distance,
                )
            ]
            if not conflicts:
                break
            for first, second in conflicts:
                proposals[first.id] = (first.position, list(first.path))
                proposals[second.id] = (second.position, list(second.path))

        for robot in self.robots:
            start = robot.position
            if movement_allowed[robot.id]:
                robot.commit_movement(proposals[robot.id])
            moved = math.dist(start, robot.position) > 1e-8
            robot.velocity = (
                (
                    (robot.position[0] - start[0]) / dt,
                    (robot.position[1] - start[1]) / dt,
                )
                if dt > 0
                else (0.0, 0.0)
            )
            if moved and robot.id in avoidance_moves:
                self._movement_counters["local_avoidance_moves"] += 1
            blocked = intended_to_move[robot.id] and not moved
            if blocked:
                self._movement_counters["blocked_ticks"] += 1
                if not self._was_blocked[robot.id]:
                    self._movement_counters["blocked_events"] += 1
                self._was_blocked[robot.id] = True
                self._blocked_seconds_by_robot[robot.id] += max(0.0, dt)
            else:
                self._was_blocked[robot.id] = False
                self._blocked_seconds_by_robot[robot.id] = 0.0

            if intended_to_move[robot.id] and robot.path:
                goal = robot.path[-1]
                remaining = math.dist(robot.position, goal)
                previous_goal = self._stuck_goal_by_robot.get(robot.id)
                best_remaining = self._best_goal_distance_by_robot.get(
                    robot.id
                )
                if previous_goal != goal or best_remaining is None:
                    self._stuck_seconds_by_robot[robot.id] = 0.0
                    best_remaining = remaining
                elif remaining < best_remaining - _STUCK_PROGRESS_EPSILON:
                    self._stuck_seconds_by_robot[robot.id] = 0.0
                    best_remaining = remaining
                else:
                    self._stuck_seconds_by_robot[robot.id] += max(0.0, dt)
                self._stuck_goal_by_robot[robot.id] = goal
                self._best_goal_distance_by_robot[robot.id] = best_remaining
            else:
                self._stuck_seconds_by_robot[robot.id] = 0.0
                self._stuck_goal_by_robot.pop(robot.id, None)
                self._best_goal_distance_by_robot.pop(robot.id, None)

            detour_goal = active_detours.get(robot.id)
            if detour_goal is not None and detour_goal not in robot.path:
                active_detours.pop(robot.id, None)
                avoidance_sides.pop(robot.id, None)

            if blocked:
                self._recover_stuck_robot(
                    robot,
                    minimum_distance,
                    active_detours,
                    avoidance_sides,
                )

        self._local_detour_by_robot = active_detours
        self._local_avoidance_side_by_robot = avoidance_sides

    def _local_avoidance_proposals(
        self,
        robot: Robot,
        blocker: Robot,
        current_proposal: MovementProposal,
        active_detour: tuple[float, float] | None,
        active_side: int | None,
        dt: float,
        minimum_distance: float,
    ) -> list[tuple[MovementProposal, tuple[float, float], int]]:
        if active_detour is not None and active_detour in robot.path:
            return [(current_proposal, active_detour, active_side or 1)]
        if not robot.path or dt <= 0.0 or robot.speed <= 0.0:
            return []

        away_x = robot.position[0] - blocker.position[0]
        away_y = robot.position[1] - blocker.position[1]
        away_length = math.hypot(away_x, away_y)
        if away_length <= 1e-8:
            away_x = 1.0 if robot.id > blocker.id else -1.0
            away_y = 0.0
        else:
            away_x /= away_length
            away_y /= away_length

        move_x = current_proposal[0][0] - robot.position[0]
        move_y = current_proposal[0][1] - robot.position[1]
        move_length = math.hypot(move_x, move_y)
        if move_length > 1e-8:
            move_x /= move_length
            move_y /= move_length
        else:
            move_x, move_y = -away_y, away_x
        tangent_x, tangent_y = -move_y, move_x

        preferred_side = active_side
        if preferred_side is None:
            stable_value = sum(
                (index + 1) * ord(char)
                for index, char in enumerate(robot.id)
            )
            preferred_side = 1 if stable_value % 2 == 0 else -1
        result = []
        for side in (preferred_side, -preferred_side):
            direction_x = away_x * 0.82 + tangent_x * side * 0.57
            direction_y = away_y * 0.82 + tangent_y * side * 0.57
            direction_length = math.hypot(direction_x, direction_y)
            if direction_length <= 1e-8:
                continue
            direction_x /= direction_length
            direction_y /= direction_length
            for multiplier in (_LOCAL_AVOIDANCE_DISTANCE, 3.0, 3.8):
                distance = max(
                    minimum_distance * multiplier,
                    robot.speed * 0.45,
                )
                goal = (
                    robot.position[0] + direction_x * distance,
                    robot.position[1] + direction_y * distance,
                )
                if (
                    not self.map.is_passable(goal)
                    or not self.map.can_traverse(robot.position, goal)
                    or robot.path
                    and not self.map.can_traverse(goal, robot.path[0])
                ):
                    continue
                detour_path = [goal, *robot.path]
                original_path = robot.path
                try:
                    robot.path = detour_path
                    proposal = robot.propose_movement(dt, self.map)
                finally:
                    robot.path = original_path
                if math.dist(robot.position, proposal[0]) <= 1e-8:
                    continue
                result.append((proposal, goal, side))
        return result

    def _recover_stuck_robot(
        self,
        robot: Robot,
        minimum_distance: float,
        active_detours: dict[str, tuple[float, float]],
        avoidance_sides: dict[str, int],
    ) -> None:
        stuck_seconds = self._stuck_seconds_by_robot[robot.id]
        now = self.elapsed_time
        if (
            stuck_seconds >= _STUCK_RECOVERY_AFTER_SECONDS
            and now >= self._stuck_recovery_after[robot.id]
        ):
            self._movement_counters["stuck_recovery_attempts"] += 1
            self._stuck_recovery_after[robot.id] = (
                now + _STUCK_RECOVERY_AFTER_SECONDS
            )
            active_detour = active_detours.get(robot.id)
            has_active_detour = active_detour is not None and active_detour in robot.path
            nearby = sorted(
                (
                    other
                    for other in self.robots
                    if other.id != robot.id
                    and not other.aerial
                    and math.dist(robot.position, other.position)
                    <= minimum_distance * 3.0
                ),
                key=lambda other: (math.dist(robot.position, other.position), other.id),
            )
            if nearby and not has_active_detour:
                candidates = self._local_avoidance_proposals(
                    robot,
                    nearby[0],
                    (robot.position, list(robot.path)),
                    None,
                    avoidance_sides.get(robot.id),
                    max(1.0 / 60.0, min(0.05, _STUCK_RECOVERY_AFTER_SECONDS)),
                    minimum_distance,
                )
                if candidates:
                    _proposal, goal, side = candidates[0]
                    if goal not in robot.path:
                        robot.path.insert(0, goal)
                    active_detours[robot.id] = goal
                    avoidance_sides[robot.id] = side
                    self._movement_counters["stuck_recovery_successes"] += 1

        if (
            stuck_seconds < _STUCK_REPATH_AFTER_SECONDS
            or now < self._stuck_repath_after[robot.id]
            or not robot.path
        ):
            return
        pending = self._pending_ai_paths.get(robot.id)
        target_key = self._ai_target_keys.get(robot.id)
        if pending is not None and pending.target_key == target_key:
            return
        structure_id = (
            target_key.removeprefix("structure:")
            if target_key is not None and target_key.startswith("structure:")
            else None
        )
        structure = next(
            (item for item in self.structures if item.id == structure_id),
            None,
        )
        tracked = self._ai_path_targets.get(robot.id)
        goal = (
            structure.position
            if structure is not None
            else tracked[1]
            if tracked is not None and tracked[0] == target_key
            else robot.path[-1]
        )
        self._ai_path_targets.pop(robot.id, None)
        self._request_ai_path(
            robot,
            goal,
            target_key=target_key,
            structure_id=structure_id,
        )
        self._movement_counters["stuck_path_replans"] += 1
        self._stuck_repath_after[robot.id] = now + _STUCK_REPATH_COOLDOWN_SECONDS

    def _build_rmuc_ai_rng(self) -> dict[str, random.Random]:
        if not self._rmuc_spectator_ai:
            return {}
        result: dict[str, random.Random] = {}
        for team_id in sorted({robot.team for robot in self.robots}):
            for robot_type in ("hero", "engineer", "infantry", "sentry", "drone"):
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
            result[f"radar:{team_id}"] = random.Random(
                f"{_RMUC_AI_SEED}:radar"
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
            ("drone", 1): (0.00, -0.30),
        }
        dx, dy = offsets.get((robot.type, role_index), (0.0, 0.0))
        if self._team_side(robot.team) == "blue":
            dx, dy = -dx, -dy
        return (
            zone.x + zone.width * (0.5 + dx),
            zone.y + zone.height * (0.5 + dy),
        )

    def _remember_ai_decision(
        self,
        robot: Robot,
        target_key: str | None,
        *,
        sticky: bool = True,
    ) -> None:
        previous = self._ai_target_keys.get(robot.id)
        self._ai_target_keys[robot.id] = target_key
        if previous != target_key:
            self._cancel_ai_path_request(robot.id)
            self._ai_assigned_approach_slots.pop(robot.id, None)
        if not sticky or target_key is None:
            self._ai_sticky_until[robot.id] = self.elapsed_time
        elif target_key != previous:
            self._ai_sticky_until[robot.id] = (
                self.elapsed_time + _RMUC_AI_STICKY_SECONDS
            )

    def _set_ai_goal(
        self,
        robot: Robot,
        intent: str,
        goal: tuple[float, float],
        *,
        target_key: str | None = None,
        sticky: bool = True,
    ) -> None:
        self._ai_intents[robot.id] = intent
        self._remember_ai_decision(robot, target_key, sticky=sticky)
        if target_key is not None and target_key.startswith("structure:"):
            structure_id = target_key.removeprefix("structure:")
            structure = next(
                (item for item in self.structures if item.id == structure_id),
                None,
            )
            if structure is not None and self.map.structure_bounds(structure_id):
                self._request_ai_path(
                    robot,
                    goal,
                    target_key=target_key,
                    structure_id=structure_id,
                )
                return
        if math.dist(robot.position, goal) <= self.map.collision_radius:
            self._clear_ai_path(robot)
            return
        self._request_ai_path(robot, goal, target_key=target_key)

    def _has_line_of_sight_to_ai_target(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        target_key: str,
    ) -> bool:
        structure_id = (
            target_key.removeprefix("structure:")
            if target_key.startswith("structure:")
            else None
        )
        return self.map.has_line_of_sight(start, end, structure_id)

    def _ai_target_occupancy(self, robot: Robot, target_key: str) -> int:
        return sum(
            1
            for teammate in self.robots
            if (                teammate.id != robot.id
                and teammate.team == robot.team
                and teammate.alive
                and self._ai_target_keys.get(teammate.id) == target_key
            )
        )

    def _occupancy_penalty(self, target_key: str, count: int) -> float:
        if count <= 0:
            return 0.0
        if target_key.startswith("zone:fortress"):
            return 1.20 * count
        if target_key.startswith("zone:central"):
            return 1.00 * count
        if target_key.startswith("support:"):
            return 0.85 * count
        if target_key.startswith("robot:"):
            return 0.55 * count
        if target_key.startswith("structure:"):
            return 0.40 * count
        return 0.45 * count

    def _desired_rmuc_team_strategy(self, team_id: str) -> str:
        side = self._team_side(team_id)
        own_structures = [
            structure
            for structure in self.structures
            if structure.team == team_id and structure.type in {"base", "outpost"}
        ]
        enemies = [
            robot
            for robot in self.robots
            if robot.alive and robot.team != team_id and robot.type != "drone"
        ]
        field_scale = max(self.map.width, self.map.height)
        pressure = {
            structure.type: (
                structure,
                structure.hp / structure.max_hp if structure.max_hp else 0.0,
                min(
                    (math.dist(structure.position, enemy.position) for enemy in enemies),
                    default=field_scale,
                ),
            )
            for structure in own_structures
        }
        base = pressure.get("base")
        outpost = pressure.get("outpost")
        if (
            base is not None
            and base[0].alive
            and (
                base[1] <= 0.30
                or (
                    base[1] <= 0.55
                    and base[2] <= 320.0 * self.map.unit_scale
                )
            )
        ) or (
            outpost is not None
            and outpost[0].alive
            and (
                outpost[1] <= 0.18
                or (
                    outpost[1] <= 0.35
                    and outpost[2] <= 220.0 * self.map.unit_scale
                )
            )
        ):
            return "return"

        if any(
            structure.alive
            and (
                hp_ratio <= (0.45 if structure.type == "outpost" else 0.65)
                or (
                    hp_ratio <= 0.78
                    and nearest_enemy <= 380.0 * self.map.unit_scale
                )
            )
            for structure, hp_ratio, nearest_enemy in pressure.values()
        ):
            return "defend"

        if any(
            (robot.hp / robot.max_hp if robot.max_hp else 0.0) <= 0.25
            and self.ruleset.can_target(robot)
            for robot in enemies
        ):
            return "focus"

        engineer_alive = any(
            robot.alive and robot.team == team_id and robot.type == "engineer"
            for robot in self.robots
        )
        display_state = self.ruleset.display_state
        if engineer_alive and display_state is not None:
            core = next(
                (
                    (d1, d2, d3, d4, active)
                    for owner, _cap, d1, d2, d3, d4, active, _outside
                    in display_state.tech_core_status
                    if owner == team_id
                ),
                None,
            )
            if core is not None and (
                core[4] is not None or any(value == 0 for value in core[:4])
            ):
                return "tech"

        side_default = "assault" if side == "red" else "control"
        return side_default

    def _refresh_rmuc_team_strategies(self) -> None:
        if not self._rmuc_spectator_ai:
            return
        for team_id in sorted(self._rmuc_ai_team_strategies):
            desired = self._desired_rmuc_team_strategy(team_id)
            current = self._rmuc_ai_team_strategies[team_id]
            if desired == current:
                continue
            changed_at = self._rmuc_ai_strategy_changed_at[team_id]
            if (
                desired != "return"
                and self.elapsed_time - changed_at < _RMUC_AI_STRATEGY_STICKY_SECONDS
            ):
                continue
            self._rmuc_ai_team_strategies[team_id] = desired
            self._rmuc_ai_strategy_changed_at[team_id] = self.elapsed_time

    def _rmuc_candidate_bonus(self, robot: Robot, target_key: str) -> float:
        side = self._team_side(robot.team)
        strategy = self._rmuc_ai_team_strategies.get(
            robot.team,
            "assault" if side == "red" else "control",
        )
        bonus = 0.0
        is_structure = target_key.startswith("structure:")
        is_enemy_robot = target_key.startswith("robot:")
        is_defense = target_key.startswith("defense:")
        is_support = target_key.startswith("support:")
        is_control_zone = target_key.startswith(
            (
                "zone:central:",
                "zone:fortress:",
                "zone:trapezoid-buff:",
                "zone:outpost-buff:",
            )
        )

        if strategy == "focus" and is_enemy_robot:
            target_id = target_key.removeprefix("robot:")
            target = next(
                (item for item in self.robots if item.id == target_id),
                None,
            )
            if (
                target is not None
                and target.max_hp
                and target.hp / target.max_hp <= 0.45
            ):
                bonus += 0.85
        elif strategy == "tech" and is_support:
            bonus += 0.72
        elif strategy == "defend" and is_defense:
            bonus += 1.35
        elif strategy == "return" and is_defense:
            bonus += 3.4

        if strategy == "return":
            if is_structure or is_enemy_robot:
                bonus -= 0.85
        elif strategy == "defend" and is_structure:
            bonus -= 0.12

        # Both sides use the same candidates with a small style-weight shift.
        if side == "red":
            if is_structure or is_enemy_robot:
                bonus += 0.42
            elif target_key.startswith("zone:central:"):
                bonus -= 0.12
        else:
            if is_control_zone or is_defense:
                bonus += 0.42
            elif is_structure:
                bonus -= 0.18

        peers = sorted(
            (
                item
                for item in self.robots
                if item.team == robot.team and item.type == robot.type
            ),
            key=lambda item: item.id,
        )
        role_index = peers.index(robot) + 1 if robot in peers else 1
        if robot.type == "hero":
            bonus += 0.28 if is_structure else 0.0
        elif robot.type == "infantry":
            if role_index == 1:
                bonus += 0.28 if (is_enemy_robot or is_structure) else 0.0
                if is_control_zone:
                    bonus -= 0.12
            else:
                bonus += 0.35 if (is_control_zone or is_defense) else 0.0
                bonus += 0.22 if is_support else 0.0
                if is_enemy_robot:
                    bonus -= 0.28
                elif is_structure:
                    bonus -= 0.18
        elif robot.type == "sentry":
            bonus += (
                0.36
                if is_defense or target_key.startswith("zone:fortress:")
                else 0.0
            )
            if is_structure:
                bonus -= 0.24
        return bonus

    def _choose_utility_candidate(
        self,
        robot: Robot,
        candidates: list[tuple[str, str, tuple[float, float], float]],
    ) -> tuple[str, str, tuple[float, float], float] | None:
        if not candidates:
            return None

        rng = self._rmuc_ai_rng[robot.id]
        scored: list[
            tuple[float, str, str, tuple[float, float], float]
        ] = []
        for target_key, intent, goal, base_score in candidates:
            occupancy = self._ai_target_occupancy(robot, target_key)
            score = (
                base_score
                + self._rmuc_candidate_bonus(robot, target_key)
                - self._occupancy_penalty(target_key, occupancy)
                + (rng.random() * 2.0 - 1.0) * _RMUC_AI_SCORE_JITTER
            )
            scored.append((score, target_key, intent, goal, base_score))

        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        best = scored[0]
        current_key = self._ai_target_keys.get(robot.id)
        sticky_active = self.elapsed_time < self._ai_sticky_until.get(robot.id, 0.0)
        if sticky_active and current_key is not None and best[1] != current_key:
            current = next(
                (item for item in scored if item[1] == current_key),
                None,
            )
            if current is not None and best[0] < current[0] + _RMUC_AI_SWITCH_MARGIN:
                best = current

        score, target_key, intent, goal, base_score = best
        del score
        return target_key, intent, goal, base_score

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
                target_key=f"zone:assembly:{side}",
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
                target_key=f"zone:assembly:{side}",
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
                target_key=f"zone:resource:{side}",
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
            target_key=f"zone:assembly:{side}",
        )
        if assembly_zone.contains(robot.position):
            start = getattr(self.ruleset, "start_tech_core_assembly", None)
            if callable(start) and start(self, robot, difficulty) and difficulty < 4:
                confirm = getattr(self.ruleset, "confirm_tech_core_assembly", None)
                if callable(confirm):
                    confirm(self, robot)
        return True

    def _support_goal(
        self,
        engineer: Robot,
        protector: Robot,
    ) -> tuple[float, float]:
        combat_peers = sorted(
            (
                item
                for item in self.robots
                if (
                    item.team == protector.team
                    and item.type != "engineer"
                    and item.alive
                )
            ),
            key=lambda item: (item.type, item.id),
        )
        slot = combat_peers.index(protector) if protector in combat_peers else 0
        angles = (math.pi, math.pi / 2, -math.pi / 2, 0.0, 3 * math.pi / 4)
        angle = angles[slot % len(angles)]
        if self._team_side(protector.team) == "blue":
            angle = math.pi - angle
        distance = max(70.0 * self.map.unit_scale, self.map.collision_radius * 3.5)
        goal = (
            min(
                self.map.width,
                max(0.0, engineer.position[0] + math.cos(angle) * distance),
            ),
            min(
                self.map.height,
                max(0.0, engineer.position[1] + math.sin(angle) * distance),
            ),
        )
        return goal if self.map.is_passable(goal) else engineer.position

    def _defense_goal(
        self,
        robot: Robot,
        structure: Structure,
    ) -> tuple[float, float]:
        side = self._team_side(robot.team)
        zone = self._zone(
            f"{side}-outpost-buff"
            if structure.type == "outpost"
            else f"{side}-supply-buff"
        )
        return (
            self._zone_goal(zone, robot)
            if zone is not None
            else structure.position
        )

    def _rmuc_tactical_candidates(
        self,
        robot: Robot,
        display_state,
    ) -> list[tuple[str, str, tuple[float, float], float]]:
        side = self._team_side(robot.team)
        field_scale = max(self.map.width, self.map.height)
        candidates: list[tuple[str, str, tuple[float, float], float]] = []

        hp_ratio = robot.hp / robot.max_hp if robot.max_hp else 0.0
        supply_zone = self._zone(f"{side}-supply-buff")
        if supply_zone is not None:
            supply_goal = self._zone_goal(supply_zone, robot)
            if hp_ratio <= 0.45:
                candidates.append(
                    (
                        f"zone:supply:{side}",
                        "回撤补给",
                        supply_goal,
                        3.35 + max(0.0, 0.45 - hp_ratio) * 6.0,
                    )
                )
            candidates.append(
                (
                    f"zone:supply:{side}",
                    "前往补给区",
                    supply_goal,
                    0.30,
                )
            )

        enemy_robots = sorted(
            (
                target
                for target in self.robots
                if (
                    target.alive
                    and target.team != robot.team
                    and target.type != "drone"
                )
            ),
            key=lambda target: (target.type, target.id),
        )
        role_attack = {
            "hero": 1.05,
            "infantry": 1.25,
            "sentry": 0.85,
        }.get(robot.type, 0.10)
        target_value = {
            "hero": 0.70,
            "engineer": 0.58,
            "infantry": 0.52,
            "sentry": 0.44,
        }
        for target in enemy_robots:
            distance = math.dist(robot.position, target.position)
            distance_score = max(0.0, 0.78 * (1.0 - distance / field_scale))
            target_hp_ratio = (
                target.hp / target.max_hp if target.max_hp else 0.0
            )
            finish_bonus = 0.0
            intent = f"追击敌方{_RMUC_ROBOT_NAMES.get(target.type, target.type)}"
            if target_hp_ratio <= 0.30:
                finish_bonus = 1.15 + (0.30 - target_hp_ratio) * 2.0
                intent = "集火残血目标"
            elif target_hp_ratio <= 0.45:
                finish_bonus = (0.45 - target_hp_ratio) * 2.4
            candidates.append(
                (
                    f"robot:{target.id}",
                    intent,
                    target.position,
                    role_attack
                    + target_value.get(target.type, 0.45)
                    + distance_score
                    + finish_bonus,
                )
            )

        enemy_structures = [
            structure
            for structure in self.structures
            if structure.team != robot.team
        ]
        enemy_outpost = next(
            (
                structure
                for structure in enemy_structures
                if structure.type == "outpost"
            ),
            None,
        )
        outpost_alive = bool(enemy_outpost is not None and enemy_outpost.alive)
        structure_role_score = {
            "hero": {"outpost": 3.20, "base": 3.45},
            "infantry": {"outpost": 1.85, "base": 1.95},
            "sentry": {"outpost": 1.15, "base": 1.10},
        }.get(robot.type, {"outpost": 0.10, "base": 0.10})
        for structure in sorted(
            enemy_structures,
            key=lambda item: (item.type, item.id),
        ):
            if not structure.alive or not self.ruleset.can_target(structure):
                continue
            if structure.type == "base" and outpost_alive:
                score = 0.35
            else:
                score = structure_role_score.get(structure.type, 0.10)
                distance = math.dist(robot.position, structure.position)
                score += max(0.0, 0.35 * (1.0 - distance / field_scale))
            intent = (
                "进攻前哨站"
                if structure.type == "outpost"
                else "进攻基地"
            )
            candidates.append(
                (
                    f"structure:{structure.id}",
                    intent,
                    structure.position,
                    score,
                )
            )

        own_structures = sorted(
            (
                structure
                for structure in self.structures
                if structure.team == robot.team and structure.alive
            ),
            key=lambda item: (item.type, item.id),
        )
        role_defense = {
            "hero": 0.35,
            "infantry": 0.90,
            "sentry": 1.55,
        }.get(robot.type, 0.0)
        if role_defense > 0:
            for structure in own_structures:
                hp_fraction = (
                    structure.hp / structure.max_hp
                    if structure.max_hp
                    else 0.0
                )
                nearest_enemy = min(
                    (
                        math.dist(structure.position, enemy.position)
                        for enemy in enemy_robots
                    ),
                    default=field_scale,
                )
                threatened = (
                    hp_fraction <= 0.70
                    or nearest_enemy <= 460.0 * self.map.unit_scale
                )
                if not threatened:
                    continue
                threat_score = (
                    max(0.0, 0.70 - hp_fraction) * 2.2
                    + max(
                        0.0,
                        1.20 - nearest_enemy / (460.0 * self.map.unit_scale),
                    )
                )
                candidates.append(
                    (
                        f"defense:{structure.id}",
                        (
                            "防守前哨站"
                            if structure.type == "outpost"
                            else "防守基地"
                        ),
                        self._defense_goal(robot, structure),
                        role_defense + threat_score,
                    )
                )

        engineer = next(
            (
                teammate
                for teammate in self.robots
                if (
                    teammate.team == robot.team
                    and teammate.type == "engineer"
                    and teammate.alive
                )
            ),
            None,
        )
        if (
            engineer is not None
            and robot.type != "engineer"
            and self._ai_intents.get(engineer.id) == "装配科技核心"
        ):
            support_score = {
                "hero": 1.35,
                "infantry": 1.95,
                "sentry": 1.30,
            }.get(robot.type, 0.0)
            engineer_hp_ratio = (
                engineer.hp / engineer.max_hp
                if engineer.max_hp
                else 0.0
            )
            support_score += max(0.0, 0.55 - engineer_hp_ratio) * 1.5
            candidates.append(
                (
                    f"support:{engineer.id}",
                    "保护工程",
                    self._support_goal(engineer, robot),
                    support_score,
                )
            )

        central = self._zone(f"{side}-central-elevated-buff")
        central_score = {
            "hero": 0.65,
            "infantry": 1.35,
            "sentry": 0.95,
        }.get(robot.type, 0.0)
        if central is not None and central_score > 0:
            candidates.append(
                (
                    f"zone:central:{side}",
                    "前往中央区域",
                    self._zone_goal(central, robot),
                    central_score,
                )
            )

        if robot.type in {"infantry", "sentry"}:
            own_outpost = next(
                (
                    structure
                    for structure in self.structures
                    if structure.team == robot.team and structure.type == "outpost"
                ),
                None,
            )
            structure_status = {
                structure_id: status
                for structure_id, _hp, _max_hp, status
                in display_state.structure_statuses
            }
            fortress_ready = own_outpost is not None and (
                not own_outpost.alive
                or "REBUILT" in structure_status.get(own_outpost.id, "")
            )
            fortress = self._zone(f"{side}-fortress-buff")
            if fortress_ready and fortress is not None:
                fortress_score = (
                    2.35 if robot.type == "infantry" else 2.65
                )
                candidates.append(
                    (
                        f"zone:fortress:{side}",
                        "占领堡垒",
                        self._zone_goal(fortress, robot),
                        fortress_score,
                    )
                )

        for suffix in ("trapezoid-buff", "outpost-buff"):
            zone = self._zone(f"{side}-{suffix}")
            if zone is not None and robot.type in {"infantry", "sentry"}:
                candidates.append(
                    (
                        f"zone:{suffix}:{side}",
                        "前往防御增益区",
                        self._zone_goal(zone, robot),
                        0.58 if robot.type == "infantry" else 0.78,
                    )
                )

        return candidates

    def _rmuc_drone_ai_step(self, robot: Robot, display_state) -> None:
        allowance = {
            robot_id: count
            for robot_id, _projectile, count in display_state.robot_projectiles
        }.get(robot.id, 0)
        active = bool(
            getattr(self.ruleset, "drone_air_support_active", lambda _id: False)(
                robot.id
            )
        )
        available = float(
            getattr(self.ruleset, "drone_air_support_available", lambda _id: 0.0)(
                robot.id
            )
        )
        team_coins = dict(display_state.coins).get(robot.team, 0)

        if not active:
            self._clear_ai_path(robot)
            if allowance <= 0:
                self._ai_intents[robot.id] = "空中弹量耗尽"
                self._remember_ai_decision(robot, None, sticky=False)
                return
            if available <= 1e-9 and team_coins <= 0:
                self._ai_intents[robot.id] = "等待空中支援"
                self._remember_ai_decision(robot, None, sticky=False)
                return
            start = getattr(self.ruleset, "start_drone_air_support", None)
            started = bool(callable(start) and start(self, robot))
            self._ai_intents[robot.id] = (
                "金币续航空中支援"
                if started and available <= 1e-9
                else "发起空中支援"
                if started
                else "等待空中支援"
            )
            self._remember_ai_decision(robot, None, sticky=False)
            return

        if allowance <= 0:
            pause = getattr(self.ruleset, "pause_drone_air_support", None)
            if callable(pause):
                pause(robot)
            self._ai_intents[robot.id] = "空中弹量耗尽"
            self._remember_ai_decision(robot, None, sticky=False)
            return

        field_scale = max(self.map.width, self.map.height)
        candidates: list[tuple[str, str, tuple[float, float], float]] = []
        for target in sorted(
            (
                item
                for item in self.robots
                if (
                    item.alive
                    and item.team != robot.team
                    and item.type != "drone"
                    and self.ruleset.can_target(item)
                )
            ),
            key=lambda item: (item.type, item.id),
        ):
            distance = math.dist(robot.position, target.position)
            hp_ratio = target.hp / target.max_hp if target.max_hp else 1.0
            role_value = {
                "engineer": 1.95,
                "hero": 1.55,
                "sentry": 1.35,
                "infantry": 1.25,
            }.get(target.type, 1.0)
            finish = (
                1.15 + max(0.0, 0.30 - hp_ratio) * 2.0
                if hp_ratio <= 0.30
                else 0.0
            )
            distance_score = max(0.0, 0.75 * (1.0 - distance / field_scale))
            intent = (
                "空中压制残血目标"
                if hp_ratio <= 0.30
                else f"空中压制敌方{_RMUC_ROBOT_NAMES.get(target.type, target.type)}"
            )
            candidates.append(
                (
                    f"robot:{target.id}",
                    intent,
                    target.position,
                    role_value + finish + distance_score,
                )
            )

        for structure in sorted(
            (
                item
                for item in self.structures
                if (
                    item.alive
                    and item.team != robot.team
                    and self.ruleset.can_target(item)
                )
            ),
            key=lambda item: (item.type, item.id),
        ):
            candidates.append(
                (
                    f"structure:{structure.id}",
                    (
                        "空中压制前哨站"
                        if structure.type == "outpost"
                        else "空中压制基地"
                    ),
                    structure.position,
                    1.75 if structure.type == "outpost" else 1.90,
                )
            )

        choice = self._choose_utility_candidate(robot, candidates)
        if choice is None:
            self._clear_ai_path(robot)
            self._ai_intents[robot.id] = "空中巡弋待命"
            self._remember_ai_decision(robot, None, sticky=False)
            return

        target_key, intent, goal, _score = choice
        if (
            math.dist(robot.position, goal) <= robot.attack_range
            and self._has_line_of_sight_to_ai_target(
                robot.position,
                goal,
                target_key,
            )
        ):
            self._clear_ai_path(robot)
            self._ai_intents[robot.id] = intent
            self._remember_ai_decision(robot, target_key)
            return
        self._set_ai_goal(
            robot,
            intent,
            goal,
            target_key=target_key,
        )

    def _rmuc_ai_step(self, robot: Robot, display_state) -> None:
        if robot.type == "drone":
            self._rmuc_drone_ai_step(robot, display_state)
            return
        if not robot.alive:
            self._clear_ai_path(robot)
            self._ai_intents[robot.id] = "等待复活"
            self._remember_ai_decision(robot, None, sticky=False)
            return

        side = self._team_side(robot.team)
        supply_zone = self._zone(f"{side}-supply-buff")
        if supply_zone is None:
            self._clear_ai_path(robot)
            self._ai_intents[robot.id] = "待机"
            self._remember_ai_decision(robot, None, sticky=False)
            return
        supply_goal = self._zone_goal(supply_zone, robot)
        hp_ratio = robot.hp / robot.max_hp if robot.max_hp else 0.0

        if hp_ratio <= 0.28 or (robot.type == "engineer" and hp_ratio <= 0.40):
            self._set_ai_goal(
                robot,
                "回撤补给",
                supply_goal,
                target_key=f"zone:supply:{side}",
                sticky=False,
            )
            return

        if robot.type == "engineer":
            if self._rmuc_engineer_step(robot, display_state):
                return
            self._set_ai_goal(
                robot,
                "后方待命",
                supply_goal,
                target_key=f"zone:supply:{side}",
            )
            return

        projectiles = {
            robot_id: count
            for robot_id, _projectile, count in display_state.robot_projectiles
        }
        ammo = projectiles.get(robot.id)
        low_ammo = ammo is not None and ammo <= (0 if robot.type == "hero" else 8)
        if low_ammo:
            if supply_zone.contains(robot.position):
                exchange = getattr(self.ruleset, "exchange_projectiles", None)
                purchased = bool(callable(exchange) and exchange(self, robot))
                self._clear_ai_path(robot)
                self._ai_intents[robot.id] = (
                    "补充弹量" if purchased else "等待补给"
                )
                self._remember_ai_decision(
                    robot,
                    f"zone:supply:{side}",
                    sticky=False,
                )
            else:
                self._set_ai_goal(
                    robot,
                    "前往补给区",
                    supply_goal,
                    target_key=f"zone:supply:{side}",
                    sticky=False,
                )
            return

        candidates = self._rmuc_tactical_candidates(robot, display_state)
        choice = self._choose_utility_candidate(robot, candidates)
        if choice is None:
            self._clear_ai_path(robot)
            self._ai_intents[robot.id] = "待机"
            self._remember_ai_decision(robot, None, sticky=False)
            return

        target_key, intent, goal, _score = choice
        target_is_attackable = target_key.startswith(("robot:", "structure:"))
        if target_is_attackable:
            distance = math.dist(robot.position, goal)
            if (
                distance <= robot.attack_range
                and self._has_line_of_sight_to_ai_target(
                    robot.position,
                    goal,
                    target_key,
                )
            ):
                self._clear_ai_path(robot)
                self._ai_intents[robot.id] = intent
                self._remember_ai_decision(robot, target_key)
                return

        self._set_ai_goal(
            robot,
            intent,
            goal,
            target_key=target_key,
        )

    def _update_rmuc_radar_ai(self, dt: float, display_state) -> None:
        set_laser = getattr(self.ruleset, "set_radar_anti_drone_laser", None)
        if not callable(set_laser):
            return

        support_by_robot = {
            robot_id: active
            for robot_id, active, _remaining in display_state.drone_air_support
        }
        anti_drone = {
            robot_id: (
                source_team_id,
                lock_remaining,
                remaining_uses,
            )
            for (
                robot_id,
                source_team_id,
                _progress,
                _threshold,
                lock_remaining,
                _activations,
                remaining_uses,
                _illuminated,
            ) in display_state.radar_anti_drone
        }
        drones = {
            robot.team: robot
            for robot in self.robots
            if robot.type == "drone"
        }

        for source_team_id in sorted(self._rmuc_radar_ai_elapsed):
            target = next(
                (
                    drone
                    for team_id, drone in sorted(drones.items())
                    if team_id != source_team_id
                ),
                None,
            )
            state = anti_drone.get(target.id) if target is not None else None
            eligible = bool(
                target is not None
                and state is not None
                and state[0] == source_team_id
                and support_by_robot.get(target.id, False)
                and state[1] <= 1e-9
                and state[2] > 0
            )

            elapsed = self._rmuc_radar_ai_elapsed[source_team_id] + dt
            if not eligible:
                self._rmuc_radar_ai_laser_active[source_team_id] = False
                elapsed = 0.0
            elif elapsed >= _RMUC_AI_REPLAN_INTERVAL:
                ticks = int(elapsed // _RMUC_AI_REPLAN_INTERVAL)
                elapsed %= _RMUC_AI_REPLAN_INTERVAL
                rng = self._rmuc_ai_rng[f"radar:{source_team_id}"]
                for _ in range(ticks):
                    self._rmuc_radar_ai_laser_active[source_team_id] = (
                        rng.random() < 0.80
                    )

            self._rmuc_radar_ai_elapsed[source_team_id] = elapsed
            if target is not None:
                set_laser(
                    source_team_id,
                    target,
                    self._rmuc_radar_ai_laser_active[source_team_id] and eligible,
                )

    def _update_ai(self, dt: float) -> None:
        if self._rmuc_spectator_ai:
            dart_ai = getattr(self.ruleset, "update_dart_ai", None)
            if callable(dart_ai):
                dart_ai(self)
            display_state = self.ruleset.display_state
            if display_state is None:
                return
            self._refresh_rmuc_team_strategies()
            self._update_rmuc_radar_ai(dt, display_state)
            for robot in sorted(self.robots, key=lambda item: item.id):
                elapsed = self._ai_replan_elapsed[robot.id] + dt
                if not robot.alive:
                    self._rmuc_ai_step(robot, display_state)
                    self._ai_replan_elapsed[robot.id] = (
                        elapsed % _RMUC_AI_REPLAN_INTERVAL
                    )
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
                self._clear_ai_path(robot)
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
                self._clear_ai_path(robot)
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
