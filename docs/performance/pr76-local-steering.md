# PR #76 — Local Steering and Stuck Recovery

## Implementation

- Global movement still uses the existing pathfinder and the existing collision radius.
- Each simulation movement step resolves swept robot-to-robot conflicts in a stable order. Stationary robots retain right of way; moving robots use their stable ID as the tie-breaker.
- A blocked robot tries a deterministic side-step and keeps its original route. Targeting the same structure assigns a preferred approach slot and avoids slots already selected by teammates.
- Stuck time follows best progress toward the route's final goal. Side-steps and short retreats no longer reset it. After 0.75 seconds without progress the robot tries a local recovery waypoint; after 1.75 seconds it requests a path through the existing budgeted A* service. The old route stays active while that request is pending.
- Movement diagnostics expose blocked ticks/events, yields, local avoidance moves, recovery attempts/successes, and path re-requests.

No utility scores, combat, collision dimensions, line of sight, field geometry, or rules were changed.

## Deterministic congestion checks

| Scenario | Before | After |
| --- | --- | --- |
| Two robots on opposing routes, 300 ticks | 273 blocked ticks per robot; both stalled at contact | Both reached the opposite endpoints; 1 blocked tick total, 2 local sidesteps, 200-unit final separation |
| Three robots crossing, 600 ticks | Two robots blocked for 215 ticks each | All three reached their endpoints; 0 blocked ticks, 1 sidestep |
| Three attackers approaching one Outpost | Shared approach point caused a pile-up | Two attackers choose distinct reachable approach points deterministically |
| Narrow corridor with a stationary robot, 600 ticks | Long mutual obstruction | 233 blocked ticks, 10 local recovery attempts, 4 path re-requests; one incremental A* search started and completed through the budgeted service |

The corridor check also verifies that robots never overlap and that the old route remains available while a replacement search is pending.

## Frame pacing

Measured in the 1100×780 `rmuc-2026-region-rules-lab.yaml` scene at 60 FPS. Each run sampled 3,480 frames after a 120-frame warm-up. Baseline was commit `fb56e5abee7f3b81b6830ec439e9d6e53020d3c8`; final values below are the two 3,600-frame runs on the completed implementation.

| Metric | Baseline p95 / p99 | Final p95 / p99 across two runs |
| --- | ---: | ---: |
| Display frame interval | 17 / 18 ms | 17 / 17–18 ms |
| Frame work (`Clock.get_rawtime`) | 10 / 11 ms | 10–16 / 11–17 ms |
| Match update | 4.650 / 5.396 ms | 4.737–4.803 / 5.273–5.317 ms |
| AI update | 0.267 / 0.321 ms | 0.289–0.293 / 0.336–0.344 ms |
| Render | 4.096 / 4.209 ms | 4.036–4.063 / 4.161–4.181 ms |
| Budgeted path service | 3.802 / 4.389 ms | 3.828–3.911 / 4.217–4.339 ms |
| Incremental A* slice | 0.147 / 0.222 ms | 0.142–0.145 / 0.212–0.213 ms |
| Completed A* CPU lifetime | 70.28 / 71.16 ms | 67.34–68.70 / 69.19–69.45 ms |

The final runs each recorded 40–41 local avoidance moves and 5 blocked ticks. Neither run triggered stuck recovery in the standard RMUC match. Search volume rose from 135 completed searches (12 unreachable, queue max 6) at baseline to 309 (18 unreachable, queue max 7) after this movement pass; per-slice and completed-search p95/p99 stayed at or below baseline, because the existing scheduler still spreads work across ticks. One of the two runs had elevated raw frame-work percentiles, while the other matched the baseline p95/p99 at 10/11 ms. Display frame p95/p99 and update/render/path p95/p99 remained stable, with no frames over 33 ms; occasional isolated 25–28 ms frames occurred in both final runs.

## Verification

- Full test suite: 1,040 passed.
- `git diff --check` and Python `compileall` passed.
