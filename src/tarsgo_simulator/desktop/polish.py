"""Small desktop-only presentation helpers for the RMUC Pygame UI."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ZoneVisualStyle:
    label: str
    family: str
    emphasized: bool = False


@dataclass(frozen=True)
class StructureVisualProfile:
    size: int
    core_radius: int
    ring_count: int


@dataclass(frozen=True)
class BadgeSpec:
    text: str
    tone: str = "neutral"


BASE_PROFILE = StructureVisualProfile(size=31, core_radius=8, ring_count=2)
OUTPOST_PROFILE = StructureVisualProfile(size=22, core_radius=6, ring_count=1)


_ZONE_FAMILIES = {
    "resource": "resource",
    "assembly": "assembly",
    "supply-buff": "supply",
    "base-buff": "defense",
    "outpost-buff": "defense",
    "central-elevated-buff": "central",
    "trapezoid-buff": "defense",
    "fortress-buff": "fortress",
    "outpost-rebuild": "rebuild",
}

_ZONE_LABELS = {
    "resource": "RESOURCE",
    "assembly": "ASSEMBLY",
    "supply-buff": "SUPPLY",
    "base-buff": "BASE",
    "outpost-buff": "OUTPOST",
    "central-elevated-buff": "CENTRAL",
    "trapezoid-buff": "TRAPEZOID",
    "fortress-buff": "FORTRESS",
    "outpost-rebuild": "REBUILD",
}

_ROLE_ZONE_FAMILIES = {
    "engineer": frozenset({"resource", "assembly", "supply", "rebuild"}),
    "hero": frozenset({"supply", "fortress", "defense", "central"}),
    "infantry": frozenset({"supply", "fortress", "defense", "central"}),
    "sentry": frozenset({"supply", "fortress", "defense", "central"}),
}


def _zone_suffix(zone_id: str) -> str | None:
    normalized = zone_id.lower()
    for prefix in ("red-", "blue-"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    return normalized if normalized in _ZONE_FAMILIES else None


def zone_visual_style(
    zone_id: str,
    *,
    selected_robot_types: set[str] | frozenset[str] = frozenset(),
) -> ZoneVisualStyle | None:
    suffix = _zone_suffix(zone_id)
    if suffix is None:
        return None
    family = _ZONE_FAMILIES[suffix]
    relevant = set()
    for robot_type in selected_robot_types:
        relevant.update(_ROLE_ZONE_FAMILIES.get(robot_type, ()))
    return ZoneVisualStyle(
        label=_ZONE_LABELS[suffix],
        family=family,
        emphasized=family in relevant,
    )


def structure_visual_profile(structure_type: str) -> StructureVisualProfile:
    return BASE_PROFILE if structure_type == "base" else OUTPOST_PROFILE


def parse_virtual_shield(status: str) -> int:
    match = re.search(r"(?:^|\s)SH:(\d+)(?:\s|$)", status)
    return int(match.group(1)) if match else 0


def status_badges(
    raw_status: str,
    *,
    invincible: bool = False,
    heat_locked: bool = False,
    permanently_locked: bool = False,
    power_off: bool = False,
) -> tuple[BadgeSpec, ...]:
    badges: list[BadgeSpec] = []
    if invincible:
        badges.append(BadgeSpec("INV", "shield"))

    defense = re.search(r"(?:^|\s)DEF\s+(\d+)%", raw_status)
    if defense:
        badges.append(BadgeSpec(f"DEF {defense.group(1)}", "defense"))

    vulnerability = re.search(r"VULN(\d+)", raw_status)
    if vulnerability:
        badges.append(BadgeSpec(f"VUL {vulnerability.group(1)}", "danger"))

    if "FORT" in raw_status and "EFORT" not in raw_status:
        badges.append(BadgeSpec("FORT", "fortress"))
    if "TDEF" in raw_status or "TCool" in raw_status:
        badges.append(BadgeSpec("TERRAIN", "terrain"))

    if permanently_locked:
        badges.append(BadgeSpec("PERM", "danger"))
    elif heat_locked:
        badges.append(BadgeSpec("LOCK", "warning"))
    if power_off:
        badges.append(BadgeSpec("PWR OFF", "warning"))
    return tuple(badges)


BASE_CONTROLS = (
    ("LMB", "Select"),
    ("Shift/LMB", "Multi-select"),
    ("Drag", "Box select"),
    ("RMB", "Move"),
    ("D", "Debug"),
    ("R", "Restart"),
    ("Esc", "Quit"),
)

COMBAT_CONTROLS = (
    ("E", "Local ammo"),
    ("F", "Remote ammo"),
)

ENGINEER_CONTROLS = (
    ("G", "Energy Unit"),
    ("1-4", "Tech Core"),
    ("Enter", "Confirm"),
    ("Q / W", "D4 Core"),
)


def contextual_controls(
    selected_robot_types: set[str] | frozenset[str],
) -> tuple[tuple[str, str, bool], ...]:
    rows = [(key, action, True) for key, action in BASE_CONTROLS]
    if len(selected_robot_types) == 1:
        robot_type = next(iter(selected_robot_types))
        if robot_type in {"hero", "infantry", "sentry"}:
            rows.extend((key, action, True) for key, action in COMBAT_CONTROLS)
        elif robot_type == "engineer":
            rows.extend((key, action, True) for key, action in ENGINEER_CONTROLS)
    return tuple(rows)
