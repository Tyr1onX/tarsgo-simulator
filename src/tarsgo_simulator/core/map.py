"""Small rectangular field with axis-aligned obstacles."""

from dataclasses import dataclass
from typing import Iterable


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


class GameMap:
    def __init__(
        self,
        width: float,
        height: float,
        obstacles: Iterable[Rectangle],
        collision_radius: float,
    ) -> None:
        self.width = float(width)
        self.height = float(height)
        self.obstacles = tuple(obstacles)
        self.collision_radius = float(collision_radius)

    def contains(self, point: tuple[float, float]) -> bool:
        x, y = point
        return 0 <= x <= self.width and 0 <= y <= self.height

    def is_passable(self, point: tuple[float, float]) -> bool:
        x, y = point
        radius = self.collision_radius
        if not (radius <= x <= self.width - radius and radius <= y <= self.height - radius):
            return False

        return not any(
            obstacle.x - radius <= x <= obstacle.right + radius
            and obstacle.y - radius <= y <= obstacle.bottom + radius
            for obstacle in self.obstacles
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
            for obstacle in self.obstacles
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
