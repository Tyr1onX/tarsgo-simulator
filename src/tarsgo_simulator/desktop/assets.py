"""Presentation-only RMUC image assets and their runtime transforms."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path, PurePosixPath
import sys

import pygame


ASSET_BUNDLE_DIRECTORY = Path("assets") / "rmuc"
_TRANSFORM_CACHE_LIMIT = 1024
_PREPARED_CACHE_LIMIT = 32
_ANGLE_QUANTUM_DEGREES = 3.0
_FILTERED_ROBOT_ROTATION_ASSETS = frozenset(
    {
        "robots/hero-chassis.png",
        "robots/hero-turret.png",
        "robots/infantry-chassis.png",
        "robots/infantry-turret.png",
        "robots/sentry-chassis.png",
        "robots/sentry-turret.png",
        "robots/engineer.png",
        "robots/drone.png",
    }
)
_FILTERED_ROBOT_ROTATION_MIN_SIZE = 64
_FILTERED_ROBOT_ROTATION_MIN_SIZE_BY_ASSET = {
    "robots/engineer.png": 96,
}


def quantize_transform_angle(angle: float) -> float:
    """Snap presentation rotations to the nearest three degree cache bucket."""
    return round(round(float(angle) / _ANGLE_QUANTUM_DEGREES) * _ANGLE_QUANTUM_DEGREES, 3) % 360.0


def resolve_asset_root(
    *,
    bundle_path: str | Path | None = None,
    package_file: str | Path | None = None,
    working_directory: str | Path | None = None,
) -> Path | None:
    """Find ``assets/rmuc`` in a PyInstaller bundle or source checkout."""
    candidates: list[Path] = []
    if bundle_path is not None:
        candidates.append(Path(bundle_path) / ASSET_BUNDLE_DIRECTORY)

    source_file = Path(package_file) if package_file is not None else Path(__file__)
    source_parts = source_file.resolve().parents
    if len(source_parts) > 3:
        candidates.append(source_parts[3] / ASSET_BUNDLE_DIRECTORY)

    if working_directory is not None:
        candidates.append(Path(working_directory) / ASSET_BUNDLE_DIRECTORY)
    else:
        candidates.append(Path.cwd() / ASSET_BUNDLE_DIRECTORY)

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_dir():
            return resolved
    return candidates[0].expanduser().resolve() if candidates else None


class AssetManager:
    """Load, cache, scale, and rotate presentation assets.

    All dimensions passed here are screen pixels. They never feed back into
    match geometry, collision, navigation, or rules.
    """

    def __init__(self, asset_root: str | Path | None = None) -> None:
        self.asset_root = (
            Path(asset_root).expanduser().resolve()
            if asset_root is not None
            else resolve_asset_root(bundle_path=getattr(sys, "_MEIPASS", None))
        )
        self._source_cache: dict[str, pygame.Surface] = {}
        self._prepared_cache: OrderedDict[
            tuple[object, ...], pygame.Surface
        ] = OrderedDict()
        self._transform_cache: OrderedDict[
            tuple[object, ...], pygame.Surface
        ] = OrderedDict()

    @staticmethod
    def _relative_key(relative_path: str | Path) -> str:
        text = str(relative_path).replace("\\", "/")
        path = PurePosixPath(text)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("asset path must be relative to the RMUC asset root")
        return path.as_posix()

    def path_for(self, relative_path: str | Path) -> Path | None:
        """Resolve one asset path while preventing traversal outside the root."""
        key = self._relative_key(relative_path)
        if self.asset_root is None:
            return None
        path = (self.asset_root / key).resolve()
        if not path.is_relative_to(self.asset_root):
            raise ValueError("asset path escapes the RMUC asset root")
        return path

    def load(
        self,
        relative_path: str | Path,
        *,
        fallback: pygame.Surface | None = None,
    ) -> pygame.Surface | None:
        """Load a PNG once; a missing or unreadable image returns fallback."""
        key = self._relative_key(relative_path)
        cached = self._source_cache.get(key)
        if cached is not None:
            return cached
        path = self.path_for(key)
        if path is None or not path.is_file():
            return fallback
        try:
            surface = pygame.image.load(str(path))
        except (OSError, pygame.error):
            return fallback
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
            surface = surface.convert_alpha()
        else:
            surface = surface.copy()
        self._source_cache[key] = surface
        return surface

    def render(
        self,
        relative_path: str | Path,
        *,
        size: tuple[int, int] | None = None,
        angle: float = 0.0,
        tint: tuple[int, int, int] | None = None,
        fallback: pygame.Surface | None = None,
    ) -> pygame.Surface | None:
        """Return a cached scale/rotation/team-tinted presentation surface."""
        key = self._relative_key(relative_path)
        source = self.load(key, fallback=fallback)
        if source is None:
            return None

        normalized_size = None if size is None else tuple(int(value) for value in size)
        if normalized_size is not None and any(value <= 0 for value in normalized_size):
            raise ValueError("asset display size must be positive")
        normalized_angle = quantize_transform_angle(angle)
        normalized_tint = None if tint is None else tuple(int(c) for c in tint)
        transform_key = (key, normalized_size, normalized_angle, normalized_tint)
        cached = self._transform_cache.get(transform_key)
        if cached is not None:
            self._transform_cache.move_to_end(transform_key)
            return cached

        rendered = source
        if normalized_size is not None and rendered.get_size() != normalized_size:
            prepared_key = (key, normalized_size)
            prepared = self._prepared_cache.get(prepared_key)
            if prepared is None:
                prepared = pygame.transform.smoothscale(rendered, normalized_size)
                self._prepared_cache[prepared_key] = prepared
                if len(self._prepared_cache) > _PREPARED_CACHE_LIMIT:
                    self._prepared_cache.popitem(last=False)
            else:
                self._prepared_cache.move_to_end(prepared_key)
            rendered = prepared
        if normalized_angle:
            # Filter detailed robot art once its on-screen pixels can show the gain.
            filtered_rotation = key in (
                "robots/hero-chassis.png",
                "robots/hero-turret.png",
            ) or (
                key in _FILTERED_ROBOT_ROTATION_ASSETS
                and normalized_size is not None
                and max(normalized_size)
                >= _FILTERED_ROBOT_ROTATION_MIN_SIZE_BY_ASSET.get(
                    key,
                    _FILTERED_ROBOT_ROTATION_MIN_SIZE,
                )
            )
            if filtered_rotation:
                rendered = pygame.transform.rotozoom(rendered, normalized_angle, 1.0)
            else:
                rendered = pygame.transform.rotate(rendered, normalized_angle)
        if normalized_tint is not None:
            # Multiplication tints only RGB and keeps the source alpha channel.
            strength = 0.30
            multiplier = tuple(
                round(255 * (1.0 - strength) + channel * strength)
                for channel in normalized_tint
            )
            tint_layer = pygame.Surface(rendered.get_size(), pygame.SRCALPHA)
            tint_layer.fill((*multiplier, 255))
            rendered = rendered.copy()
            rendered.blit(tint_layer, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        self._transform_cache[transform_key] = rendered
        if len(self._transform_cache) > _TRANSFORM_CACHE_LIMIT:
            self._transform_cache.popitem(last=False)
        return rendered

    def clear_cache(self) -> None:
        """Drop loaded and transformed surfaces, useful for reloads and tests."""
        self._source_cache.clear()
        self._prepared_cache.clear()
        self._transform_cache.clear()


ASSET_MANAGER = AssetManager()
