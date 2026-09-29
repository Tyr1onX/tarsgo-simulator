from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_rule_document
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)
RULES = (
    REPOSITORY_ROOT
    / "configs"
    / "rules"
    / "rmuc-2026-region-v1.4.0.yaml"
)
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


def _destroy_outpost(match: Match, team_id: str = RED) -> None:
    outpost = match.ruleset._outpost_by_team[team_id]
    attacker = BLUE if team_id == RED else RED
    hp_before = outpost.hp
    assert (
        match.apply_damage(
            outpost,
            100000,
            source_team_id=attacker,
        )
        == hp_before
    )
    match.update(0)
    assert match.ruleset._team_states[team_id].outpost_ever_destroyed


def _occupy(match: Match, robot: Robot) -> None:
    robot.position = _center(
        match.ruleset._fortress_zone_by_team[robot.team]
    )
    match.update(0)
    assert (
        match.ruleset._fortress_state_by_team[
            robot.team
        ].owner_robot_id
        == robot.id
    )


def _leave(match: Match, robot: Robot, dt: float = 0.0) -> None:
    robot.position = (620.0, 260.0)
    match.update(dt)


def _reserve_state(match: Match, robot: Robot):
    return match.ruleset._fortress_reserved_by_robot[robot.id]


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("base_hp", "expected"),
    [
        (5000, 100),
        (4985, 102),
        (2000, 500),
        (1000, 500),
    ],
)
def test_fortress_reserve_limit_formula_and_cap(
    base_hp: int,
    expected: int,
) -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    match.ruleset._base_by_team[RED].hp = base_hp

    assert match.ruleset._fortress_reserve_limit(infantry) == expected


def test_first_legal_occupation_initializes_current_reserve_limit() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    match.ruleset._base_by_team[RED].hp = 4985

    _occupy(match, infantry)

    state = _reserve_state(match, infantry)
    assert state.initialized
    assert state.last_limit == 102
    assert state.reserved == 102


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-infantry-1", "tarsgo-sentry"],
)
def test_only_fortress_17mm_eligible_types_have_reserve_state(
    robot_id: str,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)

    assert robot.id in match.ruleset._fortress_reserved_by_robot


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-engineer"],
)
def test_non_fortress_types_have_no_reserve_state(robot_id: str) -> None:
    match = _match()
    robot = _robot(match, robot_id)

    assert robot.id not in match.ruleset._fortress_reserved_by_robot


def test_committed_shot_consumes_reserve_before_own_allowance() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    allowance = match.ruleset._projectile_allowance_by_robot[infantry.id]
    reserve = _reserve_state(match, infantry)
    allowance.allowed = 20

    match.ruleset.on_attack_committed(infantry)

    assert reserve.reserved == 99
    assert allowance.allowed == 20


def test_zero_reserve_falls_back_to_own_allowance() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    allowance = match.ruleset._projectile_allowance_by_robot[infantry.id]
    reserve = _reserve_state(match, infantry)
    reserve.reserved = 0
    allowance.allowed = 3

    match.ruleset.on_attack_committed(infantry)

    assert reserve.reserved == 0
    assert allowance.allowed == 2


def test_active_reserve_allows_attack_with_zero_own_allowance() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    allowance = match.ruleset._projectile_allowance_by_robot[infantry.id]
    allowance.allowed = 0

    assert _reserve_state(match, infantry).reserved == 100
    assert match.ruleset.can_attack(infantry)


def test_no_legal_target_consumes_neither_reserve_nor_own_allowance() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    allowance = match.ruleset._projectile_allowance_by_robot[infantry.id]
    allowance.allowed = 7
    infantry.attack_cooldown = 0.0
    for robot in match.robots:
        if robot.team == BLUE:
            robot.position = (2700.0, 1400.0)

    reserve_before = _reserve_state(match, infantry).reserved
    heat_before = match.ruleset._shooting_heat_by_robot[infantry.id].heat
    xp_before = match.ruleset._progression_by_robot[infantry.id].experience

    match.update(0.01)

    assert _reserve_state(match, infantry).reserved == reserve_before
    assert allowance.allowed == 7
    assert match.ruleset._shooting_heat_by_robot[infantry.id].heat == heat_before
    assert match.ruleset._progression_by_robot[infantry.id].experience == xp_before


def test_leaving_fortress_keeps_reserve_but_disables_it_after_release() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    allowance = match.ruleset._projectile_allowance_by_robot[infantry.id]
    allowance.allowed = 0
    reserve_before = _reserve_state(match, infantry).reserved

    _leave(match, infantry, 2.0)

    assert _reserve_state(match, infantry).reserved == reserve_before
    assert match.ruleset._fortress_state_by_team[RED].owner_robot_id is None
    assert not match.ruleset.can_attack(infantry)


def test_two_second_release_keeps_reserve_usable() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset._projectile_allowance_by_robot[infantry.id].allowed = 0

    _leave(match, infantry, 1.9)

    assert (
        match.ruleset._fortress_state_by_team[RED].owner_robot_id
        == infantry.id
    )
    assert match.ruleset.can_attack(infantry)
    match.ruleset.on_attack_committed(infantry)
    assert _reserve_state(match, infantry).reserved == 99


def test_reentry_does_not_refill_consumed_reserve() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    reserve = _reserve_state(match, infantry)
    reserve.reserved = 73

    _leave(match, infantry, 2.0)
    _occupy(match, infantry)

    assert reserve.initialized
    assert reserve.last_limit == 100
    assert reserve.reserved == 73


def test_base_hp_loss_increases_limit_and_only_adds_capacity_delta() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    reserve = _reserve_state(match, infantry)
    reserve.reserved = 80

    match.ruleset._base_by_team[RED].hp = 4985
    match.update(0)

    assert reserve.last_limit == 102
    assert reserve.reserved == 82

    match.ruleset._base_by_team[RED].hp = 4955
    match.update(0)

    assert reserve.last_limit == 106
    assert reserve.reserved == 86


def test_capacity_growth_applies_while_robot_is_not_occupying() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    reserve = _reserve_state(match, infantry)
    reserve.reserved = 50
    _leave(match, infantry, 2.0)

    match.ruleset._base_by_team[RED].hp = 4985
    match.update(0)

    assert reserve.last_limit == 102
    assert reserve.reserved == 52
    assert not match.ruleset.can_attack(infantry)


def test_d4_base_heal_reduces_limit_and_clamps_reserve_immediately() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    base = match.ruleset._base_by_team[RED]
    base.hp = 3000
    _occupy(match, infantry)
    reserve = _reserve_state(match, infantry)
    assert reserve.last_limit == 366
    reserve.reserved = 350

    match.ruleset._apply_tech_core_first_rewards(RED, 4)

    assert base.hp == 5000
    assert base.max_hp == 5000
    assert reserve.last_limit == 100
    assert reserve.reserved == 100


def test_virtual_shield_does_not_affect_reserve_limit() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    base = match.ruleset._base_by_team[RED]
    base.hp = 5000
    match.ruleset._team_states[RED].base_virtual_shield = 2000

    assert match.ruleset._fortress_reserve_limit(infantry) == 100


def test_reserve_provisioning_does_not_spend_coins_or_purchase_cap() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    economy = match.ruleset._economy_by_team[RED]
    purchase = match.ruleset._projectile_purchase_by_team[RED]
    before = (
        economy.coins,
        purchase.purchased_17mm,
        purchase.purchased_42mm,
    )

    _occupy(match, infantry)

    after = (
        economy.coins,
        purchase.purchased_17mm,
        purchase.purchased_42mm,
    )
    assert after == before
    assert _reserve_state(match, infantry).reserved == 100


def test_death_preserves_reserve_but_immediately_stops_use() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset.on_attack_committed(infantry)
    reserve_before = _reserve_state(match, infantry).reserved
    hp_before = infantry.hp

    assert (
        match.apply_damage(
            infantry,
            100000,
            source_team_id=BLUE,
        )
        == hp_before
    )
    match.update(0)

    assert not infantry.alive
    assert match.ruleset._fortress_state_by_team[RED].owner_robot_id is None
    assert _reserve_state(match, infantry).reserved == reserve_before
    assert not match.ruleset.can_attack(infantry)


def test_reset_clears_all_fortress_reserve_state() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    assert _reserve_state(match, infantry).initialized

    match.reset()

    for state in match.ruleset._fortress_reserved_by_robot.values():
        assert not state.initialized
        assert state.reserved == 0
        assert state.last_limit == 0


def test_reserved_shot_still_settles_heat_xp_and_disengage_once() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    allowance = match.ruleset._projectile_allowance_by_robot[infantry.id]
    lifecycle = match.ruleset._robot_lifecycle_by_robot[infantry.id]
    heat = match.ruleset._shooting_heat_by_robot[infantry.id]
    progression = match.ruleset._progression_by_robot[infantry.id]
    allowance.allowed = 5
    reserve_before = _reserve_state(match, infantry).reserved

    match.ruleset.on_attack_committed(infantry)

    assert _reserve_state(match, infantry).reserved == reserve_before - 1
    assert allowance.allowed == 5
    assert lifecycle.disengaged_elapsed == 0
    assert lifecycle.combat_activity_this_frame
    assert heat.heat == 10
    assert progression.experience == 1


def test_display_keeps_own_allowance_and_fortress_reserve_separate() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset._projectile_allowance_by_robot[infantry.id].allowed = 20
    _reserve_state(match, infantry).reserved = 137

    display = match.ruleset.display_state
    projectiles = {
        robot_id: (projectile, allowed)
        for robot_id, projectile, allowed in display.robot_projectiles
    }
    reserves = dict(display.robot_projectile_reserves)

    assert projectiles[infantry.id] == ("17mm", 20)
    assert reserves[infantry.id] == 137


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["fortress_own_buff"]["reserved_projectiles"].__setitem__(
            "projectile",
            "42mm",
        ),
        lambda data: data["fortress_own_buff"]["reserved_projectiles"].__setitem__(
            "base",
            99,
        ),
        lambda data: data["fortress_own_buff"]["reserved_projectiles"].__setitem__(
            "hp_step",
            14,
        ),
        lambda data: data["fortress_own_buff"]["reserved_projectiles"].__setitem__(
            "per_step",
            3,
        ),
        lambda data: data["fortress_own_buff"]["reserved_projectiles"].__setitem__(
            "cap",
            499,
        ),
    ],
)
def test_fortress_reserve_config_rejects_non_v140_values(
    tmp_path: Path,
    mutate,
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))
