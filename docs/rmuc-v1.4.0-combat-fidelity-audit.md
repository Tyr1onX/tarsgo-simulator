# RMUC 2026 V1.4.0 combat fidelity audit

Checked against the official V1.4.0 rulebook and the Rules Lab configuration
`configs/rules/rmuc-2026-region-v1.4.0.yaml`. This simulator implements a
regional Rules Lab slice; simulator-only physical and timing values remain
explicitly marked as approximations.

| Topic | Official V1.4.0 | Current implementation | Match | Simulator approximation |
| --- | --- | --- | --- | --- |
| Robot HP / growth | Hero HP is selected by close-range or long-range performance; Infantry HP is selected by chassis performance. Engineer is 250 HP; automatic Sentry is 400 HP and semi-automatic Sentry is 200 HP. | The Rules Lab selects Hero long-range, Infantry HP-priority chassis, cooling-priority launcher, and automatic Sentry. Their configured HP tables and level thresholds (1–10: 0, 550, …, 5000 experience) match those official profiles. Engineer is 250 HP. | Yes for implemented profiles | The Rules Lab does not expose every selectable Hero / Infantry profile as a scenario option. Drone is a non-damageable foundation, not a ground-robot HP profile. |
| Armor damage | A detected robot-armor hit deals 20 HP for 17 mm or 200 HP for 42 mm (Table 5-2). | Infantry / Sentry use 20 raw damage; Hero uses 200. Damage still passes through the existing referee pipeline. | Yes | Rules Lab projectile cadence, planar flight, effective range, and panel geometry are approximations. |
| Armor contact | Damage is tied to contact with an armor module / attacked face; movement collision is not the damage definition. | Swept projectiles classify rotating front / rear / left / right armor plates separately from chassis-frame and wheel contacts. Only enemy armor contacts enter robot damage. | Rule behavior represented | V1.4.0 does not specify 2D hitbox dimensions. All panel / frame / wheel dimensions are labeled `lab_projectile_hitboxes.simulator_approximation`; no sprite dimensions are used. |
| Heat | 17 mm adds 10 Heat per detected hit and 42 mm adds 100; Heat detection is 10 Hz. Heat thresholds, cooling, and class/level tables are in §5.1.3 / performance tables. | The 10 Hz referee step, per-shot Heat, permanent-lock margins, and selected class/level cooling tables are represented in the rules config and tests. | Yes for implemented profiles | Continuous firing cadence is a Rules Lab approximation; official detection spacing is not a universal weapon fire-rate claim. |
| Ammunition / purchases | Initial allowance: Hero 0, Infantry 0, Sentry 300, Drone 750. Team caps: 17 mm 1000 and 42 mm 100. Remote purchase: 150 coins per 100 / 10 rounds; local purchase: 10 coins per 10 / 1 round. Sentry supply adds 100 rounds every 60 s. | Initial allowances, caps, purchase rates, six-second remote delay, and sentry supply match the configured rules. | Yes | Drone remains on its declared Rules Lab foundation behavior; team and match setup are simplified. |
| Coins / economy | 400 starting coins; timed grants of 50 at 60–300 s and 150 at 360 s; Tech Core periodic rewards and penalties; remote healing and paid-respawn costs. | Timed grants, Tech Core D1–D4 coin parameters, remote-healing formula, and paid immediate-respawn price are implemented from configured rule values. | Yes for modeled regional slice | Qualification modifiers are selectable; default Rules Lab ratings are B/B. |
| Respawn / invincibility | Normal respawn uses the time/previous-respawn progress formula, restores 10% HP, grants 30 s invincibility subject to the weak-state release rule. Paid immediate respawn restores full HP, grants 3 s invincibility and temporary power. | Configured formulas, thresholds, HP, invincibility, weak release, immediate-respawn price, and power window are implemented. | Yes for the modeled regional slice | Detailed physical reset/re-entry behavior and match-server timing are not simulated. |
| Defense buffs | Damage uses the official attack / defense / vulnerability factors; field defense values include Base 50%, Central 25%, Trapezoid 50%, Outpost 25%. | The values and current damage pipeline use the configured factors. | Yes for implemented zones | Zone occupation and terrain interactions are a 2D Rules Lab model. |

No official HP, raw damage, Heat, ammunition, coin, respawn, or defense value was
changed for this pass.

## Rules Lab validation snapshot

One complete fixed-seed spectator-AI match (420.017 s) compares the pre-pass
circle-contact behavior on `d965cf1` with the armor-hitbox implementation. The
sample is useful for regression comparison, not a statistical balance claim.

| Measure | Before | After |
| --- | ---: | ---: |
| Shots fired | 2944 | 3211 |
| Robot contacts / shots | 2580 / 87.64% | 2811 / 87.54% |
| Valid enemy armor hits / shots | Whole movement circle treated as a hit | 1655 / 51.54% |
| 17 mm enemy armor hit rate | Not separately classified | 1651 / 3169 = 52.10% |
| 42 mm enemy armor hit rate | Not separately classified | 4 / 42 = 9.52% |
| Non-armor robot contacts | Not separately classified | 1132 |
| Friendly armor contacts / misses | Not separately classified | 24 / 384 |
| Applied damage | 14582 | 11643 |
| Destroyed-life TTK samples / median | 42 / 7.567 s | 22 / 18.850 s |
| TTK p25 / p75 | 0.738 / 38.554 s | 7.867 / 102.633 s |

Frame pacing was sampled in the same 1100×780, 60 Hz desktop benchmark for 3600
frames (3480 measured after warm-up):

| Measure | #78 baseline | After #79 |
| --- | ---: | ---: |
| Frame interval p95 / p99 | 17 / 17 ms | 17 / 18 ms |
| Frame work p95 / p99 | 10 / 12 ms | 10 / 12 ms |
| Render `_draw` p95 / p99 | 4.03 / 4.14 ms | 4.05 / 4.13 ms |
| Match update p95 / p99 | 4.57 / 5.14 ms | 4.97 / 5.59 ms |
| Frames above 33 ms | — | 0 |

Incremental A* remained separately scheduled: completed-search CPU p95/p99 was
68.60/70.11 ms, while a path-search slice was 0.147/0.214 ms. This search metric
does not block a single rendered frame.
