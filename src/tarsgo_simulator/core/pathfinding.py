"""Deterministic grid A* for the small V0 arena."""

from heapq import heappop, heappush
from itertools import count
import math

from tarsgo_simulator.core.map import GameMap


GRID_SIZE = 20.0
_NEIGHBORS = ((0, -1), (-1, 0), (1, 0), (0, 1))


def find_path(
    game_map: GameMap,
    start: tuple[float, float],
    goal: tuple[float, float],
) -> list[tuple[float, float]] | None:
    """Return world-coordinate waypoints, including start and goal."""
    if not game_map.is_passable(start) or not game_map.is_passable(goal):
        return None

    grid_size = game_map.path_grid_size
    start_cell = _cell_for(start, grid_size)
    goal_cell = _cell_for(goal, grid_size)
    if start_cell == goal_cell:
        return [start] if start == goal else [start, goal] if game_map.can_traverse(start, goal) else None

    open_nodes: list[tuple[float, int, tuple[int, int]]] = []
    sequence = count()
    heappush(open_nodes, (_heuristic(start_cell, goal_cell), next(sequence), start_cell))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    costs = {start_cell: 0.0}
    visited: set[tuple[int, int]] = set()

    while open_nodes:
        _, _, current = heappop(open_nodes)
        if current in visited:
            continue
        visited.add(current)

        if current == goal_cell:
            cells = _reconstruct(came_from, current)
            points = [start]
            points.extend(_center(cell, grid_size) for cell in cells)
            points.append(goal)
            if not all(
                game_map.can_traverse(a, b)
                for a, b in zip(points, points[1:])
            ):
                return None
            return _smooth_path(points, game_map)

        current_point = _center(current, grid_size)
        for dx, dy in _NEIGHBORS:
            neighbor = (current[0] + dx, current[1] + dy)
            neighbor_point = _center(neighbor, grid_size)
            if neighbor in visited or not game_map.can_traverse(current_point, neighbor_point):
                continue

            new_cost = costs[current] + 1.0
            if new_cost >= costs.get(neighbor, math.inf):
                continue
            costs[neighbor] = new_cost
            came_from[neighbor] = current
            heappush(
                open_nodes,
                (new_cost + _heuristic(neighbor, goal_cell), next(sequence), neighbor),
            )

    return None


def _cell_for(
    point: tuple[float, float], grid_size: float = GRID_SIZE
) -> tuple[int, int]:
    return math.floor(point[0] / grid_size), math.floor(point[1] / grid_size)


def _center(
    cell: tuple[int, int], grid_size: float = GRID_SIZE
) -> tuple[float, float]:
    return (
        cell[0] * grid_size + grid_size / 2,
        cell[1] * grid_size + grid_size / 2,
    )


def _heuristic(start: tuple[int, int], goal: tuple[int, int]) -> float:
    return abs(start[0] - goal[0]) + abs(start[1] - goal[1])


def _smooth_path(
    points: list[tuple[float, float]], game_map: GameMap
) -> list[tuple[float, float]]:
    result = [points[0]]
    anchor = 0
    while anchor < len(points) - 1:
        next_index = len(points) - 1
        while next_index > anchor + 1 and not game_map.can_traverse(
            points[anchor], points[next_index]
        ):
            next_index -= 1
        if not game_map.can_traverse(points[anchor], points[next_index]):
            return points
        result.append(points[next_index])
        anchor = next_index
    return result


def _reconstruct(
    came_from: dict[tuple[int, int], tuple[int, int]],
    current: tuple[int, int],
) -> list[tuple[int, int]]:
    cells = [current]
    while current in came_from:
        current = came_from[current]
        cells.append(current)
    cells.reverse()
    return cells
