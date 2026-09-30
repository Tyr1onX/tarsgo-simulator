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


def _outside_supply(match: Match, robot: Robot) -> tuple[float, float]:
    other_team = BLUE if robot.team == RED else RED
    return _center(match.ruleset._supply_buff_zone_by_team[other_team])


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-infantry-1", "tarsgo-sentry"],
)
def test_remote_healing_is_available_to_hero_infantry_and_sentry(
    robot_id: str,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    robot.hp = 1
    economy = match.ruleset._economy_by_team[robot.team]
    coins_before = economy.coins

    assert match.ruleset.purchase_remote_healing(match, robot)

    assert economy.coins == coins_before - 50
    assert (
        match.ruleset._robot_lifecycle_by_robot[
            robot.id
        ].pending_remote_healing_effective_at
        == pytest.approx(6.0)
    )


def test_engineer_cannot_purchase_remote_healing() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    economy = match.ruleset._economy_by_team[engineer.team]
    coins_before = economy.coins

    assert not match.ruleset.purchase_remote_healing(match, engineer)

    assert economy.coins == coins_before


def test_remote_healing_price_matches_table_5_8_roundup_formula() -> None:
    match = _match()

    match.elapsed_time = 0.0
    assert match.ruleset.remote_healing_cost(match) == 50

    match.elapsed_time = 6.0
    assert match.ruleset.remote_healing_cost(match) == 52

    match.elapsed_time = 60.0
    assert match.ruleset.remote_healing_cost(match) == 70

    match.elapsed_time = 60.001
    assert match.ruleset.remote_healing_cost(match) == 71

    match.elapsed_time = 180.0
    assert match.ruleset.remote_healing_cost(match) == 110


def test_remote_healing_insufficient_coins_is_atomic() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    economy = match.ruleset._economy_by_team[hero.team]
    match.elapsed_time = 60.0
    economy.coins = 69

    assert not match.ruleset.purchase_remote_healing(match, hero)

    assert economy.coins == 69
    assert lifecycle.pending_remote_healing_effective_at is None


def test_remote_healing_requires_out_of_combat_at_purchase() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    economy = match.ruleset._economy_by_team[hero.team]
    lifecycle.disengaged_elapsed = 5.999
    coins_before = economy.coins

    assert not match.ruleset.purchase_remote_healing(match, hero)
    assert economy.coins == coins_before
    assert lifecycle.pending_remote_healing_effective_at is None

    lifecycle.disengaged_elapsed = 6.0
    assert match.ruleset.purchase_remote_healing(match, hero)


def test_remote_healing_rejects_dead_robot_without_charge() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    economy = match.ruleset._economy_by_team[hero.team]
    hp = hero.hp
    assert match.apply_damage(hero, hp, bypass_invincibility=True) == hp
    coins_before = economy.coins

    assert not match.ruleset.purchase_remote_healing(match, hero)

    assert economy.coins == coins_before


def test_weakened_robot_is_not_additionally_blocked_once_out_of_combat() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    lifecycle.weak = True
    lifecycle.invincible_remaining = 0.0
    lifecycle.minimum_invincible_remaining = 0.0
    lifecycle.disengaged_elapsed = 6.0
    hero.hp = 20

    assert match.ruleset.purchase_remote_healing(match, hero)

    match.update(6.0)

    assert hero.hp == 110


def test_remote_healing_delivers_once_after_six_seconds_using_current_max_hp() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    hero.hp = 1
    assert match.ruleset.purchase_remote_healing(match, hero)

    match.update(5.9)
    assert hero.hp == 1
    assert lifecycle.pending_remote_healing_effective_at == pytest.approx(6.0)

    match.ruleset._grant_experience(hero.id, 550)
    assert hero.max_hp == 165
    assert hero.hp == 16

    match.update(0.1)

    assert hero.hp == 115
    assert lifecycle.pending_remote_healing_effective_at is None


def test_remote_healing_one_shot_rounding_uses_half_up_hp_settlement() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.max_hp = 8
    hero.hp = 1

    assert match.ruleset.purchase_remote_healing(match, hero)
    match.update(6.0)

    assert hero.hp == 6


def test_full_hp_robot_may_purchase_but_delivery_stays_capped_at_max_hp() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    economy = match.ruleset._economy_by_team[hero.team]
    coins_before = economy.coins
    assert hero.hp == hero.max_hp

    assert match.ruleset.purchase_remote_healing(match, hero)
    assert economy.coins == coins_before - 50

    match.update(6.0)

    assert hero.hp == hero.max_hp


def test_second_remote_healing_request_is_rejected_while_one_is_pending() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    economy = match.ruleset._economy_by_team[hero.team]
    hero.hp = 1

    assert match.ruleset.purchase_remote_healing(match, hero)
    coins_after_first = economy.coins
    first_effective_at = lifecycle.pending_remote_healing_effective_at

    assert not match.ruleset.purchase_remote_healing(match, hero)

    assert economy.coins == coins_after_first
    assert lifecycle.pending_remote_healing_effective_at == first_effective_at

    match.update(6.0)
    assert lifecycle.pending_remote_healing_effective_at is None
    assert match.ruleset.purchase_remote_healing(match, hero)


def test_large_dt_settles_remote_healing_once_at_frame_end() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _outside_supply(match, hero)
    hero.hp = 10

    assert match.ruleset.purchase_remote_healing(match, hero)
    match.update(10.0)

    assert hero.hp == 100
    assert (
        match.ruleset._robot_lifecycle_by_robot[
            hero.id
        ].pending_remote_healing_effective_at
        is None
    )

    match.update(10.0)
    assert hero.hp == 100


def test_post_purchase_combat_does_not_cancel_remote_healing() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _outside_supply(match, hero)
    hero.hp = 100

    assert match.ruleset.purchase_remote_healing(match, hero)
    assert match.apply_damage(hero, 20, source_team_id=BLUE) == 20

    match.update(6.0)

    assert hero.hp == 150


def test_death_before_delivery_cancels_remote_healing_without_refund() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    economy = match.ruleset._economy_by_team[hero.team]
    hero.hp = 50

    assert match.ruleset.purchase_remote_healing(match, hero)
    coins_after_purchase = economy.coins

    assert match.apply_damage(
        hero,
        hero.hp,
        bypass_invincibility=True,
    ) == 50
    match.update(0)

    assert not hero.alive
    assert economy.coins == coins_after_purchase
    assert lifecycle.pending_remote_healing_effective_at is None

    required = lifecycle.respawn_required
    assert required is not None
    match.update(float(required))

    assert hero.alive
    assert hero.hp < hero.max_hp


def test_remote_healing_and_local_resupply_healing_both_settle() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[sentry.id]
    sentry.position = _outside_supply(match, sentry)
    sentry.hp = 100

    assert match.ruleset.purchase_remote_healing(match, sentry)
    match.update(5.9)
    assert sentry.hp == 100

    sentry.position = _center(match.ruleset._supply_buff_zone_by_team[sentry.team])
    match.update(0.1)

    assert sentry.hp == 344
    assert lifecycle.pending_remote_healing_effective_at is None
    assert lifecycle.healing_rounding_residual == pytest.approx(0.0)


def test_match_reset_clears_pending_remote_healing_and_restores_wallet() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    economy = match.ruleset._economy_by_team[hero.team]

    assert match.ruleset.purchase_remote_healing(match, hero)
    assert economy.coins == 350
    assert (
        match.ruleset._robot_lifecycle_by_robot[
            hero.id
        ].pending_remote_healing_effective_at
        is not None
    )

    match.reset()

    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    economy = match.ruleset._economy_by_team[hero.team]
    assert lifecycle.pending_remote_healing_effective_at is None
    assert economy.coins == 400


def test_remote_projectile_exchange_still_uses_its_independent_pending_delivery() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    economy = match.ruleset._economy_by_team[hero.team]
    economy.coins = 1000
    lifecycle.disengaged_elapsed = 6.0

    assert match.ruleset.remote_exchange_projectiles(match, hero)
    assert len(allowance.pending_remote_deliveries) == 1
    assert lifecycle.pending_remote_healing_effective_at is None
