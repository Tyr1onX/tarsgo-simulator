from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RMUC_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)
RMUL_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmul-2026-rules-lab.yaml"
)
TRAINING_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "first-steps.yaml"
)


def _match() -> Match:
    return Match.from_scenario(RMUC_SCENARIO, rmuc_spectator_ai=True)


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _zone(match: Match, zone_id: str):
    return next(zone for zone in match.map.zones if zone.id == zone_id)


def _center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


class _FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def test_rmuc_spectator_ai_controls_all_robots_symmetrically() -> None:
    match = _match()

    assert set(match._ai_replan_elapsed) == {robot.id for robot in match.robots}
    assert all(match.is_ai_controlled(robot.id) for robot in match.robots)

    match.update(1.0)

    mirrored_pairs = (
        ("tarsgo-hero", "opponent-hero"),
        ("tarsgo-engineer", "opponent-engineer"),
        ("tarsgo-infantry-1", "opponent-infantry-1"),
        ("tarsgo-infantry-2", "opponent-infantry-2"),
        ("tarsgo-sentry", "opponent-sentry"),
        ("tarsgo-drone", "opponent-drone"),
    )
    for red_id, blue_id in mirrored_pairs:
        assert match.ai_intent(red_id) == match.ai_intent(blue_id)


def test_rmuc_ai_fixed_seed_is_repeatable() -> None:
    first = _match()
    second = _match()

    for _ in range(20):
        first.update(0.5)
        second.update(0.5)

    first_snapshot = [
        (robot.id, robot.position, tuple(robot.path), first.ai_intent(robot.id), robot.hp)
        for robot in first.robots
    ]
    second_snapshot = [
        (robot.id, robot.position, tuple(robot.path), second.ai_intent(robot.id), robot.hp)
        for robot in second.robots
    ]
    assert first_snapshot == second_snapshot


def _candidate_by_key(match: Match, robot, key: str):
    return next(
        candidate
        for candidate in match._rmuc_tactical_candidates(
            robot,
            match.ruleset.display_state,
        )
        if candidate[0] == key
    )


def test_rmuc_ai_replenishes_and_critical_hp_retreats() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    supply = _zone(match, "red-supply-buff")

    infantry.position = (900.0, 750.0)
    match._rmuc_ai_step(infantry, match.ruleset.display_state)
    assert match.ai_intent(infantry.id) == "前往补给区"
    assert supply.contains(infantry.path[-1])

    hero.hp = max(1, hero.max_hp // 5)
    match._rmuc_ai_step(hero, match.ruleset.display_state)
    assert match.ai_intent(hero.id) == "回撤补给"
    assert supply.contains(hero.path[-1])


def test_low_hp_raises_retreat_utility_above_combat_choices() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    side = match._team_side(sentry.team)
    retreat_key = f"zone:supply:{side}"

    assert all(
        candidate[1] != "回撤补给"
        for candidate in match._rmuc_tactical_candidates(
            sentry,
            match.ruleset.display_state,
        )
    )

    sentry.hp = round(sentry.max_hp * 0.40)
    candidates = match._rmuc_tactical_candidates(
        sentry,
        match.ruleset.display_state,
    )
    retreat = next(candidate for candidate in candidates if candidate[0] == retreat_key)
    assert retreat[1] == "回撤补给"
    assert retreat[3] == max(candidate[3] for candidate in candidates)


def test_low_hp_enemy_gets_finish_priority_without_forcing_every_robot() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    target = _robot(match, "opponent-infantry-1")
    target_key = f"robot:{target.id}"

    full = _candidate_by_key(match, sentry, target_key)
    target.hp = max(1, round(target.max_hp * 0.20))
    weak = _candidate_by_key(match, sentry, target_key)

    assert weak[1] == "集火残血目标"
    assert weak[3] > full[3] + 1.0


def test_outpost_then_base_structure_priority_tracks_targetability() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    enemy_outpost = next(
        structure
        for structure in match.structures
        if structure.team != hero.team and structure.type == "outpost"
    )
    enemy_base = next(
        structure
        for structure in match.structures
        if structure.team != hero.team and structure.type == "base"
    )

    before = {
        candidate[0]: candidate
        for candidate in match._rmuc_tactical_candidates(
            hero,
            match.ruleset.display_state,
        )
    }
    assert f"structure:{enemy_outpost.id}" in before
    assert f"structure:{enemy_base.id}" not in before

    enemy_outpost.hp = 0
    enemy_outpost.alive = False
    after = {
        candidate[0]: candidate
        for candidate in match._rmuc_tactical_candidates(
            hero,
            match.ruleset.display_state,
        )
    }
    assert f"structure:{enemy_outpost.id}" not in after
    assert after[f"structure:{enemy_base.id}"][1] == "进攻基地"


def test_engineer_advances_resource_assembly_and_tech_core() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    resource = _zone(match, "red-resource")
    assembly = _zone(match, "red-assembly")

    engineer.position = _center(resource)
    match._rmuc_ai_step(engineer, match.ruleset.display_state)
    assert match.ai_intent(engineer.id) == "获取能量单元"
    assert dict(match.ruleset.display_state.engineer_energy_units)[engineer.id] == 1

    engineer.position = _center(assembly)
    match._rmuc_ai_step(engineer, match.ruleset.display_state)
    assert match.ai_intent(engineer.id) == "装配科技核心"
    tech = {
        team_id: (d1, d2, d3, d4)
        for team_id, _cap, d1, d2, d3, d4, _active, _outside
        in match.ruleset.display_state.tech_core_status
    }
    assert tech[engineer.team][0] == 1


def test_protect_engineer_becomes_real_tactical_choice() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    sentry = _robot(match, "tarsgo-sentry")
    match._ai_intents[engineer.id] = "装配科技核心"

    for enemy in match.robots:
        if enemy.team != sentry.team:
            enemy.alive = False
            enemy.hp = 0
    for structure in match.structures:
        if structure.team != sentry.team:
            structure.alive = False
            structure.hp = 0

    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)
    match._rmuc_ai_step(sentry, match.ruleset.display_state)

    assert match.ai_intent(sentry.id) == "保护工程"
    assert match._ai_target_keys[sentry.id] == f"support:{engineer.id}"
    assert sentry.path


def test_fortress_utility_is_high_but_occupancy_prevents_full_team_pileup() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    outpost = next(
        structure
        for structure in match.structures
        if structure.team == sentry.team and structure.type == "outpost"
    )
    outpost.hp = 0
    outpost.alive = False

    candidates = match._rmuc_tactical_candidates(
        sentry,
        match.ruleset.display_state,
    )
    fortress_key = f"zone:fortress:{match._team_side(sentry.team)}"
    fortress = next(candidate for candidate in candidates if candidate[0] == fortress_key)
    central = next(
        candidate for candidate in candidates if candidate[1] == "前往中央区域"
    )
    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)

    first = match._choose_utility_candidate(sentry, [fortress, central])
    assert first is not None and first[0] == fortress_key

    match._ai_target_keys["tarsgo-infantry-1"] = fortress_key
    match._ai_target_keys["tarsgo-infantry-2"] = fortress_key
    spread = match._choose_utility_candidate(sentry, [fortress, central])
    assert spread is not None and spread[0] != fortress_key


def test_central_zone_is_secondary_goal_when_higher_priorities_disappear() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    for enemy in match.robots:
        if enemy.team != sentry.team:
            enemy.alive = False
            enemy.hp = 0
    for structure in match.structures:
        if structure.team != sentry.team:
            structure.alive = False
            structure.hp = 0

    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)
    match._rmuc_ai_step(sentry, match.ruleset.display_state)

    assert match.ai_intent(sentry.id) == "前往中央区域"
    assert match._ai_target_keys[sentry.id].startswith("zone:central:")


def test_target_stickiness_uses_hysteresis_but_yields_to_clear_priority_jump() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)
    match._ai_target_keys[sentry.id] = "robot:a"
    match._ai_sticky_until[sentry.id] = match.elapsed_time + 1.0

    close = [
        ("robot:a", "追击敌方步兵", (100.0, 100.0), 1.00),
        ("robot:b", "追击敌方英雄", (200.0, 100.0), 1.30),
    ]
    held = match._choose_utility_candidate(sentry, close)
    assert held is not None and held[0] == "robot:a"

    urgent = [
        ("robot:a", "追击敌方步兵", (100.0, 100.0), 1.00),
        ("robot:b", "集火残血目标", (200.0, 100.0), 1.70),
    ]
    switched = match._choose_utility_candidate(sentry, urgent)
    assert switched is not None and switched[0] == "robot:b"

    target_gone = [
        ("robot:b", "追击敌方英雄", (200.0, 100.0), 1.10),
    ]
    forced = match._choose_utility_candidate(sentry, target_gone)
    assert forced is not None and forced[0] == "robot:b"


def test_team_target_occupancy_penalty_spreads_identical_role_choices() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-2")
    match._rmuc_ai_rng[infantry.id] = _FixedRandom(0.5)
    central_key = "zone:central:red"
    choices = [
        (central_key, "前往中央区域", (100.0, 100.0), 2.00),
        ("robot:opponent-hero", "追击敌方英雄", (200.0, 100.0), 1.40),
    ]

    open_choice = match._choose_utility_candidate(infantry, choices)
    assert open_choice is not None and open_choice[0] == central_key

    match._ai_target_keys["tarsgo-infantry-1"] = central_key
    spread_choice = match._choose_utility_candidate(infantry, choices)
    assert spread_choice is not None
    assert spread_choice[0] == "robot:opponent-hero"


def test_role_scores_make_hero_structural_and_sentry_defensive_biases_visible() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    sentry = _robot(match, "tarsgo-sentry")
    enemy_outpost = next(
        structure
        for structure in match.structures
        if structure.team != hero.team and structure.type == "outpost"
    )
    outpost_key = f"structure:{enemy_outpost.id}"

    hero_attack = _candidate_by_key(match, hero, outpost_key)
    infantry_attack = _candidate_by_key(match, infantry, outpost_key)
    assert hero_attack[3] > infantry_attack[3]

    own_outpost = next(
        structure
        for structure in match.structures
        if structure.team == sentry.team and structure.type == "outpost"
    )
    own_outpost.hp = round(own_outpost.max_hp * 0.50)
    sentry_defense = next(
        candidate
        for candidate in match._rmuc_tactical_candidates(
            sentry,
            match.ruleset.display_state,
        )
        if candidate[1] == "防守前哨站"
    )
    infantry_defense = next(
        candidate
        for candidate in match._rmuc_tactical_candidates(
            infantry,
            match.ruleset.display_state,
        )
        if candidate[1] == "防守前哨站"
    )
    assert sentry_defense[3] > infantry_defense[3]


def test_rmuc_ai_intent_is_exposed_in_chinese_ui_and_opponents_are_selectable() -> None:
    pygame = pytest.importorskip("pygame")
    del pygame
    from tarsgo_simulator.desktop import app

    match = _match()
    match.update(1.0)
    labels = app._rmuc_robot_labels(match)
    opponent = _robot(match, "opponent-hero")

    lines = app._selected_unit_lines(match, {opponent.id}, labels)
    assert f"当前 AI 意图  {match.ai_intent(opponent.id)}" in lines
    assert app._select_player_robot(opponent.position, match) == opponent.id
    assert not match.is_player_controlled(opponent.id)
    assert match.is_ai_controlled(opponent.id)


def test_rmuc_long_smoke_does_not_crash() -> None:
    match = _match()
    for _ in range(900):
        match.update(0.1)
    assert match.elapsed_time > 0


@pytest.mark.parametrize("scenario", [TRAINING_SCENARIO, RMUL_SCENARIO])
def test_non_rmuc_smoke_is_unchanged(scenario: Path) -> None:
    match = Match.from_scenario(scenario)
    match.update(0.01)
    assert match.elapsed_time == pytest.approx(0.01)