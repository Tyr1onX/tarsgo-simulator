"""Small desktop-only presentation helpers for the RMUC Pygame UI."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from tarsgo_simulator.core.map import TerrainConnection, TerrainFeature, Zone


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
    minimum_display_diameter: int


@dataclass(frozen=True)
class TerrainVisualMarker:
    """A screen-space terrain cue anchored to a semantic map marker.

    The anchor is not a terrain footprint, portal coordinate, or collision
    shape. Those remain deferred until the field diagrams provide exact XY
    extents.
    """

    kind: str
    center: tuple[float, float]


@dataclass(frozen=True)
class BadgeSpec:
    text: str
    tone: str = "neutral"


BASE_PROFILE = StructureVisualProfile(
    size=31,
    core_radius=8,
    ring_count=2,
    minimum_display_diameter=58,
)
OUTPOST_PROFILE = StructureVisualProfile(
    size=22,
    core_radius=6,
    ring_count=1,
    minimum_display_diameter=44,
)


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
    "resource": "资源区",
    "assembly": "装配区",
    "supply-buff": "补给区",
    "base-buff": "基地区",
    "outpost-buff": "前哨站区",
    "central-elevated-buff": "中央区",
    "trapezoid-buff": "梯形区",
    "fortress-buff": "堡垒区",
    "outpost-rebuild": "重建区",
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


def structure_display_size(
    structure_type: str,
    physical_size: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Return presentation dimensions without changing the physical footprint."""
    profile = structure_visual_profile(structure_type)
    width, height = physical_size or (profile.size * 2, profile.size * 2)
    minimum = profile.minimum_display_diameter
    return max(width, minimum), max(height, minimum)


def terrain_visual_markers(
    terrain_features: Iterable[TerrainFeature],
    terrain_connections: Iterable[TerrainConnection],
    zones: Iterable[Zone],
) -> tuple[TerrainVisualMarker, ...]:
    """Build visual-only cues from existing symbolic terrain anchors.

    Existing ``*-terrain-*`` zones are approximate location anchors, not
    terrain polygons. The returned markers intentionally use only their
    centers and never expose zone bounds to collision or pathfinding.
    """
    features = tuple(terrain_features)
    connections = tuple(terrain_connections)
    feature_kinds = {feature.kind for feature in features}
    connected_tunnels = {
        feature.id
        for feature in features
        if feature.kind == "tunnel"
        and any(connection.via_feature == feature.id for connection in connections)
    }
    markers: list[TerrainVisualMarker] = []
    for zone in zones:
        marker_name = zone.id.lower().removeprefix("red-").removeprefix("blue-")
        kind = None
        if marker_name.startswith("terrain-road-") and "surface" in feature_kinds:
            kind = "surface"
        elif marker_name.startswith("terrain-elevated-") and "elevated" in feature_kinds:
            kind = "elevated"
        elif marker_name.startswith("terrain-launch-") and "ramp" in feature_kinds:
            kind = "ramp"
        elif marker_name.startswith("terrain-tunnel-") and connected_tunnels:
            kind = "tunnel"
        if kind is None:
            continue
        center = (
            (
                sum(point[0] for point in zone.vertices) / len(zone.vertices),
                sum(point[1] for point in zone.vertices) / len(zone.vertices),
            )
            if zone.vertices
            else (zone.x + zone.width / 2, zone.y + zone.height / 2)
        )
        markers.append(TerrainVisualMarker(kind, center))
    return tuple(markers)


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
        badges.append(BadgeSpec("无敌", "shield"))

    defense = re.search(r"(?:^|\s)DEF\s+(\d+)%", raw_status)
    if defense:
        badges.append(BadgeSpec(f"防御 {defense.group(1)}%", "defense"))

    vulnerability = re.search(r"VULN(\d+)", raw_status)
    if vulnerability:
        badges.append(BadgeSpec(f"易伤 {vulnerability.group(1)}%", "danger"))

    if "FORT" in raw_status and "EFORT" not in raw_status:
        badges.append(BadgeSpec("堡垒", "fortress"))
    if "TDEF" in raw_status or "TCool" in raw_status:
        badges.append(BadgeSpec("地形增益", "terrain"))

    if permanently_locked:
        badges.append(BadgeSpec("永久禁射", "danger"))
    elif heat_locked:
        badges.append(BadgeSpec("禁射", "warning"))
    if power_off:
        badges.append(BadgeSpec("底盘断电", "warning"))
    return tuple(badges)


BASE_CONTROLS = (
    ("左键", "选择"),
    ("Shift+左键", "多选"),
    ("拖拽", "框选"),
    ("右键", "移动"),
    ("D", "调试几何"),
    ("R", "重新开始"),
    ("Esc", "退出"),
)

COMBAT_CONTROLS = (
    ("E", "本地兑换弹量"),
    ("F", "远程兑换弹量"),
)

ENGINEER_CONTROLS = (
    ("G", "获取能量单元"),
    ("1-4", "装配科技核心"),
    ("回车", "确认"),
    ("Q / W", "D4 核心选择"),
)

SPECTATOR_CONTROLS = (
    ("左键", "查看单位"),
    ("Shift+左键", "多选查看"),
    ("拖拽", "框选查看"),
    ("D", "调试几何"),
    ("R", "重新开始"),
    ("Esc", "退出"),
)


def contextual_controls(
    selected_robot_types: set[str] | frozenset[str],
    *,
    spectator: bool = False,
) -> tuple[tuple[str, str, bool], ...]:
    if spectator:
        return tuple((key, action, True) for key, action in SPECTATOR_CONTROLS)
    rows = [(key, action, True) for key, action in BASE_CONTROLS]
    if len(selected_robot_types) == 1:
        robot_type = next(iter(selected_robot_types))
        if robot_type in {"hero", "infantry", "sentry"}:
            rows.extend((key, action, True) for key, action in COMBAT_CONTROLS)
        elif robot_type == "engineer":
            rows.extend((key, action, True) for key, action in ENGINEER_CONTROLS)
    return tuple(rows)
