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
- initial per-team level cap of 5, with D2/D3 unlocks to 7/10;
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
- synthetic Engineer Energy Unit resource-credit abstraction (0..2);
- synthetic per-team resource / assembly zones;
- Tech Core Difficulty 1-4 availability and prerequisite flow;
- explicit Rules Lab mechanical-success confirmation;
- 15 s continuous assembly-zone leave failure;
- active Engineer destruction failure;
- first/repeat D1-D3 completion counts plus D4 one-time completion state;
- D2 first completion level-cap unlock 5 → 7;
- D3 first completion level-cap unlock 7 → 10;
- D4 global dual-Core coordinator and cross-team exclusivity;
- D4 180 s gate, D3 prerequisite, and two-credit requirement;
- D4 45 s total window and ordered six-step abstraction;
- D4 paired Step 2/3/5/6 five-second synchronization;
- D4 Step 1/4 exemption from paired timing;
- D4 15 s cross-team priority buffer;
- D4 normal 90 s retry lockout;
- D4 priority-takeover permanent lockout and -25/10s gold-penalty state;
- RMUC private team coin wallet;
- 400 baseline initial coins with complete S/A/B/C/D project-document and
  technical-solution rating modifiers;
- explicit Rules Lab B/B neutral pre-match rating;
- official 60/120/180/240/300/360 s timed coin grants;
- Tech Core D1-D4 first/repeat periodic-gold income accumulation;
- global 10 s Rules Lab periodic settlement convention with large-dt catch-up;
- D4 priority-failure -25/10s periodic penalty consumer with wallet floor at 0;
- D3 first-completion 25% team Defense consumer for all current ground robots,
  Outpost, and Base;
- D4 first-completion Defense upgrade to 50% using non-stacking max semantics;
- explicit half-up Defense damage settlement on known enemy attack damage;
- narrow RuleSet damage-resolution hook before the Core HP mutation path;
- D4 Base +2000 current-HP reward with overflow-to-private Virtual Shield;
- Base damage order: invincibility -> Defense -> Virtual Shield -> HP;
- Shield-only hits intentionally produce no HP-loss event / damage XP / attack
  score / Base-damage rebuild progress in the current Rules Lab;
- Hero / Infantry / Sentry RuleSet-private projectile allowance state;
- Hero / Infantry / Sentry RuleSet-private Shooting Heat state;
- 17mm +10 / 42mm +100 per committed shot;
- 10 Hz Heat cooling with fractional-tick accumulator;
- dynamic Hero / Infantry Heat Limit and Cooling from current Performance;
- fixed full-automatic Sentry Heat Limit 260 / Cooling 30;
- Q2 derived dynamically from current Q0 (+100 for 17mm, +200 for 42mm);
- temporary Heat lock with zero-only unlock;
- permanent Heat lock using the documented Rules Lab Q1 >= Q2 convention;
- death Heat reset while preserving permanent lock;
- Hero / Engineer / Infantry / Sentry private chassis Buffer state;
- 60 J base Buffer Energy maximum;
- 10 Hz chassis power settlement with an independent fractional accumulator;
- dynamic Hero / Infantry chassis power limits from current Performance;
- fixed Engineer 120 W and automatic Sentry 100 W power limits;
- Rules Lab path-intent synthetic power model: stationary 0 W, moving Pl+5 W;
- stationary / power-off Buffer recovery through the same official equation;
- 5 s Buffer-depletion chassis power-off;
- conservative whole-frame movement blocking with path preservation;
- death Buffer reset to current effective maximum;
- initial Hero 42mm=0, Infantry 17mm=0, Sentry 17mm=300 allowance;
- Drone 17mm=750 initial allowance recorded as metadata only;
- committed-shot allowance deduction and allowance-zero attack gate;
- team-wide purchased allowance caps: 17mm=1000, 42mm=100;
- non-remote 17mm / 42mm Gold-Coin exchange at synthetic own supply/base/outpost buff zones;
- out-of-combat six-second RMUC-private state used for remote exchange eligibility;
- remote 17mm / 42mm exchange with immediate wallet/cap reservation and six-second delivery;
- multiple pending remote deliveries with large-dt end-of-frame settlement;
- Sentry 100-round minute supply accrual at 60..360 s, accumulation, and whole-pending claim;
- Tech Core reward metadata with D2/D3 level caps and periodic gold consumed;
- static own Base Buff Point 50% robot Defense;
- two independently owned Central Elevated Ground Buff Points with 25% Defense
  for Hero / Infantry / Sentry;
- static own Trapezoid Elevated Ground 50% robot Defense;
- Outpost Buff Point 25% Defense with own-Outpost-alive and pre-300-second enemy
  occupancy eligibility;
- official two-second Occupy-status expiration delay for the implemented static
  Defense Buff Points;
- Robot effective Defense resolved as max(Tech Core Defense, field Defense);
- 2800 × 1500 synthetic Rules Lab world using the existing Viewport.

## Intentionally not implemented

- Drone entity and Drone Experience progression;
- Radar;
- Dart System and Dart Experience;
- physical Energy Unit entities, world placement, stock, and pickup depletion;
- Tech Core real pose / insertion / translation / rotation / sensor validation;
- Tech Core physical movement / collision / obstruction sensing;
- overload alarms and blocked-Core auto-award behavior;
- temporary reactivation of a dead Engineer during opposing D4 takeover;
- Energy Mechanism and its Experience sources;
- Hero deployment-mode Experience;
- terrain-traversal Experience;
- unknown-source / redistributed Experience;
- projectile / non-projectile source redistribution;
- remaining Field Buff system beyond the implemented static Defense points:
  Terrain Crossing, Fortress, Resupply healing/respawn, Assembly invincibility,
  Attack Buff, Vulnerability, and other field effects;
- remote healing, immediate respawn, and Drone air-support spending;
- complete RMUC respawn;
- Drone shooting-heat gameplay and Drone Heat/Performance progression;
- semi-automatic Sentry Heat profile and special mode switching;
- Sentry posture-dependent cooling modifiers;
- Energy Mechanism / Fortress / Field Buff cooling modifiers;
- muzzle-velocity limit and speed-based launcher locks;
- actual motor / wheel / electrical chassis-power physics and telemetry;
- voltage/current and supercapacitor physics;
- wireless charging;
- Buffer Energy Field Buff and terrain-traversal Buffer bonuses;
- Sentry posture-dependent power changes and semi-automatic Sentry power profile;
- abnormal-offline chassis power handling;
- yellow-card / penalty-induced Sentry power-off;
- chassis total-energy-limit mechanics if applicable;
- entity projectile physics;
- actual preload / magazine inventory and physical projectile stock;
- projectile-allowance overfire behavior;
- 42 mm shielding after Hero defeat / abnormal disconnection / overfire;
- armor-module hit detection;
- official complete RMUC field geometry/elevation;
- 42 mm shield special case;
- Outpost rotation physics;
- Sentry automatic/semi-automatic mode differences, autonomous purchase policy,
  posture, or other special commands;
- armor deployment geometry or hitbox changes.

### Unknown-source Experience

V1.4.0 contains distribution rules for damage or kills whose source cannot be
identified or whose source cannot gain Experience. Correct implementation needs
source classification such as projectile/non-projectile, penalty, Dart, or other
future systems. The current `MatchEvent` already supports the deterministic
known-attacker path required by this slice, so no premature `DamageTaxonomy`
or generic Experience-source hierarchy is added.

### Tech Core D4 physical/field boundary

The rule-level D4 state machine is implemented: global exclusivity, full
priority buffer, dual logical Core slots, six ordered steps, Step 2/3/5/6 pair
windows, 45-second total timing, normal retry lockout, and priority-takeover
permanent lockout/penalty state.

Still deferred are the physical mechanisms that would be required to model Core
movement and obstruction: real pose, motor motion, collision, overload sensing,
the blocked-Core >15 s auto-award path, and temporary reactivation/control of a
dead Engineer so it can move away from the Core.

### Energy Unit / Tech Core physical boundary

Current `energy_unit_credits` is a rules-level resource-credit abstraction,
not physical carrying capacity. It exists only to express D1-D3 consuming one
prepared unit and D4 consuming two. Resource zones remain synthetic renewable
Rules Lab sources. Physical Energy Unit count, stock, respawn, world pose,
grasp/inventory semantics, mechanical arm motion, Tech Core pose,
insertion/translation/rotation, and sensor validation remain deferred.

### Dynamic Power / Heat gameplay

Performance now directly drives both RMUC Hero/Infantry Heat Limit/Cooling and
chassis power limit. Shooting Heat and the base 60 J chassis Buffer / 5-second
movement power-off consumer are implemented independently. External Heat cooling
modifiers and Buffer/power modifiers from Energy Mechanism, Fortress, terrain
traversal, Resupply, Assembly, or Sentry posture remain deferred. Static
Base/Central/Trapezoid/Outpost Defense Buff Points are implemented separately.

### Direct-damage boundary

The current 17 mm / 42 mm values remain synthetic direct-damage approximations.
They do not reproduce projectile flight, armor-module hit detection, impact
angle, projectile speed, or hitbox geometry.

### Field boundary

Start areas, Base/Outpost positions, and rebuild rectangles remain explicit
synthetic approximations rather than official full-field coordinates.

## Next candidate

The RMUC dynamic robot-resource path now reaches Experience → Level → HP /
Heat Limit / Cooling / chassis power limit, while Gold Coins → allowance → shot
→ Heat and movement intent → synthetic Pr → Buffer → movement power-off are
both active consumers. Remaining candidates include Terrain Crossing, Fortress, Resupply/Assembly,
Energy Mechanism, Attack/Vulnerability modifiers, remote healing/instant
respawn, and Drone/Radar systems. Tech Core Defense, Base Virtual Shield, and
the static Base/Central/Trapezoid/Outpost Defense points are active consumers.
