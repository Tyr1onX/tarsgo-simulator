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
- synthetic Engineer Energy Unit carrying abstraction;
- synthetic per-team resource / assembly zones;
- Tech Core Difficulty 1-3 availability and prerequisite flow;
- explicit Rules Lab mechanical-success confirmation;
- 15 s continuous assembly-zone leave failure;
- active Engineer destruction failure;
- first/repeat D1-D3 completion counts;
- D2 first completion level-cap unlock 5 → 7;
- D3 first completion level-cap unlock 7 → 10;
- Tech Core first/repeat reward metadata with only level-cap rewards consumed;
- 2800 × 1500 synthetic Rules Lab world using the existing Viewport.

## Intentionally not implemented

- Drone entity and Drone Experience progression;
- Radar;
- Dart System and Dart Experience;
- physical Energy Unit entities, world placement, stock, and pickup depletion;
- Tech Core real pose / insertion / translation / rotation / sensor validation;
- Tech Core Difficulty 4;
- Difficulty 4 dual Tech Cores and dual Energy Units;
- Difficulty 4 per-step synchronization and timing;
- Difficulty 4 cross-team priority / interruption / cooldown / lockout rules;
- Tech Core periodic-gold gameplay;
- Difficulty 3 defense-buff gameplay;
- Difficulty 4 Base +2000 / virtual-shield / defense / gold rewards;
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

### Tech Core Difficulty 4

Difficulty 4 is deliberately deferred because it is a separate coupled system,
not a simple extension of D1-D3. It includes two Tech Cores, dual Energy Units,
per-step synchronization, V1.4.0 timing constraints, a 45-second total window,
cross-team priority, interruption buffering, failure cooldown/lockout behavior,
special gold penalties, and first-completion Base/defense/economy effects.

The current state representation can be extended later, but none of those
Difficulty 4 mechanics are partially implemented now.

### Energy Unit / Tech Core physical boundary

Current carrying state is boolean and only means the Engineer possesses the
resource required for one D1-D3 attempt. Resource zones are synthetic renewable
Rules Lab sources. Physical Energy Unit count, stock, respawn, world pose,
mechanical arm motion, Tech Core pose, insertion/translation/rotation, and
sensor validation remain deferred.

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
