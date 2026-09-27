"""The narrow boundary between the simulation engine and competition rules."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match


@dataclass(frozen=True)
class RobotParameters:
    max_hp: int
    move_speed: float
    collision_radius: float
    attack_range: float
    attack_interval: float
    damage: int


@dataclass(frozen=True)
class MatchResult:
    winner: str | None


class RuleSet(Protocol):
    @property
    def time_limit(self) -> float: ...

    def robot_parameters(self, robot_type: str) -> RobotParameters: ...

    def reset(self, match: "Match") -> None: ...

    def update(self, match: "Match", dt: float) -> None: ...

    def evaluate_result(self, match: "Match") -> MatchResult | None: ...
