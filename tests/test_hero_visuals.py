"""Hero presentation tests: visual layers and asset transforms only."""
import pygame
import pytest

from tarsgo_simulator.desktop import app
from tarsgo_simulator.desktop.assets import AssetManager


def test_hero_rotation_antialiasing_keeps_alpha_and_uses_transform_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rotozoom = pygame.transform.rotozoom
    calls = 0

    def count(surface: pygame.Surface, angle: float, scale: float) -> pygame.Surface:
        nonlocal calls
        calls += 1
        return rotozoom(surface, angle, scale)

    monkeypatch.setattr(pygame.transform, "rotozoom", count)
    manager = AssetManager(app.ASSET_MANAGER.asset_root)
    first = manager.render("robots/hero-chassis.png", size=(180, 122), angle=37)
    assert first is not None
    assert first.get_flags() & pygame.SRCALPHA
    assert first is manager.render("robots/hero-chassis.png", size=(180, 122), angle=37.4)
    assert calls == 1

    # Existing robot presentation remains on the original rendering path.
    assert manager.render("robots/infantry-chassis.png", size=(120, 92), angle=37)
    assert calls == 1


def test_hero_layers_rotate_independently_and_dead_lights_are_off() -> None:
    assert app._RMUC_ROBOT_SPRITE_SIZES["hero"][1][1] < app._RMUC_ROBOT_SPRITE_SIZES["hero"][0][1]

    def frame(body: float, turret: float, color: tuple[int, int, int], lit: bool) -> bytes:
        screen = pygame.Surface((480, 360), pygame.SRCALPHA)
        assert app._draw_rmuc_robot_sprites(
            screen,
            center=(240, 180),
            robot_type="hero",
            color=color,
            body_angle=body,
            turret_angle=turret,
            lit=lit,
            magnification=3.6,
        )
        return pygame.image.tostring(screen, "RGBA")

    initial = frame(0, 0, app.TEAM_RED_COLOR, True)
    assert frame(0.5, 0, app.TEAM_RED_COLOR, True) != initial
    assert frame(0, 0.5, app.TEAM_RED_COLOR, True) != initial
    assert frame(0, 0, app.TEAM_RED_COLOR, False) != initial
    assert frame(0, 0, app.TEAM_BLUE_COLOR, True) != initial
    assert frame(0, 0, app.TEAM_RED_COLOR, True) == initial
