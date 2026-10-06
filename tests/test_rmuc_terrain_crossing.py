from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_rule_document
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules
from rmuc_test_support import move_ground_robots_to_unbuffed_region


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
    move_ground_robots_to_unbuffed_region(match)
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _neutral(robot: Robot) -> None:
    robot.position = (14000.0, 7500.0)


def _terrain_state(match: Match, robot_id: str):
    return match.ruleset._terrain_crossing_by_robot[robot_id]


def _terrain_zones(match: Match, terrain_type: str, side: str = "red"):
    return match.ruleset._terrain_zones_by_side_and_type[side][terrain_type]


def _enter(match: Match, robot: Robot, zone, dt: float = 0.0) -> None:
    robot.position = _center(zone)
    match.update(dt)


def _leave(match: Match, robot: Robot, dt: float = 0.0) -> None:
    _neutral(robot)
    match.update(dt)


def _complete_sequence(
    match: Match,
    robot: Robot,
    terrain_type: str,
    *,
    side: str = "red",
    delay_between: float = 0.0,
    reverse_tunnel: bool = False,
) -> None:
    zones = list(_terrain_zones(match, terrain_type, side))
    if reverse_tunnel:
        zones.reverse()
    _enter(match, robot, zones[0])
    for zone in zones[1:]:
        _leave(match, robot, delay_between)
        _enter(match, robot, zone)


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("terrain_type", "window"),
    [
        ("road", 3.0),
        ("elevated_ground", 5.0),
        ("launch_ramp", 10.0),
        ("tunnel", 3.0),
    ],
)
def test_four_terrain_sequences_succeed_in_correct_order(
    terrain_type: str,
    window: float,
) -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    zones = _terrain_zones(match, terrain_type)

    _enter(match, hero, zones[0])
    per_gap = window / max(1, len(zones) - 1) - 0.01
    for zone in zones[1:]:
        _leave(match, hero, per_gap)
        _enter(match, hero, zone)

    state = _terrain_state(match, hero.id)
    assert terrain_type in state.first_acquired_types
    assert state.sequence.terrain_type is None


@pytest.mark.parametrize(
    ("terrain_type", "window"),
    [
        ("road", 3.0),
        ("elevated_ground", 5.0),
        ("launch_ramp", 10.0),
        ("tunnel", 3.0),
    ],
)
def test_four_terrain_sequences_timeout(
    terrain_type: str,
    window: float,
) -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    zones = _terrain_zones(match, terrain_type)

    _enter(match, hero, zones[0])
    _leave(match, hero, window + 0.01)
    for zone in zones[1:]:
        _enter(match, hero, zone)
        _leave(match, hero)

    state = _terrain_state(match, hero.id)
    assert terrain_type not in state.first_acquired_types
    assert match.ruleset._current_terrain_defense(hero) == 0


def test_road_sequence_accepts_exact_three_second_boundary() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lower, upper = _terrain_zones(match, "road")

    _enter(match, hero, lower)
    _leave(match, hero, 3.0)
    _enter(match, hero, upper)

    assert "road" in _terrain_state(match, hero.id).first_acquired_types


def test_engineer_can_trigger_terrain_sequence_without_progression_xp() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")

    _complete_sequence(match, engineer, "road")

    assert match.ruleset._current_terrain_defense(engineer) == pytest.approx(0.25)
    assert engineer.id not in match.ruleset._progression_by_robot


def test_tunnel_sequence_can_run_from_either_end() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    _complete_sequence(match, hero, "tunnel", reverse_tunnel=True)

    state = _terrain_state(match, hero.id)
    assert state.tunnel_defense_remaining == pytest.approx(10.0)
    assert state.tunnel_cooling_remaining == pytest.approx(120.0)


def test_wrong_sequence_order_resets_without_buff() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lower, upper = _terrain_zones(match, "road")

    _enter(match, hero, lower)
    _leave(match, hero)
    elevated_lower = _terrain_zones(match, "elevated_ground")[0]
    _enter(match, hero, elevated_lower)
    _leave(match, hero)
    _enter(match, hero, upper)

    state = _terrain_state(match, hero.id)
    assert state.sequence.terrain_type is None
    assert "road" not in state.first_acquired_types
    assert match.ruleset._current_terrain_defense(hero) == 0


def test_other_modeled_rfid_interrupts_active_sequence() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    lower, upper = _terrain_zones(match, "road")

    _enter(match, hero, lower)
    _leave(match, hero)
    _enter(match, hero, match.ruleset._field_base_zone_by_team[RED])
    _leave(match, hero)
    _enter(match, hero, upper)

    state = _terrain_state(match, hero.id)
    assert state.sequence.terrain_type is None
    assert "road" not in state.first_acquired_types


def test_launch_ramp_grants_25_percent_for_30_seconds() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    _complete_sequence(match, hero, "launch_ramp")
    state = _terrain_state(match, hero.id)

    assert state.standard_defense == pytest.approx(0.25)
    assert state.standard_defense_remaining == pytest.approx(30.0)
    assert match.ruleset._current_terrain_defense(hero) == pytest.approx(0.25)


def test_elevated_ground_grants_25_percent_for_30_seconds() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    _complete_sequence(match, hero, "elevated_ground")
    state = _terrain_state(match, hero.id)

    assert state.standard_defense == pytest.approx(0.25)
    assert state.standard_defense_remaining == pytest.approx(30.0)


def test_road_grants_25_percent_for_5_seconds_and_15_second_cooldown() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    _complete_sequence(match, hero, "road")
    state = _terrain_state(match, hero.id)

    assert state.standard_defense == pytest.approx(0.25)
    assert state.standard_defense_remaining == pytest.approx(5.0)
    assert state.road_reacquire_remaining == pytest.approx(15.0)


def test_road_cannot_be_reacquired_within_15_seconds() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    assert match.ruleset._grant_terrain_crossing_buff(hero, "road")
    state = _terrain_state(match, hero.id)
    match.ruleset._advance_terrain_crossing_timers(5.0)
    assert state.standard_defense_remaining == 0
    assert state.road_reacquire_remaining == pytest.approx(10.0)

    assert not match.ruleset._grant_terrain_crossing_buff(hero, "road")
    assert state.standard_defense_remaining == 0

    match.ruleset._advance_terrain_crossing_timers(10.0)
    assert match.ruleset._grant_terrain_crossing_buff(hero, "road")
    assert state.standard_defense_remaining == pytest.approx(5.0)


def test_tunnel_grants_50_percent_10s_and_cooling_double_120s() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    _complete_sequence(match, hero, "tunnel")
    state = _terrain_state(match, hero.id)

    assert match.ruleset._current_terrain_defense(hero) == pytest.approx(0.50)
    assert state.tunnel_defense_remaining == pytest.approx(10.0)
    assert state.tunnel_cooling_remaining == pytest.approx(120.0)


def test_standard_terrain_retrigger_upgrades_to_50_and_keeps_longer_remaining() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    match.ruleset._advance_terrain_crossing_timers(10.0)
    state = _terrain_state(match, hero.id)
    assert state.standard_defense_remaining == pytest.approx(20.0)

    assert match.ruleset._grant_terrain_crossing_buff(hero, "road")
    assert state.standard_defense == pytest.approx(0.50)
    assert state.standard_defense_remaining == pytest.approx(20.0)


def test_standard_terrain_retrigger_uses_new_longer_duration_when_needed() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    match.ruleset._advance_terrain_crossing_timers(29.0)
    state = _terrain_state(match, hero.id)
    assert state.standard_defense_remaining == pytest.approx(1.0)

    assert match.ruleset._grant_terrain_crossing_buff(hero, "road")
    assert state.standard_defense == pytest.approx(0.50)
    assert state.standard_defense_remaining == pytest.approx(5.0)


def test_tunnel_defense_timer_is_independent_from_standard_terrain_timer() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "tunnel")
    state = _terrain_state(match, hero.id)

    match.ruleset._advance_terrain_crossing_timers(11.0)

    assert state.tunnel_defense_remaining == 0
    assert state.standard_defense_remaining == pytest.approx(19.0)
    assert match.ruleset._current_terrain_defense(hero) == pytest.approx(0.25)
    assert state.tunnel_cooling_remaining == pytest.approx(109.0)


def test_tech_core_static_and_terrain_defense_use_max() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    match.ruleset._team_states[RED].tech_core_defense = 0.25

    hero.position = _center(match.ruleset._field_base_zone_by_team[RED])
    match.update(0)
    assert match.ruleset._effective_defense(hero) == pytest.approx(0.50)

    _neutral(hero)
    match.update(2.0)
    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    assert match.ruleset._effective_defense(hero) == pytest.approx(0.25)

    match.ruleset._team_states[RED].tech_core_defense = 0.50
    assert match.ruleset._effective_defense(hero) == pytest.approx(0.50)


def test_terrain_defense_damage_event_scoreboard_and_xp_use_final_hp_loss() -> None:
    match = _match()
    target = _robot(match, "tarsgo-infantry-1")
    attacker = _robot(match, "opponent-hero")
    assert match.ruleset._grant_terrain_crossing_buff(target, "launch_ramp")

    before_hp = target.hp
    assert match.apply_damage(target, 20, source_robot=attacker) == 15
    assert target.hp == before_hp - 15
    event = match.current_events[-1]
    assert event.damage == 15

    match.update(0)

    assert match.ruleset.attack_damage_by_team[BLUE] == 15
    assert match.ruleset._progression_by_robot[attacker.id].experience == 60


def test_tunnel_cooling_multiplier_changes_effective_cooling_not_heat_limit() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    match.ruleset._grant_experience(infantry.id, 2200)
    before = match.ruleset._effective_heat_parameters(infantry.id)
    assert (before.heat_limit, before.cooling_per_second) == (72, 20)

    assert match.ruleset._grant_terrain_crossing_buff(infantry, "tunnel")
    after = match.ruleset._effective_heat_parameters(infantry.id)

    assert after.heat_limit == 72
    assert after.cooling_per_second == 40


def test_tunnel_cooling_changes_actual_10hz_heat_cooling() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    match.ruleset._grant_experience(infantry.id, 2200)
    heat = match.ruleset._shooting_heat_by_robot[infantry.id]
    heat.heat = 100
    assert match.ruleset._grant_terrain_crossing_buff(infantry, "tunnel")

    match.ruleset.prepare_combat(match, 0.1)

    assert heat.heat == pytest.approx(96.0)
    assert _terrain_state(match, infantry.id).tunnel_cooling_remaining == pytest.approx(
        119.9
    )


@pytest.mark.parametrize(
    "terrain_type",
    ["launch_ramp", "elevated_ground", "road", "tunnel"],
)
def test_each_terrain_type_grants_300_xp_only_first_time(
    terrain_type: str,
) -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    progression = match.ruleset._progression_by_robot[hero.id]

    assert match.ruleset._grant_terrain_crossing_buff(hero, terrain_type)
    first = progression.experience
    assert first == 300

    if terrain_type == "road":
        match.ruleset._advance_terrain_crossing_timers(15.0)
    assert match.ruleset._grant_terrain_crossing_buff(hero, terrain_type)
    assert progression.experience == first


def test_four_distinct_terrain_types_each_grant_first_300_xp() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    for terrain_type in (
        "launch_ramp",
        "elevated_ground",
        "road",
        "tunnel",
    ):
        if terrain_type == "road":
            _terrain_state(match, hero.id).road_reacquire_remaining = 0
        assert match.ruleset._grant_terrain_crossing_buff(hero, terrain_type)

    progression = match.ruleset._progression_by_robot[hero.id]
    assert progression.experience == 1200
    assert progression.level == 3


def test_terrain_first_xp_respects_existing_level_cap_clamp() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    progression = match.ruleset._progression_by_robot[hero.id]
    match.ruleset._grant_experience(hero.id, 2100)
    assert progression.experience == 2100

    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")

    assert progression.level == 5
    assert progression.experience == 2200


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-engineer", "tarsgo-sentry"],
)
def test_non_progression_ground_robots_receive_buff_without_xp_forwarding(
    robot_id: str,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    hero = _robot(match, "tarsgo-hero")
    hero_before = match.ruleset._progression_by_robot[hero.id].experience

    assert match.ruleset._grant_terrain_crossing_buff(robot, "launch_ramp")

    assert match.ruleset._current_terrain_defense(robot) == pytest.approx(0.25)
    assert hero_before == match.ruleset._progression_by_robot[hero.id].experience
    assert robot.id not in match.ruleset._progression_by_robot


def test_death_clears_active_terrain_buffs_and_sequence_but_preserves_history() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "tunnel")
    lower = _terrain_zones(match, "road")[0]
    _enter(match, hero, lower)
    state = _terrain_state(match, hero.id)
    history_before = set(state.first_acquired_types)
    assert state.sequence.terrain_type == "road"

    hp_before = hero.hp
    assert match.apply_damage(hero, 100000, source_team_id=BLUE) == hp_before
    match.update(0)

    assert not hero.alive
    assert state.standard_defense_remaining == 0
    assert state.tunnel_defense_remaining == 0
    assert state.tunnel_cooling_remaining == 0
    assert state.sequence.terrain_type is None
    assert state.first_acquired_types == history_before


def test_death_history_prevents_duplicate_terrain_xp() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    xp_before = match.ruleset._progression_by_robot[hero.id].experience
    hp_before = hero.hp

    assert match.apply_damage(hero, 100000, source_team_id=BLUE) == hp_before
    match.update(0)
    hero.alive = True
    hero.hp = hero.max_hp

    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    assert match.ruleset._progression_by_robot[hero.id].experience == xp_before


def test_match_reset_clears_all_terrain_state_and_first_acquired_history() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "tunnel")
    assert _terrain_state(match, hero.id).first_acquired_types

    match.reset()

    state = _terrain_state(match, hero.id)
    assert state.standard_defense == 0
    assert state.standard_defense_remaining == 0
    assert state.tunnel_defense_remaining == 0
    assert state.tunnel_cooling_remaining == 0
    assert state.road_reacquire_remaining == 0
    assert state.sequence.terrain_type is None
    assert state.first_acquired_types == set()
    assert state.occupied_rfid_zone_ids == set()


def test_large_dt_expires_all_active_terrain_timers() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "tunnel")
    state = _terrain_state(match, hero.id)

    match.update(121.0)

    assert state.standard_defense_remaining == 0
    assert state.tunnel_defense_remaining == 0
    assert state.tunnel_cooling_remaining == 0
    assert match.ruleset._current_terrain_defense(hero) == 0


def test_display_includes_terrain_defense_and_tunnel_cooling() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "launch_ramp")
    assert match.ruleset._grant_terrain_crossing_buff(hero, "tunnel")

    status = dict(match.ruleset.display_state.robot_statuses)[hero.id]

    assert "DEF 50%" in status
    assert "TDEF 50% 10.0s" in status
    assert "TCool ×2 120.0s" in status


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["terrain_crossing"].__setitem__("first_experience", 299),
        lambda data: data["terrain_crossing"]["road"].__setitem__(
            "sequence_window", 4
        ),
        lambda data: data["terrain_crossing"]["road"].__setitem__(
            "reacquire_cooldown", 14
        ),
        lambda data: data["terrain_crossing"]["tunnel"].__setitem__(
            "cooling_multiplier", 1.5
        ),
        lambda data: data["terrain_crossing"]["tunnel"].__setitem__(
            "cooling_duration", 119
        ),
    ],
)
def test_terrain_config_rejects_non_v140_values(tmp_path: Path, mutate) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))
