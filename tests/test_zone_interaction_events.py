from pathlib import Path

import pytest

from tarsgo_simulator.core.events import ZoneEventType
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from rmuc_test_support import move_ground_robots_to_unbuffed_region


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)


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


def _zone_events(match: Match, robot: Robot, zone_id: str):
    return [
        event
        for event in match.zone_events
        if event.robot_id == robot.id and event.zone_id == zone_id
    ]


@pytest.mark.parametrize(
    ("side", "robot_id"),
    [("red", "tarsgo-hero"), ("blue", "opponent-hero")],
)
def test_real_movement_reads_projected_rfid_and_applies_own_base_defense(
    side: str,
    robot_id: str,
) -> None:
    match = _match()
    match._update_ai = lambda _dt: None
    robot = _robot(match, robot_id)
    team_id = match.config.scenario.teams[side].team_id
    zone = match.ruleset._field_base_zone_by_team[team_id]

    if side == "red":
        robot.position = (zone.right + 100.0, 7500.0)
        goal = (zone.right - 100.0, 7500.0)
    else:
        robot.position = (zone.x - 100.0, 7500.0)
        goal = (zone.x + 100.0, 7500.0)
    assert not zone.contains(robot.position)
    assert zone.contains(goal)

    # Prime the robot at its real starting position, then let Match movement
    # cross into the mapped interaction area on the normal simulation tick.
    match._prime_zone_presence()
    robot.speed = 200.0
    robot.set_path([goal])
    match.update(1.0)

    assert robot.position == pytest.approx(goal)
    assert match.is_robot_in_zone(robot.id, zone.id)
    entry = _zone_events(match, robot, zone.id)
    assert len(entry) == 1
    assert entry[0].type is ZoneEventType.ENTERED
    assert entry[0].cause == "movement"
    assert entry[0].time == pytest.approx(1.0)
    assert len(match.rfid_read_events) == 1
    read = match.rfid_read_events[0]
    assert (read.robot_id, read.team_id, read.zone_id) == (
        robot.id,
        team_id,
        zone.id,
    )
    assert read.approximate
    assert read.source.value == "simulated_zone_entry"
    assert read.time == pytest.approx(1.0)
    assert match.ruleset._current_field_defense(robot) == pytest.approx(0.50)


def test_staying_does_not_repeat_rfid_and_leave_reenter_reads_again() -> None:
    match = _match()
    robot = _robot(match, "tarsgo-hero")
    team_id = robot.team
    zone = match.ruleset._field_base_zone_by_team[team_id]
    outside = (zone.right + 100.0, 7500.0)
    inside = (zone.right - 100.0, 7500.0)
    robot.position = outside
    match._prime_zone_presence()
    robot.speed = 200.0

    robot.set_path([inside])
    match.update(1.0)
    assert len(match.rfid_read_events) == 1
    assert _zone_events(match, robot, zone.id)[0].type is ZoneEventType.ENTERED

    match.update(0.1)
    assert match.is_robot_in_zone(robot.id, zone.id)
    assert [event.type for event in _zone_events(match, robot, zone.id)] == [
        ZoneEventType.STAYED
    ]
    assert match.rfid_read_events == []

    robot.set_path([outside])
    match.update(2.1)
    assert not match.is_robot_in_zone(robot.id, zone.id)
    exit_events = _zone_events(match, robot, zone.id)
    assert len(exit_events) == 1
    assert exit_events[0].type is ZoneEventType.EXITED
    assert match.ruleset._current_field_defense(robot) == 0

    robot.set_path([inside])
    match.update(1.0)
    assert len(match.rfid_read_events) == 1
    assert _zone_events(match, robot, zone.id)[0].type is ZoneEventType.ENTERED


def test_engineer_entry_does_not_bypass_central_buff_robot_eligibility() -> None:
    match = _match()
    match._update_ai = lambda _dt: None
    engineer = _robot(match, "tarsgo-engineer")
    zone = match.ruleset._field_central_zones[0]
    goal = (zone.x + zone.width / 2, zone.y + zone.height / 2)
    engineer.position = (zone.x - 100.0, goal[1])
    assert not zone.contains(engineer.position)
    assert zone.contains(goal)

    match._prime_zone_presence()
    engineer.speed = 2000.0
    engineer.set_path([goal])
    match.update(1.0)

    assert any(read.zone_id == zone.id for read in match.rfid_read_events)
    assert match.ruleset._central_defense_state_by_zone[zone.id].owner_team_id is None
    assert match.ruleset._current_field_defense(engineer) == 0


def test_death_exit_and_respawn_do_not_fabricate_an_rfid_read() -> None:
    match = _match()
    robot = _robot(match, "tarsgo-hero")
    zone = match.ruleset._field_base_zone_by_team[robot.team]
    robot.position = (zone.right - 100.0, 7500.0)
    match._prime_zone_presence()
    match.update(0.1)
    assert match.is_robot_in_zone(robot.id, zone.id)

    assert match.apply_damage(
        robot,
        robot.hp,
        bypass_invincibility=True,
    ) > 0
    assert not match.is_robot_in_zone(robot.id, zone.id)
    assert match.is_robot_position_in_zone(robot.id, zone.id)
    match.update(0.0)
    death_exits = _zone_events(match, robot, zone.id)
    assert len(death_exits) == 1
    assert death_exits[0].type is ZoneEventType.EXITED
    assert death_exits[0].cause == "death"
    assert match.rfid_read_events == []

    lifecycle = match.ruleset._robot_lifecycle_by_robot[robot.id]
    required = lifecycle.respawn_required
    assert required is not None
    match.update(float(required))
    assert robot.alive
    respawn_entries = _zone_events(match, robot, zone.id)
    assert respawn_entries
    assert respawn_entries[-1].type is ZoneEventType.ENTERED
    assert respawn_entries[-1].cause == "respawn"
    assert match.rfid_read_events == []


def test_zone_occupancy_alone_cannot_be_recorded_as_rfid_read() -> None:
    match = _match()
    robot = _robot(match, "tarsgo-hero")
    zone = match.ruleset._field_base_zone_by_team[robot.team]
    robot.position = (zone.x + zone.width / 2, zone.y + zone.height / 2)
    match._prime_zone_presence()

    assert match.is_robot_in_zone(robot.id, zone.id)
    assert match.record_projected_rfid_read(
        robot.id,
        zone.id,
        time=match.elapsed_time,
    ) is None
    assert match.rfid_read_events == []


def test_generic_zone_events_keep_training_and_rmul_modes_compatible() -> None:
    training_scenario = REPOSITORY_ROOT / "configs/scenarios/first-steps.yaml"
    training = Match.from_scenario(training_scenario)
    training.update(0.1)
    assert training.rfid_read_events == []

    rmul_scenario = REPOSITORY_ROOT / "configs/scenarios/rmul-2026-rules-lab.yaml"
    rmul = Match.from_scenario(rmul_scenario)
    rmul.update(0.1)
    hero = _robot(rmul, "tarsgo-hero")
    assert any(
        event.robot_id == hero.id
        and event.zone_id == "red-supply"
        and event.type is ZoneEventType.STAYED
        for event in rmul.zone_events
    )
    assert rmul.rfid_read_events == []
