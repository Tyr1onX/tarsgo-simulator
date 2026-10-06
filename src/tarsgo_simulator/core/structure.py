"""Stationary damageable competition structures."""

from dataclasses import dataclass


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
