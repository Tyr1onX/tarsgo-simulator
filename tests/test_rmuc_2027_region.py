from collections import Counter
from fractions import Fraction
import json
import math
from pathlib import Path
import shutil
import sys

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_match_config
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.projectiles import Projectile
from tarsgo_simulator.core.replay import cli as replay_cli
from tarsgo_simulator.core.structure import StructureProjectileHitContext
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


def _structure(match: Match, structure_id: str):
    return next(item for item in match.structures if item.id == structure_id)


def _remote_blue_spawns() -> dict[str, list[int]]:
    return {
        "opponent-heavy": [15000, 1300],
        "opponent-infantry-1": [15600, 1300],
        "opponent-infantry-2": [15000, 1900],
        "opponent-sentry": [15600, 1900],
    }


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
    assert {
        (structure.id, structure.type, structure.team, structure.hp, structure.max_hp)
        for structure in match.structures
    } == {
        ("red-base", "base", RED, 10_000, 10_000),
        ("blue-base", "base", BLUE, 10_000, 10_000),
        ("red-outpost", "outpost", RED, 1_000, 1_000),
        ("blue-outpost", "outpost", BLUE, 1_000, 1_000),
    }

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


def test_reset_enables_movement_and_structure_only_combat() -> None:
    match = _match(seed=2027)
    initial_positions = {robot.id: robot.position for robot in match.robots}
    heavy = next(robot for robot in match.robots if robot.id == "tarsgo-heavy")
    sentry = next(robot for robot in match.robots if robot.id == "tarsgo-sentry")
    enemy_base = next(item for item in match.structures if item.id == "blue-base")

    match.update(0.25)
    assert match.elapsed_time == pytest.approx(0.25)
    assert match.ruleset.can_move(heavy)
    assert not match.ruleset.can_attack(heavy)
    assert match.ruleset.can_attack(sentry)
    assert not match.ruleset.can_target(heavy)
    assert match.ruleset.can_target(enemy_base)
    assert match.ruleset.resolve_damage(heavy, 50, BLUE) == 0
    assert match.ruleset.resolve_damage(enemy_base, 50, RED) == 0
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
    assert match.ruleset._remaining_sentry_ammo[sentry.id] == 300

    # P2c settles the official tie-break chain at the timer boundary.
    match.elapsed_time = match.time_limit
    result = match.ruleset.evaluate_result(match)
    assert result is not None and result.winner is None


def test_rmuc_2027_is_additive_and_has_an_explicit_rules_lab_ui_label() -> None:
    assert RULESETS["rmuc-2027-region-v1.0.0"] is RMUC2027RegionRules
    assert "rmuc-2026-region-v1.4.0" in RULESETS
    assert "rmul-2026-3v3" in RULESETS
    assert "training-v0" in RULESETS

    match = _match()
    assert _window_caption(match) == "TARS-Go RMUC 2027 Rules Lab (P2c: Settlement)"
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
    zone = next(item for item in match.map.zones if item.id == "blue-fortress-point")
    assert match.order_move(robot.id, (23000, 12000))
    for _ in range(180):
        if zone.contains(robot.position):
            break
        match.update(1 / 60)
    assert zone.contains(robot.position)
    _tick(match, 6)

    territory = _territory(match, "blue-base")
    assert territory.status == "temporary"
    assert territory.owner == RED


def test_both_temporary_territories_generate_control_degrees_in_live_match(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={
            **_remote_blue_spawns(),
            "tarsgo-infantry-1": [25200, 7500],
            "tarsgo-infantry-2": [26500, 13800],
        },
    )

    assert _territory(match, "blue-outpost").owner == BLUE
    assert _territory(match, "blue-base").owner == BLUE
    assert dict(match.ruleset.display_state.victory_points) == {RED: 0, BLUE: 0}
    _tick(match, 6)

    assert _territory(match, "blue-outpost").status == "temporary"
    assert _territory(match, "blue-base").status == "temporary"
    assert _territory(match, "blue-outpost").owner == RED
    assert _territory(match, "blue-base").owner == RED
    # Temporary control qualifies under §5.6.2; red earns (1 + 3) degrees/s.
    red_degrees = match.ruleset._control_degrees_by_team[RED]
    assert Fraction(7, 2) <= red_degrees <= Fraction(4, 1)
    assert dict(match.ruleset.display_state.victory_points)[RED] == 3

    match.reset()
    assert match.ruleset._control_degrees_by_team == {
        RED: Fraction(0),
        BLUE: Fraction(0),
    }


def _prepare_timeout_tick(match: Match) -> None:
    match.elapsed_time = match.time_limit - 1 / 60
    match.ruleset._last_update_time = match.elapsed_time
    match.update(1 / 60)
    assert match.finished
    assert match.elapsed_time == match.time_limit


def test_timeout_settlement_prefers_control_degrees_over_damage_and_hp() -> None:
    match = _match(seed=2027)
    match.ruleset._control_degrees_by_team[RED] = Fraction(11, 2)
    match.ruleset._control_degrees_by_team[BLUE] = Fraction(5, 1)
    match.ruleset._attack_damage_by_team.update({RED: 0, BLUE: 10_000})
    _prepare_timeout_tick(match)

    assert match.winner == RED


def test_timeout_settlement_uses_actual_attack_damage_when_control_ties() -> None:
    match = _match(seed=2027)
    blue_outpost = _structure(match, "blue-outpost")
    red_sentry = next(robot for robot in match.robots if robot.id == "tarsgo-sentry")
    assert match.apply_damage(blue_outpost, 37, source_robot=red_sentry) == 37
    _prepare_timeout_tick(match)

    assert dict(match.ruleset.display_state.attack_damage) == {RED: 37, BLUE: 0}
    assert match.winner == RED


def test_timeout_settlement_uses_team_robot_hp_after_control_and_damage_tie() -> None:
    match = _match(seed=2027)
    blue_robot = next(robot for robot in match.robots if robot.id == "opponent-heavy")
    blue_robot.hp = 0
    blue_robot.alive = False
    _prepare_timeout_tick(match)

    assert match.winner == RED


def test_timeout_settlement_returns_draw_when_all_three_priorities_tie() -> None:
    match = _match(seed=2027)
    _prepare_timeout_tick(match)

    assert match.finished
    assert match.winner is None


def test_base_destruction_by_match_projectile_settles_immediately(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={
            **_remote_blue_spawns(),
            "tarsgo-infantry-1": [25200, 7500],
            "tarsgo-sentry": [19000, 12374],
        },
    )
    base = _structure(match, "blue-base")
    base.hp = 20  # Keep the test short; the Match damage path remains real.
    observed_impacts = []

    for _ in range(2400):
        match.update(1 / 60)
        observed_impacts.extend(match.projectile_impacts)
        if match.finished:
            break

    assert match.finished
    assert match.winner == RED
    assert base.hp == 0 and not base.alive
    assert any(
        impact.shooter_id == "tarsgo-sentry"
        and impact.target_id == "blue-base"
        and impact.applied_damage == 20
        for impact in observed_impacts
    )


def test_outpost_and_base_projectiles_resolve_in_order_within_one_match_tick() -> None:
    match = _match(seed=2027)
    sentry = next(robot for robot in match.robots if robot.id == "tarsgo-sentry")
    outpost = _structure(match, "blue-outpost")
    base = _structure(match, "blue-base")
    outpost.hp = 20
    base.hp = 20
    speed = 13_000.0
    radius = 8.4

    # The first shot sweeps through the third projected Outpost armor panel.
    panel_angle = 5 * math.pi / 6
    outpost_start = (
        outpost.position[0] + math.cos(panel_angle) * 430.0,
        outpost.position[1] + math.sin(panel_angle) * 430.0,
    )
    outpost_velocity = (
        -math.cos(panel_angle) * speed,
        -math.sin(panel_angle) * speed,
    )

    # The second shot sweeps inward through a real Base armor edge.
    vertices = base.footprint_vertices
    first, second = vertices[0], vertices[1]
    edge = (second[0] - first[0], second[1] - first[1])
    edge_length = math.hypot(*edge)
    tangent = (edge[0] / edge_length, edge[1] / edge_length)
    area_twice = sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(vertices, (*vertices[1:], vertices[0]))
    )
    outward = (
        (tangent[1], -tangent[0])
        if area_twice > 0
        else (-tangent[1], tangent[0])
    )
    base_edge_center = (
        base.position[0] + (first[0] + second[0]) / 2,
        base.position[1] + (first[1] + second[1]) / 2,
    )
    base_start = (
        base_edge_center[0] + outward[0] * 120.0,
        base_edge_center[1] + outward[1] * 120.0,
    )
    base_velocity = (-outward[0] * speed, -outward[1] * speed)

    for projectile_id, target, position, velocity in (
        (9001, outpost, outpost_start, outpost_velocity),
        (9002, base, base_start, base_velocity),
    ):
        match.projectile_system.projectiles.append(
            Projectile(
                id=projectile_id,
                shooter_id=sentry.id,
                shooter_team_id=sentry.team,
                caliber="17mm",
                damage=20,
                radius=radius,
                speed=speed,
                effective_range=1_000.0,
                position=position,
                previous_position=position,
                velocity=velocity,
                target_id=target.id,
            )
        )

    match.update(1 / 60)

    assert _territory(match, "blue-outpost").status == "temporary"
    assert outpost.hp == 0 and not outpost.alive
    assert base.hp == 0 and not base.alive
    assert match.finished and match.winner == RED
    assert [
        (impact.target_id, impact.applied_damage)
        for impact in match.projectile_impacts
        if impact.projectile_id in {9001, 9002}
    ] == [("blue-outpost", 20), ("blue-base", 20)]


def test_sentry_projectile_hits_outpost_through_match_tick_with_official_damage(
    tmp_path: Path,
) -> None:
    spawns = {
        **_remote_blue_spawns(),
        "tarsgo-sentry": [19000, 7500],
    }
    match = _zone_match(tmp_path, spawns=spawns)
    outpost = _structure(match, "blue-outpost")
    ammo_before = match.ruleset._remaining_sentry_ammo["tarsgo-sentry"]
    observed_impacts = []

    assert match.uses_physical_projectiles
    for _ in range(1800):
        match.update(1 / 60)
        observed_impacts.extend(match.projectile_impacts)
        if outpost.hp < outpost.max_hp:
            break

    assert outpost.hp == outpost.max_hp - 20
    assert match.ruleset._remaining_sentry_ammo["tarsgo-sentry"] < ammo_before
    assert any(
        impact.shooter_id == "tarsgo-sentry"
        and impact.target_id == "blue-outpost"
        and impact.caliber == "17mm"
        and impact.applied_damage == 20
        for impact in observed_impacts
    )


def test_2027_structure_hit_speed_threshold_is_rule_set_owned() -> None:
    match = _match(seed=2027)
    outpost = _structure(match, "blue-outpost")
    rules = match.ruleset
    at_threshold = StructureProjectileHitContext(
        module_id="outpost-armor-1",
        impact_position=outpost.position,
        caliber="17mm",
        effective_impact_speed=12_000,
        center_hit=False,
        normal=(1.0, 0.0),
    )
    above_threshold = StructureProjectileHitContext(
        module_id="outpost-armor-1",
        impact_position=outpost.position,
        caliber="17mm",
        effective_impact_speed=12_001,
        center_hit=False,
        normal=(1.0, 0.0),
    )

    assert rules.projectile_minimum_hit_speed_for("17mm", "structure") == 12_000
    assert rules.resolve_structure_projectile_hit(outpost, 20, at_threshold) == (0, 1.0)
    assert rules.resolve_structure_projectile_hit(outpost, 20, above_threshold) == (20, 1.0)


def test_destroying_outpost_stops_only_its_rotation_and_rotation_stops_at_three_minutes(
    tmp_path: Path,
) -> None:
    match = _zone_match(
        tmp_path,
        spawns={
            **_remote_blue_spawns(),
            "tarsgo-sentry": [19000, 7500],
        },
    )
    blue_outpost = _structure(match, "blue-outpost")
    rules = match.ruleset

    for _ in range(1800):
        match.update(1 / 60)
        if not blue_outpost.alive:
            break
    assert not blue_outpost.alive

    def panel_vertices(structure_id: str):
        structure = _structure(match, structure_id)
        profile = rules.structure_projectile_hitbox_profile(structure)
        assert profile is not None and profile.armor_panels
        return profile.armor_panels[0].vertices

    blue_at_destruction = panel_vertices("blue-outpost")
    red_at_destruction = panel_vertices("red-outpost")
    _tick(match, 1.0)
    assert panel_vertices("blue-outpost") == blue_at_destruction
    assert panel_vertices("red-outpost") != red_at_destruction

    rules.prepare_combat(match, max(0.0, 180.0 - match.elapsed_time))
    red_at_three_minutes = panel_vertices("red-outpost")
    rules.prepare_combat(match, max(0.0, 181.0 - match.elapsed_time))
    assert panel_vertices("red-outpost") == red_at_three_minutes


def test_destroying_fully_controlled_outpost_downgrades_territory_to_temporary(
    tmp_path: Path,
) -> None:
    spawns = {
        **_remote_blue_spawns(),
        "tarsgo-sentry": [19000, 7500],
    }
    match = _zone_match(tmp_path, spawns=spawns)
    outpost = _structure(match, "blue-outpost")

    for _ in range(1800):
        match.update(1 / 60)
        if not outpost.alive:
            break

    territory = _territory(match, "blue-outpost")
    assert not outpost.alive
    assert outpost.hp == 0
    assert territory.status == "temporary"
    assert territory.owner == BLUE


def test_temporary_outpost_owner_destroys_structure_to_flip_and_rebuild_at_500_hp(
    tmp_path: Path,
) -> None:
    spawns = {
        **_remote_blue_spawns(),
        "tarsgo-infantry-1": [25200, 7500],
        "tarsgo-sentry": [18000, 7500],
    }
    match = _zone_match(tmp_path, spawns=spawns)
    sentry = next(robot for robot in match.robots if robot.id == "tarsgo-sentry")
    outpost = _structure(match, "blue-outpost")

    _tick(match, 5.2)
    territory = _territory(match, "blue-outpost")
    assert territory.status == "temporary"
    assert territory.owner == RED
    assert outpost.team == BLUE and outpost.hp == 1000

    # Sentry is autonomous in this ruleset and has no player command surface;
    # move it through the engine's normal path planner, as the AI does.
    assert match._set_robot_destination(sentry, (19000, 7500))
    for _ in range(1500):
        match.update(1 / 60)
        if outpost.team == RED and outpost.alive and outpost.hp == 500:
            break

    territory = _territory(match, "blue-outpost")
    assert territory.status == "full"
    assert territory.owner == RED
    assert outpost.team == RED
    assert outpost.alive
    assert outpost.hp == 500
    assert outpost.max_hp == 1000


def test_base_full_outpost_control_blocks_sentry_damage_until_territory_is_temporary(
    tmp_path: Path,
) -> None:
    spawns = {
        **_remote_blue_spawns(),
        "tarsgo-sentry": [19000, 12374],
        "tarsgo-infantry-1": [25200, 7500],
    }
    match = _zone_match(tmp_path, spawns=spawns)
    base = _structure(match, "blue-base")

    _tick(match, 4.8)
    assert _territory(match, "blue-outpost").status == "full"
    assert base.hp == 10_000

    _tick(match, 0.4)
    assert _territory(match, "blue-outpost").status == "temporary"
    _tick(match, 1.0)
    assert base.hp < 10_000


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


def test_seeded_replay_cli_records_and_verifies_settled_2027_timebox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace_path = tmp_path / "rmuc-2027-p2c-trace.json"
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
    assert "result_status" not in trace

    monkeypatch.setattr(sys, "argv", ["replay", "--verify", str(trace_path)])
    replay_cli()
