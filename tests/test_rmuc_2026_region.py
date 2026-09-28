from pathlib import Path

import pytest

from tarsgo_simulator.core.config import load_match_config
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RMUC_RULES_LAB_PATH = (
    REPOSITORY_ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
)
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match() -> Match:
    match = Match(load_match_config(RMUC_RULES_LAB_PATH))
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _structure(match: Match, team_id: str, structure_type: str) -> Structure:
    return next(
        structure
        for structure in match.structures
        if structure.team == team_id and structure.type == structure_type
    )


def _opponent(team_id: str) -> str:
    return BLUE if team_id == RED else RED


def _destroy_outpost(match: Match, team_id: str) -> Structure:
    outpost = _structure(match, team_id, "outpost")
    assert match.apply_damage(
        outpost, outpost.hp, source_team_id=_opponent(team_id)
    ) == 1500
    match.update(0)
    return outpost


def _grant_rebuild_opportunity(match: Match, team_id: str, *, damage: int = 1000) -> None:
    if _structure(match, team_id, "outpost").alive:
        _destroy_outpost(match, team_id)
    base = _structure(match, team_id, "base")
    assert match.apply_damage(
        base, damage, source_team_id=_opponent(team_id)
    ) == damage
    match.update(0)


def _rebuild_zone_center(match: Match, team_id: str) -> tuple[float, float]:
    zone = match.ruleset._rebuild_zone_by_team[team_id]
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _prepare_rebuild(match: Match, robot_id: str) -> tuple[Robot, Structure]:
    robot = _robot(match, robot_id)
    _grant_rebuild_opportunity(match, robot.team)
    robot.position = _rebuild_zone_center(match, robot.team)
    return robot, _structure(match, robot.team, "outpost")


def test_rmuc_ruleset_identity_roster_and_structures() -> None:
    match = _match()
    metadata = match.config.rule_document.metadata

    assert isinstance(match.ruleset, RMUC2026RegionalRules)
    assert metadata.id == "rmuc-2026-region-v1.4.0"
    assert metadata.competition == "RMUC"
    assert metadata.season == 2026
    assert metadata.stage == "regional"
    assert metadata.official_version == "1.4.0"
    assert metadata.status == "official-partial"
    assert match.time_limit == 420
    assert len(match.robots) == 10
    assert len(match.structures) == 4

    for team_id in (RED, BLUE):
        types = sorted(robot.type for robot in match.robots if robot.team == team_id)
        assert types == ["engineer", "hero", "infantry", "infantry", "sentry"]
        base = _structure(match, team_id, "base")
        outpost = _structure(match, team_id, "outpost")
        assert (base.hp, base.max_hp) == (5000, 5000)
        assert (outpost.hp, outpost.max_hp) == (1500, 1500)


def test_engineer_is_mobile_no_launcher_profile_with_required_metadata() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    parameters = match.ruleset.robot_parameters("engineer")

    assert engineer.alive
    assert parameters.max_hp == 250
    assert parameters.damage == 0
    assert match.ruleset._projectile_by_type["engineer"] is None
    assert match.ruleset._chassis_power_limit_by_type["engineer"] == 120


def test_structure_damage_emits_structure_events_and_destroyed_once() -> None:
    match = _match()
    outpost = _structure(match, RED, "outpost")

    assert match.apply_damage(outpost, 100, source_team_id=BLUE) == 100
    assert match.apply_damage(outpost, 1400, source_team_id=BLUE) == 1400
    assert match.apply_damage(outpost, 100, source_team_id=BLUE) == 0

    assert [event.type for event in match.current_events].count(
        MatchEventType.STRUCTURE_DAMAGED
    ) == 2
    destroyed = [
        event
        for event in match.current_events
        if event.type == MatchEventType.STRUCTURE_DESTROYED
    ]
    assert len(destroyed) == 1
    assert destroyed[0].structure_id == outpost.id
    assert destroyed[0].robot_id is None
    assert not outpost.alive


def test_living_outpost_makes_base_invincible_and_untargetable() -> None:
    match = _match()
    base = _structure(match, RED, "base")

    assert not match.ruleset.can_receive_damage(base)
    assert not match.ruleset.can_target(base)
    assert match.apply_damage(base, 500, source_team_id=BLUE) == 0
    assert base.hp == 5000


def test_destroyed_outpost_makes_base_vulnerable() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")

    assert match.ruleset.can_receive_damage(base)
    assert match.ruleset.can_target(base)
    assert match.apply_damage(base, 100, source_team_id=BLUE) == 100
    assert base.hp == 4900


def test_base_damage_crossing_first_1000_threshold_grants_one_opportunity() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")

    assert match.apply_damage(base, 1001, source_team_id=BLUE) == 1001
    match.update(0)

    state = match.ruleset._team_states[RED]
    assert base.hp == 3999
    assert state.base_damage_lost == 1001
    assert state.outpost_rebuild_opportunities == 1


def test_large_base_damage_crosses_multiple_thresholds_once() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")

    assert match.apply_damage(base, 2500, source_team_id=BLUE) == 2500
    match.update(0)

    state = match.ruleset._team_states[RED]
    assert base.hp == 2500
    assert state.base_damage_lost == 2500
    assert state.outpost_rebuild_opportunities == 2

    assert match.apply_damage(base, 499, source_team_id=BLUE) == 499
    match.update(0)
    assert state.outpost_rebuild_opportunities == 2

    assert match.apply_damage(base, 1, source_team_id=BLUE) == 1
    match.update(0)
    assert state.outpost_rebuild_opportunities == 3


def test_engineer_rebuilds_outpost_after_five_continuous_seconds() -> None:
    match = _match()
    _, outpost = _prepare_rebuild(match, "tarsgo-engineer")

    match.update(4.9)
    assert not outpost.alive
    match.update(0.1)

    state = match.ruleset._team_states[RED]
    assert outpost.alive
    assert outpost.hp == 750
    assert state.outpost_rebuild_opportunities == 0
    assert state.rebuild_progress_by_robot == {}
    assert state.outpost_ever_destroyed


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-infantry-1", "tarsgo-sentry"],
)
def test_non_engineer_ground_robots_rebuild_after_ten_seconds(robot_id: str) -> None:
    match = _match()
    _, outpost = _prepare_rebuild(match, robot_id)

    match.update(9.9)
    assert not outpost.alive
    match.update(0.1)

    assert outpost.alive
    assert outpost.hp == 750


def test_rebuild_progress_is_not_shared_between_robots() -> None:
    match = _match()
    hero, outpost = _prepare_rebuild(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    zone_center = _rebuild_zone_center(match, RED)

    match.update(5)
    assert not outpost.alive
    hero.position = (100.0, 100.0)
    infantry.position = zone_center
    match.update(5)

    state = match.ruleset._team_states[RED]
    assert not outpost.alive
    assert "tarsgo-hero" not in state.rebuild_progress_by_robot
    assert state.rebuild_progress_by_robot["tarsgo-infantry-1"] == pytest.approx(5)


def test_leaving_rebuild_zone_clears_that_robots_progress() -> None:
    match = _match()
    engineer, outpost = _prepare_rebuild(match, "tarsgo-engineer")

    match.update(2)
    assert match.ruleset._team_states[RED].rebuild_progress_by_robot[
        engineer.id
    ] == pytest.approx(2)

    engineer.position = (100.0, 100.0)
    match.update(0.1)

    assert engineer.id not in match.ruleset._team_states[RED].rebuild_progress_by_robot
    assert not outpost.alive


def test_rebuild_cutoff_at_300_seconds_stops_and_clears_progress() -> None:
    match = _match()
    engineer, outpost = _prepare_rebuild(match, "tarsgo-engineer")
    match.elapsed_time = 299.0

    match.update(0.5)
    assert match.ruleset._team_states[RED].rebuild_progress_by_robot[
        engineer.id
    ] == pytest.approx(0.5)

    match.update(1.0)
    assert match.elapsed_time == pytest.approx(300.5)
    assert not outpost.alive
    assert match.ruleset._team_states[RED].rebuild_progress_by_robot == {}

    match.update(5)
    assert not outpost.alive
    assert match.ruleset._team_states[RED].rebuild_progress_by_robot == {}


def test_rebuild_restores_base_invincibility_and_preserves_history() -> None:
    match = _match()
    _, outpost = _prepare_rebuild(match, "tarsgo-engineer")
    base = _structure(match, RED, "base")

    assert match.ruleset.can_receive_damage(base)
    match.update(5)

    state = match.ruleset._team_states[RED]
    assert outpost.alive
    assert outpost.hp == 750
    assert state.outpost_ever_destroyed
    assert state.outpost_rebuild_opportunities == 0
    assert not match.ruleset.can_receive_damage(base)
    assert match.apply_damage(base, 100, source_team_id=BLUE) == 0


def test_base_at_or_below_2000_deploys_armor_state() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")

    assert match.apply_damage(base, 3000, source_team_id=BLUE) == 3000
    match.update(0)

    assert base.hp == 2000
    assert match.ruleset._team_states[RED].base_armor_deployed


def test_structure_damage_counts_actual_hp_loss_as_attack_damage() -> None:
    match = _match()
    outpost = _structure(match, RED, "outpost")
    outpost.hp = 10

    assert match.apply_damage(outpost, 200, source_team_id=BLUE) == 10
    match.update(0)

    assert match.ruleset.attack_damage_by_team[BLUE] == 10


def test_invincible_base_does_not_absorb_target_selection() -> None:
    match = _match()
    attacker = _robot(match, "tarsgo-hero")
    target_robot = _robot(match, "opponent-infantry-1")
    base = _structure(match, BLUE, "base")
    for robot in match.robots:
        if robot.team == BLUE and robot is not target_robot:
            robot.alive = False
            robot.hp = 0
            robot.path.clear()

    attacker.position = (2400.0, 750.0)
    attacker.attack_cooldown = 0.0
    target_robot.position = (2180.0, 750.0)
    assert abs(attacker.position[0] - base.position[0]) < abs(
        attacker.position[0] - target_robot.position[0]
    )

    match.update(0.01)

    assert base.hp == 5000
    assert target_robot.hp == 0
    assert not target_robot.alive


def test_timeout_is_seven_minutes_and_equal_match_draws() -> None:
    match = _match()
    match.elapsed_time = 419.0

    match.update(1.0)

    assert match.finished
    assert match.elapsed_time == pytest.approx(420)
    assert match.winner is None


def test_base_destroyed_finishes_match_immediately() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")

    assert match.apply_damage(base, base.hp, source_team_id=BLUE) == 5000
    match.update(0)

    assert match.finished
    assert not base.alive
    assert match.winner == BLUE


def test_result_prefers_higher_base_remaining_hp() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    _destroy_outpost(match, BLUE)
    red_base = _structure(match, RED, "base")
    blue_base = _structure(match, BLUE, "base")

    assert match.apply_damage(red_base, 100, source_team_id=BLUE) == 100
    assert match.apply_damage(blue_base, 200, source_team_id=RED) == 200
    match.update(0)
    match.elapsed_time = 420
    match.update(0)

    assert match.winner == RED


def test_result_uses_current_outpost_hp_when_neither_was_destroyed() -> None:
    match = _match()
    blue_outpost = _structure(match, BLUE, "outpost")

    assert match.apply_damage(blue_outpost, 100, source_team_id=RED) == 100
    match.update(0)
    match.elapsed_time = 420
    match.update(0)

    assert match.winner == RED


def test_result_prefers_side_whose_outpost_was_never_destroyed() -> None:
    match = _match()
    _destroy_outpost(match, RED)

    match.elapsed_time = 420
    match.update(0)

    assert match.winner == BLUE


def test_result_uses_attack_damage_after_structure_ties() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    _destroy_outpost(match, BLUE)
    red_robot = _robot(match, "tarsgo-infantry-1")

    assert match.apply_damage(red_robot, 20, source_team_id=BLUE) == 20
    match.update(0)
    assert match.ruleset.attack_damage_by_team[BLUE] == 1520
    assert match.ruleset.attack_damage_by_team[RED] == 1500

    match.elapsed_time = 420
    match.update(0)

    assert match.winner == BLUE


def test_result_uses_robot_hp_only_after_attack_damage_tie() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    _destroy_outpost(match, BLUE)
    red_robot = _robot(match, "tarsgo-infantry-1")
    red_robot.hp -= 1

    assert match.ruleset.attack_damage_by_team[RED] == 1500
    assert match.ruleset.attack_damage_by_team[BLUE] == 1500
    match.elapsed_time = 420
    match.update(0)

    assert match.winner == BLUE


def test_result_draws_when_all_tiebreaks_are_equal() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    _destroy_outpost(match, BLUE)

    match.elapsed_time = 420
    match.update(0)

    assert match.winner is None


def test_synthetic_field_uses_existing_2800_by_1500_world_boundary() -> None:
    match = _match()
    zone_ids = {zone.id for zone in match.map.zones}

    assert (match.map.width, match.map.height) == (2800, 1500)
    assert {"red-outpost-rebuild", "blue-outpost-rebuild"} <= zone_ids
