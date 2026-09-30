from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure


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


def _structure(match: Match, team_id: str, structure_type: str) -> Structure:
    return next(
        structure
        for structure in match.structures
        if structure.team == team_id and structure.type == structure_type
    )


def _center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _destroy_outpost(match: Match, team_id: str = RED) -> None:
    outpost = _structure(match, team_id, "outpost")
    attacker = BLUE if team_id == RED else RED
    before = outpost.hp
    assert match.apply_damage(outpost, 100000, source_team_id=attacker) == before
    match.update(0)
    assert not outpost.alive


@pytest.mark.parametrize(
    ("score", "attack", "defense", "cooling"),
    [
        (1.0, 1.5, 0.25, 1.0),
        (3.0, 1.5, 0.25, 1.0),
        (3.0001, 1.5, 0.25, 2.0),
        (7.0, 1.5, 0.25, 2.0),
        (7.0001, 2.0, 0.25, 2.0),
        (8.0, 2.0, 0.25, 2.0),
        (8.0001, 2.0, 0.25, 3.0),
        (9.0, 2.0, 0.25, 3.0),
        (9.0001, 3.0, 0.50, 5.0),
        (10.0, 3.0, 0.50, 5.0),
    ],
)
def test_large_energy_mechanism_average_ring_score_tiers(
    score: float,
    attack: float,
    defense: float,
    cooling: float,
) -> None:
    match = _match()

    assert match.ruleset.activate_large_energy_mechanism_buff(RED, score, 5)

    buff = match.ruleset._large_energy_mechanism_buffs_by_team[RED][0]
    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(attack)
    assert buff.defense == pytest.approx(defense)
    assert buff.cooling_multiplier == pytest.approx(cooling)


@pytest.mark.parametrize(
    ("lit_arm_count", "duration"),
    [(5, 30.0), (6, 35.0), (7, 40.0), (8, 45.0), (9, 50.0), (10, 60.0)],
)
def test_large_energy_mechanism_lit_arm_count_controls_duration(
    lit_arm_count: int,
    duration: float,
) -> None:
    match = _match()

    assert match.ruleset.activate_large_energy_mechanism_buff(
        RED, 9.5, lit_arm_count
    )

    energy = match.ruleset._large_energy_mechanism_buffs_by_team[RED][0]
    attack = match.ruleset._attack_buffs_by_team[RED][-1]
    assert energy.remaining == pytest.approx(duration)
    assert attack.remaining == pytest.approx(duration)


@pytest.mark.parametrize(
    ("score", "lit_arm_count"),
    [
        (0.999, 5),
        (10.001, 5),
        (float("nan"), 5),
        (float("inf"), 5),
        (5.0, 4),
        (5.0, 11),
        (5.0, True),
    ],
)
def test_invalid_large_energy_mechanism_result_is_atomic(
    score: float,
    lit_arm_count: int,
) -> None:
    match = _match()

    assert not match.ruleset.activate_large_energy_mechanism_buff(
        RED, score, lit_arm_count
    )

    assert match.ruleset._large_energy_mechanism_buffs_by_team[RED] == []
    assert match.ruleset._attack_buffs_by_team[RED] == []
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0


def test_unknown_team_cannot_receive_large_energy_mechanism_buff() -> None:
    match = _match()

    assert not match.ruleset.activate_large_energy_mechanism_buff(
        "unknown-team", 9.5, 10
    )

    assert all(
        buffs == []
        for buffs in match.ruleset._large_energy_mechanism_buffs_by_team.values()
    )


@pytest.mark.parametrize(
    "robot_id",
    [
        "tarsgo-hero",
        "tarsgo-engineer",
        "tarsgo-infantry-1",
        "tarsgo-sentry",
    ],
)
def test_large_energy_mechanism_defense_applies_to_all_current_ground_robots(
    robot_id: str,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 5.0, 5)

    assert match.ruleset._effective_defense(robot) == pytest.approx(0.25)


@pytest.mark.parametrize("structure_type", ["base", "outpost"])
def test_large_energy_mechanism_defense_applies_to_base_and_outpost(
    structure_type: str,
) -> None:
    match = _match()
    target = _structure(match, RED, structure_type)
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    assert match.ruleset._effective_defense(target) == pytest.approx(0.50)


def test_large_energy_mechanism_attack_reuses_existing_team_attack_consumer() -> None:
    match = _match()
    target = _robot(match, "opponent-sentry")
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 7.5, 5)

    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(2.0)
    assert match.apply_damage(target, 100, source_team_id=RED) == 200


def test_energy_attack_and_existing_attack_buff_use_same_class_max() -> None:
    match = _match()
    assert match.ruleset.grant_attack_buff(RED, 2.0, 60.0)
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 2.0, 5)

    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(2.0)

    match.reset()
    assert match.ruleset.grant_attack_buff(RED, 2.0, 60.0)
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(3.0)


def test_same_team_large_energy_mechanism_cannot_reactivate_until_window_ends() -> None:
    match = _match()
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 5.0, 5)

    attack_count = len(match.ruleset._attack_buffs_by_team[RED])
    assert not match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 10)
    assert len(match.ruleset._attack_buffs_by_team[RED]) == attack_count
    assert len(match.ruleset._large_energy_mechanism_buffs_by_team[RED]) == 1

    match.update(30.0)

    assert match.ruleset._large_energy_mechanism_buffs_by_team[RED] == []
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 10)
    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(3.0)


def test_both_teams_can_hold_independent_large_energy_mechanism_windows() -> None:
    match = _match()

    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)
    assert match.ruleset.activate_large_energy_mechanism_buff(BLUE, 5.0, 6)

    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(3.0)
    assert match.ruleset._effective_attack_multiplier(BLUE) == pytest.approx(1.5)
    assert match.ruleset._current_large_energy_mechanism_defense(RED) == pytest.approx(
        0.50
    )
    assert match.ruleset._current_large_energy_mechanism_defense(BLUE) == pytest.approx(
        0.25
    )


def test_energy_defense_uses_max_with_tech_core_defense() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    match.ruleset._team_states[RED].tech_core_defense = 0.50
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 5.0, 5)

    assert match.ruleset._effective_defense(target) == pytest.approx(0.50)


def test_energy_defense_uses_max_with_field_defense() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    target.position = _center(match.ruleset._field_base_zone_by_team[RED])
    match.update(0)
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 5.0, 5)

    assert match.ruleset._current_field_defense(target) == pytest.approx(0.50)
    assert match.ruleset._effective_defense(target) == pytest.approx(0.50)


def test_energy_defense_uses_max_with_terrain_defense() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    assert match.ruleset._grant_terrain_crossing_buff(target, "launch_ramp")
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 5.0, 5)

    assert match.ruleset._current_terrain_defense(target) == pytest.approx(0.25)
    assert match.ruleset._effective_defense(target) == pytest.approx(0.25)

    match.reset()
    target = _robot(match, "tarsgo-infantry-1")
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)
    assert match.ruleset._grant_terrain_crossing_buff(target, "launch_ramp")

    assert match.ruleset._effective_defense(target) == pytest.approx(0.50)


def test_energy_defense_uses_max_with_fortress_defense() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    target.position = _center(match.ruleset._fortress_zone_by_team[RED])
    match.update(0)
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 5.0, 5)

    assert match.ruleset._current_fortress_defense(target) == pytest.approx(0.50)
    assert match.ruleset._effective_defense(target) == pytest.approx(0.50)


def test_energy_defense_for_structures_uses_max_with_tech_core() -> None:
    match = _match()
    match.ruleset._team_states[RED].tech_core_defense = 0.25
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    assert match.ruleset._effective_defense(
        _structure(match, RED, "outpost")
    ) == pytest.approx(0.50)
    assert match.ruleset._effective_defense(
        _structure(match, RED, "base")
    ) == pytest.approx(0.50)


@pytest.mark.parametrize(
    ("score", "expected_multiplier"),
    [(2.0, 1.0), (5.0, 2.0), (7.5, 2.0), (8.5, 3.0), (9.5, 5.0)],
)
def test_energy_cooling_uses_official_multiplier(
    score: float,
    expected_multiplier: float,
) -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    base = match.ruleset._effective_heat_parameters(sentry.id).cooling_per_second

    assert match.ruleset.activate_large_energy_mechanism_buff(RED, score, 5)

    assert match.ruleset._effective_heat_parameters(
        sentry.id
    ).cooling_per_second == pytest.approx(base * expected_multiplier)


def test_energy_cooling_and_tunnel_use_max_final_candidate() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    match.ruleset._grant_experience(infantry.id, 2200)
    base = match.ruleset._effective_heat_parameters(infantry.id).cooling_per_second
    assert match.ruleset._grant_terrain_crossing_buff(infantry, "tunnel")
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 8.5, 5)

    assert match.ruleset._effective_heat_parameters(
        infantry.id
    ).cooling_per_second == pytest.approx(base * 3.0)


def test_energy_cooling_and_fortress_use_max_final_candidate() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    infantry.position = _center(match.ruleset._fortress_zone_by_team[RED])
    match.update(0)
    match.ruleset._grant_experience(infantry.id, 2200)
    match.ruleset._base_by_team[RED].hp = 2000
    base = match.ruleset._effective_performance(infantry.id).cooling_per_second
    assert match.ruleset._fortress_cooling_bonus(infantry) == 75

    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 8.5, 5)
    assert match.ruleset._effective_heat_parameters(
        infantry.id
    ).cooling_per_second == pytest.approx(base + 75)

    match.reset()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    infantry.position = _center(match.ruleset._fortress_zone_by_team[RED])
    match.update(0)
    match.ruleset._grant_experience(infantry.id, 2200)
    match.ruleset._base_by_team[RED].hp = 4600
    base = match.ruleset._effective_performance(infantry.id).cooling_per_second
    assert match.ruleset._fortress_cooling_bonus(infantry) == 10
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    assert match.ruleset._effective_heat_parameters(
        infantry.id
    ).cooling_per_second == pytest.approx(base * 5.0)


def test_energy_mechanism_changes_actual_10hz_heat_cooling() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    heat = match.ruleset._shooting_heat_by_robot[sentry.id]
    heat.heat = 100.0
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    match.ruleset.prepare_combat(match, 0.1)

    assert heat.heat == pytest.approx(85.0)


def test_weakened_living_robot_keeps_team_defense_and_cooling_but_cannot_fire() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    lifecycle = match.ruleset._robot_lifecycle_by_robot[sentry.id]
    lifecycle.weak = True
    match.ruleset._projectile_allowance_by_robot[sentry.id].allowed = 1
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    assert match.ruleset._effective_defense(sentry) == pytest.approx(0.50)
    assert match.ruleset._effective_heat_parameters(
        sentry.id
    ).cooling_per_second == pytest.approx(150.0)
    assert not match.ruleset.can_attack(sentry)


def test_team_window_survives_robot_death_and_applies_after_immediate_respawn() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    economy = match.ruleset._economy_by_team[RED]
    economy.coins = 1000
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    hp = hero.hp
    assert match.apply_damage(
        hero,
        hp * 2,
        source_team_id=BLUE,
        bypass_invincibility=True,
    ) == hp
    match.update(0)

    assert not hero.alive
    assert match.ruleset._current_large_energy_mechanism_defense(RED) == pytest.approx(
        0.50
    )

    assert match.ruleset.purchase_immediate_respawn(match, hero)

    assert hero.alive
    assert match.ruleset._effective_defense(hero) == pytest.approx(0.50)
    assert match.ruleset._effective_attack_multiplier(RED) == pytest.approx(3.0)


def test_large_dt_expires_attack_defense_and_cooling_together() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    match.update(30.0)

    assert match.ruleset._large_energy_mechanism_buffs_by_team[RED] == []
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0
    assert match.ruleset._current_large_energy_mechanism_defense(RED) == 0.0
    assert match.ruleset._effective_heat_parameters(
        sentry.id
    ).cooling_per_second == pytest.approx(30.0)


def test_match_reset_clears_large_energy_mechanism_and_attack_state() -> None:
    match = _match()
    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 10)

    match.reset()

    assert match.ruleset._large_energy_mechanism_buffs_by_team == {
        RED: [],
        BLUE: [],
    }
    assert match.ruleset._effective_attack_multiplier(RED) == 1.0
    assert match.ruleset._current_large_energy_mechanism_defense(RED) == 0.0
    assert match.ruleset._current_large_energy_mechanism_cooling_multiplier(RED) == 1.0


def test_large_energy_mechanism_experience_distribution_remains_deferred() -> None:
    match = _match()
    before = {
        robot_id: state.experience
        for robot_id, state in match.ruleset._progression_by_robot.items()
        if match.ruleset._robots_by_id[robot_id].team == RED
    }

    assert match.ruleset.activate_large_energy_mechanism_buff(RED, 9.5, 5)

    after = {
        robot_id: state.experience
        for robot_id, state in match.ruleset._progression_by_robot.items()
        if match.ruleset._robots_by_id[robot_id].team == RED
    }
    assert after == before
