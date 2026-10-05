from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_match_config, load_rule_document
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RULES = REPOSITORY_ROOT / "configs" / "rules" / "rmuc-2026-region-v1.4.0.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match() -> Match:
    match = Match(load_match_config(SCENARIO))
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _zone_center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _place_in_local_zone(match: Match, robot: Robot, index: int = 0) -> None:
    zone = match.ruleset._projectile_exchange_zones_by_team[robot.team][index]
    robot.position = _zone_center(zone)


def _place_in_supply(match: Match, robot: Robot) -> None:
    robot.position = _zone_center(match.ruleset._supply_buff_zone_by_team[robot.team])


def _advance_to(match: Match, elapsed: float) -> None:
    assert elapsed + 1e-9 >= match.elapsed_time
    match.update(max(0.0, elapsed - match.elapsed_time))


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_initial_allowances_and_drone_metadata() -> None:
    match = _match()
    states = match.ruleset._projectile_allowance_by_robot

    assert (states["tarsgo-hero"].projectile_type, states["tarsgo-hero"].allowed) == (
        "42mm",
        0,
    )
    assert states["tarsgo-infantry-1"].allowed == 0
    assert states["tarsgo-infantry-2"].allowed == 0
    assert states["tarsgo-sentry"].allowed == 300
    assert match.ruleset._projectile_initial["drone"] == ("17mm", 750)
    assert states["tarsgo-drone"].allowed == 750
    assert states["opponent-drone"].allowed == 750
    assert "tarsgo-engineer" not in states


def test_initial_combat_gate_blocks_hero_and_infantry_but_allows_sentry() -> None:
    match = _match()

    assert not match.ruleset.can_attack(_robot(match, "tarsgo-hero"))
    assert not match.ruleset.can_attack(_robot(match, "tarsgo-infantry-1"))
    assert match.ruleset.can_attack(_robot(match, "tarsgo-sentry"))
    assert not match.ruleset.can_attack(_robot(match, "tarsgo-engineer"))


def test_committed_sentry_shot_consumes_one_round() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    state = match.ruleset._projectile_allowance_by_robot[sentry.id]
    lifecycle = match.ruleset._robot_lifecycle_by_robot[sentry.id]

    match.ruleset.on_attack_committed(sentry)

    assert state.allowed == 299
    assert lifecycle.disengaged_elapsed == 0


def test_no_legal_target_does_not_consume_allowance() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    sentry.attack_cooldown = 0.0
    sentry.position = (100.0, 100.0)
    for robot in match.robots:
        if robot.team == BLUE:
            robot.position = (2700.0, 1400.0)

    match.update(0.01)

    assert match.ruleset._projectile_allowance_by_robot[sentry.id].allowed == 300


def test_committed_structure_attack_consumes_allowance() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    outpost = next(
        structure
        for structure in match.structures
        if structure.team == BLUE and structure.type == "outpost"
    )
    for robot in match.robots:
        if robot.team == BLUE:
            robot.alive = False
            robot.hp = 0
            robot.path.clear()
    hero.position = (1750.0, 750.0)
    hero.attack_cooldown = 0.0
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 1

    match.update(0.01)

    assert outpost.hp == 1300
    assert match.ruleset._projectile_allowance_by_robot[hero.id].allowed == 0


@pytest.mark.parametrize("zone_index", [0, 1, 2])
def test_nonremote_infantry_exchange_works_in_each_own_eligible_zone(
    zone_index: int,
) -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _place_in_local_zone(match, infantry, zone_index)

    assert match.ruleset.exchange_projectiles(match, infantry)

    assert match.ruleset._economy_by_team[RED].coins == 390
    assert match.ruleset._projectile_allowance_by_robot[infantry.id].allowed == 10
    assert match.ruleset._projectile_purchase_by_team[RED].purchased_17mm == 10


def test_nonremote_hero_exchange_spends_ten_for_one_42mm_round() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _place_in_local_zone(match, hero)

    assert match.ruleset.exchange_projectiles(match, hero)

    assert match.ruleset._economy_by_team[RED].coins == 390
    assert match.ruleset._projectile_allowance_by_robot[hero.id].allowed == 1
    assert match.ruleset._projectile_purchase_by_team[RED].purchased_42mm == 1


def test_nonremote_exchange_rejects_enemy_zone_without_mutation() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    infantry.position = _zone_center(
        match.ruleset._projectile_exchange_zones_by_team[BLUE][0]
    )
    before = (
        match.ruleset._economy_by_team[RED].coins,
        match.ruleset._projectile_allowance_by_robot[infantry.id].allowed,
        match.ruleset._projectile_purchase_by_team[RED].purchased_17mm,
    )

    assert not match.ruleset.exchange_projectiles(match, infantry)

    after = (
        match.ruleset._economy_by_team[RED].coins,
        match.ruleset._projectile_allowance_by_robot[infantry.id].allowed,
        match.ruleset._projectile_purchase_by_team[RED].purchased_17mm,
    )
    assert after == before


def test_nonremote_exchange_rejects_outside_all_local_zones() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    infantry.position = (1400.0, 750.0)

    assert not match.ruleset.exchange_projectiles(match, infantry)


def test_engineer_cannot_exchange_projectiles() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _place_in_local_zone(match, engineer)

    assert not match.ruleset.exchange_projectiles(match, engineer)
    assert not match.ruleset.remote_exchange_projectiles(match, engineer)


def test_insufficient_coins_is_atomic_failure() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _place_in_local_zone(match, infantry)
    match.ruleset._economy_by_team[RED].coins = 9

    assert not match.ruleset.exchange_projectiles(match, infantry)

    assert match.ruleset._economy_by_team[RED].coins == 9
    assert match.ruleset._projectile_allowance_by_robot[infantry.id].allowed == 0
    assert match.ruleset._projectile_purchase_by_team[RED].purchased_17mm == 0


def test_17mm_team_cap_is_shared_and_has_no_partial_purchase() -> None:
    match = _match()
    first = _robot(match, "tarsgo-infantry-1")
    second = _robot(match, "tarsgo-infantry-2")
    _place_in_local_zone(match, first)
    _place_in_local_zone(match, second)
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    economy = match.ruleset._economy_by_team[RED]
    purchase.purchased_17mm = 990
    economy.coins = 1000

    assert match.ruleset.exchange_projectiles(match, first)
    assert purchase.purchased_17mm == 1000
    before = (economy.coins, match.ruleset._projectile_allowance_by_robot[second.id].allowed)
    assert not match.ruleset.exchange_projectiles(match, second)
    assert purchase.purchased_17mm == 1000
    assert (economy.coins, match.ruleset._projectile_allowance_by_robot[second.id].allowed) == before


def test_17mm_local_purchase_at_995_does_not_shrink_to_five_rounds() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _place_in_local_zone(match, infantry)
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    purchase.purchased_17mm = 995

    assert not match.ruleset.exchange_projectiles(match, infantry)
    assert purchase.purchased_17mm == 995
    assert match.ruleset._projectile_allowance_by_robot[infantry.id].allowed == 0


def test_42mm_team_cap_can_reach_100_but_not_101() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _place_in_local_zone(match, hero)
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    match.ruleset._economy_by_team[RED].coins = 1000
    purchase.purchased_42mm = 99

    assert match.ruleset.exchange_projectiles(match, hero)
    assert purchase.purchased_42mm == 100
    assert not match.ruleset.exchange_projectiles(match, hero)
    assert purchase.purchased_42mm == 100


def test_remote_hero_exchange_is_allowed_at_match_start_and_delayed() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = match.ruleset._projectile_allowance_by_robot[hero.id]
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]

    assert lifecycle.disengaged_elapsed == pytest.approx(6.0)
    assert match.ruleset.remote_exchange_projectiles(match, hero)

    assert match.ruleset._economy_by_team[RED].coins == 250
    assert match.ruleset._projectile_purchase_by_team[RED].purchased_42mm == 10
    assert state.allowed == 0
    assert [(d.amount, d.effective_at) for d in state.pending_remote_deliveries] == [
        (10, pytest.approx(6.0))
    ]

    match.update(5.999)
    assert state.allowed == 0
    match.update(0.001)
    assert state.allowed == 10
    assert state.pending_remote_deliveries == []


def test_remote_infantry_exchange_costs_150_for_100_after_six_seconds() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    state = match.ruleset._projectile_allowance_by_robot[infantry.id]

    assert match.ruleset.remote_exchange_projectiles(match, infantry)
    assert match.ruleset._economy_by_team[RED].coins == 250
    assert match.ruleset._projectile_purchase_by_team[RED].purchased_17mm == 100
    assert state.allowed == 0

    match.update(6.0)
    assert state.allowed == 100


def test_remote_action_does_not_fallback_to_local_price_inside_local_zone() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _place_in_local_zone(match, infantry)

    assert match.ruleset.remote_exchange_projectiles(match, infantry)

    assert match.ruleset._economy_by_team[RED].coins == 250
    assert match.ruleset._projectile_allowance_by_robot[infantry.id].allowed == 0


def test_committed_shot_resets_disengage_and_remote_requires_six_new_seconds() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = match.ruleset._projectile_allowance_by_robot[hero.id]
    lifecycle = match.ruleset._robot_lifecycle_by_robot[hero.id]
    state.allowed = 2

    match.ruleset.on_attack_committed(hero)
    assert state.allowed == 1
    assert lifecycle.disengaged_elapsed == 0
    assert not match.ruleset.remote_exchange_projectiles(match, hero)

    # Flush the frame containing the committed shot; the continuous six-second
    # disengage window starts after that combat-activity frame has settled.
    match.update(0)
    match.update(5.999)
    assert not match.ruleset.remote_exchange_projectiles(match, hero)
    match.update(0.001)
    assert match.ruleset.remote_exchange_projectiles(match, hero)


def test_damage_resets_disengage_and_repeated_activity_restarts_timer() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    attacker = _robot(match, "opponent-sentry")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[infantry.id]

    lifecycle.disengaged_elapsed = 0
    match.update(5.0)
    assert lifecycle.disengaged_elapsed == pytest.approx(5.0)

    assert match.apply_damage(infantry, 20, source_robot=attacker) == 20
    match.update(0)
    assert lifecycle.disengaged_elapsed == 0
    match.update(1.0)

    assert lifecycle.disengaged_elapsed == pytest.approx(1.0)
    assert not match.ruleset.remote_exchange_projectiles(match, infantry)


def test_pending_remote_delivery_is_not_cancelled_by_later_damage() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    attacker = _robot(match, "opponent-sentry")
    state = match.ruleset._projectile_allowance_by_robot[hero.id]

    assert match.ruleset.remote_exchange_projectiles(match, hero)
    match.update(1.0)
    assert match.apply_damage(hero, 20, source_robot=attacker) == 20
    match.update(0)
    match.update(5.0)

    assert state.allowed == 10
    assert state.pending_remote_deliveries == []


def test_pending_remote_delivery_still_settles_if_robot_dies() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    attacker = _robot(match, "opponent-sentry")
    state = match.ruleset._projectile_allowance_by_robot[hero.id]

    assert match.ruleset.remote_exchange_projectiles(match, hero)
    match.update(1.0)
    assert match.apply_damage(hero, hero.hp, source_robot=attacker) == 150
    match.update(0)
    assert not hero.alive

    match.update(5.0)

    assert state.allowed == 10


def test_pending_remote_purchase_counts_toward_team_cap_immediately() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    purchase.purchased_17mm = 900

    assert match.ruleset.remote_exchange_projectiles(match, infantry)
    assert purchase.purchased_17mm == 1000
    assert not match.ruleset.remote_exchange_projectiles(match, infantry)
    assert purchase.purchased_17mm == 1000


def test_local_and_remote_purchases_share_same_17mm_cap() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    match.ruleset._economy_by_team[RED].coins = 1000
    purchase.purchased_17mm = 890

    _place_in_local_zone(match, infantry)
    assert match.ruleset.exchange_projectiles(match, infantry)
    assert purchase.purchased_17mm == 900
    assert match.ruleset.remote_exchange_projectiles(match, infantry)
    assert purchase.purchased_17mm == 1000
    assert not match.ruleset.exchange_projectiles(match, infantry)


def test_sentry_initial_and_supply_allowance_do_not_count_purchase_cap() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    state = match.ruleset._projectile_allowance_by_robot[sentry.id]

    assert state.allowed == 300
    assert purchase.purchased_17mm == 0

    _place_in_supply(match, sentry)
    match.update(60.0)

    assert state.allowed == 400
    assert purchase.pending_sentry_supply == 0
    assert purchase.purchased_17mm == 0


def test_sentry_minute_supply_accumulates_while_not_occupying_supply() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    state = match.ruleset._projectile_allowance_by_robot[sentry.id]

    match.update(180.0)

    assert purchase.pending_sentry_supply == 300
    assert state.allowed == 300


def test_sentry_entering_supply_claims_all_accumulated_allowance() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    state = match.ruleset._projectile_allowance_by_robot[sentry.id]

    match.update(180.0)
    _place_in_supply(match, sentry)
    match.update(0)

    assert state.allowed == 600
    assert purchase.pending_sentry_supply == 0


def test_official_sentry_600_round_accumulation_example_at_elapsed_390() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    state = match.ruleset._projectile_allowance_by_robot[sentry.id]

    _advance_to(match, 390.0)
    assert purchase.pending_sentry_supply == 600
    _place_in_supply(match, sentry)
    match.update(0)

    assert state.allowed == 900
    assert purchase.pending_sentry_supply == 0


def test_sentry_remaining_in_supply_claims_each_minute_immediately() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    state = match.ruleset._projectile_allowance_by_robot[sentry.id]
    _place_in_supply(match, sentry)

    match.update(60.0)
    assert state.allowed == 400
    match.update(60.0)
    assert state.allowed == 500


def test_large_dt_sentry_supply_accrues_all_crossed_minute_boundaries() -> None:
    match = _match()
    purchase = match.ruleset._projectile_purchase_by_team[RED]

    match.update(50.0)
    match.update(140.0)

    assert match.elapsed_time == pytest.approx(190.0)
    assert purchase.pending_sentry_supply == 300


def test_enemy_supply_does_not_claim_sentry_pending_allowance() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    match.update(60.0)
    sentry.position = _zone_center(match.ruleset._supply_buff_zone_by_team[BLUE])

    match.update(0)

    assert purchase.pending_sentry_supply == 100
    assert match.ruleset._projectile_allowance_by_robot[sentry.id].allowed == 300


def test_display_state_reuses_robot_projectiles_for_rmuc_allowance() -> None:
    match = _match()
    projectiles = {
        robot_id: (projectile, allowed)
        for robot_id, projectile, allowed in match.ruleset.display_state.robot_projectiles
    }

    assert projectiles["tarsgo-hero"] == ("42mm", 0)
    assert projectiles["tarsgo-infantry-1"] == ("17mm", 0)
    assert projectiles["tarsgo-infantry-2"] == ("17mm", 0)
    assert projectiles["tarsgo-sentry"] == ("17mm", 300)
    assert "tarsgo-engineer" not in projectiles


def test_allowance_purchase_spends_the_existing_rmuc_wallet() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _place_in_local_zone(match, infantry)

    assert dict(match.ruleset.display_state.coins)[RED] == 400
    assert match.ruleset.exchange_projectiles(match, infantry)
    assert dict(match.ruleset.display_state.coins)[RED] == 390


def test_match_end_blocks_purchase_delivery_and_new_sentry_grant() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    sentry = _robot(match, "tarsgo-sentry")
    _advance_to(match, 414.0)
    assert match.ruleset.remote_exchange_projectiles(match, hero)
    before_sentry = match.ruleset._projectile_allowance_by_robot[sentry.id].allowed

    match.update(6.0)

    assert match.finished
    assert match.ruleset._projectile_allowance_by_robot[hero.id].allowed == 0
    assert match.ruleset._projectile_allowance_by_robot[sentry.id].allowed == before_sentry
    assert match.ruleset._next_sentry_supply_grant == pytest.approx(420.0)

    _place_in_local_zone(match, hero)
    assert not match.ruleset.exchange_projectiles(match, hero)
    assert not match.ruleset.remote_exchange_projectiles(match, hero)


def test_reset_restores_allowance_purchase_pending_supply_and_disengaged_defaults() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    sentry = _robot(match, "tarsgo-sentry")

    _place_in_local_zone(match, infantry)
    assert match.ruleset.exchange_projectiles(match, infantry)
    assert match.ruleset.remote_exchange_projectiles(match, hero)
    match.ruleset.on_attack_committed(infantry)
    match.update(60.0)

    match.reset()

    states = match.ruleset._projectile_allowance_by_robot
    assert states["tarsgo-hero"].allowed == 0
    assert states["tarsgo-infantry-1"].allowed == 0
    assert states["tarsgo-infantry-2"].allowed == 0
    assert states["tarsgo-sentry"].allowed == 300
    assert all(state.pending_remote_deliveries == [] for state in states.values())
    assert all(
        state.disengaged_elapsed == pytest.approx(6.0)
        for state in match.ruleset._robot_lifecycle_by_robot.values()
    )
    for purchase in match.ruleset._projectile_purchase_by_team.values():
        assert purchase.purchased_17mm == 0
        assert purchase.purchased_42mm == 0
        assert purchase.pending_sentry_supply == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["robot_lifecycle"].__setitem__("disengaged_after", 0),
        lambda data: data["projectile_allowance"]["initial"]["hero"].__setitem__(
            "projectile", "17mm"
        ),
        lambda data: data["projectile_allowance"]["initial"]["sentry"].__setitem__(
            "allowance", -1
        ),
        lambda data: data["projectile_allowance"]["purchase"]["17mm"].__setitem__(
            "team_cap", 0
        ),
        lambda data: data["projectile_allowance"]["purchase"]["42mm"]["remote"].__setitem__(
            "coins", 0
        ),
        lambda data: data["projectile_allowance"]["sentry_supply"].__setitem__(
            "interval", 0
        ),
    ],
)
def test_projectile_allowance_config_rejects_invalid_values(
    tmp_path: Path,
    mutate,
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))