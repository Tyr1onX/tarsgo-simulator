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
