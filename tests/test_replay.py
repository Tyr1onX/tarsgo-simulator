"""Season-independent determinism and headless replay regression tests."""

import json
import sys

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.replay import cli, run, verify


SCENARIOS = (
    ("configs/scenarios/first-steps.yaml", False),
    ("configs/scenarios/rmul-2026-rules-lab.yaml", False),
    ("configs/scenarios/rmuc-2026-region-rules-lab.yaml", True),
)


def _settings(scenario, spectator_ai=False, **overrides):
    settings = {
        "scenario": scenario,
        "seed": 42,
        "dt": 1.0,
        "max_ticks": 1000,
        "spectator_ai": spectator_ai,
        "inputs": [],
    }
    settings.update(overrides)
    return settings


@pytest.mark.parametrize("scenario,spectator_ai", SCENARIOS)
def test_headless_full_match_replays_identically(scenario, spectator_ai):
    settings = _settings(scenario, spectator_ai)
    first = run(settings)
    assert first == verify(first)
    assert len(first["checkpoints"]) > 2
    assert first["elapsed_time"] > 0


def test_rmuc_reset_reuses_explicit_random_seed():
    match = Match.from_scenario(
        "configs/scenarios/rmuc-2026-region-rules-lab.yaml",
        rmuc_spectator_ai=True,
        seed=19,
    )

    def initial_state():
        rules = match.ruleset
        return (
            rules._small_energy_mechanism_entity.rotation_direction,
            tuple(
                (team, state.outpost_rotation.direction)
                for team, state in sorted(rules._team_states.items())
            ),
            tuple(
                (team, rng.getstate())
                for team, rng in sorted(rules._small_energy_rng_by_team.items())
            ),
            tuple(
                (team, rng.getstate())
                for team, rng in sorted(rules._large_energy_rng_by_team.items())
            ),
            tuple(
                (robot, rng.getstate())
                for robot, rng in sorted(match._rmuc_ai_rng.items())
            ),
            tuple(sorted(rules._large_energy_speed_parameters_by_opportunity.items())),
        )

    first = initial_state()
    match.update(1 / 60)
    match.reset()
    assert initial_state() == first


def test_record_verify_move_input_and_detect_divergence(tmp_path, monkeypatch):
    scenario = "configs/scenarios/first-steps.yaml"
    inputs = [{"tick": 0, "robot_ids": ["tarsgo-infantry-1"], "goal": [230, 120]}]
    input_file = tmp_path / "moves.json"
    trace_file = tmp_path / "trace.json"
    input_file.write_text(json.dumps(inputs), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", [
            "replay", "--record", str(trace_file),
            "--scenario", scenario, "--seed", "17", "--dt", "1",
            "--inputs", str(input_file),
        ],
    )
    cli()
    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    assert trace["settings"]["inputs"] == inputs

    monkeypatch.setattr(sys, "argv", ["replay", "--verify", str(trace_file)])
    cli()
    trace["checkpoints"][1] = "tampered"
    with pytest.raises(ValueError, match="checkpoint 1"):
        verify(trace)


def test_unfinished_headless_match_is_not_reported_as_success():
    with pytest.raises(ValueError, match="did not finish"):
        run(_settings("configs/scenarios/first-steps.yaml", max_ticks=1))
