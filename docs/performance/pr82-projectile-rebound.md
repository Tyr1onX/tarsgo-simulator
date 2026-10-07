# PR #82 — RMUC projectile rebound and ground-contact validation

Baseline: `489f83b8393695e4e2e5af1cf4e26e572558ea15` (1,070 tests).
Candidate: presentation-only 17/42 mm contact rebounds, no physical-contact
`ImpactEffect` particles or hit flashes. The referee still owns every hit and
its damage; the recorded collision normal is copied for the cosmetic rebound.
Dart visuals and referee behavior remain unchanged.

## Actual renderer GIF

[Animated 17 mm / 42 mm / frame + obstacle / high-volume preview](../previews/pr82-projectile-rebound.gif)

The GIF contains 30 animated frames from the 1100×780 Pygame game draw path
with the RMUC scenario at fixed 60 Hz simulation ticks. Panels magnify local
cropped game views for legibility; they are not static mockups. The obstacles
and burst-contact load are deliberately staged inside the actual collision
engine for visual acceptance. The four scenes recorded 5, 1, 8 and 272
collision events respectively; high-volume presentation reached its 96-item
cap. The rolling, stopping and fading occur without any new referee damage.

## Performance (Apple Silicon macOS, SDL dummy driver)

Normal scenario comparison: 720 frames at 1100×780 with 60 Hz frame target;
120-frame warm-up discarded; 600 samples. Both runs used the existing
`tools/benchmark_rmuc_frame_pacing.py` and identical settings.

| Metric (p95 / p99, ms) | Stable main baseline | Candidate |
| --- | ---: | ---: |
| Frame interval | 19 / 19 | 21 / 22 |
| Frame work | 12 / 17 | 14 / 16 |
| Draw | 3.44 / 4.36 | 3.59 / 5.07 |
| Frames exceeding 33 ms | 0 | 0 |

Additional 720-frame high-volume collision/render stress (600 sampled frames)
used the same 1100×780, 60 Hz target with fixed robots and deterministic
bursts against a test obstacle. It recorded **1,648 real collision events**,
up to **96** concurrent visual rebounds, interval p95/p99 **21/22 ms**,
frame-work p95/p99 **7.52/8.48 ms**, render p95/p99 **4.68/6.15 ms**,
and **0 frames over 33 ms**.

The normal candidate's frame interval and draw tail increased modestly; these
short SDL-dummy measurements do **not** establish zero regression or hardware
display pacing. The stress case uses stationary robots and is not directly
comparable to the normal AI-active workload. The rebound pool is bounded to
96 visuals, and each has a fixed < 1 s lifetime; this protects against
unbounded buildup. No 3D collision simulation was added.

## Checks

- All **1,079** project tests pass, including 17/42 mm trajectory determinism,
  real contact normals, armor/obstacle reflection, ground roll, fade, cap,
  referee HP/ammo invariants and PNG transparency.
- 17 mm and 42 mm artwork is committed as transparent PNGs in
  `assets/rmuc/projectiles`, loaded through existing `AssetManager`.
- Desktop packagers already bundle `assets/`; CI verifies both new PNGs.
- No Dart referee changes.