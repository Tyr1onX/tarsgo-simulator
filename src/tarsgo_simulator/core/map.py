"""Map geometry shared by movement, line of sight and the renderer."""

from dataclasses import dataclass
import math
from typing import Iterable

from tarsgo_simulator.core.structure import Structure


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
    """A named map area; its bounds and optional polygon are inclusive."""

    id: str
    x: float
    y: float
    width: float
    height: float
    vertices: tuple[tuple[float, float], ...] = ()

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, point: tuple[float, float]) -> bool:
        if self.vertices:
            return _point_in_polygon(point, self.vertices)
        x, y = point
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    @property
    def polygon(self) -> tuple[tuple[float, float], ...]:
        if self.vertices:
            return self.vertices
        return (
            (self.x, self.y),
            (self.right, self.y),
            (self.right, self.bottom),
            (self.x, self.bottom),
        )


@dataclass(frozen=True)
class TerrainFeature:
    """Officially described terrain semantics, independent of 2D collision."""

    id: str
    kind: str
    relative_height_mm: tuple[float, float] | None = None
    slope_degrees: float | None = None
    source: str = ""


@dataclass(frozen=True)
class TerrainConnection:
    """A verified surface-to-surface transition through a named module."""

    from_surface: str
    to_surface: str
    via_feature: str


@dataclass(frozen=True)
class TerrainRegion:
    """A 2.5D surface or passage with source-backed plan geometry.

    ``platform`` has one constant top height. ``ramp`` interpolates between
    two heights along its axis. ``tunnel`` describes an open floor corridor
    with a ceiling clearance. Approximate field placement is recorded in
    ``approximation`` instead of being presented as surveyed geometry.
    """

    id: str
    kind: str
    vertices: tuple[tuple[float, float], ...]
    height_mm: float = 0.0
    height_start_mm: float | None = None
    height_end_mm: float | None = None
    axis_start: tuple[float, float] | None = None
    axis_end: tuple[float, float] | None = None
    slope_degrees: float | None = None
    clearance_mm: float | None = None
    source: str = ""
    approximation: str = ""

    @property
    def bounds(self) -> Rectangle:
        xs = [point[0] for point in self.vertices]
        ys = [point[1] for point in self.vertices]
        return Rectangle(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def contains(self, point: tuple[float, float]) -> bool:
        return _point_in_polygon(point, self.vertices)

    def height_at(self, point: tuple[float, float]) -> float | None:
        if not self.contains(point):
            return None
        if self.kind != "ramp":
            return self.height_mm
        assert self.axis_start is not None and self.axis_end is not None
        assert self.height_start_mm is not None and self.height_end_mm is not None
        dx = self.axis_end[0] - self.axis_start[0]
        dy = self.axis_end[1] - self.axis_start[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-18:
            return self.height_start_mm
        ratio = (
            (point[0] - self.axis_start[0]) * dx
            + (point[1] - self.axis_start[1]) * dy
        ) / length_squared
        ratio = max(0.0, min(1.0, ratio))
        return self.height_start_mm + (self.height_end_mm - self.height_start_mm) * ratio


class GameMap:
    def __init__(
        self,
        width: float,
        height: float,
        obstacles: Iterable[Rectangle],
        collision_radius: float,
        zones: Iterable[Zone] = (),
        structures: Iterable[Structure] = (),
        path_grid_size: float = 20.0,
        terrain_features: Iterable[TerrainFeature] = (),
        terrain_connections: Iterable[TerrainConnection] = (),
        terrain_regions: Iterable[TerrainRegion] = (),
    ) -> None:
        self.width = float(width)
        self.height = float(height)
        self.obstacles = tuple(obstacles)
        self.collision_radius = float(collision_radius)
        self.zones = tuple(zones)
        self.structures = tuple(structures)
        self.path_grid_size = float(path_grid_size)
        self.terrain_features = tuple(terrain_features)
        self.terrain_connections = tuple(terrain_connections)
        self.terrain_regions = tuple(terrain_regions)
        self._terrain_bounds = tuple(
            (region, region.bounds) for region in self.terrain_regions
        )
        self.unit_scale = self.path_grid_size / 20.0
        self._structure_bounds_by_id = {
            structure.id: Rectangle(
                structure.position[0] - structure.footprint[0] / 2,
                structure.position[1] - structure.footprint[1] / 2,
                structure.footprint[0],
                structure.footprint[1],
            )
            for structure in self.structures
            if structure.footprint is not None
        }
        self._structure_polygons_by_id = {
            structure.id: tuple(
                (structure.position[0] + x, structure.position[1] + y)
                for x, y in structure.footprint_vertices
            )
            for structure in self.structures
            if (
                structure.footprint_shape == "polygon"
                and structure.footprint is not None
                and len(structure.footprint_vertices) >= 3
            )
        }
        self._structure_circles_by_id = {
            structure.id: (structure.position, structure.footprint[0] / 2)
            for structure in self.structures
            if structure.footprint_shape == "circle" and structure.footprint is not None
        }
        self._blocking_polygons_cache = tuple(self._structure_polygons_by_id.items())
        self._blocking_circles_cache = tuple(
            (structure_id, center, radius)
            for structure_id, (center, radius) in self._structure_circles_by_id.items()
        )
        self._blocking_rectangles_cache = (
            *((None, obstacle) for obstacle in self.obstacles),
            *(
                (structure_id, bounds)
                for structure_id, bounds in self._structure_bounds_by_id.items()
                if structure_id not in self._structure_polygons_by_id
                and structure_id not in self._structure_circles_by_id
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
        clearance = self.collision_radius + 0.5 * self.unit_scale
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

    def _blocking_polygons(
        self,
        *,
        except_structure_id: str | None = None,
    ) -> tuple[tuple[str, tuple[tuple[float, float], ...]], ...]:
        if except_structure_id is None:
            return self._blocking_polygons_cache
        return tuple(
            (structure_id, vertices)
            for structure_id, vertices in self._blocking_polygons_cache
            if structure_id != except_structure_id
        )

    def _blocking_circles(
        self,
        *,
        except_structure_id: str | None = None,
    ) -> tuple[tuple[str, tuple[float, float], float], ...]:
        if except_structure_id is None:
            return self._blocking_circles_cache
        return tuple(
            (structure_id, center, radius)
            for structure_id, center, radius in self._blocking_circles_cache
            if structure_id != except_structure_id
        )

    def contains(self, point: tuple[float, float]) -> bool:
        x, y = point
        return 0 <= x <= self.width and 0 <= y <= self.height

    def terrain_height_at(self, point: tuple[float, float]) -> float:
        """Return the top surface height above the field ground in millimetres."""
        height = 0.0
        x, y = point
        for region, bounds in self._terrain_bounds:
            if not (
                bounds.x <= x <= bounds.right
                and bounds.y <= y <= bounds.bottom
            ):
                continue
            candidate = region.height_at(point)
            if candidate is not None:
                height = max(height, candidate)
        return height

    def terrain_region_at(self, point: tuple[float, float]) -> TerrainRegion | None:
        """Return the highest modeled surface at a point, if any."""
        best: TerrainRegion | None = None
        best_height = 0.0
        x, y = point
        for region, bounds in self._terrain_bounds:
            if not (
                bounds.x <= x <= bounds.right
                and bounds.y <= y <= bounds.bottom
            ):
                continue
            candidate = region.height_at(point)
            if candidate is not None and candidate >= best_height:
                best = region
                best_height = candidate
        return best

    def is_passable(
        self,
        point: tuple[float, float],
        *,
        agent_height_mm: float | None = None,
    ) -> bool:
        x, y = point
        radius = self.collision_radius
        if not (
            radius <= x <= self.width - radius
            and radius <= y <= self.height - radius
        ):
            return False

        radius = self.collision_radius
        for structure_id, vertices in self._blocking_polygons():
            bounds = self._structure_bounds_by_id[structure_id]
            if (
                bounds.x - radius <= x <= bounds.right + radius
                and bounds.y - radius <= y <= bounds.bottom + radius
                and _point_to_polygon_distance(point, vertices) <= radius
            ):
                return False
        if any(
            math.dist(point, center) <= radius + structure_radius
            for _structure_id, center, structure_radius in self._blocking_circles()
        ):
            return False

        for region, bounds in self._terrain_bounds:
            if region.kind != "tunnel" or not (
                bounds.x <= x <= bounds.right
                and bounds.y <= y <= bounds.bottom
                and region.contains(point)
            ):
                continue
            if (
                agent_height_mm is None
                or region.clearance_mm is None
                or agent_height_mm > region.clearance_mm + 1e-9
                or _tunnel_side_clearance(point, region) + 1e-9 < radius
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
        *,
        agent_height_mm: float | None = None,
    ) -> bool:
        if not self.is_passable(start, agent_height_mm=agent_height_mm) or not self.is_passable(
            end,
            agent_height_mm=agent_height_mm,
        ):
            return False

        for structure_id, vertices in self._blocking_polygons():
            bounds = self._structure_bounds_by_id[structure_id]
            if _segment_intersects_rectangle(
                start,
                end,
                bounds.x - self.collision_radius,
                bounds.y - self.collision_radius,
                bounds.right + self.collision_radius,
                bounds.bottom + self.collision_radius,
            ) and _segment_hits_polygon_with_clearance(
                start,
                end,
                vertices,
                self.collision_radius,
            ):
                return False
        if any(
            _distance_to_segment(center, start, end)
            <= structure_radius + self.collision_radius
            for _structure_id, center, structure_radius in self._blocking_circles()
        ):
            return False

        if any(
            _segment_intersects_rectangle(
                start,
                end,
                obstacle.x - self.collision_radius,
                obstacle.y - self.collision_radius,
                obstacle.right + self.collision_radius,
                obstacle.bottom + self.collision_radius,
            )
            for _structure_id, obstacle in self._blocking_rectangles()
        ):
            return False

        return self._terrain_traversable(
            start,
            end,
            agent_height_mm=agent_height_mm,
        )

    def _terrain_traversable(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        *,
        agent_height_mm: float | None,
    ) -> bool:
        if not self.terrain_regions:
            return True
        distance = math.dist(start, end)
        if distance <= 1e-9:
            return True
        spacing = min(100.0, max(10.0, self.path_grid_size / 2))
        steps = max(1, math.ceil(distance / spacing))
        previous = start
        previous_height = self.terrain_height_at(start)
        for index in range(1, steps + 1):
            ratio = index / steps
            point = (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
            height = self.terrain_height_at(point)
            step_distance = math.dist(previous, point)
            height_delta = abs(height - previous_height)
            if height_delta > 1e-6:
                midpoint = (
                    (previous[0] + point[0]) / 2,
                    (previous[1] + point[1]) / 2,
                )
                ramps = [
                    region
                    for region, bounds in self._terrain_bounds
                    if region.kind == "ramp"
                    and any(
                        bounds.x <= sample[0] <= bounds.right
                        and bounds.y <= sample[1] <= bounds.bottom
                        for sample in (previous, midpoint, point)
                    )
                    and (
                        region.contains(midpoint)
                        or region.contains(previous)
                        or region.contains(point)
                    )
                    and region.slope_degrees is not None
                ]
                if not ramps:
                    return False
                max_grade = max(
                    math.tan(math.radians(region.slope_degrees or 0.0))
                    for region in ramps
                )
                # A robot's modeled footprint can bridge a small height change
                # at a ramp's side edge. Use at least the footprint diameter as
                # the grade run, so the same short boundary crossing is judged
                # consistently by long A* edges and per-frame movement steps.
                grade_run = max(step_distance, 2 * self.collision_radius)
                if height_delta > max_grade * grade_run + 1.0:
                    return False

            for region, bounds in self._terrain_bounds:
                if region.kind != "tunnel" or not (
                    bounds.x <= point[0] <= bounds.right
                    and bounds.y <= point[1] <= bounds.bottom
                    and region.contains(point)
                ):
                    continue
                if (
                    agent_height_mm is None
                    or region.clearance_mm is None
                    or agent_height_mm > region.clearance_mm + 1e-9
                    or _tunnel_side_clearance(point, region) + 1e-9
                    < self.collision_radius
                ):
                    return False
            previous = point
            previous_height = height
        return True

    def terrain_collision_fraction(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        start_height_mm: float,
        end_height_mm: float,
    ) -> float | None:
        """Return first terrain contact for a straight 2.5D ray, if any."""
        if not self.terrain_regions:
            return None
        distance = math.dist(start, end)
        spacing = min(50.0, max(10.0, self.path_grid_size / 2))
        steps = max(1, math.ceil(distance / spacing))
        for index in range(1, steps + 1):
            ratio = index / steps
            point = (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
            ray_height = start_height_mm + (end_height_mm - start_height_mm) * ratio
            if self.terrain_height_at(point) > ray_height + 1.0:
                return (index - 1) / steps
            for region, bounds in self._terrain_bounds:
                if region.kind == "tunnel" and region.clearance_mm is not None and (
                    bounds.x <= point[0] <= bounds.right
                    and bounds.y <= point[1] <= bounds.bottom
                    and region.contains(point)
                    and ray_height > region.clearance_mm + 1e-9
                ):
                    return (index - 1) / steps
        return None

    def has_line_of_sight(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        target_structure_id: str | None = None,
        *,
        start_height_mm: float | None = None,
        end_height_mm: float | None = None,
    ) -> bool:
        """Return whether the segment avoids walls and non-target structures."""
        # Use the same closed playing-surface perimeter as movement and
        # projectile collision; an off-field ray cannot bypass that wall.
        if not self.contains(start) or not self.contains(end):
            return False

        if self.terrain_regions:
            if start_height_mm is None:
                start_height_mm = self.terrain_height_at(start)
            if end_height_mm is None:
                end_height_mm = self.terrain_height_at(end)
            if self.terrain_collision_fraction(
                start,
                end,
                start_height_mm,
                end_height_mm,
            ) is not None:
                return False

        for structure_id, vertices in self._blocking_polygons(
            except_structure_id=target_structure_id
        ):
            bounds = self._structure_bounds_by_id[structure_id]
            if _segment_intersects_rectangle(
                start,
                end,
                bounds.x,
                bounds.y,
                bounds.right,
                bounds.bottom,
            ) and _segment_hits_polygon_with_clearance(start, end, vertices, 0.0):
                return False
        if any(
            _distance_to_segment(center, start, end) <= radius
            for _structure_id, center, radius in self._blocking_circles(
                except_structure_id=target_structure_id
            )
        ):
            return False

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


def _point_in_polygon(
    point: tuple[float, float],
    vertices: tuple[tuple[float, float], ...],
) -> bool:
    x, y = point
    inside = False
    previous_x, previous_y = vertices[-1]
    for current_x, current_y in vertices:
        if _distance_to_segment(point, (previous_x, previous_y), (current_x, current_y)) <= 1e-9:
            return True
        if (current_y > y) != (previous_y > y):
            crossing_x = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x < crossing_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def _distance_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-18:
        return math.dist(point, start)
    parameter = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / length_squared,
        ),
    )
    closest = (start[0] + parameter * dx, start[1] + parameter * dy)
    return math.dist(point, closest)


def _point_to_polygon_distance(
    point: tuple[float, float],
    vertices: tuple[tuple[float, float], ...],
) -> float:
    if _point_in_polygon(point, vertices):
        return 0.0
    return min(
        _distance_to_segment(point, start, end)
        for start, end in zip(vertices, (*vertices[1:], vertices[0]))
    )


def _point_to_polygon_edge_distance(
    point: tuple[float, float],
    vertices: tuple[tuple[float, float], ...],
) -> float:
    return min(
        _distance_to_segment(point, start, end)
        for start, end in zip(vertices, (*vertices[1:], vertices[0]))
    )


def _tunnel_side_clearance(point: tuple[float, float], region: TerrainRegion) -> float:
    if region.axis_start is None or region.axis_end is None:
        return _point_to_polygon_edge_distance(point, region.vertices)
    axis_x = region.axis_end[0] - region.axis_start[0]
    axis_y = region.axis_end[1] - region.axis_start[1]
    axis_length = math.hypot(axis_x, axis_y)
    if axis_length <= 1e-9:
        return 0.0
    axis = (axis_x / axis_length, axis_y / axis_length)
    side_edges = []
    for edge_start, edge_end in zip(region.vertices, (*region.vertices[1:], region.vertices[0])):
        edge_x = edge_end[0] - edge_start[0]
        edge_y = edge_end[1] - edge_start[1]
        edge_length = math.hypot(edge_x, edge_y)
        if edge_length > 1e-9 and abs(
            (edge_x / edge_length) * axis[0] + (edge_y / edge_length) * axis[1]
        ) >= 0.8:
            side_edges.append((edge_start, edge_end))
    if not side_edges:
        return 0.0
    return min(_distance_to_segment(point, start, end) for start, end in side_edges)


def _segment_hits_polygon_with_clearance(
    start: tuple[float, float],
    end: tuple[float, float],
    vertices: tuple[tuple[float, float], ...],
    clearance: float,
) -> bool:
    if _point_in_polygon(start, vertices) or _point_in_polygon(end, vertices):
        return True
    return any(
        _segment_distance(start, end, edge_start, edge_end) <= clearance
        for edge_start, edge_end in zip(vertices, (*vertices[1:], vertices[0]))
    )


def _segment_distance(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> float:
    if _segments_intersect(first_start, first_end, second_start, second_end):
        return 0.0
    return min(
        _distance_to_segment(first_start, second_start, second_end),
        _distance_to_segment(first_end, second_start, second_end),
        _distance_to_segment(second_start, first_start, first_end),
        _distance_to_segment(second_end, first_start, first_end),
    )


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    def orientation(
        a: tuple[float, float],
        b: tuple[float, float],
        c: tuple[float, float],
    ) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(
        point: tuple[float, float],
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> bool:
        return (
            min(a[0], b[0]) - 1e-9 <= point[0] <= max(a[0], b[0]) + 1e-9
            and min(a[1], b[1]) - 1e-9 <= point[1] <= max(a[1], b[1]) + 1e-9
        )

    first_a = orientation(first_start, first_end, second_start)
    first_b = orientation(first_start, first_end, second_end)
    second_a = orientation(second_start, second_end, first_start)
    second_b = orientation(second_start, second_end, first_end)
    if first_a * first_b < 0 and second_a * second_b < 0:
        return True
    return (
        abs(first_a) <= 1e-9 and on_segment(second_start, first_start, first_end)
    ) or (
        abs(first_b) <= 1e-9 and on_segment(second_end, first_start, first_end)
    ) or (
        abs(second_a) <= 1e-9 and on_segment(first_start, second_start, second_end)
    ) or (
        abs(second_b) <= 1e-9 and on_segment(first_end, second_start, second_end)
    )
