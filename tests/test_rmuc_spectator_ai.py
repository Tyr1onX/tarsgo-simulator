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


def test_rmuc_ai_chases_replenishes_and_retreats() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    supply = _zone(match, "red-supply-buff")

    infantry.position = (900.0, 750.0)
    match._rmuc_ai_step(infantry, match.ruleset.display_state)
    assert match.ai_intent(infantry.id) == "前往补给区"
    assert supply.contains(infantry.path[-1])

    hero.position = _center(supply)
    assert match.ruleset.exchange_projectiles(match, hero)
    hero.position = (900.0, 500.0)
    match._rmuc_ai_rng[hero.id] = _FixedRandom(0.0)
    match._rmuc_ai_step(hero, match.ruleset.display_state)
    assert match.ai_intent(hero.id).startswith("追击敌方")
    assert hero.path

    hero.hp = max(1, hero.max_hp // 5)
    match._rmuc_ai_step(hero, match.ruleset.display_state)
    assert match.ai_intent(hero.id) == "回撤"
    assert supply.contains(hero.path[-1])


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


def test_infantry_and_sentry_consider_fortress_after_outpost_loss() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    outpost = next(
        structure
        for structure in match.structures
        if structure.team == sentry.team and structure.type == "outpost"
    )
    outpost.hp = 0
    outpost.alive = False

    found = False
    for value in (0.55, 0.65, 0.75, 0.85, 0.92):
        match._rmuc_ai_rng[sentry.id] = _FixedRandom(value)
        match._rmuc_ai_step(sentry, match.ruleset.display_state)
        if match.ai_intent(sentry.id) == "占领堡垒":
            found = True
            break

    assert found


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