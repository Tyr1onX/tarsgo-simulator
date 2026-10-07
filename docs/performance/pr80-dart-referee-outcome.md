# PR #80 Dart referee outcome performance check

Both samples used the RMUC 2026 Rules Lab scenario, 1100×780 rendering, a
60 Hz target, and 3600 frames. The benchmark discards the first 120 frames and
reports the remaining 3480. SDL's dummy video driver kept the run off the
desktop; this measures simulator update and pygame rendering work, not display
compositor latency.

| Metric | Stable baseline `0d9f25c` p95 / p99 | PR #80 p95 / p99 |
| --- | ---: | ---: |
| Frame interval | 21 / 22 ms | 21 / 22 ms |
| Frame work | 12 / 15 ms | 11 / 15 ms |
| Match update | 5.509 / 6.573 ms | 5.352 / 6.310 ms |
| AI update | 0.385 / 0.435 ms | 0.351 / 0.407 ms |
| Render draw | 3.606 / 3.747 ms | 3.553 / 3.699 ms |
| A* budget slice | 0.175 / 0.240 ms | 0.173 / 0.241 ms |

The p95/p99 measurements show no frame-time regression. One isolated 34 ms
frame occurred in the PR sample, compared with a 25 ms maximum in the baseline;
neither sample had a recurring tail spike, and the PR sample had no repeated
frames above 33 ms. The maximum render-draw sample was a similar cold-start
cache-build outlier in both runs (170.7 ms baseline, 170.0 ms PR).

The automatic resolver exits immediately when no Dart attempts are pending.
While a launch is pending, it examines at most the four darts allowed per team.
