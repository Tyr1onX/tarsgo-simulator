"""Uniform world/screen transform for the desktop renderer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Viewport:
    """Fit one world rectangle into a screen rectangle without stretching."""

    origin: tuple[float, float]
    scale: float
    world_size: tuple[float, float]

    @classmethod
    def fit(
        cls,
        world_size: tuple[float, float],
        screen_rect: tuple[float, float, float, float],
    ) -> "Viewport":
        world_width, world_height = world_size
        left, top, available_width, available_height = screen_rect
        if world_width <= 0 or world_height <= 0:
            raise ValueError("world_size must be positive")
        if available_width <= 0 or available_height <= 0:
            raise ValueError("screen_rect must have positive size")

        scale = min(
            available_width / world_width,
            available_height / world_height,
        )
        rendered_width = world_width * scale
        rendered_height = world_height * scale
        origin = (
            left + (available_width - rendered_width) / 2,
            top + (available_height - rendered_height) / 2,
        )
        return cls(origin=origin, scale=scale, world_size=world_size)

    @property
    def screen_size(self) -> tuple[float, float]:
        return (
            self.world_size[0] * self.scale,
            self.world_size[1] * self.scale,
        )

    def world_to_screen(self, point: tuple[float, float]) -> tuple[float, float]:
        return (
            self.origin[0] + point[0] * self.scale,
            self.origin[1] + point[1] * self.scale,
        )

    def screen_to_world(
        self, point: tuple[float, float]
    ) -> tuple[float, float] | None:
        world = (
            (point[0] - self.origin[0]) / self.scale,
            (point[1] - self.origin[1]) / self.scale,
        )
        epsilon = 1e-9
        if (
            -epsilon <= world[0] <= self.world_size[0] + epsilon
            and -epsilon <= world[1] <= self.world_size[1] + epsilon
        ):
            return (
                min(self.world_size[0], max(0.0, world[0])),
                min(self.world_size[1], max(0.0, world[1])),
            )
        return None

    def world_length_to_screen(self, value: float) -> float:
        return value * self.scale
