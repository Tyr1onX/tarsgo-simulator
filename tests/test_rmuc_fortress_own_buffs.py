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


def _occupy(
    match: Match,
    robot: Robot,
    *,
    team_id: str | None = None,
) -> None:
    zone = match.ruleset._fortress_zone_by_team[team_id or robot.team]
    robot.position = _center(zone)
    match.update(0)


def _leave(match: Match, robot: Robot, dt: float = 0.0) -> None:
    robot.position = (620.0, 260.0)
    match.update(dt)


def _owner(match: Match, team_id: str = RED) -> str | None:
    return match.ruleset._fortress_state_by_team[team_id].owner_robot_id


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_fortress_is_inactive_before_own_outpost_first_destruction() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")

    _occupy(match, infantry)

    assert not match.ruleset._team_states[RED].outpost_ever_destroyed
    assert _owner(match) is None
    assert match.ruleset._current_fortress_defense(infantry) == 0
    assert match.ruleset._fortress_cooling_bonus(infantry) == 0


def test_fortress_activates_after_own_outpost_first_destruction() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)

    _occupy(match, infantry)

    assert _owner(match) == infantry.id
    assert match.ruleset._current_fortress_defense(infantry) == pytest.approx(
        0.50
    )


def test_fortress_stays_enabled_after_outpost_rebuild() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)

    base = match.ruleset._base_by_team[RED]
    assert match.apply_damage(base, 1000, source_team_id=BLUE) == 1000
    match.update(0)
    assert match.ruleset._team_states[RED].outpost_rebuild_opportunities == 1

    rebuild_zone = match.ruleset._rebuild_zone_by_team[RED]
    engineer.position = _center(rebuild_zone)
    match.update(5.0)

    outpost = match.ruleset._outpost_by_team[RED]
    assert outpost.alive
    assert outpost.hp == 750
    assert match.ruleset._team_states[RED].outpost_ever_destroyed

    _occupy(match, infantry)
    assert _owner(match) == infantry.id


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-infantry-1", "tarsgo-sentry"],
)
def test_infantry_and_sentry_can_occupy_own_fortress(robot_id: str) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    _destroy_outpost(match)

    _occupy(match, robot)

    assert _owner(match) == robot.id
    assert match.ruleset._current_fortress_defense(robot) == pytest.approx(
        0.50
    )


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-engineer"],
)
def test_hero_and_engineer_cannot_occupy_own_fortress(robot_id: str) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    _destroy_outpost(match)

    _occupy(match, robot)

    assert _owner(match) is None
    assert match.ruleset._current_fortress_defense(robot) == 0


def test_enemy_robot_has_no_own_fortress_gameplay_effect() -> None:
    match = _match()
    enemy = _robot(match, "opponent-infantry-1")
    _destroy_outpost(match, RED)

    _occupy(match, enemy, team_id=RED)

    assert _owner(match, RED) is None
    assert match.ruleset._current_fortress_defense(enemy) == 0


def test_only_one_same_team_robot_owns_fortress_at_a_time() -> None:
    match = _match()
    first = _robot(match, "tarsgo-infantry-1")
    second = _robot(match, "tarsgo-sentry")
    _destroy_outpost(match)
    zone = match.ruleset._fortress_zone_by_team[RED]

    first.position = _center(zone)
    second.position = _center(zone)
    match.update(0)

    assert _owner(match) == first.id
    assert match.ruleset._current_fortress_defense(first) == pytest.approx(
        0.50
    )
    assert match.ruleset._current_fortress_defense(second) == 0


def test_fortress_owner_release_and_takeover_waits_two_seconds() -> None:
    match = _match()
    first = _robot(match, "tarsgo-infantry-1")
    second = _robot(match, "tarsgo-sentry")
    _destroy_outpost(match)
    _occupy(match, first)
    zone = match.ruleset._fortress_zone_by_team[RED]

    first.position = (620.0, 260.0)
    second.position = _center(zone)
    match.update(1.9)

    state = match.ruleset._fortress_state_by_team[RED]
    assert state.owner_robot_id == first.id
    assert state.release_remaining == pytest.approx(0.1)
    assert match.ruleset._current_fortress_defense(first) == pytest.approx(
        0.50
    )
    assert match.ruleset._current_fortress_defense(second) == 0

    match.update(0.1)

    assert state.owner_robot_id == second.id
    assert state.release_remaining == pytest.approx(2.0)
    assert match.ruleset._current_fortress_defense(first) == 0
    assert match.ruleset._current_fortress_defense(second) == pytest.approx(
        0.50
    )


def test_returning_owner_refreshes_fortress_release_timer() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)

    _leave(match, infantry, 1.5)
    state = match.ruleset._fortress_state_by_team[RED]
    assert state.release_remaining == pytest.approx(0.5)

    infantry.position = _center(match.ruleset._fortress_zone_by_team[RED])
    match.update(0)

    assert state.owner_robot_id == infantry.id
    assert state.release_remaining == pytest.approx(2.0)


def test_fortress_defense_uses_max_with_other_defense_sources() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    match.ruleset._team_states[RED].tech_core_defense = 0.25
    assert match.ruleset._grant_terrain_crossing_buff(
        infantry,
        "launch_ramp",
    )
    _occupy(match, infantry)

    assert match.ruleset._effective_defense(infantry) == pytest.approx(0.50)

    match.ruleset._team_states[RED].tech_core_defense = 0.50
    assert match.ruleset._effective_defense(infantry) == pytest.approx(0.50)


def test_fortress_defense_reduces_actual_enemy_damage() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    hp_before = infantry.hp

    assert match.apply_damage(infantry, 20, source_team_id=BLUE) == 10
    assert infantry.hp == hp_before - 10


@pytest.mark.parametrize(
    ("base_hp", "expected_bonus"),
    [
        (5000, 0),
        (4960, 1),
        (2000, 75),
        (1000, 75),
    ],
)
def test_fortress_cooling_bonus_uses_floor_delta_over_40_and_cap(
    base_hp: int,
    expected_bonus: int,
) -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    base = match.ruleset._base_by_team[RED]
    base.hp = base_hp

    assert match.ruleset._fortress_cooling_bonus(infantry) == expected_bonus


def test_fortress_cooling_reads_base_hp_dynamically() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    base = match.ruleset._base_by_team[RED]

    base.hp = 4800
    assert match.ruleset._fortress_cooling_bonus(infantry) == 5

    base.hp = 4000
    assert match.ruleset._fortress_cooling_bonus(infantry) == 25

    base.hp = 5000
    assert match.ruleset._fortress_cooling_bonus(infantry) == 0


def test_d4_base_heal_immediately_reduces_fortress_cooling_bonus() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    base = match.ruleset._base_by_team[RED]
    base.hp = 3000

    assert match.ruleset._fortress_cooling_bonus(infantry) == 50

    match.ruleset._apply_tech_core_first_rewards(RED, 4)

    assert base.hp == 5000
    assert base.max_hp == 5000
    assert match.ruleset._fortress_cooling_bonus(infantry) == 0


def test_virtual_shield_does_not_count_toward_fortress_delta() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    base = match.ruleset._base_by_team[RED]
    base.hp = 5000
    match.ruleset._team_states[RED].base_virtual_shield = 2000

    assert match.ruleset._fortress_cooling_bonus(infantry) == 0


def test_fortress_and_tunnel_cooling_take_max_final_result_not_sum() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset._grant_experience(infantry.id, 2200)
    base = match.ruleset._base_by_team[RED]
    base.hp = 2000
    assert match.ruleset._grant_terrain_crossing_buff(infantry, "tunnel")

    parameters = match.ruleset._effective_heat_parameters(infantry.id)

    assert parameters.heat_limit == 72
    assert parameters.cooling_per_second == 95


def test_tunnel_cooling_wins_when_multiplier_result_is_higher() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset._grant_experience(infantry.id, 2200)
    base = match.ruleset._base_by_team[RED]
    base.hp = 4600
    assert match.ruleset._grant_terrain_crossing_buff(infantry, "tunnel")

    parameters = match.ruleset._effective_heat_parameters(infantry.id)

    assert match.ruleset._fortress_cooling_bonus(infantry) == 10
    assert parameters.cooling_per_second == 40


def test_fortress_cooling_changes_actual_10hz_heat_cooling() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset._grant_experience(infantry.id, 2200)
    match.ruleset._base_by_team[RED].hp = 2000
    heat = match.ruleset._shooting_heat_by_robot[infantry.id]
    heat.heat = 100

    match.ruleset.prepare_combat(match, 0.1)

    assert (
        match.ruleset._effective_heat_parameters(
            infantry.id
        ).cooling_per_second
        == 95
    )
    assert heat.heat == pytest.approx(90.5)


def test_fortress_cooling_does_not_change_heat_limit_or_q2() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    base = match.ruleset._base_by_team[RED]
    base.hp = 2000

    before_limit = match.ruleset._effective_heat_parameters(
        infantry.id
    ).heat_limit
    parameters = match.ruleset._effective_heat_parameters(infantry.id)

    assert parameters.heat_limit == before_limit == 40
    assert parameters.permanent_threshold == 140
    assert parameters.cooling_per_second == 87


def test_fortress_defense_and_cooling_expire_together_after_release() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset._base_by_team[RED].hp = 4600

    _leave(match, infantry, 1.9)

    assert _owner(match) == infantry.id
    assert match.ruleset._current_fortress_defense(infantry) == pytest.approx(
        0.50
    )
    assert match.ruleset._fortress_cooling_bonus(infantry) == 10

    match.update(0.1)

    assert _owner(match) is None
    assert match.ruleset._current_fortress_defense(infantry) == 0
    assert match.ruleset._fortress_cooling_bonus(infantry) == 0


def test_owner_death_clears_fortress_immediately_without_waiting_release() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
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

    state = match.ruleset._fortress_state_by_team[RED]
    assert not infantry.alive
    assert state.owner_robot_id is None
    assert state.release_remaining == 0


def test_reset_clears_fortress_owner_and_disables_until_new_destruction() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    assert _owner(match) == infantry.id

    match.reset()

    state = match.ruleset._fortress_state_by_team[RED]
    assert state.owner_robot_id is None
    assert state.release_remaining == 0
    assert not match.ruleset._team_states[RED].outpost_ever_destroyed


def test_display_includes_fortress_occupant_status() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    _occupy(match, infantry)
    match.ruleset._base_by_team[RED].hp = 3520

    status = dict(match.ruleset.display_state.robot_statuses)[infantry.id]

    assert "DEF 50%" in status
    assert "FORT DEF50 FC:+37" in status


def test_fortress_zone_interrupts_active_terrain_crossing_sequence() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match)
    road_lower, road_upper = (
        match.ruleset._terrain_zones_by_side_and_type["red"]["road"]
    )

    infantry.position = _center(road_lower)
    match.update(0)
    infantry.position = (620.0, 260.0)
    match.update(0)
    infantry.position = _center(match.ruleset._fortress_zone_by_team[RED])
    match.update(0)
    infantry.position = (620.0, 260.0)
    match.update(0)
    infantry.position = _center(road_upper)
    match.update(0)

    terrain = match.ruleset._terrain_crossing_by_robot[infantry.id]
    assert "road" not in terrain.first_acquired_types


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["fortress_own_buff"].__setitem__("defense", 0.25),
        lambda data: data["fortress_own_buff"].__setitem__(
            "cooling_hp_step",
            39,
        ),
        lambda data: data["fortress_own_buff"].__setitem__("cooling_cap", 74),
        lambda data: data["fortress_own_buff"].__setitem__(
            "eligible_types",
            ["hero", "sentry"],
        ),
    ],
)
def test_fortress_config_rejects_non_v140_values(
    tmp_path: Path,
    mutate,
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))
