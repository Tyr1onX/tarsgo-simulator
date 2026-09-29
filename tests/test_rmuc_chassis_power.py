from pathlib import Path

import pytest
import yaml

from tarsgo_simulator.core.config import ConfigError, load_match_config, load_rule_document
from tarsgo_simulator.core.match import Match
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
        robot.path.clear()
    return match


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _chassis(match: Match, robot_id: str):
    return match.ruleset._chassis_power_by_robot[robot_id]


def _path(robot, dx: float = 100.0) -> None:
    robot.path = [(robot.position[0] + dx, robot.position[1])]


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_initial_chassis_state_is_full_for_all_ground_robots() -> None:
    match = _match()

    assert set(match.ruleset._chassis_power_by_robot) == {
        robot.id for robot in match.robots
    }
    for state in match.ruleset._chassis_power_by_robot.values():
        assert state.buffer_energy == 60
        assert state.power_off_remaining == 0
        assert not state.blocked_this_frame
    assert match.ruleset._chassis_power_accumulator == 0
    assert set(match.ruleset._current_synthetic_power_by_robot.values()) == {0.0}


def test_default_effective_power_limits() -> None:
    match = _match()

    assert match.ruleset._effective_chassis_power_limit("tarsgo-hero") == 50
    assert (
        match.ruleset._effective_chassis_power_limit("tarsgo-infantry-1")
        == 45
    )
    assert match.ruleset._effective_chassis_power_limit("tarsgo-engineer") == 120
    assert match.ruleset._effective_chassis_power_limit("tarsgo-sentry") == 100


def test_effective_buffer_max_is_currently_fixed_sixty() -> None:
    match = _match()

    for robot in match.robots:
        assert match.ruleset._effective_buffer_energy_max(robot.id) == 60


def test_stationary_full_buffer_stays_full() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")

    match.ruleset.prepare_movement(match, 2.0)

    assert _chassis(match, hero.id).buffer_energy == 60
    assert match.ruleset._current_synthetic_power_by_robot[hero.id] == 0


@pytest.mark.parametrize(
    ("robot_id", "limit", "power"),
    [
        ("tarsgo-hero", 50, 55),
        ("tarsgo-infantry-1", 45, 50),
        ("tarsgo-engineer", 120, 125),
        ("tarsgo-sentry", 100, 105),
    ],
)
def test_path_intent_uses_dynamic_limit_plus_five(
    robot_id: str,
    limit: float,
    power: float,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    _path(robot)

    match.ruleset.prepare_movement(match, 0.1)

    assert match.ruleset._effective_chassis_power_limit(robot_id) == limit
    assert match.ruleset._current_synthetic_power_by_robot[robot_id] == power
    assert _chassis(match, robot_id).buffer_energy == pytest.approx(59.5)


def test_stationary_recharge_uses_same_official_formula() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _chassis(match, hero.id)
    state.buffer_energy = 30

    match.ruleset.prepare_movement(match, 0.1)

    assert state.buffer_energy == pytest.approx(35.0)
    assert match.ruleset._current_synthetic_power_by_robot[hero.id] == 0


def test_stationary_recharge_caps_at_sixty() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _chassis(match, hero.id)
    state.buffer_energy = 59

    match.ruleset.prepare_movement(match, 1.0)

    assert state.buffer_energy == 60


def test_chassis_power_partial_tick_is_retained() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)

    match.ruleset.prepare_movement(match, 0.09)
    assert _chassis(match, hero.id).buffer_energy == 60
    assert match.ruleset._chassis_power_accumulator == pytest.approx(0.09)

    match.ruleset.prepare_movement(match, 0.01)
    assert _chassis(match, hero.id).buffer_energy == pytest.approx(59.5)
    assert match.ruleset._chassis_power_accumulator == pytest.approx(0.0)


def test_chassis_power_large_dt_runs_every_full_tick() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)

    match.ruleset.prepare_movement(match, 0.35)

    assert _chassis(match, hero.id).buffer_energy == pytest.approx(58.5)
    assert match.ruleset._chassis_power_accumulator == pytest.approx(0.05)


def test_twelve_seconds_continuous_pathing_depletes_buffer_and_triggers_off() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)

    match.ruleset.prepare_movement(match, 12.0)

    state = _chassis(match, hero.id)
    assert state.buffer_energy == 0
    assert state.power_off_remaining == pytest.approx(5.0)
    assert state.blocked_this_frame
    assert not match.ruleset.can_move(hero)


def test_zero_buffer_stationary_recharges_without_retriggering_power_off() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _chassis(match, hero.id)
    state.buffer_energy = 0

    match.ruleset.prepare_movement(match, 0.1)

    assert state.buffer_energy == pytest.approx(5.0)
    assert state.power_off_remaining == 0
    assert not state.blocked_this_frame


def test_triggered_power_off_preserves_path() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)
    original_path = list(hero.path)
    state = _chassis(match, hero.id)
    state.buffer_energy = 0.5

    match.ruleset.prepare_movement(match, 0.1)

    assert state.power_off_remaining == 5
    assert hero.path == original_path
    assert not match.ruleset.can_move(hero)


def test_power_off_blocks_actual_movement_without_clearing_path() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.speed = 100
    _path(hero)
    original_position = hero.position
    original_path = list(hero.path)
    state = _chassis(match, hero.id)
    state.buffer_energy = 0.5

    match.update(0.1)

    assert hero.position == original_position
    assert hero.path == original_path
    assert state.power_off_remaining == 5


def test_new_move_order_is_accepted_while_powered_off() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _chassis(match, hero.id)
    state.power_off_remaining = 3.0
    state.blocked_this_frame = True
    old_position = hero.position

    goal = (hero.position[0] + 200, hero.position[1] + 100)
    assert match.order_move(hero.id, goal)
    assert hero.path

    hero.speed = 100
    match.update(0.1)

    assert hero.position == old_position
    assert hero.path


def test_power_off_expiry_resumes_movement_on_next_frame_only() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.speed = 100
    _path(hero, 300)
    state = _chassis(match, hero.id)
    state.buffer_energy = 10
    state.power_off_remaining = 0.05
    before = hero.position

    match.update(0.1)

    assert state.power_off_remaining == 0
    assert state.blocked_this_frame
    assert hero.position == before

    match.update(0.01)

    assert not state.blocked_this_frame
    assert hero.position != before


def test_trigger_on_late_tick_blocks_entire_frame_conservatively() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    hero.speed = 100
    _path(hero, 300)
    state = _chassis(match, hero.id)
    state.buffer_energy = 1.0
    before = hero.position

    match.update(0.35)

    assert state.power_off_remaining > 0
    assert state.blocked_this_frame
    assert hero.position == before
    assert hero.path


def test_power_off_ticks_use_zero_power_and_recharge_buffer() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)
    state = _chassis(match, hero.id)
    state.buffer_energy = 0
    state.power_off_remaining = 5

    match.ruleset.prepare_movement(match, 0.1)

    assert state.buffer_energy == pytest.approx(5.0)
    assert state.power_off_remaining == pytest.approx(4.9)
    assert state.blocked_this_frame
    assert match.ruleset._current_synthetic_power_by_robot[hero.id] == 0


def test_five_second_power_off_recharges_to_cap() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)
    state = _chassis(match, hero.id)
    state.buffer_energy = 0
    state.power_off_remaining = 5

    match.ruleset.prepare_movement(match, 5.0)

    assert state.buffer_energy == 60
    assert state.power_off_remaining == 0
    assert state.blocked_this_frame


def test_hero_level_up_changes_limit_and_synthetic_power_not_buffer() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)
    state = _chassis(match, hero.id)
    state.buffer_energy = 20

    assert match.ruleset._effective_chassis_power_limit(hero.id) == 50
    assert match.ruleset._synthetic_chassis_power(hero, state) == 55

    match.ruleset._grant_experience(hero.id, 550)

    assert match.ruleset._effective_chassis_power_limit(hero.id) == 55
    assert match.ruleset._synthetic_chassis_power(hero, state) == 60
    assert state.buffer_energy == 20


def test_infantry_level_up_changes_limit_and_synthetic_power() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _path(infantry)
    state = _chassis(match, infantry.id)

    assert match.ruleset._effective_chassis_power_limit(infantry.id) == 45
    assert match.ruleset._synthetic_chassis_power(infantry, state) == 50

    match.ruleset._grant_experience(infantry.id, 550)

    assert match.ruleset._effective_chassis_power_limit(infantry.id) == 50
    assert match.ruleset._synthetic_chassis_power(infantry, state) == 55


def test_level_up_does_not_clear_existing_power_off() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _chassis(match, hero.id)
    state.power_off_remaining = 3

    match.ruleset._grant_experience(hero.id, 550)

    assert state.power_off_remaining == 3
    assert match.ruleset._effective_chassis_power_limit(hero.id) == 55


@pytest.mark.parametrize(
    "robot_id",
    [
        "tarsgo-hero",
        "tarsgo-engineer",
        "tarsgo-infantry-1",
        "tarsgo-sentry",
    ],
)
def test_death_resets_buffer_and_power_off(robot_id: str) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    state = _chassis(match, robot_id)
    state.buffer_energy = 10
    state.power_off_remaining = 3
    state.blocked_this_frame = True

    assert match.apply_damage(robot, robot.hp, source_team_id=BLUE) > 0
    match.update(0)

    assert state.buffer_energy == 60
    assert state.power_off_remaining == 0
    assert not state.blocked_this_frame
    assert match.ruleset._current_synthetic_power_by_robot[robot_id] == 0


def test_death_buffer_reset_preserves_projectile_allowance_and_heat_semantics() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    heat = match.ruleset._shooting_heat_by_robot[hero.id]
    chassis = _chassis(match, hero.id)
    allowance.allowed = 7
    heat.heat = 200
    heat.permanently_locked = True
    chassis.buffer_energy = 5
    chassis.power_off_remaining = 2

    assert match.apply_damage(hero, hero.hp, source_team_id=BLUE) == 150
    match.update(0)

    assert allowance.allowed == 7
    assert heat.heat == 0
    assert heat.permanently_locked
    assert chassis.buffer_energy == 60
    assert chassis.power_off_remaining == 0


def test_power_off_does_not_block_launcher() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    match.ruleset._projectile_allowance_by_robot[hero.id].allowed = 1
    chassis = _chassis(match, hero.id)
    chassis.power_off_remaining = 3
    chassis.blocked_this_frame = True

    assert not match.ruleset.can_move(hero)
    assert match.ruleset.can_attack(hero)


def test_power_off_does_not_modify_economy_or_projectile_state() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    economy_before = match.ruleset._economy_by_team[RED].coins
    purchase_before = match.ruleset._projectile_purchase_by_team[RED].purchased_42mm
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    allowance.allowed = 3
    pending_before = list(allowance.pending_remote_deliveries)
    chassis = _chassis(match, hero.id)
    chassis.power_off_remaining = 1

    match.ruleset.prepare_movement(match, 0.5)

    assert match.ruleset._economy_by_team[RED].coins == economy_before
    assert match.ruleset._projectile_purchase_by_team[RED].purchased_42mm == purchase_before
    assert allowance.allowed == 3
    assert allowance.pending_remote_deliveries == pending_before


def test_power_off_does_not_reset_disengage_timer() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    allowance = match.ruleset._projectile_allowance_by_robot[hero.id]
    allowance.disengaged_elapsed = 2
    chassis = _chassis(match, hero.id)
    chassis.power_off_remaining = 1

    match.update(0.5)

    assert allowance.disengaged_elapsed == pytest.approx(2.5)


def test_engineer_power_off_does_not_cancel_active_tech_core_attempt_inside_zone() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    engineer.position = (
        match.ruleset._resource_zone_by_team[RED].x
        + match.ruleset._resource_zone_by_team[RED].width / 2,
        match.ruleset._resource_zone_by_team[RED].y
        + match.ruleset._resource_zone_by_team[RED].height / 2,
    )
    assert match.ruleset.pickup_energy_unit(match, engineer)
    assembly = match.ruleset._assembly_zone_by_team[RED]
    engineer.position = (
        assembly.x + assembly.width / 2,
        assembly.y + assembly.height / 2,
    )
    assert match.ruleset.start_tech_core_assembly(match, engineer, 1)
    chassis = _chassis(match, engineer.id)
    chassis.power_off_remaining = 3
    chassis.blocked_this_frame = True

    match.update(1.0)

    assert match.ruleset._tech_core_by_team[RED].active_attempt is not None


def test_powered_off_sentry_can_claim_pending_supply_when_already_inside_zone() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    supply = match.ruleset._supply_buff_zone_by_team[RED]
    sentry.position = (
        supply.x + supply.width / 2,
        supply.y + supply.height / 2,
    )
    match.ruleset._projectile_purchase_by_team[RED].pending_sentry_supply = 100
    chassis = _chassis(match, sentry.id)
    chassis.power_off_remaining = 3

    match.update(0)

    assert match.ruleset._projectile_allowance_by_robot[sentry.id].allowed == 400
    assert match.ruleset._projectile_purchase_by_team[RED].pending_sentry_supply == 0


def test_powered_off_robot_remains_collision_blocker() -> None:
    match = _match()
    blocker = _robot(match, "tarsgo-hero")
    mover = _robot(match, "tarsgo-engineer")
    blocker.position = (1000.0, 750.0)
    mover.position = (940.0, 750.0)
    blocker.path.clear()
    mover.path = [(1060.0, 750.0)]
    mover.speed = 600
    blocker_state = _chassis(match, blocker.id)
    blocker_state.power_off_remaining = 3
    blocker_state.blocked_this_frame = True

    before = mover.position
    match.update(0.1)

    assert blocker.position == (1000.0, 750.0)
    assert mover.position == before


def test_display_state_reuses_robot_chassis_power_with_dynamic_limit() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _chassis(match, hero.id)
    state.buffer_energy = 42
    _path(hero)
    match.ruleset.prepare_movement(match, 0)

    display = {
        robot_id: (buffer, maximum, power, limit, off)
        for robot_id, buffer, maximum, power, limit, off
        in match.ruleset.display_state.robot_chassis_power
    }

    assert display[hero.id] == (42, 60, 55, 50, 0)
    assert display["tarsgo-engineer"] == (60, 60, 0, 120, 0)
    assert len(display) == len(match.robots)


def test_reset_restores_chassis_state_and_accumulator() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    state = _chassis(match, hero.id)
    state.buffer_energy = 1
    state.power_off_remaining = 4
    state.blocked_this_frame = True
    match.ruleset._chassis_power_accumulator = 0.07

    match.reset()

    for reset_state in match.ruleset._chassis_power_by_robot.values():
        assert reset_state.buffer_energy == 60
        assert reset_state.power_off_remaining == 0
        assert not reset_state.blocked_this_frame
    assert match.ruleset._chassis_power_accumulator == 0
    assert set(match.ruleset._current_synthetic_power_by_robot.values()) == {0.0}


def test_heat_and_chassis_accumulators_are_independent() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    _path(hero)
    match.ruleset._shooting_heat_by_robot[hero.id].heat = 100

    match.ruleset.prepare_movement(match, 0.09)
    match.ruleset.prepare_combat(match, 0.04)

    assert match.ruleset._chassis_power_accumulator == pytest.approx(0.09)
    assert match.ruleset._heat_cooling_accumulator == pytest.approx(0.04)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["chassis_power"].__setitem__("detection_hz", 9),
        lambda data: data["chassis_power"].__setitem__("buffer_energy_max", 59),
        lambda data: data["chassis_power"].__setitem__("power_off_duration", 4),
        lambda data: data["chassis_power"]["lab_power_demand"].__setitem__(
            "stationary", 1
        ),
        lambda data: data["chassis_power"]["lab_power_demand"].__setitem__(
            "moving_over_limit", 4
        ),
    ],
)
def test_chassis_power_config_rejects_non_v140_or_non_lab_values(
    tmp_path: Path,
    mutate,
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))
