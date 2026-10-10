"""Rules Lab geometry for the RMUC small energy mechanism."""

from __future__ import annotations

from dataclasses import dataclass
import math


SMALL_ENERGY_ROTATION_SPEED_RAD_S = math.pi / 3.0
LARGE_ENERGY_BASE_ROTATION_SPEED_RAD_S = math.pi / 3.0
SMALL_ENERGY_TARGET_MAX_DIAMETER_MM = 308.0
SMALL_ENERGY_TARGET_DETECTION_DIAMETER_MM = 300.0


@dataclass(frozen=True, slots=True)
class EnergyMechanismPanel:
    """One visible lamp arm and its official circular detection target."""

    module_index: int
    center: tuple[float, float]
    vertices: tuple[tuple[float, float], ...]
    detection_radius_mm: float = SMALL_ENERGY_TARGET_DETECTION_DIAMETER_MM / 2.0


@dataclass(frozen=True, slots=True)
class SmallEnergyMechanism:
    """Shared central mechanism entity; each team has separate rule state.

    V1.4.0 specifies a 300 mm effective circular detection region within a
    lamp target whose maximum diameter is 308 mm, and a constant small-
    mechanism speed. The target center's full-field coordinates, panel-arm
    silhouette, height, and 2D projection are Rules Lab approximations. The
    official detection circle is shared by collision and rendering.
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
        return _panels_at_angle(
            self.center,
            self.panel_inner_radius_mm,
            self.panel_outer_radius_mm,
            self.panel_width_mm,
            self.angle_at(elapsed_time),
        )


@dataclass(slots=True)
class LargeEnergyMechanism:
    """Rules Lab 2D projection for the RMUC five-arm large mechanism.

    V1.4.0 fixes the inactive speed and the active speed function, and Fig. 5-17
    defines a 300 mm detection circle with ten 15 mm radial scoring bands.
    The arm silhouette, reach, field height, and its 2D projection are not
    dimensioned in the manual and remain explicit Rules Lab approximations.
    The sinusoid's local time starts at the opportunity's activatable timestamp
    and advances only while the mechanism is in its activating state.
    """

    center: tuple[float, float]
    rotation_direction: int
    id: str = "rmuc-large-energy-mechanism"
    initial_angle: float = -math.pi / 2.0
    panel_inner_radius_mm: float = 330.0
    panel_outer_radius_mm: float = 760.0
    panel_width_mm: float = 220.0
    _anchor_time: float = 0.0
    _anchor_angle: float | None = None
    _activation_started_at: float | None = None
    _speed_time_origin: float = 0.0
    _speed_a: float = 0.0
    _speed_omega: float = 0.0

    def __post_init__(self) -> None:
        if self._anchor_angle is None:
            self._anchor_angle = self.initial_angle

    def angle_at(self, elapsed_time: float) -> float:
        elapsed = max(0.0, elapsed_time)
        anchor_angle = self._anchor_angle or 0.0
        if self._activation_started_at is None or elapsed < self._activation_started_at:
            return anchor_angle + (
                self.rotation_direction
                * LARGE_ENERGY_BASE_ROTATION_SPEED_RAD_S
                * max(0.0, elapsed - self._anchor_time)
            )
        active_elapsed = elapsed - self._activation_started_at
        phase_at_start = max(0.0, self._activation_started_at - self._speed_time_origin)
        phase_now = phase_at_start + active_elapsed
        omega = self._speed_omega
        offset = (
            self._speed_a / omega
            * (math.cos(omega * phase_at_start) - math.cos(omega * phase_now))
            + (2.090 - self._speed_a) * active_elapsed
        )
        return anchor_angle + self.rotation_direction * offset

    def start_activation(
        self,
        elapsed_time: float,
        *,
        speed_a: float,
        speed_omega: float,
        speed_time_origin: float | None = None,
    ) -> None:
        now = max(0.0, elapsed_time)
        current_angle = self.angle_at(now)
        self._anchor_time = now
        self._anchor_angle = current_angle
        self._activation_started_at = now
        self._speed_time_origin = (
            now if speed_time_origin is None else max(0.0, speed_time_origin)
        )
        self._speed_a = speed_a
        self._speed_omega = speed_omega

    def stop_activation(self, elapsed_time: float) -> None:
        now = max(0.0, elapsed_time)
        self._anchor_angle = self.angle_at(now)
        self._anchor_time = now
        self._activation_started_at = None

    def panels_at(self, elapsed_time: float) -> tuple[EnergyMechanismPanel, ...]:
        return _panels_at_angle(
            self.center,
            self.panel_inner_radius_mm,
            self.panel_outer_radius_mm,
            self.panel_width_mm,
            self.angle_at(elapsed_time),
        )


def _panels_at_angle(
    center: tuple[float, float],
    panel_inner_radius_mm: float,
    panel_outer_radius_mm: float,
    panel_width_mm: float,
    angle: float,
) -> tuple[EnergyMechanismPanel, ...]:
    middle_radius = (panel_inner_radius_mm + panel_outer_radius_mm) / 2.0
    half_length = (panel_outer_radius_mm - panel_inner_radius_mm) / 2.0
    half_width = panel_width_mm / 2.0
    panels: list[EnergyMechanismPanel] = []
    for module_index in range(5):
        module_angle = angle + module_index * math.tau / 5.0
        radial = (math.cos(module_angle), math.sin(module_angle))
        tangent = (-radial[1], radial[0])
        module_center = (
            center[0] + radial[0] * middle_radius,
            center[1] + radial[1] * middle_radius,
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
