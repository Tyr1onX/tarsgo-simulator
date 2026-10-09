"""Stationary damageable competition structures."""

from dataclasses import dataclass
import math

OUTPOST_ARMOR_MAX_SPEED = 0.8 * math.pi
OUTPOST_ARMOR_RAMP_SECONDS = 5.0
OUTPOST_ARMOR_STOP_SECONDS = 180.0
OUTPOST_ARMOR_RETURN_SECONDS = 10.0
OUTPOST_ARMOR_SYMMETRY_PERIOD = math.tau / 3.0


@dataclass(frozen=True, slots=True)
class StructureProjectileHitboxProfile:
    """Current per-structure armor projection for projectile collision."""

    module_width_mm: float
    deployed_offset_mm: float
    center_area_size_mm: float
    deployed: bool
    upper_front_edge_index: int
    armor_panels: tuple["StructureArmorPanelProjection", ...] = ()


@dataclass(frozen=True, slots=True)
class StructureArmorPanelProjection:
    """A planar Rules Lab projection of one structure armor module."""

    module_id: str
    vertices: tuple[tuple[float, float], ...]
    center: tuple[float, float]
    long_axis: tuple[float, float] = (1.0, 0.0)
    short_axis: tuple[float, float] = (0.0, 1.0)


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
class OutpostArmorRotationState:
    """Authoritative per-match Outpost middle-armor rotation state.

    V1.4.0 defines the timing and stop triggers, but does not dimension the
    panel projection or its return curve. Geometry and easing are Rules Lab
    approximations shared by collision and rendering. Return motion starts
    from the visible stopped pose and takes the shortest 120-degree-symmetric
    path to the initial three-panel pose.
    """

    direction: int
    stop_time: float | None = None
    destroyed_at_stop: bool = False

    def stop(self, time: float, *, destroyed: bool = False) -> None:
        at = max(0.0, time)
        if self.stop_time is None or (
            destroyed
            and not self.destroyed_at_stop
            and math.isclose(self.stop_time, at, rel_tol=0.0, abs_tol=1e-9)
        ):
            self.stop_time = at
            self.destroyed_at_stop = destroyed

    def angle_at(self, time: float) -> float:
        now = max(0.0, time)
        if self.stop_time is None or now <= self.stop_time:
            return _wrap_angle(self.direction * _outpost_active_angle(now))
        stopped_angle = _wrap_angle(
            self.direction * _outpost_active_angle(self.stop_time)
        )
        if self.destroyed_at_stop:
            return stopped_angle
        progress = min(
            1.0,
            max(0.0, (now - self.stop_time) / OUTPOST_ARMOR_RETURN_SECONDS),
        )
        smooth_return = progress * progress * (3.0 - 2.0 * progress)
        return_delta = _wrap_to_period(
            -stopped_angle,
            OUTPOST_ARMOR_SYMMETRY_PERIOD,
        )
        return _wrap_angle(stopped_angle + return_delta * smooth_return)


def outpost_armor_panel_projections(
    diameter: float,
    angle: float,
) -> tuple[StructureArmorPanelProjection, ...]:
    """Return the three rotating panels in local planar coordinates.

    V1.4.0 Figure 4-33 identifies three armor modules and the rotating middle
    assembly but does not dimension the panel footprint. The ratios below
    reproduce the existing Rules Lab visual projection; callers must treat
    them as approximate rather than surveyed field geometry.
    """
    diameter = max(0.0, diameter)
    outer_radius = diameter * 0.38
    inner_radius = diameter * 0.11
    inner_half_width = diameter * 0.075 * 0.78
    outer_half_width = diameter * 0.075 * 0.60
    panels = []
    for index in range(3):
        module_angle = angle - math.pi / 2 + index * math.tau / 3
        direction = (math.cos(module_angle), math.sin(module_angle))
        tangent = (-direction[1], direction[0])
        inner_center = (
            direction[0] * inner_radius,
            direction[1] * inner_radius,
        )
        outer_center = (
            direction[0] * outer_radius,
            direction[1] * outer_radius,
        )
        vertices = tuple(
            (
                along_center[0] + tangent[0] * half_width,
                along_center[1] + tangent[1] * half_width,
            )
            for along_center, half_width in (
                (inner_center, inner_half_width),
                (outer_center, outer_half_width),
                (outer_center, -outer_half_width),
                (inner_center, -inner_half_width),
            )
        )
        panels.append(
            StructureArmorPanelProjection(
                module_id=f"outpost-armor-{index + 1}",
                vertices=vertices,
                center=(
                    (inner_center[0] + outer_center[0]) / 2,
                    (inner_center[1] + outer_center[1]) / 2,
                ),
                long_axis=direction,
                short_axis=tangent,
            )
        )
    return tuple(panels)


def _outpost_active_angle(elapsed_time: float) -> float:
    elapsed = max(0.0, elapsed_time)
    acceleration = OUTPOST_ARMOR_MAX_SPEED / OUTPOST_ARMOR_RAMP_SECONDS
    if elapsed <= OUTPOST_ARMOR_RAMP_SECONDS:
        return 0.5 * acceleration * elapsed * elapsed
    ramp_angle = (
        0.5 * OUTPOST_ARMOR_MAX_SPEED * OUTPOST_ARMOR_RAMP_SECONDS
    )
    return ramp_angle + OUTPOST_ARMOR_MAX_SPEED * (
        elapsed - OUTPOST_ARMOR_RAMP_SECONDS
    )


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % math.tau - math.pi


def _wrap_to_period(angle: float, period: float) -> float:
    return (angle + period / 2.0) % period - period / 2.0


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
