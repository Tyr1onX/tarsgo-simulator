"""Partial RMUL 2026 rules for the VP and central control-zone slice."""

import math
from typing import TYPE_CHECKING, Any, Mapping

from tarsgo_simulator.core.config import ConfigError, RuleDocument, load_rule_document
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.rules.protocol import (
    MatchResult,
    RobotParameters,
    RuleSetDisplayState,
)
from tarsgo_simulator.rules.training_v0 import TrainingV0Rules


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

    @property
    def time_limit(self) -> float:
        return self._time_limit

    @property
    def display_state(self) -> RuleSetDisplayState:
        return RuleSetDisplayState(
            victory_points=tuple(sorted(self.victory_points.items())),
            control_owner=self.control_owner,
        )

    def robot_parameters(self, robot_type: str) -> RobotParameters:
        """Use the explicitly synthetic infantry profile in the rules lab."""
        return self._lab_parameters.robot_parameters(robot_type)

    def reset(self, match: "Match") -> None:
        zones = [zone for zone in match.map.zones if zone.id == self._control_zone_id]
        if len(zones) != 1:
            raise ConfigError(
                f"{self._document.path}: scenario must define exactly one map zone "
                f"with id `{self._control_zone_id}`"
            )
        self._control_zone = zones[0]
        self.victory_points = {
            team.team_id: self._initial_victory_points
            for team in match.config.scenario.teams.values()
        }
        self.control_owner = None
        self._control_loss_elapsed = 0.0
        self._control_tick_accumulator = 0.0
        self._previous_zone_teams = set()

    def update(self, match: "Match", dt: float) -> None:
        # Apply every same-frame fact before Match asks this ruleset for a result.
        for event in match.current_events:
            if (
                event.type == MatchEventType.ROBOT_DESTROYED
                and event.team_id in self.victory_points
            ):
                self.victory_points[event.team_id] = max(
                    0,
                    self.victory_points[event.team_id] - self._robot_destroyed_penalty,
                )

        frame_start = match.elapsed_time - dt
        active_dt = max(0.0, min(dt, self._time_limit - frame_start))
        present_teams = {
            robot.team
            for robot in match.robots
            if robot.alive and self._control_zone.contains(robot.position)
        }
        entering_teams = present_teams - self._previous_zone_teams
        self._advance_control(present_teams, entering_teams, active_dt)
        self._previous_zone_teams = present_teams

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
        # V1.2.0 next compares team damage, then total HP. Damage statistics do
        # not exist in the Engine yet, so this partial ruleset reports a draw.
        return MatchResult(leaders[0] if len(leaders) == 1 else None)


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


if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match
