from pathlib import Path

import pytest

from tarsgo_simulator.core.events import MatchEventType
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


def _zone_center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _place_in_resource(match: Match, engineer: Robot) -> None:
    engineer.position = _zone_center(match.ruleset._resource_zone_by_team[engineer.team])


def _place_in_assembly(match: Match, engineer: Robot) -> None:
    engineer.position = _zone_center(match.ruleset._assembly_zone_by_team[engineer.team])


def _pickup(match: Match, engineer: Robot, count: int = 1) -> None:
    _place_in_resource(match, engineer)
    state = match.ruleset._engineer_resources_by_id[engineer.id]
    while state.energy_unit_credits < count:
        assert match.ruleset.pickup_energy_unit(match, engineer)


def _complete(match: Match, engineer: Robot, difficulty: int) -> None:
    _pickup(match, engineer)
    _place_in_assembly(match, engineer)
    assert match.ruleset.start_tech_core_assembly(match, engineer, difficulty)
    assert match.ruleset.confirm_tech_core_assembly(match, engineer)


def _complete_d1(match: Match, engineer: Robot) -> None:
    _complete(match, engineer, 1)


def _complete_d2(match: Match, engineer: Robot) -> None:
    if match.ruleset._tech_core_by_team[engineer.team].completion_count_by_difficulty[1] == 0:
        _complete_d1(match, engineer)
    match.elapsed_time = max(match.elapsed_time, 60.0)
    _complete(match, engineer, 2)


def _complete_d3(match: Match, engineer: Robot) -> None:
    if match.ruleset._tech_core_by_team[engineer.team].completion_count_by_difficulty[2] == 0:
        _complete_d2(match, engineer)
    match.elapsed_time = max(match.elapsed_time, 120.0)
    _complete(match, engineer, 3)


def _prepare_d4(match: Match, engineer: Robot) -> None:
    state = match.ruleset._tech_core_by_team[engineer.team]
    if state.completion_count_by_difficulty[3] == 0:
        _complete_d3(match, engineer)
    match.elapsed_time = max(match.elapsed_time, 180.0)
    _pickup(match, engineer, 2)
    _place_in_assembly(match, engineer)
    assert match.ruleset.start_tech_core_assembly(match, engineer, 4)


def _complete_d4(match: Match, engineer: Robot) -> None:
    _prepare_d4(match, engineer)
    for step in range(1, 7):
        assert match.ruleset.confirm_d4_step(match, engineer, "own", step)
        assert match.ruleset.confirm_d4_step(match, engineer, "opponent", step)


def _destroy_outpost(match: Match, team_id: str) -> None:
    attacker_team = BLUE if team_id == RED else RED
    outpost = _structure(match, team_id, "outpost")
    assert match.apply_damage(
        outpost,
        100000,
        source_team_id=attacker_team,
    ) == outpost.max_hp
    match.update(0)


def _clear_processed_events(match: Match) -> None:
    match.update(0)


def test_initial_defense_and_virtual_shield_are_zero() -> None:
    match = _match()

    for team_id in (RED, BLUE):
        state = match.ruleset._team_states[team_id]
        assert state.tech_core_defense == 0
        assert state.base_virtual_shield == 0


def test_d3_first_grants_twenty_five_percent_and_repeat_does_not_stack() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d3(match, engineer)
    state = match.ruleset._team_states[RED]
    assert state.tech_core_defense == pytest.approx(0.25)

    _complete(match, engineer, 3)

    assert match.ruleset._tech_core_by_team[RED].completion_count_by_difficulty[3] == 2
    assert state.tech_core_defense == pytest.approx(0.25)


def test_d4_upgrades_defense_to_fifty_percent_not_seventy_five() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_d3(match, engineer)
    assert match.ruleset._team_states[RED].tech_core_defense == pytest.approx(0.25)

    _complete_d4(match, engineer)

    assert match.ruleset._team_states[RED].tech_core_defense == pytest.approx(0.50)


@pytest.mark.parametrize(
    "robot_id",
    [
        "tarsgo-hero",
        "tarsgo-engineer",
        "tarsgo-infantry-1",
        "tarsgo-sentry",
    ],
)
def test_d3_defense_reduces_enemy_damage_to_all_ground_robot_types(
    robot_id: str,
) -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    target = _robot(match, robot_id)
    _complete_d3(match, engineer)
    before = target.hp

    assert match.apply_damage(target, 20, source_team_id=BLUE) == 15
    assert target.hp == before - 15


def test_d3_defense_reduces_outpost_damage() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d3(match, engineer)
    outpost = _structure(match, RED, "outpost")

    assert match.apply_damage(outpost, 200, source_team_id=BLUE) == 150
    assert outpost.hp == 1350


def test_d3_defense_reduces_base_damage_after_outpost_is_destroyed() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d3(match, engineer)
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")

    assert match.apply_damage(base, 200, source_team_id=BLUE) == 150
    assert base.hp == 4850


@pytest.mark.parametrize(
    ("defense", "incoming", "expected"),
    [
        (0.25, 1, 1),
        (0.25, 2, 2),
        (0.25, 3, 2),
        (0.25, 6, 5),
        (0.50, 1, 1),
        (0.50, 3, 2),
        (0.50, 5, 3),
    ],
)
def test_defense_rounding_is_explicit_half_up(
    defense: float,
    incoming: int,
    expected: int,
) -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    match.ruleset._team_states[RED].tech_core_defense = defense
    before = target.hp

    assert match.apply_damage(target, incoming, source_team_id=BLUE) == expected
    assert target.hp == before - expected


@pytest.mark.parametrize(
    ("starting_hp", "expected_hp", "expected_shield"),
    [
        (5000, 5000, 2000),
        (4500, 5000, 1500),
        (3000, 5000, 0),
        (1000, 3000, 0),
    ],
)
def test_d4_base_bonus_fills_hp_then_converts_overflow_to_virtual_shield(
    starting_hp: int,
    expected_hp: int,
    expected_shield: int,
) -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    base = _structure(match, RED, "base")
    base.hp = starting_hp

    _complete_d4(match, engineer)

    assert base.max_hp == 5000
    assert base.hp == expected_hp
    assert match.ruleset._team_states[RED].base_virtual_shield == expected_shield


def test_d4_shield_absorbs_post_defense_damage_before_base_hp() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d4(match, engineer)
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")
    state = match.ruleset._team_states[RED]
    assert state.base_virtual_shield == 2000

    assert match.apply_damage(base, 200, source_team_id=BLUE) == 0

    assert state.base_virtual_shield == 1900
    assert base.hp == 5000


def test_d4_shield_crossing_zero_applies_only_remainder_to_base_hp() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d4(match, engineer)
    _destroy_outpost(match, RED)
    base = _structure(match, RED, "base")
    state = match.ruleset._team_states[RED]
    state.base_virtual_shield = 50

    assert match.apply_damage(base, 200, source_team_id=BLUE) == 50

    assert state.base_virtual_shield == 0
    assert base.hp == 4950


def test_base_invincibility_precedes_defense_and_shield_resolution() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d4(match, engineer)
    base = _structure(match, RED, "base")
    state = match.ruleset._team_states[RED]
    before = (base.hp, state.base_virtual_shield)

    assert match.apply_damage(base, 200, source_team_id=BLUE) == 0

    assert (base.hp, state.base_virtual_shield) == before


def test_damage_event_scoreboard_and_robot_xp_use_reduced_real_hp_loss() -> None:
    match = _match()
    red_engineer = _robot(match, "tarsgo-engineer")
    attacker = _robot(match, "opponent-hero")
    target = _robot(match, "tarsgo-infantry-1")
    _complete_d3(match, red_engineer)

    assert match.apply_damage(target, 20, source_robot=attacker) == 15
    event = match.current_events[-1]
    assert event.type == MatchEventType.ROBOT_DAMAGED
    assert event.damage == 15

    match.update(0)

    assert match.ruleset.attack_damage_by_team[BLUE] == 15
    assert match.ruleset._progression_by_robot[attacker.id].experience == 60


def test_base_hp_loss_xp_scoreboard_and_threshold_use_only_post_shield_hp_loss() -> None:
    match = _match()
    red_engineer = _robot(match, "tarsgo-engineer")
    attacker = _robot(match, "opponent-hero")
    _complete_d4(match, red_engineer)
    _destroy_outpost(match, RED)
    _clear_processed_events(match)

    base = _structure(match, RED, "base")
    state = match.ruleset._team_states[RED]
    state.base_virtual_shield = 50
    scoreboard_before = match.ruleset.attack_damage_by_team[BLUE]
    xp_before = match.ruleset._progression_by_robot[attacker.id].experience
    base_damage_before = state.base_damage_lost

    assert match.apply_damage(base, 200, source_robot=attacker) == 50
    assert match.current_events[-1].damage == 50
    match.update(0)

    assert state.base_virtual_shield == 0
    assert match.ruleset.attack_damage_by_team[BLUE] == scoreboard_before + 50
    assert match.ruleset._progression_by_robot[attacker.id].experience == xp_before + 25
    assert state.base_damage_lost == base_damage_before + 50


def test_shield_only_hit_emits_no_hp_loss_event_or_score_xp() -> None:
    match = _match()
    red_engineer = _robot(match, "tarsgo-engineer")
    attacker = _robot(match, "opponent-hero")
    _complete_d4(match, red_engineer)
    _destroy_outpost(match, RED)
    _clear_processed_events(match)

    base = _structure(match, RED, "base")
    state = match.ruleset._team_states[RED]
    scoreboard_before = match.ruleset.attack_damage_by_team[BLUE]
    xp_before = match.ruleset._progression_by_robot[attacker.id].experience
    base_damage_before = state.base_damage_lost
    shield_before = state.base_virtual_shield
    event_count = len(match.current_events)

    assert match.apply_damage(base, 200, source_robot=attacker) == 0

    assert state.base_virtual_shield == shield_before - 100
    assert base.hp == 5000
    assert len(match.current_events) == event_count

    match.update(0)

    assert match.ruleset.attack_damage_by_team[BLUE] == scoreboard_before
    assert match.ruleset._progression_by_robot[attacker.id].experience == xp_before
    assert state.base_damage_lost == base_damage_before


def test_unknown_or_friendly_source_does_not_consume_defense_or_shield() -> None:
    match = _match()
    base = _structure(match, RED, "base")
    target = _robot(match, "tarsgo-infantry-1")
    state = match.ruleset._team_states[RED]
    state.tech_core_defense = 0.50
    state.base_virtual_shield = 500
    _destroy_outpost(match, RED)
    shield_before = state.base_virtual_shield

    before = target.hp
    assert match.apply_damage(target, 20) == 20
    assert target.hp == before - 20

    assert match.apply_damage(base, 200, source_team_id=RED) == 200
    assert state.base_virtual_shield == shield_before
    assert base.hp == 4800


def test_defense_persists_after_robot_death() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    target = _robot(match, "tarsgo-infantry-1")
    _complete_d3(match, engineer)

    assert match.apply_damage(target, 100000, source_team_id=BLUE) == target.max_hp
    match.update(0)

    assert not target.alive
    assert match.ruleset._team_states[RED].tech_core_defense == pytest.approx(0.25)


def test_d4_does_not_change_base_max_hp_or_base_armor_state() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    base = _structure(match, RED, "base")
    state = match.ruleset._team_states[RED]
    state.base_armor_deployed = True
    base.hp = 4500

    _complete_d4(match, engineer)

    assert base.max_hp == 5000
    assert base.hp == 5000
    assert state.base_virtual_shield == 1500
    assert state.base_armor_deployed


def test_display_reuses_robot_and_structure_statuses_for_defense_and_shield() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d4(match, engineer)

    display = match.ruleset.display_state
    robot_statuses = dict(display.robot_statuses)
    structures = {
        structure_id: status
        for structure_id, _hp, _max_hp, status in display.structure_statuses
    }

    assert robot_statuses["tarsgo-hero"] == "DEF 50%"
    assert robot_statuses["tarsgo-engineer"] == "DEF 50%"
    assert robot_statuses["tarsgo-infantry-1"] == "DEF 50%"
    assert robot_statuses["tarsgo-sentry"] == "DEF 50%"
    assert "DEF 50%" in structures[_structure(match, RED, "outpost").id]
    assert "DEF 50%" in structures[_structure(match, RED, "base").id]
    assert "SH:2000" in structures[_structure(match, RED, "base").id]


def test_reset_clears_defense_and_virtual_shield() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    _complete_d4(match, engineer)

    assert match.ruleset._team_states[RED].tech_core_defense == pytest.approx(0.50)
    assert match.ruleset._team_states[RED].base_virtual_shield == 2000

    match.reset()

    for state in match.ruleset._team_states.values():
        assert state.tech_core_defense == 0
        assert state.base_virtual_shield == 0


def test_tech_core_defense_does_not_mutate_heat_buffer_allowance_or_coin_wallet() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    hero = _robot(match, "tarsgo-hero")
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    heat = match.ruleset._shooting_heat_by_robot[hero.id]
    chassis = match.ruleset._chassis_power_by_robot[hero.id]
    allowance.allowed = 7
    heat.heat = 33
    chassis.buffer_energy = 42
    coins_before = match.ruleset._economy_by_team[RED].coins

    _complete_d3(match, engineer)

    assert allowance.allowed == 7
    assert heat.heat == 33
    assert chassis.buffer_energy == 42
    assert match.ruleset._economy_by_team[RED].coins == coins_before
