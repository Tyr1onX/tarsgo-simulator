"""A single, data-driven infantry robot used by the V0 slice."""

from dataclasses import dataclass, field
import math

from tarsgo_simulator.core.map import GameMap


MovementProposal = tuple[tuple[float, float], list[tuple[float, float]]]


@dataclass
class Robot:
    id: str
    team: str
    position: tuple[float, float]
    hp: int
    max_hp: int
    speed: float
    attack_range: float
    attack_interval: float
    damage: int
    type: str = "infantry"
    path: list[tuple[float, float]] = field(default_factory=list)
    attack_cooldown: float = 0.0
    alive: bool = True

    def set_path(self, path: list[tuple[float, float]]) -> None:
        self.path = list(path)
        if self.path and _distance(self.position, self.path[0]) < 0.001:
            self.path.pop(0)

    def take_damage(self, amount: int) -> None:
        if not self.alive:
            return
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.alive = False
            self.path.clear()

    def update_cooldown(self, dt: float) -> None:
        if not self.alive:
            return
        self.attack_cooldown = max(0.0, self.attack_cooldown - dt)

    def propose_movement(self, dt: float, game_map: GameMap) -> MovementProposal:
        """Calculate this frame's move without changing the robot's state."""
        if not self.alive:
            return self.position, list(self.path)

        remaining = self.speed * dt
        position = self.position
        path = list(self.path)
        while path and remaining > 0:
            waypoint = path[0]
            distance = _distance(position, waypoint)
            if distance < 0.001:
                position = waypoint
                path.pop(0)
                continue
            if not game_map.can_traverse(position, waypoint):
                return position, []
            if distance <= remaining:
                position = waypoint
                path.pop(0)
                remaining -= distance
                continue

            ratio = remaining / distance
            next_position = (
                position[0] + (waypoint[0] - position[0]) * ratio,
                position[1] + (waypoint[1] - position[1]) * ratio,
            )
            if not game_map.can_traverse(position, next_position):
                return position, []
            position = next_position
            remaining = 0
        return position, path

    def commit_movement(self, proposal: MovementProposal) -> None:
        self.position, self.path = proposal


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])
