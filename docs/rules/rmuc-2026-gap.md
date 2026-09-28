# RMUC 2026 Regional V1.4.0 Gap

RuleSet: `rmuc-2026-region-v1.4.0`

This file distinguishes implemented Rules Lab behavior from the full RMUC 2026
Regional V1.4.0 manual.

## Implemented

- first-class Regional V1.4.0 RuleSet identity;
- 420-second match duration;
- Hero ×1, Engineer ×1, Infantry ×2, Sentry ×1 per team;
- Base / Outpost damageable structures and lifecycle;
- Base invincibility while Outpost is alive;
- Outpost destruction/rebuild, 300 s cutoff, and Base-damage rebuild
  opportunities;
- V1.4.0 match-result chain;
- Hero and Infantry private Experience state;
- complete Lv1-Lv10 Experience thresholds;
- current per-team level cap of 5 with XP clamped at 2200;
- deterministic Hero/Infantry committed-shot Experience;
- known-source Robot / Outpost / Base actual-damage Experience;
- known-source Robot kill Experience formula;
- Engineer / Sentry victim level treated as 1;
- complete Hero close-range and long-range Performance tables;
- complete Infantry power-priority / hp-priority chassis tables;
- complete Infantry burst-priority / cooling-priority launcher tables;
- Rules Lab defaults: Hero long-range, Infantry hp-priority + cooling-priority;
- multi-level progression;
- max-HP increase applied as the same delta to living current HP;
- dead robots remain dead when max HP grows;
- effective Power / Heat Limit / Cooling values exposed without enabling their
  gameplay systems;
- minimal level / XP HUD labels;
- 2800 × 1500 synthetic Rules Lab world using the existing Viewport.

## Intentionally not implemented

- Drone entity and Drone Experience progression;
- Radar;
- Dart System and Dart Experience;
- Tech Core assembly;
- Tech Core level-cap unlock from 5 → 7 → 10;
- Energy Unit;
- Energy Mechanism and its Experience sources;
- Hero deployment-mode Experience;
- terrain-traversal Experience;
- unknown-source / redistributed Experience;
- projectile / non-projectile source redistribution;
- complete Field Buff system;
- RMUC economy;
- complete RMUC respawn;
- RMUC shooting-heat gameplay using dynamic Performance stats;
- RMUC chassis-buffer / power-off gameplay using dynamic Performance stats;
- entity projectile physics;
- armor-module hit detection;
- official complete RMUC field geometry/elevation;
- 42 mm shield special case;
- Outpost rotation physics;
- Sentry automatic/semi-automatic mode differences, posture, remote exchange, or
  special commands;
- armor deployment geometry or hitbox changes.

### Unknown-source Experience

V1.4.0 contains distribution rules for damage or kills whose source cannot be
identified or whose source cannot gain Experience. Correct implementation needs
source classification such as projectile/non-projectile, penalty, Dart, or other
future systems. The current `MatchEvent` already supports the deterministic
known-attacker path required by this slice, so no premature `DamageTaxonomy`
or generic Experience-source hierarchy is added.

### Dynamic Power / Heat gameplay

Performance now provides effective chassis power limit, heat limit, and cooling
rate at the current level, but this round deliberately does not port RMUL's heat
or chassis-buffer simulation into RMUC. The rule data is ready for a later
consumer without coupling progression to those gameplay systems.

### Direct-damage boundary

The current 17 mm / 42 mm values remain synthetic direct-damage approximations.
They do not reproduce projectile flight, armor-module hit detection, impact
angle, projectile speed, or hitbox geometry.

### Field boundary

Start areas, Base/Outpost positions, and rebuild rectangles remain explicit
synthetic approximations rather than official full-field coordinates.

## Next candidate

This round stops after Experience + Performance. A later phase can use the
per-team level-cap boundary to add Tech Core / Energy Unit behavior without
rewriting progression, but that phase is not part of this implementation.
