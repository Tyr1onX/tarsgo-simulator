"""Rules Lab geometry for the RMUC small energy mechanism."""

from __future__ import annotations

from dataclasses import dataclass
import math


SMALL_ENERGY_ROTATION_SPEED_RAD_S = math.pi / 3.0


@dataclass(frozen=True, slots=True)
class EnergyMechanismPanel:
    """One of the five rotating target modules in the planar field model."""

    module_index: int
    center: tuple[float, float]
    vertices: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class SmallEnergyMechanism:
    """Shared central mechanism entity; each team has separate rule state.

    V1.4.0 specifies five armor modules and a constant small-mechanism speed,
    but does not publish a dimensioned module footprint or exact XY center.
    The centered location and radial panel dimensions are Rules Lab
    approximations. Collision and rendering consume these same projections.
    """

    center: tuple[float, float]
    rotation_direction: int
    id: str = "rmuc-small-energy-mechanism"
    initial_angle: float = -math.pi / 2.0
    panel_inner_radius_mm: float = 330.0
    panel_outer_radius_mm: float = 760.0
    panel_width_mm: float = 220.0

    def angle_at(self, elapsed_time: float) -> float:
        elapsed = max(0.0, elapsed_time)
        return self.initial_angle + (
            self.rotation_direction * SMALL_ENERGY_ROTATION_SPEED_RAD_S * elapsed
        )

    def panels_at(self, elapsed_time: float) -> tuple[EnergyMechanismPanel, ...]:
        """Return the visible and collidable five-panel pose for this time."""
        angle = self.angle_at(elapsed_time)
        middle_radius = (
            self.panel_inner_radius_mm + self.panel_outer_radius_mm
        ) / 2.0
        half_length = (
            self.panel_outer_radius_mm - self.panel_inner_radius_mm
        ) / 2.0
        half_width = self.panel_width_mm / 2.0
        panels: list[EnergyMechanismPanel] = []
        for module_index in range(5):
            module_angle = angle + module_index * math.tau / 5.0
            radial = (math.cos(module_angle), math.sin(module_angle))
            tangent = (-radial[1], radial[0])
            module_center = (
                self.center[0] + radial[0] * middle_radius,
                self.center[1] + radial[1] * middle_radius,
            )
            vertices = tuple(
                (
                    module_center[0] + radial[0] * along + tangent[0] * across,
                    module_center[1] + radial[1] * along + tangent[1] * across,
                )
                for along, across in (
                    (-half_length, -half_width),
                    (half_length, -half_width),
                    (half_length, half_width),
                    (-half_length, half_width),
                )
            )
            panels.append(
                EnergyMechanismPanel(
                    module_index=module_index,
                    center=module_center,
                    vertices=vertices,
                )
            )
        return tuple(panels)
