"""Measure live RMUC frame pacing and presentation hot paths.

Run from the repository root with the desktop display available:
    .venv/bin/python tools/benchmark_rmuc_frame_pacing.py --frames 3600

The simulator opens its normal 1100x780 window and closes after the requested
sample. This is a diagnostic utility; it does not change game rules or assets.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import time

import pygame

from tarsgo_simulator.core import match as match_module
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.pathfinding import IncrementalAStar
from tarsgo_simulator.desktop import app
from tarsgo_simulator.desktop.assets import (
    ASSET_MANAGER,
    quantize_transform_angle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = (
    ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
)


class Measurements:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = {}
        self.counts: dict[str, int] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.asset_render_depth = 0
        self.current_update_ai_ns = 0
        self.matches: list[Match] = []
        self.search_started_ns: dict[IncrementalAStar, int] = {}
        self.search_cpu_ns: dict[IncrementalAStar, int] = {}
        self.completed_searches: set[IncrementalAStar] = set()

    def add(self, key: str, elapsed_ns: int) -> None:
        self.samples.setdefault(key, []).append(elapsed_ns / 1_000_000)
        self.counts[key] = self.counts.get(key, 0) + 1


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0}
    return {
        "mean_ms": statistics.fmean(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": max(values),
    }


def _timed(measurements: Measurements, owner, name: str, key: str):
    original = getattr(owner, name)

    def wrapper(*args, **kwargs):
        started = time.perf_counter_ns()
        try:
            return original(*args, **kwargs)
        finally:
            measurements.add(key, time.perf_counter_ns() - started)

    setattr(owner, name, wrapper)
    return lambda: setattr(owner, name, original)


def _install_instrumentation(measurements: Measurements, frame_count: int, fps: int):
    restorers = []

    def timed_update(self, dt):
        measurements.current_update_ai_ns = 0
        started = time.perf_counter_ns()
        try:
            return original_update(self, dt)
        finally:
            elapsed = time.perf_counter_ns() - started
            measurements.add("update_total", elapsed)
            measurements.add(
                "update_without_ai",
                max(0, elapsed - measurements.current_update_ai_ns),
            )

    original_update = Match.update
    Match.update = timed_update
    restorers.append(lambda: setattr(Match, "update", original_update))

    original_ai = Match._update_ai

    def timed_ai(self, dt):
        started = time.perf_counter_ns()
        try:
            return original_ai(self, dt)
        finally:
            elapsed = time.perf_counter_ns() - started
            measurements.current_update_ai_ns += elapsed
            measurements.add("ai_update", elapsed)

    Match._update_ai = timed_ai
    restorers.append(lambda: setattr(Match, "_update_ai", original_ai))

    original_match_init = Match.__init__

    def tracked_match_init(self, *args, **kwargs):
        original_match_init(self, *args, **kwargs)
        measurements.matches.append(self)

    Match.__init__ = tracked_match_init
    restorers.append(lambda: setattr(Match, "__init__", original_match_init))

    original_path_service = Match._advance_path_requests

    def timed_path_service(self):
        started = time.perf_counter_ns()
        try:
            return original_path_service(self)
        finally:
            measurements.add("path_budget_service", time.perf_counter_ns() - started)

    Match._advance_path_requests = timed_path_service
    restorers.append(
        lambda: setattr(Match, "_advance_path_requests", original_path_service)
    )

    original_advance = IncrementalAStar.advance

    def timed_advance(self, work_budget):
        measurements.search_started_ns.setdefault(self, time.perf_counter_ns())
        started = time.perf_counter_ns()
        try:
            return original_advance(self, work_budget)
        finally:
            elapsed = time.perf_counter_ns() - started
            measurements.search_cpu_ns[self] = (
                measurements.search_cpu_ns.get(self, 0) + elapsed
            )
            measurements.add("path_search_slice", elapsed)
            if self.done and self not in measurements.completed_searches:
                measurements.completed_searches.add(self)
                measurements.add(
                    "astar_search_cpu",
                    measurements.search_cpu_ns[self],
                )
                measurements.add(
                    "astar_search_wall",
                    time.perf_counter_ns()
                    - measurements.search_started_ns[self],
                )

    IncrementalAStar.advance = timed_advance
    restorers.append(lambda: setattr(IncrementalAStar, "advance", original_advance))

    for name, key in (
        ("_draw", "render_draw"),
        ("_draw_rmuc_battlefield", "static_battlefield"),
        ("_draw_rmuc_field_regions", "static_regions"),
        ("_draw_rmuc_terrain", "static_terrain"),
        ("_draw_rmuc_zone", "dynamic_zone_overlay"),
        ("_draw_rmuc_team_led_overlay", "led_overlay"),
        ("_draw_outpost_rotor", "outpost_rotor"),
    ):
        restorers.append(_timed(measurements, app, name, key))

    original_path = match_module.find_path

    def timed_path(*args, **kwargs):
        started = time.perf_counter_ns()
        try:
            return original_path(*args, **kwargs)
        finally:
            measurements.add("pathfinding", time.perf_counter_ns() - started)

    match_module.find_path = timed_path
    restorers.append(lambda: setattr(match_module, "find_path", original_path))

    original_render = ASSET_MANAGER.render

    def timed_asset_render(self, relative_path, *, size=None, angle=0.0, tint=None, fallback=None):
        key = self._relative_key(relative_path)
        normalized_size = None if size is None else tuple(int(value) for value in size)
        normalized_angle = quantize_transform_angle(angle)
        normalized_tint = None if tint is None else tuple(int(c) for c in tint)
        transform_key = (key, normalized_size, normalized_angle, normalized_tint)
        if transform_key in self._transform_cache:
            measurements.cache_hits += 1
        else:
            measurements.cache_misses += 1
        measurements.asset_render_depth += 1
        started = time.perf_counter_ns()
        try:
            return original_render(
                relative_path,
                size=size,
                angle=angle,
                tint=tint,
                fallback=fallback,
            )
        finally:
            measurements.asset_render_depth -= 1
            measurements.add("asset_render", time.perf_counter_ns() - started)

    ASSET_MANAGER.render = timed_asset_render.__get__(ASSET_MANAGER, type(ASSET_MANAGER))
    restorers.append(lambda: setattr(ASSET_MANAGER, "render", original_render))

    for name in ("rotate", "smoothscale"):
        original = getattr(pygame.transform, name)

        def make_wrapper(transform_name, original_transform):
            def wrapper(*args, **kwargs):
                started = time.perf_counter_ns()
                try:
                    return original_transform(*args, **kwargs)
                finally:
                    elapsed = time.perf_counter_ns() - started
                    if measurements.asset_render_depth:
                        measurements.add(f"asset_transform_{transform_name}", elapsed)
                    else:
                        measurements.add(f"presentation_transform_{transform_name}", elapsed)

            return wrapper

        setattr(pygame.transform, name, make_wrapper(name, original))
        restorers.append(
            lambda transform_name=name, transform=original: setattr(
                pygame.transform, transform_name, transform
            )
        )

    original_clock = pygame.time.Clock
    frame_intervals: list[float] = []
    frame_work: list[float] = []

    class MeasuredClock:
        def __init__(self):
            self.clock = original_clock()
            self.frames = 0

        def tick(self, limit=0):
            elapsed = self.clock.tick(limit or fps)
            raw_elapsed = self.clock.get_rawtime()
            self.frames += 1
            if self.frames > 120:
                frame_intervals.append(float(elapsed))
                frame_work.append(float(raw_elapsed))
            if self.frames >= frame_count:
                pygame.event.post(pygame.event.Event(pygame.QUIT))
            return elapsed

        def get_rawtime(self):
            return self.clock.get_rawtime()

    pygame.time.Clock = MeasuredClock
    restorers.append(lambda: setattr(pygame.time, "Clock", original_clock))
    return restorers, frame_intervals, frame_work


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--frames", type=int, default=3600)
    parser.add_argument("--fps", type=int, default=60)
    args = parser.parse_args()
    if args.frames <= 120 or args.fps <= 0:
        parser.error("--frames must be greater than 120 and --fps must be positive")

    measurements = Measurements()
    intervals: list[float] = []
    work: list[float] = []
    ASSET_MANAGER.clear_cache()
    restorers, intervals, work = _install_instrumentation(
        measurements,
        frame_count=args.frames,
        fps=args.fps,
    )
    try:
        app.main(args.scenario)
    finally:
        for restore in reversed(restorers):
            restore()

    transform_calls = sum(
        count
        for key, count in measurements.counts.items()
        if key.startswith("asset_transform_")
    )
    cache_total = measurements.cache_hits + measurements.cache_misses
    pathfinding_counters = {
        key: sum(match._pathfinding_counters[key] for match in measurements.matches)
        for key in (
            "requests",
            "cache_hits",
            "cache_misses",
            "searches_started",
            "searches_completed",
            "searches_failed",
            "node_pops",
            "node_expansions",
        )
    }
    pathfinding_counters["max_queue_length"] = max(
        (match._pathfinding_counters["max_queue_length"] for match in measurements.matches),
        default=0,
    )
    result = {
        "scenario": str(args.scenario),
        "window_size": list(app.WINDOW_SIZE),
        "target_fps": args.fps,
        "sampled_frames": len(intervals),
        "frame_interval_ms": _summary(intervals),
        "frame_work_ms": _summary(work),
        "frames_over_20ms": sum(value > 20.0 for value in intervals),
        "frames_over_25ms": sum(value > 25.0 for value in intervals),
        "frames_over_33ms": sum(value > 33.0 for value in intervals),
        "asset_transform_cache": {
            "hits": measurements.cache_hits,
            "misses": measurements.cache_misses,
            "hit_rate": measurements.cache_hits / cache_total if cache_total else 0.0,
            "transform_calls": transform_calls,
        },
        "pathfinding_scheduler": pathfinding_counters,
        "phases": {
            key: {"calls": measurements.counts.get(key, 0), **_summary(values)}
            for key, values in sorted(measurements.samples.items())
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
