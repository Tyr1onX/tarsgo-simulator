from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_rule_document
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPOSITORY_ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RULES = REPOSITORY_ROOT / "configs" / "rules" / "rmuc-2026-region-v1.4.0.yaml"
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


def _sync(match: Match, dt: float = 0.0) -> None:
    match.update(dt)


def _defense(match: Match, robot: Robot) -> float:
    return match.ruleset._effective_defense(robot)


def _field(match: Match, robot: Robot) -> float:
    return match.ruleset._current_field_defense(robot)


def _destroy_outpost(match: Match, team_id: str) -> None:
    outpost = match.ruleset._outpost_by_team[team_id]
    attacker = BLUE if team_id == RED else RED
    hp_before = outpost.hp
    assert match.apply_damage(outpost, 100000, source_team_id=attacker) == hp_before
    match.update(0)


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_static_field_zone_bindings_reuse_base_and_outpost_points() -> None:
    match = _match()

    assert match.ruleset._field_base_zone_by_team[RED].id == "red-base-buff"
    assert match.ruleset._field_base_zone_by_team[BLUE].id == "blue-base-buff"
    assert match.ruleset._field_outpost_zone_by_team[RED].id == "red-outpost-buff"
    assert match.ruleset._field_outpost_zone_by_team[BLUE].id == "blue-outpost-buff"
    assert match.ruleset._field_trapezoid_zone_by_team[RED].id == "red-trapezoid-buff"
    assert match.ruleset._field_trapezoid_zone_by_team[BLUE].id == "blue-trapezoid-buff"
    assert {zone.id for zone in match.ruleset._field_central_zones} == {
        "red-central-elevated-buff",
        "blue-central-elevated-buff",
    }


def test_own_base_point_grants_fifty_percent_defense() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._field_base_zone_by_team[RED])

    _sync(match)

    assert _field(match, hero) == pytest.approx(0.50)
    assert _defense(match, hero) == pytest.approx(0.50)


def test_enemy_base_point_does_not_grant_defense() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._field_base_zone_by_team[BLUE])

    _sync(match)

    assert _field(match, hero) == 0
    assert _defense(match, hero) == 0


def test_own_trapezoid_grants_fifty_percent_defense() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = _center(match.ruleset._field_trapezoid_zone_by_team[RED])

    _sync(match)

    assert _field(match, engineer) == pytest.approx(0.50)


def test_enemy_trapezoid_does_not_grant_defense() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    infantry.position = _center(match.ruleset._field_trapezoid_zone_by_team[BLUE])

    _sync(match)

    assert _field(match, infantry) == 0


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-infantry-1", "tarsgo-sentry"],
)
def test_central_point_grants_twenty_five_percent_to_legal_types(
    robot_id: str,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    zone = match.ruleset._field_central_zones[0]
    robot.position = _center(zone)

    _sync(match)

    assert match.ruleset._central_defense_state_by_zone[zone.id].owner_team_id == RED
    assert _field(match, robot) == pytest.approx(0.25)


def test_engineer_cannot_occupy_central_point() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    zone = match.ruleset._field_central_zones[0]
    engineer.position = _center(zone)

    _sync(match)

    state = match.ruleset._central_defense_state_by_zone[zone.id]
    assert state.owner_team_id is None
    assert _field(match, engineer) == 0


def test_two_central_points_have_independent_owners() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    blue = _robot(match, "opponent-hero")
    first, second = match.ruleset._field_central_zones
    red.position = _center(first)
    blue.position = _center(second)

    _sync(match)

    assert match.ruleset._central_defense_state_by_zone[first.id].owner_team_id == RED
    assert match.ruleset._central_defense_state_by_zone[second.id].owner_team_id == BLUE
    assert _field(match, red) == pytest.approx(0.25)
    assert _field(match, blue) == pytest.approx(0.25)


def test_same_team_multiple_robots_can_share_central_buff() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    zone = match.ruleset._field_central_zones[0]
    hero.position = _center(zone)
    infantry.position = _center(zone)

    _sync(match)

    assert match.ruleset._central_defense_state_by_zone[zone.id].owner_team_id == RED
    assert _field(match, hero) == pytest.approx(0.25)
    assert _field(match, infantry) == pytest.approx(0.25)


def test_existing_central_owner_excludes_opponent() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    blue = _robot(match, "opponent-hero")
    zone = match.ruleset._field_central_zones[0]
    red.position = _center(zone)
    _sync(match)

    blue.position = _center(zone)
    _sync(match)

    assert match.ruleset._central_defense_state_by_zone[zone.id].owner_team_id == RED
    assert _field(match, red) == pytest.approx(0.25)
    assert _field(match, blue) == 0


def test_empty_central_same_frame_two_team_entry_is_contested() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    blue = _robot(match, "opponent-hero")
    zone = match.ruleset._field_central_zones[0]
    red.position = _center(zone)
    blue.position = _center(zone)

    _sync(match)

    assert match.ruleset._central_defense_state_by_zone[zone.id].owner_team_id is None
    assert _field(match, red) == 0
    assert _field(match, blue) == 0


def test_contested_central_is_claimed_when_only_one_team_remains() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    blue = _robot(match, "opponent-hero")
    zone = match.ruleset._field_central_zones[0]
    red.position = _center(zone)
    blue.position = _center(zone)
    _sync(match)

    blue.position = (2500.0, 1200.0)
    _sync(match)

    assert match.ruleset._central_defense_state_by_zone[zone.id].owner_team_id == RED
    assert _field(match, red) == pytest.approx(0.25)


def test_central_owner_has_two_second_release_delay() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    zone = match.ruleset._field_central_zones[0]
    red.position = _center(zone)
    _sync(match)

    red.position = (600.0, 300.0)
    _sync(match, 1.9)

    state = match.ruleset._central_defense_state_by_zone[zone.id]
    assert state.owner_team_id == RED
    assert state.release_remaining == pytest.approx(0.1)
    assert _field(match, red) == pytest.approx(0.25)

    _sync(match, 0.1)

    assert state.owner_team_id is None
    assert _field(match, red) == 0


def test_opponent_cannot_take_central_until_owner_release_delay_expires() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    blue = _robot(match, "opponent-hero")
    zone = match.ruleset._field_central_zones[0]
    red.position = _center(zone)
    _sync(match)

    red.position = (600.0, 300.0)
    blue.position = _center(zone)
    _sync(match, 1.9)

    state = match.ruleset._central_defense_state_by_zone[zone.id]
    assert state.owner_team_id == RED
    assert _field(match, blue) == 0

    _sync(match, 0.1)

    assert state.owner_team_id == BLUE
    assert _field(match, blue) == pytest.approx(0.25)


@pytest.mark.parametrize(
    "zone_getter",
    [
        lambda match: match.ruleset._field_base_zone_by_team[RED],
        lambda match: match.ruleset._field_trapezoid_zone_by_team[RED],
    ],
)
def test_personal_occupy_buff_has_two_second_exit_delay(zone_getter) -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    zone = zone_getter(match)
    hero.position = _center(zone)
    _sync(match)
    expected = 0.50

    hero.position = (600.0, 300.0)
    _sync(match, 1.99)
    assert _field(match, hero) == pytest.approx(expected)

    _sync(match, 0.01)
    assert _field(match, hero) == 0


def test_own_outpost_alive_grants_twenty_five_percent() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._field_outpost_zone_by_team[RED])

    _sync(match)

    assert _field(match, hero) == pytest.approx(0.25)


def test_own_outpost_point_stops_buff_immediately_when_outpost_destroyed() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.position = _center(match.ruleset._field_outpost_zone_by_team[RED])
    _sync(match)
    assert _field(match, hero) == pytest.approx(0.25)

    _destroy_outpost(match, RED)
    _sync(match)

    assert _field(match, hero) == 0


def test_enemy_outpost_point_is_occupiable_before_300_when_conditions_hold() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 299.0
    hero.position = _center(match.ruleset._field_outpost_zone_by_team[BLUE])

    _sync(match)

    assert match.ruleset._outpost_by_team[RED].alive
    assert not match.ruleset._outpost_by_team[BLUE].alive
    assert _field(match, hero) == pytest.approx(0.25)


def test_enemy_outpost_point_loses_eligibility_at_exactly_300_seconds() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 299.0
    hero.position = _center(match.ruleset._field_outpost_zone_by_team[BLUE])
    _sync(match)
    assert _field(match, hero) == pytest.approx(0.25)

    match.elapsed_time = 300.0
    _sync(match)

    assert _field(match, hero) == 0


def test_enemy_outpost_point_requires_own_outpost_alive() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _destroy_outpost(match, BLUE)
    _destroy_outpost(match, RED)
    match.elapsed_time = 200.0
    hero.position = _center(match.ruleset._field_outpost_zone_by_team[BLUE])

    _sync(match)

    assert _field(match, hero) == 0


def test_field_and_tech_core_defense_use_max_not_sum() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    team_state = match.ruleset._team_states[RED]

    team_state.tech_core_defense = 0.25
    hero.position = _center(match.ruleset._field_base_zone_by_team[RED])
    _sync(match)
    assert _defense(match, hero) == pytest.approx(0.50)

    team_state.tech_core_defense = 0.50
    hero.position = _center(match.ruleset._field_central_zones[0])
    _sync(match)
    assert _defense(match, hero) == pytest.approx(0.50)


def test_defense_switches_back_to_tech_core_after_field_release() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    match.ruleset._team_states[RED].tech_core_defense = 0.25
    hero.position = _center(match.ruleset._field_base_zone_by_team[RED])
    _sync(match)
    assert _defense(match, hero) == pytest.approx(0.50)

    hero.position = (600.0, 300.0)
    _sync(match, 2.0)

    assert _field(match, hero) == 0
    assert _defense(match, hero) == pytest.approx(0.25)


def test_field_defense_damage_event_scoreboard_and_xp_use_final_hp_loss() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    attacker = _robot(match, "opponent-hero")
    target.position = _center(match.ruleset._field_base_zone_by_team[RED])
    _sync(match)

    before_hp = target.hp
    assert match.apply_damage(target, 20, source_robot=attacker) == 10
    assert target.hp == before_hp - 10
    event = match.current_events[-1]
    assert event.type == MatchEventType.ROBOT_DAMAGED
    assert event.damage == 10

    match.update(0)

    assert match.ruleset.attack_damage_by_team[BLUE] == 10
    assert match.ruleset._progression_by_robot[attacker.id].experience == 40


def test_structure_defense_does_not_inherit_robot_field_buff() -> None:
    match = _match()
    outpost = match.ruleset._outpost_by_team[RED]
    match.ruleset._team_states[RED].tech_core_defense = 0.25

    assert match.ruleset._effective_defense(outpost) == pytest.approx(0.25)


def test_display_reports_current_effective_robot_defense() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    match.ruleset._team_states[RED].tech_core_defense = 0.25
    hero.position = _center(match.ruleset._field_base_zone_by_team[RED])
    _sync(match)

    statuses = dict(match.ruleset.display_state.robot_statuses)
    assert statuses[hero.id] == "DEF 50%"

    hero.position = (600.0, 300.0)
    _sync(match, 2.0)
    statuses = dict(match.ruleset.display_state.robot_statuses)
    assert statuses[hero.id] == "DEF 25%"


def test_reset_clears_central_owners_and_field_occupancy() -> None:
    match = _match()
    red = _robot(match, "tarsgo-hero")
    zone = match.ruleset._field_central_zones[0]
    red.position = _center(zone)
    _sync(match)
    assert match.ruleset._central_defense_state_by_zone[zone.id].owner_team_id == RED
    assert match.ruleset._field_occupy_remaining

    match.reset()

    assert all(
        state.owner_team_id is None and state.release_remaining == 0
        for state in match.ruleset._central_defense_state_by_zone.values()
    )
    assert match.ruleset._field_occupy_remaining == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["field_defense_buffs"].__setitem__(
            "occupy_release_delay", 1
        ),
        lambda data: data["field_defense_buffs"]["defense"].__setitem__(
            "base", 0.25
        ),
        lambda data: data["field_defense_buffs"]["defense"].__setitem__(
            "central", 0.50
        ),
        lambda data: data["field_defense_buffs"]["defense"].__setitem__(
            "trapezoid", 0.25
        ),
        lambda data: data["field_defense_buffs"]["defense"].__setitem__(
            "outpost", 0.50
        ),
    ],
)
def test_field_defense_config_rejects_non_v140_values(
    tmp_path: Path,
    mutate,
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))
