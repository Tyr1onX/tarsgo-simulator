"""Small rectangular field with axis-aligned obstacles."""

from dataclasses import dataclass
from typing import Iterable

from tarsgo_simulator.core.structure import Structure


# RMUC 2026 V1.4.0 field-unit dimensions converted from the structure
# footprint drawings (Figure 4-9 Base pedestal, Figure 4-33 Outpost). The
# Rules Lab's structure positions are synthetic; these are axis-aligned 2D
# collision approximations and do not model height or overhangs.
_STRUCTURE_FOOTPRINTS = {
    "base": (188.1, 161.9),
    "outpost": (65.0, 65.0),
}


@dataclass(frozen=True)
class Rectangle:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True)
class Zone:
    """A named rectangular map area; its bounds are inclusive."""

    id: str
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, point: tuple[float, float]) -> bool:
        x, y = point
        return self.x <= x <= self.right and self.y <= y <= self.bottom


class GameMap:
    def __init__(
        self,
        width: float,
        height: float,
        obstacles: Iterable[Rectangle],
        collision_radius: float,
        zones: Iterable[Zone] = (),
        structures: Iterable[Structure] = (),
    ) -> None:
        self.width = float(width)
        self.height = float(height)
        self.obstacles = tuple(obstacles)
        self.collision_radius = float(collision_radius)
        self.zones = tuple(zones)
        self.structures = tuple(structures)
        self._structure_bounds_by_id = {
            structure.id: Rectangle(
                structure.position[0] - width / 2,
                structure.position[1] - height / 2,
                width,
                height,
            )
            for structure in self.structures
            if (dimensions := _STRUCTURE_FOOTPRINTS.get(structure.type)) is not None
            for width, height in (dimensions,)
        }
        self._blocking_rectangles_cache = (
            *((None, obstacle) for obstacle in self.obstacles),
            *(
                (structure_id, bounds)
                for structure_id, bounds in self._structure_bounds_by_id.items()
            ),
        )

    def structure_bounds(self, structure_id: str) -> Rectangle | None:
        """Return a structure's 2D blocking footprint, if it has one."""
        return self._structure_bounds_by_id.get(structure_id)

    def structure_approach_points(
        self,
        structure_id: str,
    ) -> tuple[tuple[float, float], ...]:
        """Passable cardinal points just outside a structure's footprint."""
        bounds = self.structure_bounds(structure_id)
        if bounds is None:
            return ()
        clearance = self.collision_radius + 0.5
        center_x = bounds.x + bounds.width / 2
        center_y = bounds.y + bounds.height / 2
        return (
            (center_x, bounds.y - clearance),
            (bounds.x - clearance, center_y),
            (bounds.right + clearance, center_y),
            (center_x, bounds.bottom + clearance),
        )

    def _blocking_rectangles(
        self,
        *,
        except_structure_id: str | None = None,
    ) -> tuple[tuple[str | None, Rectangle], ...]:
        if except_structure_id is None:
            return self._blocking_rectangles_cache
        return tuple(
            (structure_id, bounds)
            for structure_id, bounds in self._blocking_rectangles_cache
            if structure_id != except_structure_id
        )

    def contains(self, point: tuple[float, float]) -> bool:
        x, y = point
        return 0 <= x <= self.width and 0 <= y <= self.height

    def is_passable(self, point: tuple[float, float]) -> bool:
        x, y = point
        radius = self.collision_radius
        if not (
            radius <= x <= self.width - radius
            and radius <= y <= self.height - radius
        ):
            return False

        return not any(
            obstacle.x - radius <= x <= obstacle.right + radius
            and obstacle.y - radius <= y <= obstacle.bottom + radius
            for _structure_id, obstacle in self._blocking_rectangles()
        )

    def can_traverse(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        if not self.is_passable(start) or not self.is_passable(end):
            return False

        return not any(
            _segment_intersects_rectangle(
                start,
                end,
                obstacle.x - self.collision_radius,
                obstacle.y - self.collision_radius,
                obstacle.right + self.collision_radius,
                obstacle.bottom + self.collision_radius,
            )
            for _structure_id, obstacle in self._blocking_rectangles()
        )

    def has_line_of_sight(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        target_structure_id: str | None = None,
    ) -> bool:
        """Return whether the segment avoids walls and non-target structures."""
        return not any(
            _segment_intersects_rectangle(
                start,
                end,
                obstacle.x,
                obstacle.y,
                obstacle.right,
                obstacle.bottom,
            )
            for _structure_id, obstacle in self._blocking_rectangles(
                except_structure_id=target_structure_id
            )
        )


def _segment_intersects_rectangle(
    start: tuple[float, float],
    end: tuple[float, float],
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> bool:
    """Return whether a line segment intersects an axis-aligned rectangle."""
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    t_min, t_max = 0.0, 1.0

    for p, q in (
        (-dx, x1 - left),
        (dx, right - x1),
        (-dy, y1 - top),
        (dy, bottom - y1),
    ):
        if p == 0:
            if q < 0:
                return False
            continue

        ratio = q / p
        if p < 0:
            t_min = max(t_min, ratio)
        else:
            t_max = min(t_max, ratio)
        if t_min > t_max:
            return False

    return True
