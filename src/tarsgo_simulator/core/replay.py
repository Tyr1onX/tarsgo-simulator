"""Record and verify deterministic, headless matches using the existing Match state."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from tarsgo_simulator.core.match import Match


def _fingerprint(match: Match) -> str:
    display = match.ruleset.display_state
    state = {
        "time": match.elapsed_time,
        "finished": match.finished,
        "winner": match.winner,
        "robots": [asdict(robot) for robot in match.robots],
        "structures": [asdict(structure) for structure in match.structures],
        "projectiles": [asdict(projectile) for projectile in match.projectiles],
        "impacts": [asdict(impact) for impact in match.projectile_impacts],
        "events": [asdict(event) for event in match.current_events],
        "zones": [asdict(event) for event in match.zone_events],
        "rfid": [asdict(event) for event in match.rfid_read_events],
        "rules": asdict(display) if display is not None else None,
        "report": asdict(match.battle_report()),
        "projectile_diagnostics": match.projectile_diagnostics,
    }
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def run(settings: dict) -> dict:
    """Run to a result or declared timebox; inputs apply before their tick."""
    scenario = Path(settings["scenario"])
    match = Match.from_scenario(
        scenario,
        rmuc_spectator_ai=settings["spectator_ai"],
        seed=settings["seed"],
    )
    commands: dict[int, list[dict]] = {}
    for action in settings["inputs"]:
        tick = action["tick"]
        if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
            raise ValueError(f"Invalid input tick: {tick!r}")
        if set(action) != {"tick", "robot_ids", "goal"}:
            raise ValueError(f"Unsupported replay input: {action!r}")
        commands.setdefault(tick, []).append(action)

    step = settings["dt"]
    if not 0 < step <= match.time_limit:
        raise ValueError("dt must be positive and within the match time limit")
    if settings["max_ticks"] <= 0:
        raise ValueError("max_ticks must be positive")

    checkpoints = [_fingerprint(match)]
    replay_timebox_without_settlement = getattr(
        match.ruleset, "replay_timebox_without_settlement", False
    )
    for tick in range(settings["max_ticks"]):
        for action in commands.get(tick, []):
            if not match.order_group_move(
                action["robot_ids"], tuple(action["goal"])
            ):
                raise ValueError(f"Move rejected at tick {tick}: {action!r}")
        match.update(step)
        checkpoints.append(_fingerprint(match))
        if match.finished:
            break
        if replay_timebox_without_settlement and match.elapsed_time >= match.time_limit:
            break

    if not match.finished and not (
        replay_timebox_without_settlement and match.elapsed_time >= match.time_limit
    ):
        raise ValueError("Match did not finish within max_ticks")
    if any(tick >= len(checkpoints) - 1 for tick in commands):
        raise ValueError("Input scheduled after match finished")
    result = {
        "settings": settings,
        "scenario_sha256": sha256(scenario.read_bytes()).hexdigest(),
        "checkpoints": checkpoints,
        "winner": match.winner,
        "elapsed_time": match.elapsed_time,
    }
    if not match.finished:
        result["result_status"] = "unsettled-timebox"
    return result


def verify(expected: dict) -> dict:
    actual = run(expected["settings"])
    if actual != expected:
        for i, (old, new) in enumerate(
            zip(expected["checkpoints"], actual["checkpoints"])
        ):
            if old != new:
                raise ValueError(f"Replay diverged at checkpoint {i}")
        raise ValueError("Replay metadata, length or final result differs")
    return actual


def cli() -> None:
    parser = argparse.ArgumentParser(description="Headless deterministic match replay")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", type=Path, help="Write a JSON checkpoint trace")
    mode.add_argument("--verify", type=Path, help="Verify an existing trace")
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dt", type=float, default=1 / 60)
    parser.add_argument("--max-ticks", type=int, default=30000)
    parser.add_argument("--spectator-ai", action="store_true")
    parser.add_argument("--inputs", type=Path, help="JSON array of tick-indexed move inputs")
    args = parser.parse_args()

    if args.record is not None:
        if args.scenario is None:
            parser.error("--scenario is required to record")
        settings = {
            "scenario": str(args.scenario),
            "seed": args.seed,
            "dt": args.dt,
            "max_ticks": args.max_ticks,
            "spectator_ai": args.spectator_ai,
            "inputs": json.loads(args.inputs.read_text(encoding="utf-8"))
            if args.inputs else [],
        }
        result = run(settings)
        args.record.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Recorded {len(result['checkpoints']) - 1} ticks: {args.record}")
    else:
        expected = json.loads(args.verify.read_text(encoding="utf-8"))
        result = verify(expected)
        print(f"Verified {len(result['checkpoints']) - 1} ticks: {args.verify}")


if __name__ == "__main__":
    cli()
