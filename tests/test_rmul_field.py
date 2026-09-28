import math
from pathlib import Path

from tarsgo_simulator.core.config import load_match_config
from tarsgo_simulator.core.match import Match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RULES_LAB_PATH = REPOSITORY_ROOT / "configs" / "scenarios" / "rmul-2026-rules-lab.yaml"
FIELD_WIDTH = 1200.0
FIELD_HEIGHT = 800.0


def _match() -> Match:
    return Match(load_match_config(RULES_LAB_PATH))


def _zone(match: Match, zone_id: str):
    return next(zone for zone in match.map.zones if zone.id == zone_id)


def _rectangle_center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _rotated_rectangle(zone) -> tuple[float, float, float, float]:
    return (
        FIELD_WIDTH - zone.right,
        FIELD_HEIGHT - zone.bottom,
        zone.width,
        zone.height,
    )


def test_rmul_field_uses_official_twelve_by_eight_meter_footprint_scale() -> None:
    match = _match()

    assert match.map.width == FIELD_WIDTH
    assert match.map.height == FIELD_HEIGHT
    assert match.map.obstacles == ()


def test_supply_regions_are_center_symmetric() -> None:
    match = _match()
    red = _zone(match, "red-supply")
    blue = _zone(match, "blue-supply")

    assert _rotated_rectangle(red) == (blue.x, blue.y, blue.width, blue.height)


def test_control_region_is_centered_on_battlefield() -> None:
    match = _match()
    control = _zone(match, "center-control")

    assert _rectangle_center(control) == (FIELD_WIDTH / 2, FIELD_HEIGHT / 2)


def test_high_ground_regions_are_center_symmetric_and_pathable() -> None:
    match = _match()
    red = _zone(match, "red-high-ground")
    blue = _zone(match, "blue-high-ground")

    assert _rotated_rectangle(red) == (blue.x, blue.y, blue.width, blue.height)
    assert match.map.is_passable(_rectangle_center(red))
    assert match.map.is_passable(_rectangle_center(blue))


def test_all_rmul_field_regions_stay_inside_field_bounds() -> None:
    match = _match()

    for zone in match.map.zones:
        assert 0 <= zone.x <= zone.right <= FIELD_WIDTH
        assert 0 <= zone.y <= zone.bottom <= FIELD_HEIGHT


def test_rmul_spawns_are_synthetic_points_inside_own_supply_regions() -> None:
    match = _match()
    red_supply = _zone(match, "red-supply")
    blue_supply = _zone(match, "blue-supply")
    red_team = match.config.scenario.teams["red"].team_id
    blue_team = match.config.scenario.teams["blue"].team_id

    for robot in match.robots:
        supply = red_supply if robot.team == red_team else blue_supply
        assert supply.contains(robot.position)

    minimum_distance = match.map.collision_radius * 2
    for index, first in enumerate(match.robots):
        for second in match.robots[index + 1 :]:
            assert math.dist(first.position, second.position) >= minimum_distance


def test_existing_rmul_rules_resolve_same_zone_ids_on_new_geometry() -> None:
    match = _match()
    rules = match.ruleset

    assert rules._control_zone.id == "center-control"
    assert rules._supply_zones[match.config.scenario.teams["red"].team_id].id == "red-supply"
    assert rules._supply_zones[match.config.scenario.teams["blue"].team_id].id == "blue-supply"
    assert rules._forbidden_zones[match.config.scenario.teams["red"].team_id].id == "blue-supply"
    assert rules._forbidden_zones[match.config.scenario.teams["blue"].team_id].id == "red-supply"
