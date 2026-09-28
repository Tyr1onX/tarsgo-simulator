"""The narrow boundary between the simulation engine and competition rules."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match
    from tarsgo_simulator.core.robot import Robot


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


@dataclass(frozen=True)
class RuleSetDisplayState:
    victory_points: tuple[tuple[str, int], ...]
    control_owner: str | None
    robot_statuses: tuple[tuple[str, str], ...] = ()
    attack_damage: tuple[tuple[str, int], ...] = ()
    coins: tuple[tuple[str, int], ...] = ()
    robot_projectiles: tuple[tuple[str, str, int], ...] = ()
    robot_shooting_heat: tuple[tuple[str, float, float, bool, bool], ...] = ()
    robot_chassis_power: tuple[
        tuple[str, float, float, float, float, float], ...
    ] = ()


class RuleSet(Protocol):
    @property
    def time_limit(self) -> float: ...

    def robot_parameters(self, robot_type: str) -> RobotParameters: ...

    def can_move(self, robot: "Robot") -> bool: ...

    def can_attack(self, robot: "Robot") -> bool: ...

    def on_attack_committed(self, robot: "Robot") -> None: ...

    def exchange_projectiles(self, match: "Match", robot: "Robot") -> bool: ...

    def can_receive_damage(self, robot: "Robot") -> bool: ...

    def prepare_movement(self, match: "Match", dt: float) -> None: ...

    def prepare_combat(self, match: "Match", dt: float) -> None: ...

    def reset(self, match: "Match") -> None: ...

    def update(self, match: "Match", dt: float) -> None: ...

    def evaluate_result(self, match: "Match") -> MatchResult | None: ...

    @property
    def display_state(self) -> RuleSetDisplayState | None: ...
