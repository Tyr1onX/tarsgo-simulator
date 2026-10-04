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