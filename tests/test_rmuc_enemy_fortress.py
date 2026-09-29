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


def _destroy_outpost(match: Match, team_id: str) -> None:
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


def _state(match: Match, robot: Robot, fortress_team_id: str):
    return match.ruleset._enemy_fortress_occupation[
        (robot.id, fortress_team_id)
    ]


def _place_enemy_fortress(
    match: Match,
    robot: Robot,
    fortress_team_id: str,
) -> None:
    robot.position = _center(
        match.ruleset._fortress_zone_by_team[fortress_team_id]
    )


def _neutral(robot: Robot) -> None:
    robot.position = (620.0, 260.0)


def _activate_enemy_fortress(
    match: Match,
    robot: Robot,
    fortress_team_id: str,
    *,
    elapsed: float = 180.0,
) -> None:
    if not match.ruleset._team_states[
        fortress_team_id
    ].outpost_ever_destroyed:
        _destroy_outpost(match, fortress_team_id)
    match.elapsed_time = elapsed
    _place_enemy_fortress(match, robot, fortress_team_id)
    match.update(0)


def _mutated_rules(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "rmuc.yaml"
    path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_enemy_fortress_is_unavailable_before_180_seconds() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 179.999
    _place_enemy_fortress(match, infantry, BLUE)

    match.update(0)

    state = _state(match, infantry, BLUE)
    assert state.occupy_remaining == 0
    assert state.occupation_elapsed == 0
    assert match.ruleset._effective_vulnerability(infantry) == 0


def test_enemy_fortress_is_available_at_exactly_180_seconds() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)

    state = _state(match, infantry, BLUE)
    assert state.occupy_remaining == pytest.approx(2.0)
    assert state.occupation_elapsed == 0
    assert match.ruleset._effective_vulnerability(infantry) == pytest.approx(
        1.0
    )


def test_enemy_fortress_requires_target_outpost_ever_destroyed() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    match.elapsed_time = 180.0
    _place_enemy_fortress(match, infantry, BLUE)

    match.update(0)

    assert not match.ruleset._team_states[BLUE].outpost_ever_destroyed
    assert _state(match, infantry, BLUE).occupy_remaining == 0
    assert match.ruleset._effective_vulnerability(infantry) == 0


def test_rebuilt_target_outpost_does_not_close_enemy_fortress() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match, BLUE)
    outpost = match.ruleset._outpost_by_team[BLUE]
    outpost.alive = True
    outpost.hp = 750
    match.elapsed_time = 180.0
    _place_enemy_fortress(match, infantry, BLUE)

    match.update(0)

    assert match.ruleset._team_states[BLUE].outpost_ever_destroyed
    assert outpost.alive
    assert _state(match, infantry, BLUE).occupy_remaining == pytest.approx(
        2.0
    )


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-hero", "tarsgo-engineer"],
)
def test_hero_and_engineer_cannot_enemy_occupy_fortress(
    robot_id: str,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 180.0
    _place_enemy_fortress(match, robot, BLUE)

    match.update(0)

    assert (robot.id, BLUE) not in match.ruleset._enemy_fortress_occupation
    assert match.ruleset._effective_vulnerability(robot) == 0


@pytest.mark.parametrize(
    "robot_id",
    ["tarsgo-infantry-1", "tarsgo-infantry-2", "tarsgo-sentry"],
)
def test_infantry_and_sentry_can_enemy_occupy_fortress(
    robot_id: str,
) -> None:
    match = _match()
    robot = _robot(match, robot_id)
    _activate_enemy_fortress(match, robot, BLUE)

    assert _state(match, robot, BLUE).occupy_remaining == pytest.approx(2.0)
    assert match.ruleset._effective_vulnerability(robot) == pytest.approx(1.0)


def test_multiple_enemy_robots_keep_independent_occupation_timers() -> None:
    match = _match()
    first = _robot(match, "tarsgo-infantry-1")
    second = _robot(match, "tarsgo-infantry-2")
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 180.0
    _place_enemy_fortress(match, first, BLUE)
    _place_enemy_fortress(match, second, BLUE)

    match.update(5.0)

    assert _state(match, first, BLUE).occupation_elapsed == pytest.approx(5.0)
    assert _state(match, second, BLUE).occupation_elapsed == pytest.approx(5.0)
    assert not match.ruleset._team_states[BLUE].base_armor_deployed


def test_own_fortress_owner_does_not_block_enemy_occupant() -> None:
    match = _match()
    blue_sentry = _robot(match, "opponent-sentry")
    red_infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 180.0
    zone = match.ruleset._fortress_zone_by_team[BLUE]
    blue_sentry.position = _center(zone)
    red_infantry.position = _center(zone)

    match.update(0)

    assert (
        match.ruleset._fortress_state_by_team[BLUE].owner_robot_id
        == blue_sentry.id
    )
    assert _state(match, red_infantry, BLUE).occupy_remaining == pytest.approx(
        2.0
    )
    assert match.ruleset._effective_vulnerability(
        red_infantry
    ) == pytest.approx(1.0)


def test_two_second_release_continues_timer_and_vulnerability() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(5.0)
    assert _state(match, infantry, BLUE).occupation_elapsed == pytest.approx(
        5.0
    )

    _neutral(infantry)
    match.update(1.9)

    state = _state(match, infantry, BLUE)
    assert state.occupy_remaining == pytest.approx(0.1)
    assert state.occupation_elapsed == pytest.approx(6.9)
    assert match.ruleset._effective_vulnerability(infantry) == pytest.approx(
        1.0
    )


def test_occupy_expiration_starts_three_second_retention_and_pauses_timer() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(5.0)
    _neutral(infantry)

    match.update(2.0)

    state = _state(match, infantry, BLUE)
    assert state.occupy_remaining == 0
    assert state.occupation_elapsed == pytest.approx(7.0)
    assert state.retention_remaining == pytest.approx(3.0)
    assert match.ruleset._effective_vulnerability(infantry) == 0

    match.update(2.0)

    assert state.occupation_elapsed == pytest.approx(7.0)
    assert state.retention_remaining == pytest.approx(1.0)


def test_reenter_during_retention_resumes_previous_timer() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(5.0)
    _neutral(infantry)
    match.update(2.0)
    match.update(2.0)

    state = _state(match, infantry, BLUE)
    assert state.occupation_elapsed == pytest.approx(7.0)
    assert state.retention_remaining == pytest.approx(1.0)

    _place_enemy_fortress(match, infantry, BLUE)
    match.update(0)

    assert state.occupy_remaining == pytest.approx(2.0)
    assert state.retention_remaining == 0
    assert state.occupation_elapsed == pytest.approx(7.0)

    match.update(1.0)

    assert state.occupation_elapsed == pytest.approx(8.0)


def test_retention_expiration_resets_accumulated_timer() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(5.0)
    _neutral(infantry)
    match.update(2.0)

    state = _state(match, infantry, BLUE)
    assert state.retention_remaining == pytest.approx(3.0)

    match.update(3.0)

    assert state.retention_remaining == 0
    assert state.occupation_elapsed == 0


def test_large_dt_crosses_release_and_retention_boundaries() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(4.0)
    _neutral(infantry)

    match.update(5.0)

    state = _state(match, infantry, BLUE)
    assert state.occupy_remaining == 0
    assert state.retention_remaining == 0
    assert state.occupation_elapsed == 0


def test_death_ends_occupy_and_starts_full_three_second_retention() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(5.0)
    state = _state(match, infantry, BLUE)
    elapsed_before = state.occupation_elapsed
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
    assert state.occupy_remaining == 0
    assert state.occupation_elapsed == pytest.approx(elapsed_before)
    assert state.retention_remaining == pytest.approx(3.0)
    assert match.ruleset._effective_vulnerability(infantry) == 0


def test_death_retention_pauses_then_expires_accumulated_timer() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(5.0)
    state = _state(match, infantry, BLUE)
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

    match.update(2.9)
    assert state.occupation_elapsed == pytest.approx(5.0)
    assert state.retention_remaining == pytest.approx(0.1)

    match.update(0.1)
    assert state.occupation_elapsed == 0
    assert state.retention_remaining == 0


def test_exact_twenty_seconds_deploys_opponent_base_armor() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)

    match.update(20.0)

    assert _state(match, infantry, BLUE).occupation_elapsed == pytest.approx(
        20.0
    )
    assert match.ruleset._team_states[BLUE].base_armor_deployed


def test_two_robots_do_not_sum_occupation_time() -> None:
    match = _match()
    first = _robot(match, "tarsgo-infantry-1")
    second = _robot(match, "tarsgo-infantry-2")
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 180.0
    _place_enemy_fortress(match, first, BLUE)
    _place_enemy_fortress(match, second, BLUE)

    match.update(10.0)

    assert _state(match, first, BLUE).occupation_elapsed == pytest.approx(10.0)
    assert _state(match, second, BLUE).occupation_elapsed == pytest.approx(10.0)
    assert not match.ruleset._team_states[BLUE].base_armor_deployed

    _neutral(first)
    match.update(10.0)

    assert match.ruleset._team_states[BLUE].base_armor_deployed
    assert _state(match, second, BLUE).occupation_elapsed == pytest.approx(20.0)


def test_frame_crossing_twenty_deploys_armor_only_at_update_end() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    state = _state(match, infantry, BLUE)
    state.occupation_elapsed = 19.8

    assert not match.ruleset._team_states[BLUE].base_armor_deployed
    assert match.ruleset._effective_vulnerability(infantry) == pytest.approx(
        1.0
    )

    match.update(0.5)

    assert state.occupation_elapsed == pytest.approx(20.3)
    assert match.ruleset._team_states[BLUE].base_armor_deployed
    assert match.ruleset._effective_vulnerability(infantry) == 0


def test_fortress_vulnerability_doubles_damage_without_defense() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    hp_before = infantry.hp

    assert match.apply_damage(infantry, 20, source_team_id=BLUE) == 40
    assert infantry.hp == hp_before - 40


def test_fifty_defense_plus_full_vulnerability_gives_one_point_five_multiplier() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.ruleset._team_states[RED].tech_core_defense = 0.50
    hp_before = infantry.hp

    assert match.apply_damage(infantry, 20, source_team_id=BLUE) == 30
    assert infantry.hp == hp_before - 30


def test_vulnerability_damage_keeps_explicit_half_up_rounding() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.ruleset._team_states[RED].tech_core_defense = 0.50
    hp_before = infantry.hp

    assert match.apply_damage(infantry, 1, source_team_id=BLUE) == 2
    assert infantry.hp == hp_before - 2


def test_fortress_vulnerability_only_applies_to_enemy_attack_damage() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    hp_before = infantry.hp

    assert match.apply_damage(infantry, 20) == 20
    assert infantry.hp == hp_before - 20


def test_hp_threshold_armor_deployment_disables_fortress_vulnerability() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    base = match.ruleset._base_by_team[BLUE]
    base.hp = 2020

    assert match.apply_damage(base, 20, source_team_id=RED) == 20
    match.update(0)

    assert base.hp == 2000
    assert match.ruleset._team_states[BLUE].base_armor_deployed
    assert _state(match, infantry, BLUE).occupy_remaining > 0
    assert match.ruleset._effective_vulnerability(infantry) == 0


def test_fortress_triggered_armor_disables_all_current_occupant_vulnerability() -> None:
    match = _match()
    first = _robot(match, "tarsgo-infantry-1")
    second = _robot(match, "tarsgo-infantry-2")
    _destroy_outpost(match, BLUE)
    match.elapsed_time = 180.0
    _place_enemy_fortress(match, first, BLUE)
    _place_enemy_fortress(match, second, BLUE)
    match.update(0)
    _state(match, first, BLUE).occupation_elapsed = 19.0
    _state(match, second, BLUE).occupation_elapsed = 3.0

    match.update(1.0)

    assert match.ruleset._team_states[BLUE].base_armor_deployed
    assert match.ruleset._effective_vulnerability(first) == 0
    assert match.ruleset._effective_vulnerability(second) == 0
    assert _state(match, second, BLUE).occupation_elapsed == pytest.approx(4.0)


def test_fortress_armor_deployment_does_not_mutate_base_resources_or_invincibility() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _destroy_outpost(match, BLUE)
    outpost = match.ruleset._outpost_by_team[BLUE]
    outpost.alive = True
    outpost.hp = 750
    base = match.ruleset._base_by_team[BLUE]
    base.hp = 4500
    state = match.ruleset._team_states[BLUE]
    state.base_virtual_shield = 321
    match.elapsed_time = 180.0
    _place_enemy_fortress(match, infantry, BLUE)
    match.update(0)

    before = (
        base.hp,
        base.max_hp,
        state.base_virtual_shield,
        match.ruleset.can_receive_damage(base),
    )
    match.update(20.0)
    after = (
        base.hp,
        base.max_hp,
        state.base_virtual_shield,
        match.ruleset.can_receive_damage(base),
    )

    assert state.base_armor_deployed
    assert before == (4500, 5000, 321, False)
    assert after == before


def test_display_shows_active_enemy_fortress_vulnerability_and_timer() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(13.4)

    status = dict(match.ruleset.display_state.robot_statuses)[infantry.id]

    assert "EFORT VULN100 T:13.4/20" in status


def test_display_shows_retention_hold_without_vulnerability() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(5.0)
    _neutral(infantry)
    match.update(2.0)
    match.update(0.9)

    status = dict(match.ruleset.display_state.robot_statuses)[infantry.id]

    assert "EFORT HOLD 2.1s" in status
    assert "VULN100" not in status


def test_display_hides_vulnerability_after_base_armor_deployed() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(20.0)

    status = dict(match.ruleset.display_state.robot_statuses)[infantry.id]

    assert "EFORT" in status
    assert "VULN100" not in status


def test_reset_clears_enemy_fortress_occupation_and_base_armor() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-1")
    _activate_enemy_fortress(match, infantry, BLUE)
    match.update(20.0)
    assert match.ruleset._team_states[BLUE].base_armor_deployed

    match.reset()

    assert not match.ruleset._team_states[BLUE].base_armor_deployed
    assert not match.ruleset._team_states[BLUE].outpost_ever_destroyed
    for occupation in match.ruleset._enemy_fortress_occupation.values():
        assert occupation.occupy_remaining == 0
        assert occupation.occupation_elapsed == 0
        assert occupation.retention_remaining == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["fortress_enemy_occupation"].__setitem__(
            "available_after",
            179,
        ),
        lambda data: data["fortress_enemy_occupation"].__setitem__(
            "vulnerability",
            0.75,
        ),
        lambda data: data["fortress_enemy_occupation"].__setitem__(
            "armor_after",
            19,
        ),
        lambda data: data["fortress_enemy_occupation"].__setitem__(
            "retention",
            2,
        ),
        lambda data: data["fortress_enemy_occupation"].__setitem__(
            "eligible_types",
            ["hero", "sentry"],
        ),
    ],
)
def test_enemy_fortress_config_rejects_non_v140_values(
    tmp_path: Path,
    mutate,
) -> None:
    path = _mutated_rules(tmp_path, mutate)

    with pytest.raises(ConfigError):
        RMUC2026RegionalRules(load_rule_document(path))
