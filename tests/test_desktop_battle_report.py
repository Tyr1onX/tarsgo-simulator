import importlib
from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "configs/scenarios/rmuc-2026-region-rules-lab.yaml"
OTHER_SCENARIOS = (
    ROOT / "configs/scenarios/first-steps.yaml",
    ROOT / "configs/scenarios/rmul-2026-rules-lab.yaml",
)


def test_finished_match_renders_battle_report_over_the_final_frame() -> None:
    app = importlib.import_module("tarsgo_simulator.desktop.app")
    pygame = importlib.import_module("pygame")
    pygame.font.init()
    match = Match.from_scenario(SCENARIO)
    attacker = next(robot for robot in match.robots if robot.id == "tarsgo-hero")
    victim = next(robot for robot in match.robots if robot.id == "opponent-infantry-1")
    damage = match.apply_damage(victim, 35, source_robot=attacker)
    assert damage > 0
    match.elapsed_time = 172.4
    match.winner = attacker.team
    match.finished = True

    screen = pygame.Surface(app.WINDOW_SIZE)
    screen.fill((0, 0, 0))
    app._draw_battle_report(
        screen,
        pygame.font.Font(None, 25),
        pygame.font.Font(None, 18),
        app.ui_font(12),
        match,
    )

    pixels = pygame.image.tostring(screen, "RGB")
    assert len(set(pixels)) > 20
    report = match.battle_report()
    assert report.elapsed_seconds == pytest.approx(172.4)
    assert report.winner_id == attacker.team
    assert next(item for item in report.robots if item.robot_id == attacker.id).damage_dealt == damage


def test_finished_reports_render_in_training_and_rmul_without_level_state() -> None:
    app = importlib.import_module("tarsgo_simulator.desktop.app")
    pygame = importlib.import_module("pygame")
    pygame.font.init()
    for scenario in OTHER_SCENARIOS:
        match = Match.from_scenario(scenario)
        match.finished = True
        match.winner = next(iter(match.config.scenario.teams.values())).team_id
        screen = pygame.Surface(app.WINDOW_SIZE)
        app._draw_battle_report(
            screen,
            pygame.font.Font(None, 25),
            pygame.font.Font(None, 18),
            app.ui_font(12),
            match,
        )
        assert all(item.level is None for item in match.battle_report().robots)
        assert all(item.experience is None for item in match.battle_report().robots)
