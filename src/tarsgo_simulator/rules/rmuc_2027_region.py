"""RMUC 2027 P1 startup and roster scaffold; match mechanics are not implemented."""

from collections import Counter
import math
from typing import TYPE_CHECKING, Any

from tarsgo_simulator.core.config import ConfigError, RuleDocument
from tarsgo_simulator.rules.protocol import (
    DamageableTarget,
    DamageResolution,
    MatchResult,
    RobotParameters,
    RuleSetDisplayState,
    StructureParameters,
)

if TYPE_CHECKING:
    from tarsgo_simulator.core.config import ScenarioDefinition
    from tarsgo_simulator.core.match import Match
    from tarsgo_simulator.core.robot import Robot


RMUC_2027_RULE_ID = "rmuc-2027-region-v1.0.0"
_GROUND_ROSTER = {"heavy": 1, "infantry": 2, "sentry": 1}
_SYSTEM_ROSTER = {
    "air": {"hangar": 1, "aircraft": 4},
    "dart": {"launcher": 1, "dart_bodies": 4},
    "radar": {"computing_platform": 1, "sensor": 1},
}


class RMUC2027RegionRules:
    """A deliberately restricted ruleset for P1 scenario and reset validation.

    Only the official match duration and active roster are represented. The
    small physical profile in the rules YAML exists to render the startup
    scene; it is synthetic and does not encode official robot performance.
    """

    def __init__(self, document: RuleDocument) -> None:
        if document.metadata.id != RMUC_2027_RULE_ID:
            raise ConfigError(
                f"{document.path}: RMUC 2027 requires `{RMUC_2027_RULE_ID}`"
            )
        if document.metadata.status != "rules-lab-partial":
            raise ConfigError(
                f"{document.path}: RMUC 2027 P1 must be marked `rules-lab-partial`"
            )
        if (
            document.metadata.competition != "RMUC"
            or document.metadata.season != 2027
            or document.metadata.official_version != "V1.0.0"
        ):
            raise ConfigError(
                f"{document.path}: RMUC 2027 P1 requires RMUC season 2027 V1.0.0 metadata"
            )

        roster = document.data.get("active_roster")
        expected_roster = {"ground": _GROUND_ROSTER, "systems": _SYSTEM_ROSTER}
        if roster != expected_roster:
            raise ConfigError(
                f"{document.path}: `active_roster` must match the RMUC 2027 V1.0.0 roster"
            )
        self._ground_roster = Counter(_GROUND_ROSTER)

        duration = document.data.get("match_duration")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration != 420
        ):
            raise ConfigError(
                f"{document.path}: RMUC 2027 V1.0.0 match duration must be 420 seconds"
            )
        self._time_limit = float(duration)

        profile = document.data.get("rules_lab_placeholder")
        if not isinstance(profile, dict):
            raise ConfigError(
                f"{document.path}: `rules_lab_placeholder` must explicitly define the P1 render profile"
            )
        self._parameters = RobotParameters(
            max_hp=_positive_integer(profile, "max_hp", document),
            move_speed=_non_negative_number(profile, "move_speed", document),
            collision_radius=_positive_number(profile, "collision_radius", document),
            attack_range=_non_negative_number(profile, "attack_range", document),
            attack_interval=_positive_number(profile, "attack_interval", document),
            damage=_non_negative_integer(profile, "damage", document),
        )

    @property
    def time_limit(self) -> float:
        return self._time_limit

    @property
    def replay_timebox_without_settlement(self) -> bool:
        """Allow deterministic P1 traces to stop at 420s without inventing a winner."""
        return True

    @property
    def display_state(self) -> RuleSetDisplayState | None:
        return None

    def validate_scenario(self, scenario: "ScenarioDefinition") -> None:
        """Reject any active ground roster that is not the official 2027 lineup."""
        for team in scenario.teams.values():
            actual = Counter(robot.type for robot in team.robots)
            if actual != self._ground_roster:
                raise ConfigError(
                    f"RMUC 2027 active ground roster for `{team.team_id}` must be "
                    "heavy×1, infantry×2, sentry×1; combination systems are not ground robots"
                )

    def robot_parameters(self, robot_type: str) -> RobotParameters:
        if robot_type not in _GROUND_ROSTER:
            raise ConfigError(
                f"RMUC 2027 P1 Rules Lab does not support mobile robot type `{robot_type}`"
            )
        return self._parameters

    def structure_parameters(self, structure_type: str) -> StructureParameters:
        raise ConfigError(
            f"RMUC 2027 P1 Rules Lab does not implement `{structure_type}` structures"
        )

    def can_move(self, robot: "Robot") -> bool:
        del robot
        return False

    def can_attack(self, robot: "Robot") -> bool:
        del robot
        return False

    def can_target(self, target: DamageableTarget) -> bool:
        del target
        return False

    def on_attack_committed(self, robot: "Robot") -> None:
        del robot

    def exchange_projectiles(self, match: "Match", robot: "Robot") -> bool:
        del match, robot
        return False

    def can_receive_damage(self, target: DamageableTarget) -> bool:
        del target
        return False

    def resolve_damage(
        self,
        target: DamageableTarget,
        amount: int,
        source_team_id: str | None,
        *,
        bypass_attack_defense: bool = False,
        attack_multiplier: float = 1.0,
    ) -> int:
        del target, amount, source_team_id, bypass_attack_defense, attack_multiplier
        return 0

    def resolve_damage_detail(
        self,
        target: DamageableTarget,
        amount: int,
        source_team_id: str | None,
        *,
        bypass_attack_defense: bool = False,
        attack_multiplier: float = 1.0,
    ) -> DamageResolution:
        return DamageResolution(
            self.resolve_damage(
                target,
                amount,
                source_team_id,
                bypass_attack_defense=bypass_attack_defense,
                attack_multiplier=attack_multiplier,
            )
        )

    def prepare_movement(self, match: "Match", dt: float) -> None:
        del match, dt

    def prepare_combat(self, match: "Match", dt: float) -> None:
        del match, dt

    def reset(self, match: "Match") -> None:
        del match

    def update(self, match: "Match", dt: float) -> None:
        del match, dt

    def evaluate_result(self, match: "Match") -> MatchResult | None:
        del match
        return None


def _positive_integer(profile: dict[str, Any], key: str, document: RuleDocument) -> int:
    value = profile.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(
            f"{document.path}: `rules_lab_placeholder.{key}` must be a positive integer"
        )
    return value


def _non_negative_integer(profile: dict[str, Any], key: str, document: RuleDocument) -> int:
    value = profile.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(
            f"{document.path}: `rules_lab_placeholder.{key}` must be a non-negative integer"
        )
    return value


def _positive_number(profile: dict[str, Any], key: str, document: RuleDocument) -> float:
    value = profile.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigError(
            f"{document.path}: `rules_lab_placeholder.{key}` must be a positive number"
        )
    return float(value)


def _non_negative_number(profile: dict[str, Any], key: str, document: RuleDocument) -> float:
    value = profile.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ConfigError(
            f"{document.path}: `rules_lab_placeholder.{key}` must be a non-negative number"
        )
    return float(value)
