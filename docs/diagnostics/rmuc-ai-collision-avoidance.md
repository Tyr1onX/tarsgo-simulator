# RMUC AI collision avoidance recovery

Baseline: `69dd2f94a140314cd064066ec71b9af2e66e3472`  
Scenario: `configs/scenarios/rmuc-2026-region-rules-lab.yaml`  
Frame rate: fixed 60 Hz

## Reproduced deadlock

The deterministic edge fixture places red `tarsgo-infantry-1` at `(13341.26, 260.92)` and blue `opponent-hero` at `(12989.04, 401.59)`. Their centers start 379.27 mm apart; both have valid map paths, are alive, have movement permission, and have empty pathfinding queues. Their direct next-frame proposals violate the existing 360 mm minimum center distance.

On the baseline, both robots stayed at the same coordinates for all 10 simulated seconds. Each accumulated 600 blocked ticks, for 1200 together; each had a live path and `can_move=True`. The local avoidance generator returned no legal proposal, the recovery counter retried 26 times without success, and two global path replans reproduced the same routes. Full values are saved in [baseline telemetry](rmuc-ai-head-on-before.json).

Root cause: the old local side-step required the temporary point to connect directly to `robot.path[0]`. At this edge, the side-step itself was passable, but the straight connector to that distant waypoint crossed an illegal terrain/boundary segment. The proposal was discarded, leaving both bots to retry the same movement.

The 420-second baseline replay also exposed a terrain-boundary variant: a live sentry was pinned behind a stationary dead robot. Its only nearby side-step endpoints crossed the highland edge, so the candidate generator had no move. This is separate from legal waits, chassis power locks, and death/respawn.

## State transition audit and repair

- `_move_robots` computes movement permission and proposals, resolves pairwise conflicts, checks every candidate against all other proposals, and applies a final collision-safe stop before committing. The resolver still uses the original collision radius and map traversal checks.
- `_local_avoidance_proposals` generated side-step endpoints, then rejected them unless one direct `can_traverse(goal, path[0])` edge was legal. It had no connector path, so terrain-aware routes around an obstacle could never be represented.
- `_recover_stuck_robot` retried local avoidance after 0.75 seconds and requested a global route after 1.75 seconds. The global route used the same goal and did not account for nearby robot bodies, so it could return the same blocked route.

The repair preserves valid direct side-steps. When they cannot reconnect directly, a bounded A* search finds a short connector to a point farther along the existing route, using a temporary circle for each nearby ground robot. The search is capped at 512 node pops per local planning call, retries are limited by the existing 0.75-second recovery interval, and the connector is still checked against `GameMap` before it can be installed. A fallback search can start at the robot's current position when terrain makes all side-step endpoints unreachable. Dead robots remain collision obstacles and are routed around; they are not removed or ignored.

When both robots are moving, right of way alternates deterministically on one-second slices using the sorted robot IDs as a stable phase offset. A stationary robot retains right of way over a mover. Every accepted move still passes the existing swept pairwise collision test, so the change does not relax overlap, wall, ramp, power, or damage rules.

At the 420-second boundary, accumulated `dt` is snapped to the configured time limit within a 1e-9-second tolerance. This addresses the observed 60 Hz sum (`419.9999999999…`) without changing the duration or combat formulas.

## Before and after

The same 10-second fixture now makes both bots progress. Red travels 14,483.14 mm and blue 13,096.81 mm; their closest center separation is 377.98 mm, above the existing 360 mm minimum. Neither has a collision-blocked frame after the initial resolution. The local planner performs three searches using 113 total node pops; no recovery retry or global replan is needed. See [fixed telemetry](rmuc-ai-head-on-after.json).

The screenshots use the actual desktop Pygame `_draw` pipeline with `CombatVisualState` and `RMUCStaticFieldCache`:

- [Before: both robots remain locked at the edge](../screenshots/rmuc-head-on-before.png)
- [After: sprites and labels separate as both robots pass](../screenshots/rmuc-head-on-after.png)

## Full 420-second AI replay

The full spectator-AI replay completed exactly 25,200 fixed ticks and settled at `420.0` seconds. The final result was the blue side. No robot centers fell below 360 mm separation; the measured minimum was 360.026 mm. Longest continuous collision-yield stall was 1.817 seconds, peak path queue was 12, and the simulation ran at 6.19 simulated seconds per wall-clock second.

Across the 12 robots, stationary robot-frames were classified as:

| Classification | Robot-frames |
| --- | ---: |
| Legal wait with no active route | 128,932 |
| Pathfinding pending | 2,813 |
| Chassis or rule movement lock | 21,020 |
| Collision yield | 1,597 |
| Dead or respawning | 27,291 |
| Active path with no movement and no block reason | 0 |

The detailed per-second position, target, intent, path state, movement permission, block reason, and stationary duration are in [the full replay CSV](rmuc-ai-collision-recovery-420s.csv); aggregate counters are in [its summary](rmuc-ai-collision-recovery-420s.summary.json).
