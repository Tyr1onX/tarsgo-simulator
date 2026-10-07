"""The narrow boundary between the simulation engine and competition rules."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match
    from tarsgo_simulator.core.robot import Robot


class DamageableTarget(Protocol):
    id: str
    team: str
    hp: int
    max_hp: int
    alive: bool


@dataclass(frozen=True)
class RobotParameters:
    max_hp: int
    move_speed: float
    collision_radius: float
    attack_range: float
    attack_interval: float
    damage: int


@dataclass(frozen=True)
class ProjectileParameters:
    """Rules Lab projectile profile in the match's world units."""

    caliber: str
    speed: float
    firing_interval: float
    radius: float
    effective_range: float


@dataclass(frozen=True)
class AimMotionParameters:
    """Rules Lab-only turret and chassis motion rates, in radians/second."""

    turret_turn_rate: float
    chassis_spin_rate: float


@dataclass(frozen=True)
class MatchResult:
    winner: str | None


@dataclass(frozen=True)
class StructureParameters:
    max_hp: int


@dataclass(frozen=True)
class RuleSetDisplayState:
    victory_points: tuple[tuple[str, int], ...]
    control_owner: str | None
    robot_statuses: tuple[tuple[str, str], ...] = ()
    attack_damage: tuple[tuple[str, int], ...] = ()
    coins: tuple[tuple[str, int], ...] = ()
    team_economy: tuple[tuple[str, int, int, int, int], ...] = ()
    robot_projectiles: tuple[tuple[str, str, int], ...] = ()
    robot_projectile_reserves: tuple[tuple[str, int], ...] = ()
    robot_shooting_heat: tuple[tuple[str, float, float, bool, bool], ...] = ()
    robot_chassis_power: tuple[
        tuple[str, float, float, float, float, float], ...
    ] = ()
    structure_statuses: tuple[tuple[str, int, int, str], ...] = ()
    rebuild_opportunities: tuple[tuple[str, int], ...] = ()
    rebuild_progress: tuple[tuple[str, str, float, float], ...] = ()
    robot_progression: tuple[tuple[str, int, float, int], ...] = ()
    robot_performance: tuple[tuple[str, int, int, int, int], ...] = ()
    tech_core_status: tuple[
        tuple[str, int, int, int, int, int, int | None, float], ...
    ] = ()
    engineer_energy_units: tuple[tuple[str, int], ...] = ()
    d4_status: tuple[
        tuple[str, str, int, float, float, float, float, bool, int], ...
    ] = ()
    drone_air_support: tuple[tuple[str, bool, float], ...] = ()
    radar_anti_drone: tuple[
        tuple[str, str, float, float, float, int, int, bool], ...
    ] = ()
    energy_mechanism_effect_timers: tuple[tuple[str, str, float], ...] = ()
    dart_system_statuses: tuple[
        tuple[str, int, int, str, float, str, str], ...
    ] = ()
    dart_effect_statuses: tuple[tuple[str, float, float], ...] = ()


class RuleSet(Protocol):
    @property
    def time_limit(self) -> float: ...

    def robot_parameters(self, robot_type: str) -> RobotParameters: ...

    def structure_parameters(self, structure_type: str) -> StructureParameters: ...

    def can_move(self, robot: "Robot") -> bool: ...

    def can_attack(self, robot: "Robot") -> bool: ...

    def can_target(self, target: DamageableTarget) -> bool: ...

    def on_attack_committed(self, robot: "Robot") -> None: ...

    def exchange_projectiles(self, match: "Match", robot: "Robot") -> bool: ...

    def can_receive_damage(self, target: DamageableTarget) -> bool: ...

    def resolve_damage(
        self,
        target: DamageableTarget,
        amount: int,
        source_team_id: str | None,
        *,
        bypass_attack_defense: bool = False,
    ) -> int: ...

    def prepare_movement(self, match: "Match", dt: float) -> None: ...

    def prepare_combat(self, match: "Match", dt: float) -> None: ...

    def reset(self, match: "Match") -> None: ...

    def update(self, match: "Match", dt: float) -> None: ...

    def evaluate_result(self, match: "Match") -> MatchResult | None: ...

    @property
    def display_state(self) -> RuleSetDisplayState | None: ...
