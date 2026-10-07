from pathlib import Path

import pygame
import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.desktop.assets import AssetManager, resolve_asset_root
from tarsgo_simulator.desktop.polish import structure_display_size


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = REPOSITORY_ROOT / "assets" / "rmuc"
RMUC_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)


def _write_alpha_png(path: Path) -> pygame.Surface:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = pygame.Surface((8, 6), pygame.SRCALPHA, 32)
    image.fill((220, 90, 50, 128))
    pygame.image.save(image, path)
    return image


def test_asset_root_prefers_pyinstaller_bundle_and_paths_stay_inside_root(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundled_assets = bundle / "assets" / "rmuc"
    bundled_assets.mkdir(parents=True)
    source_root = tmp_path / "source"
    package_file = source_root / "src" / "tarsgo_simulator" / "desktop" / "assets.py"
    (source_root / "assets" / "rmuc").mkdir(parents=True)
    package_file.parent.mkdir(parents=True)
    package_file.touch()

    resolved = resolve_asset_root(
        bundle_path=bundle,
        package_file=package_file,
        working_directory=tmp_path / "elsewhere",
    )
    source_resolved = resolve_asset_root(
        package_file=package_file,
        working_directory=tmp_path / "elsewhere",
    )

    assert resolved == bundled_assets.resolve()
    assert source_resolved == (source_root / "assets" / "rmuc").resolve()
    manager = AssetManager(resolved)
    assert manager.path_for("structures/base.png") == (
        bundled_assets / "structures" / "base.png"
    ).resolve()
    with pytest.raises(ValueError):
        manager.path_for("../outside.png")
    with pytest.raises(ValueError):
        manager.path_for("/outside.png")


def test_asset_manager_loads_alpha_png_and_caches_source_and_transforms(
    tmp_path: Path,
) -> None:
    original = _write_alpha_png(tmp_path / "field" / "sample.png")
    manager = AssetManager(tmp_path)

    first = manager.load("field/sample.png")
    second = manager.load("field/sample.png")
    assert first is not None
    assert first is second
    assert first.get_flags() & pygame.SRCALPHA
    assert first.get_at((3, 3)).a == 128

    rendered = manager.render(
        "field/sample.png",
        size=(20, 12),
        angle=90,
        tint=(210, 80, 75),
    )
    assert rendered is not None
    assert rendered is manager.render(
        "field/sample.png",
        size=(20, 12),
        angle=90,
        tint=(210, 80, 75),
    )
    assert rendered.get_size() == (12, 20)
    assert rendered.get_flags() & pygame.SRCALPHA
    assert original.get_size() == (8, 6)


def test_missing_asset_uses_the_supplied_fallback() -> None:
    fallback = pygame.Surface((10, 8), pygame.SRCALPHA)
    manager = AssetManager("/definitely/missing/rmuc-assets")

    assert manager.load("structures/not-installed.png", fallback=fallback) is fallback
    assert manager.render(
        "structures/not-installed.png",
        fallback=fallback,
    ) is fallback


def test_structure_sprites_keep_transparency_and_asset_manager_tints() -> None:
    manager = AssetManager(ASSET_ROOT)
    for name in ("structures/base.png", "structures/outpost.png"):
        sprite = manager.load(name)
        assert sprite is not None
        assert sprite.get_flags() & pygame.SRCALPHA
        assert sprite.get_at((0, 0)).a == 0
        assert any(sprite.get_at((x, y)).a >= 240 for x, y in (
            (sprite.get_width() // 2, sprite.get_height() // 2),
            (sprite.get_width() // 2, sprite.get_height() // 3),
        ))

    red = manager.render(
        "structures/base.png",
        size=(72, 62),
        tint=(213, 83, 78),
    )
    blue = manager.render(
        "structures/base.png",
        size=(72, 62),
        tint=(80, 137, 211),
    )
    assert red is not None and blue is not None
    assert red.get_at((36, 31)) != blue.get_at((36, 31))


def test_rmuc_team_lighting_is_local_and_uses_red_or_blue() -> None:
    from tarsgo_simulator.desktop import app

    pygame.font.init()
    cases = (
        (app.TEAM_RED_COLOR, (250, 63, 71), "red"),
        (app.TEAM_BLUE_COLOR, (72, 157, 255), "blue"),
    )
    for team_color, expected_led, dominant in cases:
        screen = pygame.Surface((100, 80), pygame.SRCALPHA, 32)
        screen.fill((0, 0, 0, 255))
        app._draw_rmuc_team_led_overlay(
            screen,
            center=(50, 40),
            size=(40, 24),
            angle=0.0,
            lights=((0.0, 0.0, "h"),),
            color=team_color,
        )

        pixel = screen.get_at((50, 40))
        assert app._rmuc_led_color(team_color) == expected_led
        assert pixel[0] > pixel[2] if dominant == "red" else pixel[2] > pixel[0]
        assert screen.get_at((5, 5))[:3] == (0, 0, 0)
        colored_pixels = sum(
            screen.get_at((x, y))[:3] != (0, 0, 0)
            for x in range(screen.get_width())
            for y in range(screen.get_height())
        )
        assert 0 < colored_pixels < 200


def test_robot_sprite_set_is_complete_transparent_and_presentation_only() -> None:
    manager = AssetManager(ASSET_ROOT)
    sprite_names = (
        "robots/hero-chassis.png",
        "robots/hero-turret.png",
        "robots/engineer.png",
        "robots/infantry-chassis.png",
        "robots/infantry-turret.png",
        "robots/sentry-chassis.png",
        "robots/sentry-turret.png",
        "robots/drone.png",
    )

    for name in sprite_names:
        sprite = manager.load(name)
        assert sprite is not None
        assert sprite.get_flags() & pygame.SRCALPHA
        assert sprite.get_at((0, 0)).a <= 1
        rendered = manager.render(name, size=(48, 32), angle=37, tint=(213, 83, 78))
        assert rendered is not None
        assert rendered.get_flags() & pygame.SRCALPHA


def test_missing_structure_sprite_uses_procedural_drawing_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tarsgo_simulator.desktop import app

    monkeypatch.setattr(app, "ASSET_MANAGER", AssetManager(tmp_path / "missing"))
    pygame.font.init()
    screen = pygame.Surface(app.WINDOW_SIZE)
    screen.fill((0, 0, 0))
    size = app._draw_rmuc_structure(
        screen,
        pygame.font.Font(None, 18),
        structure_type="base",
        center=(100, 100),
        color=app.TEAM_RED_COLOR,
        alive=True,
        hp=5000,
        max_hp=5000,
        status="",
        animation_time=0.0,
        debug_geometry=False,
    )

    assert size > 0
    assert screen.get_at((100, 100))[:3] != (0, 0, 0)
    floor_screen = pygame.Surface(app.WINDOW_SIZE)
    floor_screen.fill((0, 0, 0))
    app._draw_rmuc_battlefield(
        floor_screen,
        pygame.Rect(*app.RMUC_FIELD_VIEW_RECT),
    )
    assert floor_screen.get_at((100, 250))[:3] != (0, 0, 0)


def test_missing_robot_sprite_uses_procedural_drawing_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tarsgo_simulator.desktop import app

    monkeypatch.setattr(app, "ASSET_MANAGER", AssetManager(tmp_path / "missing"))
    screen = pygame.Surface((128, 128))
    screen.fill((0, 0, 0))
    app._draw_rmuc_robot_shape(
        screen,
        center=(64, 64),
        robot_type="hero",
        color=app.TEAM_RED_COLOR,
        body_angle=0.2,
        turret_angle=-0.1,
        alive=True,
        selected=False,
        animation_time=0.0,
        muzzle_remaining=0.0,
        muzzle_caliber="42mm",
        impact_remaining=0.0,
    )

    assert screen.get_at((64, 64))[:3] != (0, 0, 0)


def test_rmuc_art_renders_at_1100x780_without_changing_mm_footprints() -> None:
    from tarsgo_simulator.desktop import app
    from tarsgo_simulator.desktop.visuals import CombatVisualState

    pygame.font.init()
    match = Match.from_scenario(RMUC_SCENARIO)
    structures = tuple(match.structures)
    original = {
        structure.id: (
            match.map.structure_bounds(structure.id),
            structure.footprint,
            structure.footprint_vertices,
            structure.footprint_shape,
        )
        for structure in structures
    }
    original_robots = {
        robot.id: (
            robot.position,
            robot.type,
            robot.alive,
            match.ruleset.robot_parameters(robot.type),
        )
        for robot in match.robots
    }
    viewport = app._viewport_for_match(match)
    screen = pygame.Surface(app.WINDOW_SIZE)
    teams = tuple(team.team_id for team in match.config.scenario.teams.values())
    player_team = match.config.scenario.player_team
    opponent_team = next(team_id for team_id in teams if team_id != player_team)

    visual_state = CombatVisualState()
    visual_state.reset(match)
    app._draw(
        screen,
        pygame.font.Font(None, 25),
        pygame.font.Font(None, 18),
        match,
        player_team,
        opponent_team,
        set(),
        None,
        viewport,
        visual_state=visual_state,
    )

    assert screen.get_size() == (1100, 780)
    assert app.ASSET_MANAGER.load("field/floor-surface.png") is not None
    assert app.ASSET_MANAGER.load("structures/base.png") is not None
    assert app.ASSET_MANAGER.load("structures/outpost.png") is not None
    assert all(
        app.ASSET_MANAGER.load(f"robots/{name}") is not None
        for name in (
            "hero-chassis.png",
            "hero-turret.png",
            "engineer.png",
            "infantry-chassis.png",
            "infantry-turret.png",
            "sentry-chassis.png",
            "sentry-turret.png",
            "drone.png",
        )
    )
    for structure in structures:
        assert (
            match.map.structure_bounds(structure.id),
            structure.footprint,
            structure.footprint_vertices,
            structure.footprint_shape,
        ) == original[structure.id]
    for robot in match.robots:
        assert (
            robot.position,
            robot.type,
            robot.alive,
            match.ruleset.robot_parameters(robot.type),
        ) == original_robots[robot.id]

    outpost = next(item for item in structures if item.type == "outpost")
    physical_bounds = match.map.structure_bounds(outpost.id)
    assert physical_bounds is not None
    physical_diameter = round(viewport.world_length_to_screen(outpost.footprint[0]))
    assert physical_diameter < structure_display_size(
        "outpost",
        (physical_diameter, physical_diameter),
    )[0]


def test_default_rmuc_view_uses_small_road_cues_and_keeps_debug_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tarsgo_simulator.desktop import app

    pygame.font.init()
    match = Match.from_scenario(RMUC_SCENARIO)
    teams = tuple(team.team_id for team in match.config.scenario.teams.values())
    player_team = match.config.scenario.player_team
    opponent_team = next(team_id for team_id in teams if team_id != player_team)
    calls: list[bool] = []

    def record_terrain_draw(*_args: object, **kwargs: object) -> tuple[()]:
        calls.append(bool(kwargs.get("debug_geometry")))
        return ()

    monkeypatch.setattr(app, "_draw_rmuc_terrain", record_terrain_draw)
    arguments = (
        pygame.font.Font(None, 25),
        pygame.font.Font(None, 18),
        match,
        player_team,
        opponent_team,
        set(),
        None,
        app._viewport_for_match(match),
    )

    app._draw(pygame.Surface(app.WINDOW_SIZE), *arguments)
    assert calls == [False]

    app._draw(pygame.Surface(app.WINDOW_SIZE), *arguments, debug_geometry=True)
    assert calls == [False, True]


def test_default_floor_regions_use_only_configured_nonterrain_polygons() -> None:
    from tarsgo_simulator.desktop import app

    pygame.font.init()
    match = Match.from_scenario(RMUC_SCENARIO)
    zones_before = tuple(
        (zone.id, zone.vertices, zone.x, zone.y, zone.width, zone.height)
        for zone in match.map.zones
    )
    rendered = app._draw_rmuc_field_regions(
        pygame.Surface(app.WINDOW_SIZE),
        pygame.Rect(*app.RMUC_FIELD_VIEW_RECT),
        app._viewport_for_match(match),
        match.map.zones,
    )

    rendered_ids = set(rendered)
    assert {
        "red-start",
        "blue-start",
        "red-base-buff",
        "blue-base-buff",
        "red-resource",
        "blue-resource",
        "red-assembly",
        "blue-assembly",
    } <= rendered_ids
    assert not any("terrain-" in zone_id for zone_id in rendered_ids)
    assert tuple(
        (zone.id, zone.vertices, zone.x, zone.y, zone.width, zone.height)
        for zone in match.map.zones
    ) == zones_before


def test_packaging_configuration_copies_the_rmuc_asset_directory() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "build-desktop.yml").read_text()
    required_files = (
        ASSET_ROOT / "field" / "floor-surface.png",
        ASSET_ROOT / "structures" / "base.png",
        ASSET_ROOT / "structures" / "outpost.png",
        ASSET_ROOT / "robots" / "hero-chassis.png",
        ASSET_ROOT / "robots" / "hero-turret.png",
        ASSET_ROOT / "robots" / "engineer.png",
        ASSET_ROOT / "robots" / "infantry-chassis.png",
        ASSET_ROOT / "robots" / "infantry-turret.png",
        ASSET_ROOT / "robots" / "sentry-chassis.png",
        ASSET_ROOT / "robots" / "sentry-turret.png",
        ASSET_ROOT / "robots" / "drone.png",
    )

    assert all(path.is_file() for path in required_files)
    assert '--add-data "assets${{ matrix.data_separator }}assets"' in workflow
