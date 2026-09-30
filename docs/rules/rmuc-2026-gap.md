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
- explicit V1.4.0 projectile-damage settlement
  `original * Attack * (1 - Defense + Vulnerability)` with one final half-up
  integer rounding step;
- RMUC-private timed team Attack Buff facts with independent durations and
  same-class max semantics;
- Large Energy Mechanism result consumer with the official five average-ring
  tiers and 5..10-arm duration table;
- Large Energy Mechanism team Attack Buff routed through the existing timed
  Attack consumer;
- Large Energy Mechanism team Defense applied to living robots plus Base/Outpost
  through the existing max-based effective Defense path;
- Large Energy Mechanism Shooting-Heat Cooling ×1/×2/×3/×5 consumed as a
  complete Cooling candidate alongside Tunnel and Fortress Cooling;
- same-class Attack/Defense/Cooling max semantics and same-team no-reactivation
  while the Large Energy Mechanism remains in its activated Buff window;
- Attack Buff resolution for current direct-projectile Robot/Base/Outpost
  damage without changing the Core HP-loss path;
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
- out-of-combat six-second RMUC-private lifecycle state shared by projectile exchange and Resupply healing;
- own Resupply healing at 10% max HP/s, rising to 25% max HP/s after elapsed 240 s while out of combat, with half-up cumulative integer settlement;
- Hero/Infantry/Sentry remote healing while out of combat with immediate atomic
  Gold-Coin reservation, Table 5-8
  `50 + ROUNDUP((elapsed/60)*20)` pricing, six-second delayed one-shot
  delivery, 60% current-max-HP half-up settlement, and max-HP clamp;
- death-before-delivery cancellation without refund, large-dt one-shot
  settlement, reset cleanup, and independent coexistence with local Resupply
  healing;
- automatic respawn progress using death-time elapsed, future immediate-respawn count, 1/s normal progress, and 4/s acceleration in own Resupply or below 2000 Base HP;
- automatic respawn at 10% current max HP with half-up integer settlement, 30 s Invincibility, and Weakened state;
- paid immediate respawn for the instantiated ground robots with atomic Gold-Coin
  deduction, Table 5-8 elapsed/level pricing, 100% current max HP, 3 s
  Invincibility, no Weakened state, immediate-respawn count increment, and
  clearing of the active automatic-respawn bar/progress;
- immediate-respawn 4 s chassis-power-limit ×2 effect capped at 200 W through
  the existing effective chassis-power helper;
- Weakened launcher lock, static/Terrain/Fortress/Assembly Buff Point and Outpost-rebuild exclusion, including Tech Core start/confirmation gates and continuous Assembly absence semantics;
- same-lifecycle-settlement Weakened release when automatic respawn finishes inside a legal Base/Outpost/Resupply release point, with the official 10 s minimum post-respawn Invincibility;
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
- official two-second Occupy-status expiration delay for implemented field Buff
  Points, including Engineer Assembly / own-Resupply Invincibility;
- own Assembly Buff Point Engineer-only Invincibility with a cumulative
  180-second round budget, leave/re-enter persistence, immediate death expiry,
  Weakened exclusion, and reset-only budget reset;
- own Resupply Engineer Invincibility with no cumulative cap or out-of-combat
  prerequisite, kept independent from Resupply healing;
- independent automatic-respawn / Assembly / Resupply Invincibility sources
  combined only at the existing `can_receive_damage()` gate;
- Robot effective Defense resolved as max(Tech Core Defense, static field Defense,
  Terrain Crossing Defense);
- synthetic ordered Terrain Crossing RFID sequences for Road, Elevated Ground,
  Launch Ramp, and Tunnel;
- official crossing windows: Road/Tunnel 3 s, Elevated Ground 5 s, Launch Ramp 10 s;
- Launch Ramp / Elevated Ground 25% Defense for 30 s;
- Road 25% Defense for 5 s plus 15 s reacquire restriction;
- standard Terrain Defense retrigger upgrade to 50% with max-duration rule;
- Tunnel 50% Defense for 10 s plus independent Cooling ×2 for 120 s;
- Tunnel Cooling consumed by the existing 10 Hz Shooting Heat path;
- +300 first-acquisition Terrain Experience for each terrain type using the
  existing Hero/Infantry progression and level-cap clamp;
- death clears active Terrain buffs/sequences while preserving first-acquired
  XP history until match reset;
- own Fortress activation permanently after first own-Outpost destruction;
- own Fortress single-owner Infantry/Sentry occupancy with the shared 2-second
  Occupy-release semantics;
- own Fortress 50% Defense integrated into the existing max-based effective
  Defense calculation;
- live Fortress Cooling bonus `w=floor((Base max_hp-Base hp)/40)`, capped at 75;
- Fortress `base+w` Cooling and Tunnel `base×2` Cooling compared as complete
  final candidates rather than added;
- Fortress Cooling consumed by the existing 10 Hz Shooting Heat path without
  changing Heat Limit/Q2;
- own Fortress reserved 17 mm Projectile Allowance with
  `N=min(500, 100+2*floor(Base HP loss/15))`;
- reserve kept separate from robot own allowance, coins, and purchased-17mm cap;
- Fortress occupant shot consumption prioritizes reserve then falls back to own
  allowance through the existing single `on_attack_committed()` path;
- Rules Lab reserve provisioning state prevents leave/re-entry refill farming,
  expands only by increased N capacity, and clamps when N decreases;
- reserve persists off-point and through death but resets between matches;
- enemy Fortress occupation for Infantry/Sentry after 180 s once the target
  Outpost has ever been destroyed;
- independent per-robot opponent-Fortress Occupy timers with 2 s Occupy release
  and 3 s paused retention after Occupy expiry or death;
- V1.4.0 opponent-Fortress 100% Vulnerability through max-based
  `_effective_vulnerability()`;
- target-specific Radar Vulnerability effect for current ground robots, with
  official P-derived 15% / 20% values represented through a narrow
  `set_radar_vulnerability()` rule boundary;
- Radar base Vulnerability has no invented duration: repeated official-state
  updates replace/clear the target's current P-derived effect;
- Radar P-derived effect proxy persists through robot death/respawn and clears
  on match reset, matching V1.4.0's retained-P / reset-x rule;
- Radar double-Vulnerability effect doubles only Radar-origin values for 30 s,
  caps effect starts at two per match, and leaves opportunity accumulation /
  command transport outside the Rules Lab;
- Radar and opponent-Fortress Vulnerability share existing same-class max
  semantics rather than summing;
- damage resolution now uses
  `Attack * (1 - Defense + Vulnerability)` with existing final half-up
  rounding before Base Virtual Shield;
- single-robot 20 s opponent-Fortress trigger reuses
  `base_armor_deployed`;
- Base armor deployment disables all Fortress Vulnerability without mutating
  HP, max HP, Virtual Shield, or Outpost-driven Base invincibility;
- 2800 × 1500 synthetic Rules Lab world using the existing Viewport.

## Intentionally not implemented

- Drone entity and Drone Experience progression;
- Radar entity, coordinate detection, vision, marking accuracy, x/P progression,
  missing-data decay, map marking, and interference-wave gameplay;
- Dart System and Dart Experience;
- physical Energy Unit entities, world placement, stock, and pickup depletion;
- Tech Core real pose / insertion / translation / rotation / sensor validation;
- Tech Core physical movement / collision / obstruction sensing;
- overload alarms and blocked-Core auto-award behavior;
- temporary reactivation of a dead Engineer during opposing D4 takeover;
- physical Large Energy Mechanism gameplay: rotating entity, activation
  opportunities, operator/Sentry trigger commands, random lit-module selection,
  projectile-hit timing, armor/ring hit detection, and ring-score recognition;
- Large Energy Mechanism 750-point Experience distribution, because the official
  divisor includes all living Hero/Infantry/Drone robots and the current Rules
  Lab has no Drone entity/alive state;
- Small Energy Mechanism gameplay and its Defense/Experience effects;
- Hero deployment-mode Experience;
- unknown-source / redistributed Experience;
- projectile / non-projectile source redistribution;
- remaining Field Buff system beyond static Defense, Terrain Crossing, Resupply
  healing/Engineer Invincibility, Assembly Engineer Invincibility, and the
  implemented Fortress own/enemy rule-level effects;
- V1.4.0 says all living robots receive Large Energy Mechanism Buffs during the
  active window but does not separately define the death/respawn-mid-window
  transition; the Rules Lab keeps the team window alive through robot death and
  lets a respawned robot see it while time remains;
- Base/Outpost 10 mm × 10 mm armor-center 150% Attack Buff is audited but not
  wired because armor hit detection/projectile geometry is intentionally
  unimplemented;
- long-range Hero Deployment Mode 42 mm-vs-Base 150% Attack Buff is audited but
  not wired because Deployment Mode is outside this Sprint;
- the current Core damage hook carries source team but not projectile/source
  kind; this is sufficient for the current direct-projectile Rules Lab combat,
  but future collision/penalty/source-specific damage must not inherit Attack
  Buff without adding narrow source context;
- Radar's one-minute Vulnerability-opportunity accumulator is not modeled;
  simultaneous-target non-additive timing remains deferred with the rest of
  Radar marking gameplay;
- Radar double-Vulnerability command transport/queueing is not modeled;
  `start_radar_double_vulnerability_effect()` means an official effect start
  has already been authorized;
- interference-wave difficulty gating is not modeled; the Radar Vulnerability
  setter may only be used after that official condition has already been
  resolved externally;
- aerial targets may carry Radar marking P but Table 5-22 limits Vulnerability
  to ground robots; Drone remains uninstantiated and receives no modeled Radar
  Vulnerability effect;
- V1.4.0 does not explicitly state whether Engineer death resets the already
  consumed portion of the Assembly 180-second Invincibility budget; the current
  Rules Lab preserves consumed time because the manual only says death makes the
  active Buff expire and gives no budget-reset rule;
- Drone air-support spending;
- V1.4.0 says remote-healing exchanges are unlimited but does not explicitly
  define whether one robot may hold multiple simultaneous six-second pending
  remote-healing transactions; the current Rules Lab permits one pending request
  per robot and allows another after settlement;
- V1.4.0 does not explicitly discuss Weakened with remote healing; the current
  Rules Lab does not add a Weakened prohibition beyond the explicit
  living/eligible-type/out-of-combat requirements;
- V1.4.0 does not explicitly forbid buying remote healing at full HP; the current
  Rules Lab accepts it and lets the delayed heal clamp to max HP;
- same-frame death-versus-six-second-delivery ordering is not specified by the
  manual; the Rules Lab consumes destruction first, so death cancels the pending
  heal in that discrete frame;
- Table 5-8 does not explicitly state how its "robot level" price term applies
  to Engineer/Sentry, which are outside the Experience System; the current
  Rules Lab uses its existing level-1 convention for those non-progression
  robots, matching the only explicit Engineer/Sentry level convention elsewhere
  in V1.4.0 but retaining this as an audit edge;
- automatic-Sentry gimbal-operator intervention surcharge (+50 coins), including
  remote-healing and immediate-respawn actions, plus the semi-automatic-Sentry
  free operator-action distinction from §5.6.4 remain deferred because action
  origin/control mode is not modeled;
- Drone shooting-heat gameplay and Drone Heat/Performance progression;
- semi-automatic Sentry Heat profile and special mode switching;
- Sentry posture-dependent cooling modifiers;
- remaining non-Fortress / non-Tunnel / non-Large-Energy-Mechanism Cooling
  modifiers;
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
- Base armor deployment geometry or hitbox changes.

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
movement power-off consumer are implemented independently. Tunnel Cooling ×2,
own Fortress dynamic Cooling, and Large Energy Mechanism Cooling multipliers are
active external Heat-cooling consumers using complete-result max semantics.
Other Heat cooling modifiers and Buffer/power modifiers from Resupply, Assembly,
terrain-specific Buffer effects, or Sentry posture remain deferred. Static
Base/Central/Trapezoid/Outpost Defense Buff Points, own Fortress
Defense/Cooling, Large Energy Mechanism rule-level Buffs, and rule-level Terrain
Crossing are implemented separately from real terrain physics.

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
both active consumers. Remaining candidates include physical Base-armor geometry,
physical Assembly/Energy-Mechanism activation work, and full Drone/Radar
systems. Tech Core Defense, Base
Virtual Shield, static Defense points, own Fortress Defense/Cooling, and
rule-level Terrain Crossing are active consumers; real terrain physics remains
deferred.
