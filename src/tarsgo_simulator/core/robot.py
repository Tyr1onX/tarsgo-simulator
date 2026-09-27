"""A single, data-driven infantry robot used by the V0 slice."""

from dataclasses import dataclass, field
import math

from tarsgo_simulator.core.map import GameMap


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

    def update(self, dt: float, game_map: GameMap) -> None:
        if not self.alive:
            return

        self.attack_cooldown = max(0.0, self.attack_cooldown - dt)
        remaining = self.speed * dt
        while self.path and remaining > 0:
            waypoint = self.path[0]
            distance = _distance(self.position, waypoint)
            if distance < 0.001:
                self.position = waypoint
                self.path.pop(0)
                continue
            if not game_map.can_traverse(self.position, waypoint):
                self.path.clear()
                return
            if distance <= remaining:
                self.position = waypoint
                self.path.pop(0)
                remaining -= distance
                continue

            ratio = remaining / distance
            next_position = (
                self.position[0] + (waypoint[0] - self.position[0]) * ratio,
                self.position[1] + (waypoint[1] - self.position[1]) * ratio,
            )
            if not game_map.can_traverse(self.position, next_position):
                self.path.clear()
                return
            self.position = next_position
            remaining = 0


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])
