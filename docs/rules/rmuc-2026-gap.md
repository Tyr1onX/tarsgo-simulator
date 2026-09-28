# RMUC 2026 Regional V1.4.0 Gap

RuleSet: `rmuc-2026-region-v1.4.0`

This file distinguishes the implemented structure/lifecycle slice from the full
RMUC 2026 Regional V1.4.0 manual.

## Implemented in this round

- first-class regional V1.4.0 RuleSet identity and metadata;
- 420-second match duration;
- Hero ×1, Engineer ×1, Infantry ×2, Sentry ×1 per team;
- stationary damageable Base and Outpost entities;
- Base 5000 HP and Outpost 1500 HP;
- Outpost alive → Base invincible;
- Outpost destruction history;
- Base armor-deployed state at Base HP ≤ 2000;
- one Outpost rebuild opportunity per cumulative 1000 Base HP loss;
- large Base hits crossing multiple opportunity thresholds;
- synthetic red/blue Outpost rebuild zones;
- independent continuous rebuild progress per robot;
- Engineer 5 s rebuild;
- Hero / Infantry / Sentry 10 s rebuild;
- 300 s rebuild cutoff with incomplete progress cleared;
- rebuilt Outpost = 750 HP and one opportunity consumed;
- rebuilt Outpost restores Base invincibility;
- Robot-or-Structure combat targets with Robot-only attackers;
- 17 mm → 20 and 42 mm → 200 synthetic direct-damage intents;
- actual enemy Robot/Structure HP loss included in team attack damage;
- V1.4.0 Base/Outpost/attack-damage/Robot-HP result chain;
- minimal structure/rebuild HUD state;
- 2800 × 1500 synthetic Rules Lab world using the existing Viewport.

## Intentionally not implemented

- Drone;
- Radar;
- Dart System;
- Tech Core;
- Energy Unit;
- Experience;
- Performance progression;
- Energy Mechanism;
- complete Buff system;
- complete economy and projectile allowance;
- complete RMUC respawn;
- entity projectile physics;
- armor-module hit detection;
- official complete RMUC field geometry/elevation;
- 42 mm shield special case;
- Outpost rotation physics;
- Sentry automatic/semi-automatic mode differences, posture, remote exchange, or
  special commands;
- armor deployment geometry or hitbox changes.

### Outpost rotation

V1.4.0 includes opening rotation, acceleration over 5 seconds to 0.8π rad/s,
random direction, and multiple stop conditions. The current simulator has no
armor facing or projectile hitbox model, so rotation would have no observable
combat meaning. It is deliberately deferred instead of adding unused physics.

### Direct-damage boundary

The current 17 mm / 42 mm numbers are a combat resolution approximation. They do
not mean that armor-module detection, projectile flight, impact angle, projectile
speed, or hitbox geometry has been reproduced.

### Field boundary

The scenario's start areas, Base/Outpost positions, and rebuild rectangles are
synthetic approximations. This round does not claim official field-coordinate
fidelity.

## Next candidate

Stop after this slice. The next suggested RMUC phase is:

**RMUC-2: Experience + Performance**

Drone, Dart, Radar, and projectile physics should remain later work because many
subsequent mechanisms depend on dynamic level-dependent robot properties.
