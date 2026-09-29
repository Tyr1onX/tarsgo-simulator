from pathlib import Path

import pytest

from tarsgo_simulator.core.config import load_match_config
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure


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


def _zone_center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _own_supply_center(match: Match, robot: Robot) -> tuple[float, float]:
    return _zone_center(match.ruleset._supply_buff_zone_by_team[robot.team])


def _outside_own_supply(match: Match, robot: Robot) -> tuple[float, float]:
    other_team = BLUE if robot.team == RED else RED
    return _zone_center(match.ruleset._supply_buff_zone_by_team[other_team])


def _kill_and_register(match: Match, robot: Robot) -> None:
    hp = robot.hp
    assert match.apply_damage(
        robot,
        hp,
        bypass_invincibility=True,
    ) == hp
    assert not robot.alive
    match.update(0)
    assert match.ruleset._robot_lifecycle_by_robot[robot.id].respawn_required is not None


def _complete_normal_respawn(match: Match, robot: Robot) -> None:
    robot.position = _outside_own_supply(match, robot)
    _kill_and_register(match, robot)
    required = match.ruleset._robot_lifecycle_by_robot[robot.id].respawn_required
    assert required is not None
    match.update(float(required))
    assert robot.alive


def test_lifecycle_state_is_private_per_ground_robot_and_starts_disengaged() -> None:
    match = _match()
    states = match.ruleset._robot_lifecycle_by_robot

    assert set(states) == {robot.id for robot in match.robots}
    assert "tarsgo-engineer" in states
    assert "tarsgo-engineer" not in match.ruleset._projectile_allowance_by_robot
    for state in states.values():
        assert state.disengaged_elapsed == pytest.approx(6.0)
        assert not state.combat_activity_this_frame
        assert state.respawn_progress == 0
        assert state.respawn_required is None
        assert state.immediate_respawn_count == 0
        assert not state.weak
        assert state.invincible_remaining == 0
        assert state.minimum_invincible_remaining == 0
        assert state.healing_rounding_residual == 0


def test_resupply_heals_ten_percent_max_hp_per_second_for_all_ground_robots() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _own_supply_center(match, engineer)
    engineer.hp = 100

    match.update(1.0)

    assert engineer.hp == 125

    engineer.position = _outside_own_supply(match, engineer)
    match.update(1.0)
    assert engineer.hp == 125


def test_enhanced_resupply_healing_splits_large_frame_at_both_240s_and_disengage_boundaries() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    hero.position = _own_supply_center(match, hero)
    hero.hp = 50
    match.elapsed_time = 239.0
    lifecycle.disengaged_elapsed = 5.0

    match.update(2.0)

    # First second: 10%; second second: 25%. 150 * 0.35 = 52.5 -> half-up 53.
    assert hero.hp == 103
    assert lifecycle.healing_rounding_residual == pytest.approx(-0.5)
    assert lifecycle.disengaged_elapsed == pytest.approx(7.0)


def test_combat_activity_keeps_late_resupply_healing_at_base_rate_and_restarts_disengage() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    hero.position = _own_supply_center(match, hero)
    hero.hp = 50
    match.elapsed_time = 300.0
    lifecycle.disengaged_elapsed = 6.0
    allowance.allowed = 1

    match.ruleset.on_attack_committed(hero)
    match.update(1.0)

    assert hero.hp == 65
    assert lifecycle.disengaged_elapsed == 0


def test_resupply_half_up_rounding_is_stable_across_small_frames() -> None:
    one_frame = _match()
    split_frames = _match()
    one_hero = _robot(one_frame, "tarsgo-hero")
    split_hero = _robot(split_frames, "tarsgo-hero")

    for match, hero in ((one_frame, one_hero), (split_frames, split_hero)):
        hero.position = _own_supply_center(match, hero)
        hero.hp = 50

    one_frame.update(1.0)
    for _ in range(10):
        split_frames.update(0.1)

    assert one_hero.hp == 65
    assert split_hero.hp == 65
    assert (
        split_frames.ruleset._robot_lifecycle_by_robot[
            split_hero.id
        ].healing_rounding_residual
        == pytest.approx(0.0)
    )


@pytest.mark.parametrize(
    ("elapsed", "immediate_count", "expected"),
    [
        (0.0, 0, 10),
        (5.0, 0, 11),
        (300.0, 2, 80),
    ],
)
def test_death_freezes_official_respawn_progress_requirement(
    elapsed: float,
    immediate_count: int,
    expected: int,
) -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    hero.position = _outside_own_supply(match, hero)
    match.elapsed_time = elapsed
    lifecycle.immediate_respawn_count = immediate_count

    _kill_and_register(match, hero)

    assert lifecycle.respawn_required == expected
    assert lifecycle.respawn_progress == 0


def test_normal_respawn_starts_next_frame_and_preserves_progression_ammo_and_permanent_heat_lock() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _outside_own_supply(match, hero)
    progression = match.ruleset._progression_by_robot[hero.id]
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    heat = match.ruleset._shooting_heat_by_robot[hero.id]
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    allowance.allowed = 7
    heat.permanently_locked = True

    _kill_and_register(match, hero)
    assert lifecycle.respawn_required == 10

    # Progression changes while dead must update the max HP used at respawn.
    match.ruleset._grant_experience(hero.id, 550)
    assert progression.level == 2
    assert hero.max_hp == 165
    assert hero.hp == 0

    match.update(9.999)
    assert not hero.alive
    assert lifecycle.respawn_progress == pytest.approx(9.999)

    match.update(0.001)

    assert hero.alive
    assert progression.level == 2
    assert progression.experience == 550
    assert hero.max_hp == 165
    assert hero.hp == 17
    assert allowance.allowed == 7
    assert heat.permanently_locked
    assert heat.heat == 0
    assert lifecycle.weak
    assert lifecycle.invincible_remaining == pytest.approx(30.0)
    assert lifecycle.minimum_invincible_remaining == pytest.approx(10.0)
    assert lifecycle.disengaged_elapsed == 0


def test_automatic_respawn_rounding_keeps_exact_integer_result() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _outside_own_supply(match, engineer)

    _kill_and_register(match, engineer)
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    required = lifecycle.respawn_required
    assert required is not None

    match.update(float(required))

    assert engineer.alive
    assert engineer.max_hp == 250
    assert engineer.hp == 25


def test_automatic_respawn_rounding_never_creates_zero_hp_alive_robot() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _outside_own_supply(match, engineer)
    engineer.max_hp = 1
    engineer.hp = 1

    _kill_and_register(match, engineer)
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    required = lifecycle.respawn_required
    assert required is not None

    match.update(float(required))

    assert engineer.alive
    assert engineer.max_hp == 1
    assert engineer.hp == 1


def test_respawn_progress_accelerates_in_supply_or_when_base_is_below_2000_hp() -> None:
    supply_match = _match()
    supply_hero = _robot(supply_match, "tarsgo-hero")
    supply_hero.position = _own_supply_center(supply_match, supply_hero)
    _kill_and_register(supply_match, supply_hero)

    supply_match.update(2.499)
    assert not supply_hero.alive
    assert (
        supply_match.ruleset._robot_lifecycle_by_robot[supply_hero.id].respawn_progress
        == pytest.approx(9.996)
    )
    supply_match.update(0.001)
    assert supply_hero.alive

    base_match = _match()
    base_hero = _robot(base_match, "tarsgo-hero")
    base_hero.position = _outside_own_supply(base_match, base_hero)
    _structure(base_match, RED, "base").hp = 2000
    _kill_and_register(base_match, base_hero)

    base_match.update(1.0)
    lifecycle = base_match.ruleset._robot_lifecycle_by_robot[base_hero.id]
    assert lifecycle.respawn_progress == pytest.approx(1.0)

    _structure(base_match, RED, "base").hp = 1999
    base_match.update(1.0)
    assert lifecycle.respawn_progress == pytest.approx(5.0)


def test_respawn_inside_supply_releases_weak_in_same_lifecycle_settlement() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    hero.position = _own_supply_center(match, hero)

    _kill_and_register(match, hero)
    required = lifecycle.respawn_required
    assert required is not None

    match.update(required / 4.0)

    assert hero.alive
    assert not lifecycle.weak
    assert lifecycle.invincible_remaining == pytest.approx(10.0)
    assert lifecycle.minimum_invincible_remaining == pytest.approx(10.0)
    assert lifecycle.disengaged_elapsed == 0


def test_automatic_respawn_invincibility_blocks_hp_loss() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _complete_normal_respawn(match, hero)
    before = hero.hp

    assert match.apply_damage(hero, 20, source_team_id=BLUE) == 0
    assert hero.hp == before


def test_weak_release_caps_invincibility_at_ten_seconds_total() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _complete_normal_respawn(match, hero)
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]

    hero.position = _own_supply_center(match, hero)
    match.update(2.0)

    assert not lifecycle.weak
    assert lifecycle.invincible_remaining == pytest.approx(8.0)
    assert match.apply_damage(hero, 20, source_team_id=BLUE) == 0

    match.update(8.0)
    assert lifecycle.invincible_remaining == 0
    assert match.apply_damage(hero, 20, source_team_id=BLUE) == 20


def test_weak_release_after_ten_seconds_ends_remaining_30s_invincibility_immediately() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _complete_normal_respawn(match, hero)
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]

    match.update(11.0)
    assert lifecycle.weak
    assert lifecycle.invincible_remaining == pytest.approx(19.0)
    assert lifecycle.minimum_invincible_remaining == 0

    hero.position = _zone_center(match.ruleset._field_base_zone_by_team[hero.team])
    match.update(0)

    assert not lifecycle.weak
    assert lifecycle.invincible_remaining == 0


def test_weak_robot_cannot_attack_occupy_central_buff_or_rebuild_outpost() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    lifecycle.weak = True
    allowance.allowed = 10

    assert not match.ruleset.can_attack(hero)

    central = match.ruleset._field_central_zones[0]
    hero.position = _zone_center(central)
    match.ruleset._advance_field_defense_occupancy(match, 0)
    assert (
        match.ruleset._field_occupy_remaining.get((hero.id, central.id), 0.0)
        == 0
    )

    outpost = _structure(match, hero.team, "outpost")
    outpost.alive = False
    outpost.hp = 0
    team_state = match.ruleset._team_states[hero.team]
    team_state.outpost_rebuild_opportunities = 1
    hero.position = _zone_center(match.ruleset._rebuild_zone_by_team[hero.team])
    match.ruleset._advance_rebuild(match, 10.0)

    assert not outpost.alive
    assert team_state.rebuild_progress_by_robot == {}


def test_reset_clears_rmuc_lifecycle_state() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    lifecycle.disengaged_elapsed = 0.0
    lifecycle.combat_activity_this_frame = True
    lifecycle.respawn_progress = 8.0
    lifecycle.respawn_required = 40
    lifecycle.immediate_respawn_count = 3
    lifecycle.weak = True
    lifecycle.invincible_remaining = 12.0
    lifecycle.minimum_invincible_remaining = 2.0
    lifecycle.healing_rounding_residual = -0.25

    match.reset()

    reset = match.ruleset._robot_lifecycle_by_robot[hero.id]
    assert reset.disengaged_elapsed == pytest.approx(6.0)
    assert not reset.combat_activity_this_frame
    assert reset.respawn_progress == 0
    assert reset.respawn_required is None
    assert reset.immediate_respawn_count == 0
    assert not reset.weak
    assert reset.invincible_remaining == 0
    assert reset.minimum_invincible_remaining == 0
    assert reset.healing_rounding_residual == 0
