"""Presentation-only spectator camera; never changes simulation positions."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING

from tarsgo_simulator.desktop.viewport import Viewport

if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match


MAX_CAMERA_ZOOM = 3.6
_CAMERA_RESPONSE = 7.0
_AUTOCUT_COOLDOWN = 2.8
_AUTO_IDLE_SECONDS = 5.0


@dataclass
class SpectatorCamera:
    """One camera state for full-field, manual, follow and automatic broadcasts."""

    base: Viewport
    mode: str = "full"
    zoom: float = 1.0
    target_zoom: float = 1.0
    center: tuple[float, float] = field(init=False)
    target_center: tuple[float, float] = field(init=False)
    follow_id: str | None = None
    auto_pair: tuple[str, str] | None = None
    cut_cooldown: float = 0.0
    idle: float = 0.0

    def __post_init__(self) -> None:
        self.center = self.world_midpoint
        self.target_center = self.center

    @property
    def world_midpoint(self) -> tuple[float, float]:
        return (self.base.world_size[0] / 2, self.base.world_size[1] / 2)

    @property
    def frame_rect(self) -> tuple[int, int, int, int]:
        mid_x, mid_y = self.base.world_to_screen(self.world_midpoint)
        return (
            round(mid_x - self.base.screen_size[0] / 2),
            round(mid_y - self.base.screen_size[1] / 2),
            round(self.base.screen_size[0]),
            round(self.base.screen_size[1]),
        )

    def _clamp(self, point: tuple[float, float], zoom: float) -> tuple[float, float]:
        width, height = self.base.world_size
        half_x = min(width / 2, self.base.screen_size[0] / (2 * self.base.scale * zoom))
        half_y = min(height / 2, self.base.screen_size[1] / (2 * self.base.scale * zoom))
        return (
            max(half_x, min(width - half_x, point[0])),
            max(half_y, min(height - half_y, point[1])),
        )

    def viewport(self) -> Viewport:
        screen_mid = self.base.world_to_screen(self.world_midpoint)
        scale = self.base.scale * self.zoom
        return Viewport(
            origin=(screen_mid[0] - self.center[0] * scale,
                    screen_mid[1] - self.center[1] * scale),
            scale=scale,
            world_size=self.base.world_size,
        )

    def manual(self) -> None:
        self.mode = "manual"
        self.follow_id = None
        self.auto_pair = None

    def reset(self) -> None:
        self.mode = "full"
        self.follow_id = None
        self.auto_pair = None
        self.target_zoom = 1.0
        self.target_center = self.world_midpoint

    def zoom_at(self, steps: int, screen_point: tuple[int, int]) -> None:
        if not steps:
            return
        viewport = self.viewport()
        world_point = viewport.screen_to_world(screen_point)
        if world_point is None:
            return
        self.manual()
        new_zoom = max(1.0, min(MAX_CAMERA_ZOOM, self.target_zoom * 1.25 ** steps))
        # Keep the cursor's current world point under the cursor as zoom changes.
        screen_mid = self.base.world_to_screen(self.world_midpoint)
        self.target_center = self._clamp(
            (
                world_point[0] - (screen_point[0] - screen_mid[0]) / (self.base.scale * new_zoom),
                world_point[1] - (screen_point[1] - screen_mid[1]) / (self.base.scale * new_zoom),
            ),
            new_zoom,
        )
        self.target_zoom = new_zoom

    def pan(self, relative_pixels: tuple[int, int]) -> None:
        self.manual()
        dx, dy = relative_pixels
        scale = self.base.scale * self.zoom
        self.target_center = self._clamp(
            (self.target_center[0] - dx / scale, self.target_center[1] - dy / scale),
            self.target_zoom,
        )

    def follow(self, robot_id: str) -> None:
        self.mode = "follow"
        self.follow_id = robot_id
        self.auto_pair = None
        self.target_zoom = max(self.target_zoom, 2.6)

    def auto(self) -> None:
        self.mode = "auto"
        self.follow_id = None
        self.auto_pair = None
        self.cut_cooldown = 0.0
        self.idle = 0.0

    def observe(self, match: "Match") -> None:
        if self.mode != "auto":
            return
        robots = {robot.id: robot for robot in match.robots if robot.alive}
        candidates = []
        for contact in match.projectile_impacts:
            shooter = robots.get(contact.shooter_id)
            target = robots.get(contact.target_id)
            if shooter is None or target is None or shooter.team == target.team:
                continue
            priority = 3 if contact.applied_damage and contact.surface == "armor" else (
                2 if contact.surface == "armor" else 1
            )
            candidates.append((priority, contact.projectile_id, shooter.id, target.id))
        if not candidates:
            return
        _, _, attacker_id, target_id = max(candidates)
        pair = (attacker_id, target_id)
        if self.auto_pair and set(pair) == set(self.auto_pair):
            self.idle = 0.0
            return
        if self.auto_pair is not None and self.cut_cooldown > 0:
            return
        self.auto_pair = pair
        self.cut_cooldown = _AUTOCUT_COOLDOWN
        self.idle = 0.0

    def update(self, dt: float, match: "Match" | None = None) -> None:
        dt = max(0.0, dt)
        self.cut_cooldown = max(0.0, self.cut_cooldown - dt)
        if match is not None and self.mode == "follow" and self.follow_id:
            robot = next((item for item in match.robots if item.id == self.follow_id), None)
            if robot is not None and robot.alive:
                self.target_center = robot.position
        elif match is not None and self.mode == "auto":
            self.idle += dt
            robots = {robot.id: robot for robot in match.robots if robot.alive}
            if self.auto_pair and self.idle < _AUTO_IDLE_SECONDS and all(
                rid in robots for rid in self.auto_pair
            ):
                first, second = (robots[rid].position for rid in self.auto_pair)
                self.target_center = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
                dx, dy = abs(first[0] - second[0]), abs(first[1] - second[1])
                # Both participants fit with room for their projectiles.
                fit = min(
                    self.base.world_size[0] / (dx + 4800.0),
                    self.base.world_size[1] / (dy + 2800.0),
                )
                self.target_zoom = min(MAX_CAMERA_ZOOM, max(1.0, fit))
            else:
                self.auto_pair = None
                self.target_center = self.world_midpoint
                self.target_zoom = 1.0

        fraction = 1.0 - math.exp(-_CAMERA_RESPONSE * dt)
        self.zoom += (self.target_zoom - self.zoom) * fraction
        if abs(self.zoom - self.target_zoom) < 0.002:
            self.zoom = self.target_zoom
        self.zoom = max(1.0, min(MAX_CAMERA_ZOOM, self.zoom))
        dest = self._clamp(self.target_center, self.zoom)
        self.center = self._clamp(
            (self.center[0] + (dest[0] - self.center[0]) * fraction,
             self.center[1] + (dest[1] - self.center[1]) * fraction),
            self.zoom,
        )
        if math.dist(self.center, dest) < 1.0:
            self.center = dest
