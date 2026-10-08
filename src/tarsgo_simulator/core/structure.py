"""Stationary damageable competition structures."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StructureProjectileHitboxProfile:
    """Current per-structure armor projection for projectile collision."""

    module_width_mm: float
    deployed_offset_mm: float
    center_area_size_mm: float
    deployed: bool
    upper_front_edge_index: int


@dataclass(frozen=True, slots=True)
class StructureProjectileHitContext:
    """Facts from one swept projectile contact with a competition structure."""

    module_id: str | None
    impact_position: tuple[float, float]
    caliber: str
    effective_impact_speed: float
    center_hit: bool
    normal: tuple[float, float]


@dataclass
class Structure:
    id: str
    team: str
    type: str
    position: tuple[float, float]
    hp: int
    max_hp: int
    alive: bool = True
    # World-unit footprint dimensions, shape and optional local polygon outline.
    footprint: tuple[float, float] | None = None
    footprint_shape: str = "rectangle"
    footprint_vertices: tuple[tuple[float, float], ...] = ()
