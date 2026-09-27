"""Partial RMUL 2026 rules for VP, control zones, and respawn lifecycle."""

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, Any, Mapping

from tarsgo_simulator.core.config import ConfigError, RuleDocument, load_rule_document
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.map import Zone
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.protocol import (
    MatchResult,
    RobotParameters,
    RuleSetDisplayState,
)
from tarsgo_simulator.rules.training_v0 import TrainingV0Rules


@dataclass
class _RobotLifecycle:
    death_count: int = 0
    respawn_progress: float = 0.0
    respawn_required: float | None = None
    weak: bool = False
    invincible_remaining: float = 0.0
    healing_hp_fraction: float = 0.0


class RMUL2026Rules:
    def __init__(self, document: RuleDocument) -> None:
        if document.metadata.status != "official-partial":
            raise ConfigError(
                f"{document.path}: rmul-2026-3v3 requires `status: official-partial`"
            )
        if document.metadata.official_version != "1.2.0":
            raise ConfigError(
                f"{document.path}: this implementation is verified against manual V1.2.0"
            )

        self._document = document
        self._time_limit = _number(document.data, "match_duration", document)
        victory_points = _mapping(document.data, "victory_points", document)
        self._initial_victory_points = _integer(
            victory_points, "initial", document, "victory_points.initial"
        )
        self._control_drain_per_second = _integer(
            victory_points,
            "control_drain_per_second",
            document,
            "victory_points.control_drain_per_second",
        )
        self._robot_destroyed_penalty = _integer(
            victory_points,
            "robot_destroyed_penalty",
            document,
            "victory_points.robot_destroyed_penalty",
        )
        control_zone = _mapping(document.data, "control_zone", document)
        self._control_zone_id = _string(control_zone, "id", document, "control_zone.id")
        self._control_loss_delay = _number(
            control_zone, "loss_delay", document, "control_zone.loss_delay"
        )

        respawn = _mapping(document.data, "respawn", document)
        self._initial_respawn_progress = _number(
            respawn,
            "initial_progress_required",
            document,
            "respawn.initial_progress_required",
        )
        self._additional_respawn_progress_per_death = _number(
            respawn,
            "additional_progress_per_death",
            document,
            "respawn.additional_progress_per_death",
        )
        self._respawn_progress_per_second = _number(
            respawn,
            "progress_per_second",
            document,
            "respawn.progress_per_second",
        )
        self._respawn_hp_fraction = _fraction(
            respawn, "hp_fraction", document, "respawn.hp_fraction"
        )
        self._invincibility_duration = _number(
            respawn,
            "invincibility_duration",
            document,
            "respawn.invincibility_duration",
        )
        supply = _mapping(document.data, "supply", document)
        self._supply_heal_fraction_per_second = _fraction(
            supply,
            "heal_fraction_per_second",
            document,
            "supply.heal_fraction_per_second",
        )
        supply_zones = _mapping(document.data, "supply_zones", document)
        self._supply_zone_ids = {
            side: _string(supply_zones, side, document, f"supply_zones.{side}")
            for side in ("red", "blue")
        }
        if len(set(self._supply_zone_ids.values())) != 2:
            raise ConfigError(f"{document.path}: red / blue 补给区必须使用不同的 zone id")

        parameter_profile = _string(
            document.data, "lab_parameter_profile", document, "lab_parameter_profile"
        )
        if parameter_profile != "training-v0":
            raise ConfigError(
                f"{document.path}: rules lab currently requires `lab_parameter_profile: training-v0`"
            )
        profile_document = load_rule_document(
            document.path.with_name(f"{parameter_profile}.yaml"), parameter_profile
        )
        self._lab_parameters = TrainingV0Rules(profile_document)

        self.victory_points: dict[str, int] = {}
        self.control_owner: str | None = None
        self._control_loss_elapsed = 0.0
        self._control_tick_accumulator = 0.0
        self._previous_zone_teams: set[str] = set()
        self._robot_lifecycles: dict[str, _RobotLifecycle] = {}
        self._supply_zones: dict[str, Zone] = {}

    @property
    def time_limit(self) -> float:
        return self._time_limit

    @property
    def display_state(self) -> RuleSetDisplayState:
        robot_statuses = []
        for robot_id, lifecycle in sorted(self._robot_lifecycles.items()):
            if lifecycle.respawn_required is not None:
                status = (
                    f"RESP {lifecycle.respawn_progress:.1f}/"
                    f"{lifecycle.respawn_required:g}"
                )
            elif lifecycle.weak and lifecycle.invincible_remaining > 0:
                status = f"WEAK INV {math.ceil(lifecycle.invincible_remaining)}s"
            elif lifecycle.weak:
                status = "WEAK"
            elif lifecycle.invincible_remaining > 0:
                status = f"INV {math.ceil(lifecycle.invincible_remaining)}s"
            else:
                continue
            robot_statuses.append((robot_id, status))
        return RuleSetDisplayState(
            victory_points=tuple(sorted(self.victory_points.items())),
            control_owner=self.control_owner,
            robot_statuses=tuple(robot_statuses),
            attack_damage=tuple(sorted(self.attack_damage_by_team.items())),
        )

    def robot_parameters(self, robot_type: str) -> RobotParameters:
        """Use the explicitly synthetic infantry profile in the rules lab."""
        return self._lab_parameters.robot_parameters(robot_type)

    def can_attack(self, robot: Robot) -> bool:
        lifecycle = self._robot_lifecycles.get(robot.id)
        return robot.alive and (lifecycle is None or not lifecycle.weak)

    def can_receive_damage(self, robot: Robot) -> bool:
        lifecycle = self._robot_lifecycles.get(robot.id)
        return robot.alive and (
            lifecycle is None or lifecycle.invincible_remaining <= 0
        )

    def reset(self, match: "Match") -> None:
        zones = [zone for zone in match.map.zones if zone.id == self._control_zone_id]
        if len(zones) != 1:
            raise ConfigError(
                f"{self._document.path}: scenario must define exactly one map zone "
                f"with id `{self._control_zone_id}`"
            )
        self._control_zone = zones[0]
        zones_by_id = {zone.id: zone for zone in match.map.zones}
        missing_supply_zones = sorted(
            set(self._supply_zone_ids.values()) - set(zones_by_id)
        )
        if missing_supply_zones:
            missing = ", ".join(missing_supply_zones)
            raise ConfigError(
                f"{self._document.path}: scenario 缺少补给区 map zones：{missing}"
            )
        self._supply_zones = {
            match.config.scenario.teams[side].team_id: zones_by_id[zone_id]
            for side, zone_id in self._supply_zone_ids.items()
        }
        self._robot_lifecycles = {
            robot.id: _RobotLifecycle() for robot in match.robots
        }
        self.victory_points = {
            team.team_id: self._initial_victory_points
            for team in match.config.scenario.teams.values()
        }
        self.attack_damage_by_team = dict.fromkeys(self.victory_points, 0)
        self.control_owner = None
        self._control_loss_elapsed = 0.0
        self._control_tick_accumulator = 0.0
        self._previous_zone_teams = set()

    def update(self, match: "Match", dt: float) -> None:
        # Apply every same-frame fact before Match asks this ruleset for a result.
        newly_destroyed: set[str] = set()
        for event in match.current_events:
            if event.type == MatchEventType.ROBOT_DAMAGED:
                if (
                    event.attacker_team_id in self.attack_damage_by_team
                    and event.damage > 0
                ):
                    self.attack_damage_by_team[event.attacker_team_id] += event.damage
                continue
            if event.type != MatchEventType.ROBOT_DESTROYED:
                continue
            lifecycle = self._robot_lifecycles.get(event.robot_id)
            if lifecycle is not None:
                lifecycle.death_count += 1
                lifecycle.respawn_progress = 0.0
                lifecycle.respawn_required = self._initial_respawn_progress + (
                    lifecycle.death_count - 1
                ) * self._additional_respawn_progress_per_death
                lifecycle.weak = False
                lifecycle.invincible_remaining = 0.0
                newly_destroyed.add(event.robot_id)
            if event.team_id in self.victory_points:
                self.victory_points[event.team_id] = max(
                    0,
                    self.victory_points[event.team_id] - self._robot_destroyed_penalty,
                )

        frame_start = match.elapsed_time - dt
        active_dt = max(0.0, min(dt, self._time_limit - frame_start))
        alive_before_lifecycle = {robot.id: robot.alive for robot in match.robots}
        self._advance_robot_lifecycles(match, active_dt, newly_destroyed)
        newly_respawned = {
            robot.id
            for robot in match.robots
            if robot.alive and not alive_before_lifecycle[robot.id]
        }
        self._advance_supply_healing(match, active_dt, newly_respawned)
        present_teams = {
            robot.team
            for robot in match.robots
            if robot.alive
            and not self._robot_lifecycles[robot.id].weak
            and self._control_zone.contains(robot.position)
        }
        entering_teams = present_teams - self._previous_zone_teams
        self._advance_control(present_teams, entering_teams, active_dt)
        self._previous_zone_teams = present_teams

    def _advance_robot_lifecycles(
        self,
        match: "Match",
        dt: float,
        newly_destroyed: set[str],
    ) -> None:
        for robot in match.robots:
            lifecycle = self._robot_lifecycles[robot.id]
            if not robot.alive:
                # The robot died during this frame. Start accumulating next frame.
                if robot.id in newly_destroyed or lifecycle.respawn_required is None:
                    continue
                lifecycle.respawn_progress += dt * self._respawn_progress_per_second
                if lifecycle.respawn_progress + 1e-9 < lifecycle.respawn_required:
                    continue

                robot.alive = True
                # HP is an integer in the Engine; positive fractional values round down.
                robot.hp = max(1, int(robot.max_hp * self._respawn_hp_fraction))
                robot.path.clear()
                lifecycle.respawn_progress = 0.0
                lifecycle.respawn_required = None
                lifecycle.weak = True
                lifecycle.invincible_remaining = self._invincibility_duration
                continue

            lifecycle.invincible_remaining = max(
                0.0, lifecycle.invincible_remaining - dt
            )
            supply_zone = self._supply_zones[robot.team]
            if lifecycle.weak and supply_zone.contains(robot.position):
                lifecycle.weak = False
                lifecycle.invincible_remaining = 0.0

    def _advance_supply_healing(
        self,
        match: "Match",
        dt: float,
        newly_respawned: set[str],
    ) -> None:
        for robot in match.robots:
            lifecycle = self._robot_lifecycles[robot.id]
            supply_zone = self._supply_zones[robot.team]
            if robot.id in newly_respawned:
                lifecycle.healing_hp_fraction = 0.0
                continue
            if not robot.alive or not supply_zone.contains(robot.position):
                lifecycle.healing_hp_fraction = 0.0
                continue
            if robot.hp >= robot.max_hp:
                lifecycle.healing_hp_fraction = 0.0
                continue

            lifecycle.healing_hp_fraction += (
                dt * robot.max_hp * self._supply_heal_fraction_per_second
            )
            healing_points = math.floor(lifecycle.healing_hp_fraction + 1e-9)
            if healing_points <= 0:
                continue

            robot.hp = min(robot.max_hp, robot.hp + healing_points)
            if robot.hp >= robot.max_hp:
                lifecycle.healing_hp_fraction = 0.0
            else:
                lifecycle.healing_hp_fraction = max(
                    0.0, lifecycle.healing_hp_fraction - healing_points
                )

    def _advance_control(
        self,
        present_teams: set[str],
        entering_teams: set[str],
        dt: float,
    ) -> None:
        if self.control_owner is None:
            self._control_loss_elapsed = 0.0
            if not present_teams:
                self._control_tick_accumulator = 0.0
                return
            self.control_owner = self._choose_claimant(entering_teams or present_teams)
            self._control_tick_accumulator = 0.0
            self._apply_control_time(self.control_owner, dt)
            return

        if self.control_owner in present_teams:
            self._control_loss_elapsed = 0.0
            self._apply_control_time(self.control_owner, dt)
            return

        held_time = min(dt, max(0.0, self._control_loss_delay - self._control_loss_elapsed))
        self._control_loss_elapsed += dt
        self._apply_control_time(self.control_owner, held_time)
        if self._control_loss_elapsed + 1e-9 < self._control_loss_delay:
            return

        self.control_owner = None
        self._control_loss_elapsed = 0.0
        self._control_tick_accumulator = 0.0
        remaining_time = max(0.0, dt - held_time)
        if present_teams:
            self.control_owner = self._choose_claimant(entering_teams or present_teams)
            self._apply_control_time(self.control_owner, remaining_time)

    def _apply_control_time(self, owner: str, dt: float) -> None:
        if dt <= 0:
            return
        self._control_tick_accumulator += dt
        ticks = math.floor(self._control_tick_accumulator + 1e-9)
        if ticks <= 0:
            return
        self._control_tick_accumulator = max(0.0, self._control_tick_accumulator - ticks)
        for team_id in self.victory_points:
            if team_id != owner:
                self.victory_points[team_id] = max(
                    0,
                    self.victory_points[team_id]
                    - ticks * self._control_drain_per_second,
                )

    @staticmethod
    def _choose_claimant(candidates: set[str]) -> str:
        # Frame-sampled arrivals cannot reveal order within a frame; team id is
        # the documented, stable tie-break and does not depend on robot order.
        return min(candidates)

    def evaluate_result(self, match: "Match") -> MatchResult | None:
        teams_at_zero = [
            team_id for team_id, points in self.victory_points.items() if points <= 0
        ]
        if teams_at_zero:
            remaining = [
                team_id for team_id, points in self.victory_points.items() if points > 0
            ]
            return MatchResult(remaining[0] if len(remaining) == 1 else None)

        if match.elapsed_time < self.time_limit:
            return None

        highest = max(self.victory_points.values())
        leaders = [
            team_id for team_id, points in self.victory_points.items() if points == highest
        ]
        if len(leaders) == 1:
            return MatchResult(leaders[0])

        highest_damage = max(self.attack_damage_by_team.values())
        damage_leaders = [
            team_id
            for team_id, damage in self.attack_damage_by_team.items()
            if damage == highest_damage
        ]
        if len(damage_leaders) == 1:
            return MatchResult(damage_leaders[0])

        remaining_hp = {
            team.team_id: sum(
                robot.hp for robot in match.robots if robot.team == team.team_id
            )
            for team in match.config.scenario.teams.values()
        }
        highest_hp = max(remaining_hp.values())
        hp_leaders = [
            team_id for team_id, hp in remaining_hp.items() if hp == highest_hp
        ]
        return MatchResult(hp_leaders[0] if len(hp_leaders) == 1 else None)


def _mapping(data: Mapping[str, Any], key: str, document: RuleDocument) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{document.path}: `{key}` 必须是 YAML 字典")
    return value


def _string(
    data: Mapping[str, Any], key: str, document: RuleDocument, field: str
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{document.path}: `{field}` 必须是非空字符串")
    return value.strip()


def _number(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str | None = None,
) -> float:
    value = data.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigError(f"{document.path}: `{field or key}` 必须是大于 0 的数字")
    return float(value)


def _integer(
    data: Mapping[str, Any], key: str, document: RuleDocument, field: str
) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{document.path}: `{field}` 必须是正整数")
    return value


def _fraction(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> float:
    value = data.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 < value <= 1
    ):
        raise ConfigError(f"{document.path}: `{field}` 必须在 0 和 1 之间（含 1）")
    return float(value)


if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match
