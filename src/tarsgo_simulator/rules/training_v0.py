"""Synthetic sandbox rules retained for tutorials and engine tests."""

import math
from typing import TYPE_CHECKING, Any, Mapping

from tarsgo_simulator.core.config import ConfigError, RuleDocument
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.protocol import MatchResult, RobotParameters, RuleSetDisplayState


class TrainingV0Rules:
    def __init__(self, document: RuleDocument) -> None:
        if document.metadata.status != "synthetic":
            raise ConfigError(
                f"{document.path}: training-v0 requires `status: synthetic`; "
                "it does not represent official rules"
            )
        data = document.data
        infantry = _mapping(data, "infantry", document)
        self._infantry = RobotParameters(
            max_hp=_number(infantry, "max_hp", document, integer=True),
            move_speed=_number(infantry, "move_speed", document),
            collision_radius=_number(infantry, "collision_radius", document),
            attack_range=_number(infantry, "attack_range", document),
            attack_interval=_number(infantry, "attack_interval", document),
            damage=_number(infantry, "damage", document, integer=True),
        )
        self._time_limit = _number(data, "match_duration", document, field="match_duration")

    @property
    def time_limit(self) -> float:
        return self._time_limit

    @property
    def display_state(self) -> RuleSetDisplayState | None:
        return None

    def robot_parameters(self, robot_type: str) -> RobotParameters:
        if robot_type != "infantry":
            raise ConfigError(f"training-v0 不支持机器人类型 `{robot_type}`")
        return self._infantry

    def can_move(self, robot: Robot) -> bool:
        return robot.alive

    def can_attack(self, robot: Robot) -> bool:
        return robot.alive

    def on_attack_committed(self, robot: Robot) -> None:
        """Training V0 has no limited projectile resource."""

    def exchange_projectiles(self, match: "Match", robot: Robot) -> bool:
        """Training V0 has no economy or projectile exchange."""
        return False

    def can_receive_damage(self, robot: Robot) -> bool:
        return robot.alive

    def prepare_movement(self, match: "Match", dt: float) -> None:
        """Training V0 has no chassis buffer state to advance."""

    def prepare_combat(self, match: "Match", dt: float) -> None:
        """Training V0 has no shooting heat to advance."""

    def reset(self, match: "Match") -> None:
        """Training V0 keeps no state outside the Match."""

    def update(self, match: "Match", dt: float) -> None:
        """Training V0 has no per-frame rule state to advance."""

    def evaluate_result(self, match: "Match") -> MatchResult | None:
        living_teams = {robot.team for robot in match.robots if robot.alive}
        if len(living_teams) <= 1:
            return MatchResult(next(iter(living_teams), None))

        if match.elapsed_time >= self.time_limit:
            hp_by_team = {
                team.team_id: sum(
                    robot.hp for robot in match.robots if robot.team == team.team_id
                )
                for team in match.config.scenario.teams.values()
            }
            highest_hp = max(hp_by_team.values())
            leaders = [team_id for team_id, hp in hp_by_team.items() if hp == highest_hp]
            return MatchResult(leaders[0] if len(leaders) == 1 else None)
        return None


def _mapping(data: Mapping[str, Any], key: str, document: RuleDocument) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{document.path}: `{key}` 必须是 YAML 字典")
    return value


def _number(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    *,
    integer: bool = False,
    field: str | None = None,
) -> int | float:
    value = data.get(key)
    valid_type = isinstance(value, int) if integer else isinstance(value, (int, float))
    valid = valid_type and not isinstance(value, bool) and math.isfinite(value)
    if not valid or value <= 0:
        kind = "正整数" if integer else "大于 0 的数字"
        field_name = field or f"infantry.{key}"
        raise ConfigError(f"{document.path}: `{field_name}` 必须是{kind}")
    return value


if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match
