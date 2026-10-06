# RMUC presentation assets

The assets in this directory belong to the desktop presentation layer. They
are loaded by `tarsgo_simulator.desktop.assets.AssetManager` and are never
used to calculate gameplay state.

## First batch

| Path | Use | Source |
| --- | --- | --- |
| `field/floor-surface.png` | Arena floor material | Original project asset generated for PR #67 on 2026-10-06. Prompt: orthographic top-down graphite-gray matte composite panels with large restrained seams, a subtle brushed technical surface, sparse cool-white and muted-blue details; no arena objects, markings, symbols, text, logos, neon, or hexagons. |
| `structures/base.png` | Base sprite | Original project asset generated for this simulator on 2026-10-06. Prompt: isolated, transparent, orthographic armored arena base with charcoal metal, silver edges, amber lights, and restrained red/blue panels; no marks, logos, text, or external references. |
| `structures/outpost.png` | Outpost sprite | Original project asset generated for this simulator on 2026-10-06. Prompt: isolated, transparent, orthographic circular arena outpost with a segmented metal ring, central hub, amber lights, and restrained red/blue panels; no marks, logos, text, or external references. |
| `robots/*.png` | Five RMUC robot types and layered weapon art | Original project assets generated with the built-in image-generation tool on 2026-10-07, guided by the user's real RMUC robot photos. Role-specific prompts and file mapping are documented in `robots/README.md`. |

These are self-created assets produced with the built-in image-generation tool
from the prompts above. The robot sprites use the user's private real-robot
photos as structural references; those source photos are not copied into this
repository. No third-party or network-sourced materials were used. The assets
are distributed under the repository license in `LICENSE`.

## Rendering boundary

```text
official millimeter geometry -> collision / A* / LOS / rules
official millimeter position -> viewport -> sprite rendering
```

Structure sprites are scaled to display sizes derived by the renderer from the
existing viewport and structure geometry. Robot sprites use the existing
desktop visual profiles and `body_angle` / `turret_angle`. Their source pixel
dimensions do not define or modify structure or robot footprints. Missing or
unreadable sprites use the existing procedural drawing fallback. `terrain/`
remains reserved for later presentation-only additions.

## Field region rendering

The default view adds low-contrast floor treatments only for existing
start, base, outpost, resource and assembly polygons in the field map. Road
markings use the existing symbolic terrain anchors as small surface cues; they
do not claim or draw a road footprint. Unmapped terrain polygons remain
deferred. Debug mode continues to display the internal zone and terrain
topology.
