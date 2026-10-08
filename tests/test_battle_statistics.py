from pathlib import Path

from tarsgo_simulator.core.match import Match


ROOT = Path(__file__).resolve().parents[1]
TRAINING_SCENARIO = ROOT / "configs/scenarios/first-steps.yaml"
RMUC_SCENARIO = ROOT / "configs/scenarios/rmuc-2026-region-rules-lab.yaml"
RMUL_SCENARIO = ROOT / "configs/scenarios/rmul-2026-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _quiet_match(scenario: Path) -> Match:
    match = Match.from_scenario(scenario)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
    return match


def test_robot_damage_kills_and_deaths_are_reduced_from_match_events_once() -> None:
    match = _quiet_match(TRAINING_SCENARIO)
    attacker = _robot(match, "tarsgo-infantry-1")
    victim = _robot(match, "opponent-infantry-1")
    victim_hp = victim.hp

    assert match.apply_damage(victim, victim_hp, source_robot=attacker) == victim_hp
    assert match.apply_damage(victim, 100, source_robot=attacker) == 0

    report = match.battle_report()
    attacker_stats = next(item for item in report.robots if item.robot_id == attacker.id)
    victim_stats = next(item for item in report.robots if item.robot_id == victim.id)
    assert attacker_stats.damage_dealt == victim_hp
    assert attacker_stats.kills == 1
    assert attacker_stats.deaths == 0
    assert victim_stats.damage_dealt == 0
    assert victim_stats.kills == 0
    assert victim_stats.deaths == 1
    assert next(team for team in report.teams if team.team_id == attacker.team).damage_dealt == victim_hp

    match.update(0.01)
    assert next(
        item for item in match.battle_report().robots if item.robot_id == attacker.id
    ).kills == 1


def test_rmuc_actual_hp_damage_and_virtual_shield_absorption_are_separate() -> None:
    match = _quiet_match(RMUC_SCENARIO)
    attacker = _robot(match, "opponent-hero")
    base = next(
        structure
        for structure in match.structures
        if structure.team == RED and structure.type == "base"
    )
    outpost = next(
        structure
        for structure in match.structures
        if structure.team == RED and structure.type == "outpost"
    )
    outpost.hp = 0
    outpost.alive = False
    match.ruleset._team_states[RED].base_virtual_shield = 80

    actual_hp_damage = match.apply_damage(base, 200, source_robot=attacker)

    event = match.current_events[-1]
    assert event.damage == actual_hp_damage
    assert event.virtual_shield_absorbed == 80
    attacker_stats = next(
        item for item in match.battle_report().robots if item.robot_id == attacker.id
    )
    assert attacker_stats.damage_dealt == actual_hp_damage
    assert attacker_stats.virtual_shield_absorbed == 80
    blue_stats = next(
        item for item in match.battle_report().teams if item.team_id == BLUE
    )
    assert blue_stats.damage_dealt == actual_hp_damage
    assert blue_stats.virtual_shield_absorbed == 80
    red_structures = next(
        item for item in match.battle_report().teams if item.team_id == RED
    )
    assert red_structures.base_hp == base.hp
    assert red_structures.outpost_hp == outpost.hp == 0

    match.update(0.01)
    repeat_report = match.battle_report()
    assert next(team for team in repeat_report.teams if team.team_id == BLUE) == blue_stats


def test_battle_statistics_reset_and_levels_only_exist_for_progression_robots() -> None:
    match = _quiet_match(RMUC_SCENARIO)
    attacker = _robot(match, "opponent-hero")
    victim = _robot(match, "tarsgo-infantry-1")
    match.apply_damage(victim, 25, source_robot=attacker)

    report = match.battle_report()
    records = {item.robot_id: item for item in report.robots}
    assert records[attacker.id].level == 1
    assert records[attacker.id].experience == 0
    assert records["tarsgo-engineer"].level is None
    assert records["tarsgo-engineer"].experience is None
    assert records["tarsgo-sentry"].level is None
    assert records["tarsgo-sentry"].experience is None

    match.reset()
    reset_report = match.battle_report()
    assert reset_report.elapsed_seconds == 0
    assert reset_report.winner_id is None
    assert all(item.damage_dealt == 0 for item in reset_report.robots)
    assert all(item.virtual_shield_absorbed == 0 for item in reset_report.robots)
    assert all(item.kills == 0 and item.deaths == 0 for item in reset_report.robots)
    reset_records = {item.robot_id: item for item in reset_report.robots}
    assert reset_records[attacker.id].level == 1
    assert reset_records[attacker.id].experience == 0


def test_training_and_rmul_reports_do_not_invent_robot_levels() -> None:
    for scenario in (TRAINING_SCENARIO, RMUL_SCENARIO):
        report = _quiet_match(scenario).battle_report()
        assert report.robots
        assert all(item.level is None for item in report.robots)
        assert all(item.experience is None for item in report.robots)


def test_report_snapshot_contains_terminal_time_and_winner() -> None:
    match = _quiet_match(RMUC_SCENARIO)
    match.elapsed_time = 249.5
    match.winner = RED
    match.finished = True

    report = match.battle_report()

    assert report.elapsed_seconds == 249.5
    assert report.winner_id == RED
    assert {team.team_id for team in report.teams} == {RED, BLUE}
