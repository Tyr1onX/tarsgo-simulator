from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot


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
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _outside_field_invincibility(match: Match, robot: Robot) -> tuple[float, float]:
    other_team = BLUE if robot.team == RED else RED
    return _center(match.ruleset._assembly_zone_by_team[other_team])


def _sync(match: Match, dt: float = 0.0) -> None:
    match.update(dt)


def _damage(match: Match, robot: Robot, amount: int = 20) -> int:
    source_team = BLUE if robot.team == RED else RED
    return match.apply_damage(robot, amount, source_team_id=source_team)


def test_engineer_inside_own_assembly_is_invincible() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])

    _sync(match)

    before = engineer.hp
    assert _damage(match, engineer) == 0
    assert engineer.hp == before


def test_non_engineer_does_not_gain_assembly_invincibility() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._assembly_zone_by_team[RED])

    _sync(match)

    before = hero.hp
    assert _damage(match, hero) == 20
    assert hero.hp == before - 20


def test_enemy_assembly_does_not_grant_engineer_invincibility() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _center(match.ruleset._assembly_zone_by_team[BLUE])

    _sync(match)

    assert _damage(match, engineer) == 20


def test_weakened_engineer_cannot_gain_or_accumulate_assembly_invincibility() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    lifecycle.weak = True
    lifecycle.invincible_remaining = 0.0
    lifecycle.minimum_invincible_remaining = 0.0
    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])

    _sync(match, 1.0)

    assert lifecycle.weak
    assert match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id] == 0
    assert _damage(match, engineer) == 20


def test_assembly_release_delay_consumes_budget_then_expires() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    assembly = match.ruleset._assembly_zone_by_team[RED]
    engineer.position = _center(assembly)
    _sync(match)

    engineer.position = _outside_field_invincibility(match, engineer)
    _sync(match, 1.9)

    key = (engineer.id, assembly.id)
    assert match.ruleset._field_occupy_remaining[key] == pytest.approx(0.1)
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(1.9)
    )
    assert _damage(match, engineer) == 0

    _sync(match, 0.1)

    assert match.ruleset._field_occupy_remaining[key] == 0
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(2.0)
    )
    assert _damage(match, engineer) == 20


def test_assembly_accumulated_time_persists_across_leave_and_reenter() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    assembly = match.ruleset._assembly_zone_by_team[RED]
    engineer.position = _center(assembly)

    _sync(match, 60.0)
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(60.0)
    )

    engineer.position = _outside_field_invincibility(match, engineer)
    _sync(match, 2.0)
    _sync(match, 10.0)
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(62.0)
    )

    engineer.position = _center(assembly)
    _sync(match, 58.0)

    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(120.0)
    )
    assert _damage(match, engineer) == 0


def test_assembly_invincibility_exhausts_at_180_seconds_with_large_dt_cap() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])

    _sync(match, 179.5)
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(179.5)
    )
    assert _damage(match, engineer) == 0

    _sync(match, 2.0)

    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(180.0)
    )
    assert _damage(match, engineer) == 20


def test_death_stops_assembly_accumulation_but_preserves_consumed_budget_through_respawn() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])
    _sync(match, 60.0)

    assert match.apply_damage(
        engineer,
        engineer.hp,
        bypass_invincibility=True,
    ) == engineer.max_hp
    _sync(match)

    assert not engineer.alive
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(60.0)
    )

    engineer.position = _outside_field_invincibility(match, engineer)
    _sync(match, 5.0)
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(60.0)
    )

    required = lifecycle.respawn_required
    assert required is not None
    _sync(match, float(required) - 5.0)
    assert engineer.alive
    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(60.0)
    )

    engineer.position = _center(match.ruleset._field_base_zone_by_team[RED])
    _sync(match)
    assert not lifecycle.weak
    lifecycle.invincible_remaining = 0.0
    lifecycle.minimum_invincible_remaining = 0.0

    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])
    _sync(match)
    assert _damage(match, engineer) == 0


def test_match_reset_restores_full_assembly_invincibility_budget() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])
    _sync(match, 75.0)

    assert (
        match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id]
        == pytest.approx(75.0)
    )

    match.reset()

    assert match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id] == 0


def test_engineer_in_own_resupply_is_invincible_without_out_of_combat_requirement() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    lifecycle.disengaged_elapsed = 0.0
    engineer.position = _center(match.ruleset._supply_buff_zone_by_team[RED])

    _sync(match)

    assert _damage(match, engineer) == 0


def test_non_engineer_in_resupply_does_not_gain_engineer_invincibility() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._supply_buff_zone_by_team[RED])

    _sync(match)

    assert _damage(match, hero) == 20


def test_enemy_resupply_does_not_grant_engineer_invincibility() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _center(match.ruleset._supply_buff_zone_by_team[BLUE])

    _sync(match)

    assert _damage(match, engineer) == 20


def test_weakened_engineer_does_not_use_stale_resupply_field_invincibility() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    supply = match.ruleset._supply_buff_zone_by_team[RED]
    engineer.position = _center(supply)
    _sync(match)

    key = (engineer.id, supply.id)
    assert match.ruleset._field_occupy_remaining[key] > 0

    lifecycle.weak = True
    lifecycle.invincible_remaining = 0.0
    lifecycle.minimum_invincible_remaining = 0.0

    assert _damage(match, engineer) == 20


def test_resupply_invincibility_uses_two_second_occupy_release_delay() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    supply = match.ruleset._supply_buff_zone_by_team[RED]
    engineer.position = _center(supply)
    _sync(match)

    engineer.position = _outside_field_invincibility(match, engineer)
    _sync(match, 1.9)
    assert _damage(match, engineer) == 0

    _sync(match, 0.1)
    assert _damage(match, engineer) == 20


def test_resupply_invincibility_has_no_assembly_180_second_budget() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id] = 180.0
    engineer.position = _center(match.ruleset._supply_buff_zone_by_team[RED])

    _sync(match)

    assert _damage(match, engineer) == 0


def test_lifecycle_invincibility_remains_active_after_assembly_budget_is_exhausted() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    match.ruleset._assembly_invincibility_elapsed_by_engineer[engineer.id] = 180.0
    lifecycle.invincible_remaining = 5.0
    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])

    _sync(match)

    assert _damage(match, engineer) == 0


def test_assembly_invincibility_remains_active_after_lifecycle_invincibility_expires() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[engineer.id]
    lifecycle.invincible_remaining = 0.0
    lifecycle.minimum_invincible_remaining = 0.0
    engineer.position = _center(match.ruleset._assembly_zone_by_team[RED])

    _sync(match)

    assert _damage(match, engineer) == 0
