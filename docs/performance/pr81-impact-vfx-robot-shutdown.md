# PR #81 impact VFX and shutdown performance check

The baseline and candidate samples used the RMUC 2026 Rules Lab scenario,
1100×780 rendering, a 60 Hz target, and 3600 frames. The benchmark discards the
first 120 frames and reports the remaining 3480. SDL's dummy video driver keeps
the run off the desktop; these results measure simulator update and Pygame
render work, not display compositor latency. Three candidate runs were taken.

| Metric (p95 / p99, ms) | Baseline `a339719` | Run 1 | Run 2 | Run 3 |
| --- | ---: | ---: | ---: | ---: |
| Frame interval | 19 / 19 | 19 / 19 | 19 / 19 | 19 / 19 |
| Frame work | 9 / 13 | 10 / 14 | 10 / 14 | 10 / 14 |
| Match update | 4.682 / 5.500 | 5.290 / 6.179 | 5.251 / 6.147 | 5.286 / 6.163 |
| AI update | 0.325 / 0.411 | 0.346 / 0.389 | 0.351 / 0.406 | 0.349 / 0.400 |
| Render draw | 3.297 / 4.779 | 3.440 / 3.585 | 3.501 / 3.834 | 3.475 / 3.743 |
| A* budget slice | 0.150 / 0.243 | 0.167 / 0.240 | 0.168 / 0.242 | 0.168 / 0.246 |
| Max frame interval | 26 | 31 | 35 | 32 |

The 60 Hz frame-interval p95/p99 stayed at 19/19 ms in all three candidate
runs. Render-draw p99 was 0.95–1.19 ms lower than baseline. Frame-work p95/p99
moved up by 1 ms; match-update p95/p99 moved up by about 0.57–0.68 ms, while
the baseline's 16.18 ms update maximum fell to 6.82–10.67 ms in the candidate
runs. One candidate run had one 35 ms sampled frame; the other two stayed at
or below 32 ms, with no repeated >33 ms frames in any candidate sample.

The new renderer stays within the existing impact budget: at most 4 / 10 / 14
particles for 17 mm / 42 mm / Dart, with the global 384-particle draw cap still
in force. The screenshots in `docs/screenshots/` use the actual RMUC scenario
and application drawing path with fixed presentation-only hit and shutdown
states so the short-lived feedback can be reviewed in a still image.
