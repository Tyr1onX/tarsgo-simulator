# RMUC robot sprites

All PNG files in this directory are original project presentation assets
generated with the built-in image-generation tool. The V2 set was generated on
2026-10-07 using the user's real Hero, Engineer, Infantry, Sentry, and Drone
photos as private structural references. The photos are not included in the
repository or shipped with the game. No third-party or network-sourced images
were used. The assets are distributed under the repository MIT license.

| File | Presentation role |
| --- | --- |
| `hero-chassis.png` | Open Hero chassis with visible wheel modules and CNC plates, rendered with `body_angle`. |
| `hero-turret.png` | Separate open Hero gimbal and 42 mm launcher, rendered with `turret_angle`. |
| `engineer.png` | Open Engineer chassis with lift and articulated tool, rendered with `body_angle`. |
| `infantry-chassis.png` | Compact four-mecanum Infantry chassis with exposed motors, rendered with `body_angle`. |
| `infantry-turret.png` | Separate compact Infantry gimbal and friction-wheel launcher, rendered with `turret_angle`. |
| `sentry-chassis.png` | Open four-wheel Sentry chassis with CNC panels, rendered with `body_angle`. |
| `sentry-turret.png` | Separate sensor gimbal and twin launcher rails, rendered with `turret_angle`. |
| `drone.png` | Drone with four large wire-mesh rotor guards, rendered with `body_angle`. |

Every image has a transparent background. Black anodized aluminum,
carbon-fiber, perforated CNC plates, exposed motors, wiring and sensors define
the shared style. The robots keep open competition-engineering structures
instead of enclosed armor. Hero, Infantry, and Sentry use separate chassis
and turret layers so their body and weapon directions remain independent.

The desktop renderer adds small, steady referee-system LED strips to the
chassis and turret layers. It colors those strips red or blue from the robot's
existing team identity, with a faint local bloom. It does not tint or illuminate
the rest of the robot art. Dead robots have their team LEDs switched off.

Source prompts describe orthographic top-down competition sprites with black
anodized-aluminum frames, carbon-fiber parts, CNC cutouts, visible motors,
wiring, sensors, and restrained team indicators. Role-specific details follow
the attached references: the Hero's broad drive chassis and gimbal, Engineer's
lift and manipulator, Infantry's compact four-mecanum frame, Sentry's
autonomous gimbal, and the Drone's four large mesh rotor guards. Text, team
numbers and logos are omitted from generated sprites.

## PR #84 Hero detail trial (2026-10-08)

The two Hero PNGs are **derived from the existing V2 originals** in commit
`fdb79dfcc50e372af0ec1d524156f0638961760e`; no third-party photos, new
AI illustrations, or externally sourced geometry were added. The pixel-level
trial preserves native size, transparent alpha, and layer registration, using
a mild per-channel gamma adjustment (0.83) and native-resolution unsharp mask
(radius 1.65, 62%, threshold 4). Source authorship and MIT permission remain
unchanged. The presentation-only gimbal footprint was reduced to uncover the
wheel modules, and its display rotation uses Pygame's filtered `rotozoom`.
See `docs/pr84-hero-visual-audit.md` for reproducible comparison evidence.

Sprite dimensions and pixel bounds are presentation data only. The renderer
scales them using desktop visual profiles; collision footprints, navigation,
AI, official millimeter geometry, and rules do not read these files. If any
required sprite is missing or unreadable, the existing procedural robot
drawing remains the fallback.
