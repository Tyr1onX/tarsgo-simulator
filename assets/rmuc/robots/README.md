# RMUC robot sprites

All PNG files in this directory are original project presentation assets
generated with the built-in image-generation tool on 2026-10-06. No third-party
images, team photographs, official robot images, or network-sourced material
were used. The assets are distributed under the repository MIT license.

| File | Presentation role |
| --- | --- |
| `hero-chassis.png` | Heavy tracked Hero chassis, rendered with `body_angle`. |
| `hero-turret.png` | Hero turret and cannon, rendered with `turret_angle`. |
| `engineer.png` | Compact Engineer vehicle with articulated arm, rendered with `body_angle`. |
| `infantry-chassis.png` | Compact Infantry four-wheel chassis, rendered with `body_angle`. |
| `infantry-turret.png` | Light Infantry turret and cannon, rendered with `turret_angle`. |
| `sentry-chassis.png` | Broad heavy tracked Sentry chassis, rendered with `body_angle`. |
| `sentry-turret.png` | Wide twin-rail Sentry turret and autocannon, rendered with `turret_angle`. |
| `drone.png` | Four-rotor airborne Drone, rendered with `body_angle`. |

Every image has a transparent background. Dark graphite armor, restrained red
and blue accent panels, soft overhead shadows, and readable mechanical
silhouettes are shared across the set. Hero, Infantry, and Sentry use separate
chassis and turret layers so their body and weapon directions remain
independent.

Source prompts described orthographic top-down competition robots with dark
graphite metal, restrained red/blue details, mechanical structure and soft
shadows. Role-specific details requested the Hero's heavy cannon and tracked
chassis, Engineer's articulated gripper arm, compact four-wheel Infantry,
wide tracked Sentry with twin cannon rails, and Drone's four rotor guards.

Sprite dimensions and pixel bounds are presentation data only. The renderer
scales them using desktop visual profiles; collision footprints, navigation,
AI, official millimeter geometry, and rules do not read these files. If any
required sprite is missing or unreadable, the existing procedural robot
drawing remains the fallback.
