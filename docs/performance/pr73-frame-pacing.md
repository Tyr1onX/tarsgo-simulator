# PR #73: RMUC frame pacing and render cache

## Method

Measured the real Pygame RMUC 2026 region-rules-lab scene at 1100×780 with
`tools/benchmark_rmuc_frame_pacing.py`. Each run warms for 120 frames and then
reports frame interval and active frame work, plus update, AI, rendering, asset
transforms, static scene layers, LED overlays, Outpost rotor, and pathfinding.
The benchmark uses the normal desktop loop and match scenario; it does not
change simulation rules.

The before sample used 1,800 rendered frames (1,680 measured). The after sample
uses a 3,600-frame run (3,480 measured) to check sustained operation. Frame
interval percentiles are wall-clock time between frames; Pygame's raw frame
work excludes time spent waiting in `Clock.tick(60)`.

## Before

Baseline commit: `876476a5d6b9850b9a329fba5f66a0bb99a43b2b`.

| Metric | Mean | p50 | p95 | p99 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frame interval | 23.04 ms | 17 ms | 36 ms | 157 ms | 165 ms |
| Frame work | 17.10 ms | 10 ms | 36 ms | 157 ms | 165 ms |
| `Match.update` | 7.81 ms | 0.82 ms | 19.98 ms | 147.98 ms | 153.77 ms |
| `Match._update_ai` | 7.19 ms | 0.20 ms | 19.38 ms | 147.33 ms | 153.19 ms |
| Render draw | 7.82 ms | 7.17 ms | 11.98 ms | 16.88 ms | 176.11 ms |

The asset transform cache had 38,068 hits and 6,932 misses (84.6% hit rate).
Scaling occurred 6,932 times. Static battlefield, region, and terrain drawing
ran every frame. Each robot LED layer was allocated and drawn per sprite part
per frame.

## After

The 3,600-frame run sampled 3,480 frames over about 80 seconds.

| Metric | Mean | p50 | p95 | p99 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frame interval | 22.10 ms | 17 ms | 32 ms | 155 ms | 162 ms |
| Frame work | 12.94 ms | 6 ms | 32 ms | 155 ms | 162 ms |
| `Match.update` | 5.64 ms | 0.80 ms | 22.19 ms | 149.22 ms | 155.42 ms |
| `Match._update_ai` | 5.01 ms | 0.15 ms | 21.70 ms | 148.58 ms | 154.83 ms |
| Render draw | 3.46 ms | 3.42 ms | 3.89 ms | 4.04 ms | 174.42 ms |

The transform cache recorded 85,632 hits and 769 misses (99.11% hit rate),
versus 84.6% before. `smoothscale` ran 11 times in the whole run, versus 6,932
times before. The static floor, region, and terrain layers each rebuilt once
during startup, then were reused. LED overlay time fell from 0.0120 ms to
0.0051 ms per call. The Outpost rotor remained negligible at 0.018 ms per call.

Frame-work p95 improved by 11%; p99 improved by 1%. Render-draw p95/p99
improved by about 68%/76%. The fraction of frames over 33 ms was 4.8% after,
compared with 5.1% before. The samples differ in length (1,680 versus 3,480
measured frames), and the host was not otherwise isolated.

## Changes

- Advance match and visual state at fixed 60 Hz simulation ticks, carrying
  elapsed time in an accumulator.
- Interpolate robot presentation positions between the previous and current
  fixed-tick states.
- Quantize sprite and LED rotation to 3° buckets; retain transformed assets in
  a bounded LRU and cache scaled source surfaces separately.
- Precompose LED layers and cache their rotated forms.
- Cache the static RMUC floor, official region treatment, barriers, and terrain
  markings by scenario, field size, zoom, and debug-geometry state. Animated
  zone overlays stay dynamic. Camera shake translates the cached layer without
  rebuilding it.
- Leave Outpost rotor drawing uncached: the audit measured about 0.015 ms per
  call, too little to justify more rotation-frame memory.

## Remaining hotspot

The measured `find_path` calls remain the main source of update and frame-time
tail spikes: 1,334 calls in the after sample, with 63.19 ms p95, 66.20 ms p99,
and 67.28 ms max. Baseline pathfinding had 60.13 ms p95 and 61.18 ms p99.
The 155 ms overall p99 therefore remains a real limitation: this pass reduces
render work and keeps robot motion interpolated, but does not eliminate
occasional whole-frame pauses caused by pathfinding. No pathfinding or AI
decision changes were made, per scope.
