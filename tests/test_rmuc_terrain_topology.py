from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_match_config
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.pathfinding import find_path, find_terrain_path


ROOT = Path(__file__).resolve().parents[1]
RMUC = ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RMUL = ROOT / "configs" / "scenarios" / "rmul-2026-rules-lab.yaml"
TRAINING = ROOT / "configs" / "scenarios" / "first-steps.yaml"


def _match(path: Path = RMUC) -> Match:
    return Match.from_scenario(path)


def test_official_terrain_metadata_keeps_only_documented_measurements() -> None:
    match = _match()
    features = {feature.id: feature for feature in match.map.terrain_features}

    assert features["field-ground"].kind == "ground"
    assert features["central-highland"].kind == "elevated"
    assert features["north-road"].kind == "surface"
    assert features["central-ramp-north"].slope_degrees == 10.5
    assert features["central-ramp-south"].slope_degrees == 10.5
    assert features["red-trapezoid-highland"].relative_height_mm == (200.0, 400.0)
    assert features["red-trapezoid-ramp-steep"].slope_degrees == 43
    assert features["red-trapezoid-ramp-shallow"].slope_degrees == 23
    assert features["road-ramp-11"].slope_degrees == 11
    assert features["road-ramp-15"].slope_degrees == 15
    assert features["fly-slope"].slope_degrees == 17
    assert features["fortress-ramp"].slope_degrees == 20
    assert features["assembly-slope-red-outer"].slope_degrees == 14
    assert features["assembly-slope-red-inner"].slope_degrees == 12
    assert features["assembly-slope-blue-inner"].slope_degrees == 45
    assert features["assembly-slope-blue-outer"].slope_degrees == 15
    assert all(feature.source for feature in features.values())


def test_central_highland_is_reachable_from_both_roads_only_via_ramp() -> None:
    match = _match()

    northbound = find_terrain_path(match.map, "north-road", "central-highland")
    southbound = find_terrain_path(match.map, "south-road", "central-highland")

    assert northbound == ["north-road", "central-ramp-north", "central-highland"]
    assert southbound == ["south-road", "central-ramp-south", "central-highland"]
    assert find_terrain_path(match.map, "central-highland", "north-road") == list(
        reversed(northbound)
    )
    assert find_terrain_path(match.map, "field-ground", "central-highland") is None


def test_trapezoid_ramp_grade_does_not_invent_robot_traversability() -> None:
    match = _match()

    assert find_terrain_path(match.map, "field-ground", "red-trapezoid-highland") is None
    assert find_terrain_path(match.map, "field-ground", "blue-trapezoid-highland") is None


def test_tunnel_route_uses_a_named_passage_between_its_two_mouths() -> None:
    match = _match()

    assert find_terrain_path(
        match.map,
        "road-tunnel-west-entry",
        "road-tunnel-west-exit",
    ) == [
        "road-tunnel-west-entry",
        "road-tunnel-west-passage",
        "road-tunnel-west-exit",
    ]
    assert find_terrain_path(
        match.map,
        "road-tunnel-east-entry",
        "road-tunnel-east-exit",
    ) == [
        "road-tunnel-east-entry",
        "road-tunnel-east-passage",
        "road-tunnel-east-exit",
    ]


def test_terrain_graph_does_not_change_xy_collision_or_drone_pathing() -> None:
    match = _match()
    drone = next(robot for robot in match.robots if robot.type == "drone")
    start, goal = (1000.0, 1000.0), (10000.0, 1000.0)

    assert match.map.is_passable(start) and match.map.is_passable(goal)
    path = find_path(match.map, start, goal)
    assert path is not None
    assert all(match.map.can_traverse(a, b) for a, b in zip(path, path[1:]))

    drone.position = start
    drone.path = [goal]
    drone.speed = 5000.0
    drone.alive = True
    new_position, remaining = drone.propose_movement(2.0, match.map)
    assert new_position != start
    assert remaining == []


def test_reset_rebuilds_terrain_metadata_without_carrying_map_state() -> None:
    match = _match()
    old_map = match.map
    old_features = old_map.terrain_features

    match.reset()

    assert match.map is not old_map
    assert match.map.terrain_features == old_features
    assert find_terrain_path(match.map, "north-road", "central-highland") is not None


def test_training_and_rmul_maps_do_not_receive_rmuc_terrain_metadata() -> None:
    for scenario in (TRAINING, RMUL):
        config = load_match_config(scenario)
        assert config.scenario.terrain_features == ()
        assert config.scenario.terrain_connections == ()
        assert _match(scenario).map.terrain_features == ()


def test_unverified_connections_fail_config_validation(tmp_path: Path) -> None:
    # Keep the field source local to this temporary scenario so this assertion
    # checks schema validation without changing the repository's canonical YAML.
    config_root = tmp_path / "configs"
    (config_root / "scenarios").mkdir(parents=True)
    (config_root / "rules").mkdir()
    (config_root / "fields").mkdir()
    (config_root / "teams").mkdir()
    scenario_data = yaml.safe_load(RMUC.read_text(encoding="utf-8"))
    field_id = scenario_data["field_geometry"]
    field_data = yaml.safe_load(
        (ROOT / "configs" / "fields" / f"{field_id}.yaml").read_text(encoding="utf-8")
    )
    field_data["terrain"]["connections"].append(
        {"from": "field-ground", "to": "central-highland", "via": "central-highland"}
    )
    (config_root / "fields" / f"{field_id}.yaml").write_text(
        yaml.safe_dump(field_data, sort_keys=False), encoding="utf-8"
    )
    (config_root / "scenarios" / RMUC.name).write_text(
        RMUC.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for folder in ("rules", "teams"):
        for source in (ROOT / "configs" / folder).glob("*.yaml"):
            (config_root / folder / source.name).write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )

    with pytest.raises(ConfigError, match="via.*坡道或隧道"):
        load_match_config(config_root / "scenarios" / RMUC.name)
