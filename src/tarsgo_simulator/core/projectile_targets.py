"""Non-damageable targets shared by projectile physics and rule systems."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectileAimTarget:
    """A temporary same-team objective for a legally commanded shooter."""

    id: str
    position: tuple[float, float]
    robot_id: str
    alignment_tolerance_rad: float | None = None
    approach_position: tuple[float, float] | None = None
    approach_tolerance_mm: float = 400.0


@dataclass(frozen=True, slots=True)
class ProjectileSpecialHitbox:
    """A physical, non-damageable target consumed by a rules callback."""

    id: str
    target_kind: str
    module_id: str
    vertices: tuple[tuple[float, float], ...]
