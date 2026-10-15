from collections import Counter
import json
from pathlib import Path
import shutil
import sys

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_match_config
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.replay import cli as replay_cli
from tarsgo_simulator.desktop.app import (
    _is_rmuc_2027_rules_lab,
    _robot_display_names,
    _window_caption,
)
from tarsgo_simulator.rules.registry import RULESETS
from tarsgo_simulator.rules.rmuc_2027_region import RMUC_2027_RULE_ID, RMUC2027RegionRules


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "configs" / "scenarios" / "rmuc-2027-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2027-region"
BLUE = "opponent-rmuc-2027-region"
ACTIVE_GROUND_ROSTER = Counter({"heavy": 1, "infantry": 2, "sentry": 1})


def _match(*, seed: int | None = None) -> Match:
    return Match.from_scenario(SCENARIO, seed=seed)


def _copy_configs(tmp_path: Path) -> Path:
    config_root = tmp_path / "configs"
    shutil.copytree(ROOT / "configs", config_root)
    return config_root


def _zone_match(
    tmp_path: Path,
    *,
    spawns: dict[str, list[int]],
) -> Match:
    config_root = _copy_configs(tmp_path)
    scenario_file = config_root / "scenarios" / SCENARIO.name
    scenario = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    scenario["setup"]["spawns"].update(spawns)
    scenario_file.write_text(
        yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8"
    )
    return Match.from_scenario(scenario_file, seed=2027)


def _tick(match: Match, seconds: float) -> None:
    for _ in range(round(seconds * 60)):
        match.update(1 / 60)


def _territory(match: Match, territory_id: str):
    return next(
        item
        for item in match.ruleset.display_state.territory_control
        if item.territory_id == territory_id
    )


def test_rmuc_2027_ruleset_identity_and_official_active_roster() -> None:
    match = _match(seed=27)
    metadata = match.config.rule_document.metadata

    assert isinstance(match.ruleset, RMUC2027RegionRules)
    assert metadata.id == RMUC_2027_RULE_ID
    assert metadata.competition == "RMUC"
    assert metadata.season == 2027
    assert metadata.official_version == "V1.0.0"
    assert metadata.status == "rules-lab-partial"
    assert match.time_limit == 420
    assert match.seed == 27
    assert match.config.scenario.map_width == 28000
    assert match.config.scenario.map_height == 15000
    assert len(match.config.scenario.zones) == 8
    assert all(zone.approximation for zone in match.config.scenario.zones)
    assert match.structures == []

    for team_id in (RED, BLUE):
        assert Counter(
            robot.type for robot in match.robots if robot.team == team_id
        ) == ACTIVE_GROUND_ROSTER
    assert len(match.robots) == 8
    assert all(not robot.aerial for robot in match.robots)
    assert match.config.scenario.player_controlled == frozenset(
        {"tarsgo-heavy", "tarsgo-infantry-1", "tarsgo-infantry-2"}
    )

    active_roster = match.config.rule_document.data["active_roster"]
    assert active_roster["systems"] == {
        "air": {"hangar": 1, "aircraft": 4},
        "dart": {"launcher": 1, "dart_bodies": 4},
        "radar": {"computing_platform": 1, "sensor": 1},
    }


def test_rmuc_2027_ruleset_rejects_legacy_and_non_ground_robot_types() -> None:
    rules = _match().ruleset

    for robot_type in ("hero", "engineer", "drone", "hangar", "dart", "radar"):
        with pytest.raises(ConfigError, match="does not support mobile robot type"):
            rules.robot_parameters(robot_type)


@pytest.mark.parametrize(
    ("robot_id", "replacement_type"),
    [
        ("tarsgo-heavy", "hero"),
        ("tarsgo-infantry-1", "engineer"),
        ("tarsgo-infantry-1", "drone"),
        ("tarsgo-sentry", "infantry"),
    ],
)
def test_match_rejects_legacy_or_illegal_2027_rosters(
    tmp_path: Path, robot_id: str, replacement_type: str
) -> None:
    config_root = _copy_configs(tmp_path)
    team_file = config_root / "teams" / "tarsgo-rmuc-2027-region.yaml"
    team_data = yaml.safe_load(team_file.read_text(encoding="utf-8"))
    robot = next(item for item in team_data["robots"] if item["id"] == robot_id)
    robot["type"] = replacement_type
    team_file.write_text(yaml.safe_dump(team_data, sort_keys=False), encoding="utf-8")

    config = load_match_config(config_root / "scenarios" / SCENARIO.name)
    with pytest.raises(ConfigError, match="active ground roster"):
        Match(config)


def test_reset_enables_real_movement_but_keeps_combat_unimplemented() -> None:
    match = _match(seed=2027)
    initial_positions = {robot.id: robot.position for robot in match.robots}
    heavy = next(robot for robot in match.robots if robot.id == "tarsgo-heavy")

    match.update(0.25)
    assert match.elapsed_time == pytest.approx(0.25)
    assert match.ruleset.can_move(heavy)
    assert not match.ruleset.can_attack(heavy)
    assert not match.ruleset.can_target(heavy)
    assert match.ruleset.resolve_damage(heavy, 50, BLUE) == 0
    assert match.ruleset.evaluate_result(match) is None
    assert all(item.status == "full" for item in match.ruleset.display_state.territory_control)

    heavy.hp = 0
    heavy.alive = False
    match.reset()

    assert match.seed == 2027
    assert match.elapsed_time == 0
    assert all(robot.alive and robot.hp == robot.max_hp for robot in match.robots)
    assert {robot.id: robot.position for robot in match.robots} == initial_positions
    assert all(not robot.aerial for robot in match.robots)

    assert all(
        item.status == "full"
        for item in match.ruleset.display_state.territory_control
    )

    # P2a still has no official winner calculation at the timer boundary.
    match.elapsed_time = match.time_limit
    assert match.ruleset.evaluate_result(match) is None


def test_rmuc_2027_is_additive_and_has_an_explicit_rules_lab_ui_label() -> None:
    assert RULESETS["rmuc-2027-region-v1.0.0"] is RMUC2027RegionRules
    assert "rmuc-2026-region-v1.4.0" in RULESETS
    assert "rmul-2026-3v3" in RULESETS
    assert "training-v0" in RULESETS

    match = _match()
    assert _window_caption(match) == (
        "TARS-Go RMUC 2027 Rules Lab (P2a: Territory Control)"
    )
    names = _robot_display_names(match)
    assert names["tarsgo-heavy"] == "重装"
    assert _is_rmuc_2027_rules_lab(match)


def test_real_movement_captures_opponent_outpost_territory_after_five_seconds(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={"tarsgo-infantry-1": [23000, 7500]},
    )
    robot = next(item for item in match.robots if item.id == "tarsgo-infantry-1")
    zone = next(item for item in match.map.zones if item.id == "blue-outpost-point")

    assert match.order_move(robot.id, (25200, 7500))
    for _ in range(180):
        if zone.contains(robot.position):
            break
        match.update(1 / 60)
    assert zone.contains(robot.position)
    _tick(match, 4.5)
    assert _territory(match, "blue-outpost").status == "full"
    _tick(match, 0.6)

    territory = _territory(match, "blue-outpost")
    assert territory.status == "temporary"
    assert territory.owner == RED

    match.reset()
    assert _territory(match, "blue-outpost").status == "full"
    assert _territory(match, "blue-outpost").owner == BLUE


def test_interrupted_capture_retreats_after_two_second_activation_invalidation(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={"tarsgo-infantry-1": [23000, 7500]},
    )
    robot = next(item for item in match.robots if item.id == "tarsgo-infantry-1")
    zone = next(item for item in match.map.zones if item.id == "blue-outpost-point")
    assert match.order_move(robot.id, (25200, 7500))
    for _ in range(180):
        if zone.contains(robot.position):
            break
        match.update(1 / 60)
    assert zone.contains(robot.position)
    _tick(match, 1.0)
    before_exit = _territory(match, "blue-outpost").progress_seconds
    assert 0.9 <= before_exit <= 1.1

    assert match.order_move(robot.id, (22600, 7500))
    for _ in range(180):
        if not zone.contains(robot.position):
            break
        match.update(1 / 60)
    assert not zone.contains(robot.position)
    progress_at_exit = _territory(match, "blue-outpost").progress_seconds
    _tick(match, 1.8)
    during_invalidation = _territory(match, "blue-outpost").progress_seconds
    assert during_invalidation == pytest.approx(
        progress_at_exit + 1.8, abs=0.04
    )
    _tick(match, 0.7)
    assert _territory(match, "blue-outpost").progress_seconds < during_invalidation


def test_temporary_outpost_control_returns_to_prior_full_owner_after_five_idle_seconds(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={"tarsgo-infantry-1": [23000, 7500]},
    )
    robot = next(item for item in match.robots if item.id == "tarsgo-infantry-1")
    zone = next(item for item in match.map.zones if item.id == "blue-outpost-point")
    assert match.order_move(robot.id, (25200, 7500))
    for _ in range(180):
        if zone.contains(robot.position):
            break
        match.update(1 / 60)
    assert zone.contains(robot.position)
    _tick(match, 5.2)
    assert _territory(match, "blue-outpost").status == "temporary"
    assert _territory(match, "blue-outpost").owner == RED

    assert match.order_move(robot.id, (22600, 7500))
    for _ in range(180):
        if not zone.contains(robot.position):
            break
        match.update(1 / 60)
    assert not zone.contains(robot.position)
    _tick(match, 7.2)
    territory = _territory(match, "blue-outpost")
    assert territory.status == "full"
    assert territory.owner == BLUE


def test_opponent_can_only_take_temporary_control_of_base_territory(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={
            "tarsgo-infantry-1": [23000, 13200],
            "opponent-heavy": [23000, 10000],
            "opponent-infantry-1": [23600, 10000],
            "opponent-infantry-2": [23000, 10600],
            "opponent-sentry": [23600, 10600],
        },
    )
    robot = next(item for item in match.robots if item.id == "tarsgo-infantry-1")
    zone = next(item for item in match.map.zones if item.id == "blue-base-point")
    assert match.order_move(robot.id, (25950, 13200))
    for _ in range(180):
        if zone.contains(robot.position):
            break
        match.update(1 / 60)
    assert zone.contains(robot.position)
    _tick(match, 6)

    territory = _territory(match, "blue-base")
    assert territory.status == "temporary"
    assert territory.owner == RED


def test_opposing_robots_on_distinct_gainpoints_pause_the_same_territory(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={
            "tarsgo-infantry-1": [15500, 7500],
            "opponent-infantry-1": [23800, 7500],
        },
    )
    red = next(item for item in match.robots if item.id == "tarsgo-infantry-1")
    blue = next(item for item in match.robots if item.id == "opponent-infantry-1")
    blue_outpost = next(
        item for item in match.map.zones if item.id == "blue-outpost-point"
    )
    blue_highland = next(
        item for item in match.map.zones if item.id == "blue-central-highland-point"
    )
    assert match.order_move(red.id, (16650, 7500))
    # The opponent has no manual command surface in this match; dispatch its
    # destination through the same engine path planner used by the AI.
    assert match._set_robot_destination(blue, (25200, 7500))
    for _ in range(180):
        if blue_highland.contains(red.position) and blue_outpost.contains(blue.position):
            break
        match.update(1 / 60)
    assert blue_highland.contains(red.position)
    assert blue_outpost.contains(blue.position)

    state = _territory(match, "blue-outpost")
    assert set(state.active_team_ids) == {RED, BLUE}
    progress = state.progress_seconds
    _tick(match, 2)
    assert _territory(match, "blue-outpost").progress_seconds == pytest.approx(
        progress, abs=0.04
    )


def test_seeded_replay_cli_records_and_verifies_unsettled_2027_timebox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace_path = tmp_path / "rmuc-2027-p1-trace.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "replay",
            "--record",
            str(trace_path),
            "--scenario",
            str(SCENARIO),
            "--seed",
            "2027",
            "--dt",
            "1",
            "--max-ticks",
            "500",
        ],
    )
    replay_cli()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["settings"]["seed"] == 2027
    assert trace["winner"] is None
    assert trace["elapsed_time"] == 420
    assert trace["result_status"] == "unsettled-timebox"

    monkeypatch.setattr(sys, "argv", ["replay", "--verify", str(trace_path)])
    replay_cli()
