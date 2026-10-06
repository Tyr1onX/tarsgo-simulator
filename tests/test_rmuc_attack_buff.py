from pathlib import Path

import pytest

from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure
from rmuc_test_support import move_ground_robots_to_unbuffed_region


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match() -> Match:
    match = Match.from_scenario(SCENARIO)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    move_ground_robots_to_unbuffed_region(match)
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _structure(match: Match, team_id: str, structure_type: str) -> Structure:
    return next(
        structure
        for structure in match.structures
        if structure.team == team_id and structure.type == structure_type
    )


def _center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _destroy_outpost(match: Match, team_id: str) -> None:
    outpost = _structure(match, team_id, "outpost")
    attacker = BLUE if team_id == RED else RED
    before = outpost.hp
    assert match.apply_damage(outpost, 100000, source_team_id=attacker) == before
    match.update(0)
    assert not outpost.alive


def _activate_enemy_fortress_vulnerability(
    match: Match,
    target: Robot,
    fortress_team_id: str,
) -> None:
    _destroy_outpost(match, fortress_team_id)
    match.elapsed_time = 180.0
    target.position = _center(match.ruleset._fortress_zone_by_team[fortress_team_id])
    match.update(0)
    assert match.ruleset._effective_vulnerability(target) == pytest.approx(1.0)


def test_no_attack_buff_keeps_raw_enemy_damage() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    before = target.hp

    assert match.apply_damage(target, 20, source_team_id=BLUE) == 20
    assert target.hp == before - 20
    assert match.ruleset._effective_attack_multiplier(BLUE) == 1.0


@pytest.mark.parametrize(
    ("attacker_id", "raw_damage", "expected"),
    [
        ("opponent-infantry-1", 20, 40),
        ("opponent-hero", 200, 400),
    ],
)
def test_attack_buff_applies_equally_to_17mm_and_42mm_projectile_damage(
    attacker_id: str,
    raw_damage: int,
    expected: int,
) -> None:
    match = _match()
    attacker = _robot(match, attacker_id)
    target = _robot(match, "tarsgo-sentry")
    assert match.ruleset.grant_attack_buff(BLUE, 2.0, 30.0)

    assert (
        match.apply_damage(
            target,
            raw_damage,
            source_robot=attacker,
        )
        == expected
    )


def test_attack_buff_does_not_change_projectile_eligibility() -> None:
    match = _match()
    assert match.ruleset.grant_attack_buff(RED, 2.0, 30.0)

    for robot_id in ("tarsgo-hero", "tarsgo-infantry-1", "tarsgo-sentry"):
        robot = _robot(match, robot_id)
        match.ruleset._projectile_allowance_by_robot[robot.id].allowed = 1
        assert match.ruleset.can_attack(robot)

    engineer = _robot(match, "tarsgo-engineer")
    assert engineer.id not in match.ruleset._projectile_allowance_by_robot
    assert not match.ruleset.can_attack(engineer)


def test_field_buff_point_occupancy_never_grants_attack_buff_or_uses_release_delay() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._field_base_zone_by_team[RED])

    match.update(0)
    assert match.ruleset._current_field_defense(hero) == pytest.approx(0.50)
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0

    hero.position = (600.0, 300.0)
    match.update(1.9)
    assert match.ruleset._current_field_defense(hero) == pytest.approx(0.50)
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0

    match.update(0.1)
    assert match.ruleset._current_field_defense(hero) == 0
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0


def test_enemy_field_buff_point_does_not_grant_attack_buff() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._field_base_zone_by_team[BLUE])

    match.update(0)

    assert match.ruleset._effective_attack_multiplier(RED) == 1.0


def test_weakened_robot_cannot_use_active_team_attack_buff_through_legal_combat() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 1
    assert match.ruleset.grant_attack_buff(RED, 2.0, 30.0)

    lifecycle.weak = True

    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(2.0)
    assert not match.ruleset.can_attack(hero)


def test_attack_buff_duration_expires_and_can_be_regranted() -> None:
    match = _match()
    assert match.ruleset.grant_attack_buff(RED, 1.5, 5.0)

    match.update(4.9)
    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(1.5)

    match.update(0.1)
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0

    assert match.ruleset.grant_attack_buff(RED, 2.0, 10.0)
    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(2.0)


def test_multiple_attack_buff_sources_take_max_and_keep_independent_durations() -> None:
    match = _match()
    assert match.ruleset.grant_attack_buff(RED, 1.5, 30.0)
    assert match.ruleset.grant_attack_buff(RED, 2.0, 10.0)

    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(2.0)

    match.update(10.0)

    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(1.5)
    assert len(match.ruleset._attack_buffs_by_team[RED]) == 1
    assert match.ruleset._attack_buffs_by_team[RED][0].remaining == pytest.approx(20.0)


def test_team_attack_buff_survives_robot_death_and_respawn_while_window_remains() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    hero.position = _center(match.ruleset._supply_buff_zone_by_team[RED])
    assert match.ruleset.grant_attack_buff(RED, 1.5, 30.0)

    hp = hero.hp
    assert match.apply_damage(hero, hp, source_team_id=BLUE) == hp
    match.update(0)

    assert not hero.alive
    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(1.5)

    required = lifecycle.respawn_required
    assert required is not None
    match.update(float(required))

    assert hero.alive
    assert not lifecycle.weak
    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(1.5)
    assert match.ruleset._attack_buffs_by_team[RED][0].remaining == pytest.approx(20.0)


@pytest.mark.parametrize("target_kind", ["robot", "outpost", "base"])
def test_team_attack_buff_applies_to_projectile_damage_against_all_supported_targets(
    target_kind: str,
) -> None:
    match = _match()
    assert match.ruleset.grant_attack_buff(BLUE, 1.5, 30.0)

    if target_kind == "robot":
        target = _robot(match, "tarsgo-sentry")
        raw = 20
        expected = 30
    elif target_kind == "outpost":
        target = _structure(match, RED, "outpost")
        raw = 200
        expected = 300
    else:
        _destroy_outpost(match, RED)
        target = _structure(match, RED, "base")
        raw = 200
        expected = 300

    assert match.apply_damage(target, raw, source_team_id=BLUE) == expected


def test_attack_and_defense_follow_manual_multiplication_order() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    match.ruleset._team_states[RED].tech_core_defense = 0.25
    assert match.ruleset.grant_attack_buff(BLUE, 2.0, 30.0)

    assert match.apply_damage(target, 20, source_team_id=BLUE) == 30


def test_attack_and_vulnerability_follow_manual_multiplication_order() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress_vulnerability(match, target, BLUE)
    assert match.ruleset.grant_attack_buff(BLUE, 2.0, 30.0)

    assert match.apply_damage(target, 20, source_team_id=BLUE) == 80


def test_attack_defense_and_vulnerability_follow_manual_example_order() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress_vulnerability(match, target, BLUE)
    match.ruleset._team_states[RED].tech_core_defense = 0.25
    assert match.ruleset.grant_attack_buff(BLUE, 2.0, 30.0)

    assert match.apply_damage(target, 20, source_team_id=BLUE) == 70


def test_attack_buff_rounds_only_after_full_modifier_expression_half_up() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    assert match.ruleset.grant_attack_buff(BLUE, 1.5, 30.0)

    assert match.apply_damage(target, 1, source_team_id=BLUE) == 2


def test_attack_buff_resolves_before_base_virtual_shield() -> None:
    match = _match()
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")
    state = match.ruleset._team_states[RED]
    state.tech_core_defense = 0.50
    state.base_virtual_shield = 50
    assert match.ruleset.grant_attack_buff(BLUE, 2.0, 30.0)

    assert match.apply_damage(base, 100, source_team_id=BLUE) == 50

    assert state.base_virtual_shield == 0
    assert base.hp == base.max_hp - 50


def test_attack_buff_events_scoreboard_and_experience_use_final_actual_hp_loss() -> None:
    match = _match()
    attacker = _robot(match, "opponent-hero")
    target = _robot(match, "tarsgo-infantry-1")
    match.ruleset._team_states[RED].tech_core_defense = 0.50
    assert match.ruleset.grant_attack_buff(BLUE, 2.0, 30.0)

    xp_before = match.ruleset._progression_by_robot[attacker.id].experience
    assert match.apply_damage(target, 20, source_robot=attacker) == 20

    event = match.current_events[-1]
    assert event.type == MatchEventType.ROBOT_DAMAGED
    assert event.damage == 20

    match.update(0)

    assert match.ruleset.attack_damage_by_team[BLUE] == 20
    assert match.ruleset._progression_by_robot[attacker.id].experience == xp_before + 80


def test_large_dt_expires_attack_buff_before_that_frames_single_combat_pass() -> None:
    match = _match()
    assert match.ruleset.grant_attack_buff(BLUE, 2.0, 5.0)

    match.update(10.0)

    assert match.ruleset._effective_attack_multiplier(BLUE) == 1.0
    target = _robot(match, "tarsgo-infantry-1")
    assert match.apply_damage(target, 20, source_team_id=BLUE) == 20


def test_friendly_and_unknown_damage_do_not_consume_attack_buff() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    assert match.ruleset.grant_attack_buff(RED, 3.0, 30.0)

    before = target.hp
    assert match.apply_damage(target, 20, source_team_id=RED) == 20
    assert target.hp == before - 20

    before = target.hp
    assert match.apply_damage(target, 20) == 20
    assert target.hp == before - 20


def test_match_reset_clears_attack_buff_round_state() -> None:
    match = _match()
    assert match.ruleset.grant_attack_buff(RED, 3.0, 60.0)
    assert match.ruleset.grant_attack_buff(BLUE, 1.5, 30.0)

    match.reset()

    assert match.ruleset._attack_buffs_by_team == {RED: [], BLUE: []}
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0
    assert match.ruleset._effective_attack_multiplier(BLUE) == 1.0
