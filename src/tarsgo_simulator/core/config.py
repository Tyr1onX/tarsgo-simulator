"""Load shared metadata and scenario data from the project's YAML files."""

from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml

from tarsgo_simulator.core.map import (
    Rectangle,
    TerrainConnection,
    TerrainFeature,
    Zone,
)


class ConfigError(ValueError):
    """Raised when a required configuration value is invalid."""


@dataclass(frozen=True)
class RuleMetadata:
    schema_version: int
    id: str
    status: str
    competition: str | None
    season: int | None
    format: str | None
    official_version: str | None
    source_url: str | None
    last_verified: str | None
    stage: str | None = None


@dataclass(frozen=True)
class RuleDocument:
    metadata: RuleMetadata
    data: Mapping[str, Any]
    path: Path


@dataclass(frozen=True)
class RobotDefinition:
    id: str
    type: str


@dataclass(frozen=True)
class TeamDefinition:
    team_id: str
    display_name: str
    robots: tuple[RobotDefinition, ...]


@dataclass(frozen=True)
class StructureDefinition:
    id: str
    type: str
    side: str
    team: str
    position: tuple[float, float]
    footprint: tuple[float, float] | None = None
    footprint_shape: str = "rectangle"
    footprint_vertices: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class ScenarioDefinition:
    player_team: str
    player_controlled: frozenset[str]
    map_width: float
    map_height: float
    obstacles: tuple[Rectangle, ...]
    zones: tuple[Zone, ...]
    teams: dict[str, TeamDefinition]
    structures: tuple[StructureDefinition, ...]
    spawns: dict[str, tuple[float, float]]
    path_grid_size: float = 20.0
    terrain_features: tuple[TerrainFeature, ...] = ()
    terrain_connections: tuple[TerrainConnection, ...] = ()


@dataclass(frozen=True)
class MatchConfig:
    rule_document: RuleDocument
    scenario: ScenarioDefinition


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[3]


def default_scenario_path() -> Path:
    return resource_root() / "configs" / "scenarios" / "first-steps.yaml"


def load_match_config(scenario_path: str | Path) -> MatchConfig:
    scenario_file = Path(scenario_path).resolve()
    config_root = scenario_file.parent.parent
    scenario_data = _read_yaml(scenario_file)
    _check_schema(scenario_data, scenario_file)

    rules_id = _string(scenario_data, "rules", "rules", scenario_file)
    player_team = _string(scenario_data, "player_team", "player_team", scenario_file)
    goals = _required(scenario_data, "learning_goals", "learning_goals", scenario_file)
    if not isinstance(goals, list) or not goals or not all(
        isinstance(goal, str) and goal.strip() for goal in goals
    ):
        raise ConfigError(f"{scenario_file}: `learning_goals` 必须是非空字符串列表")

    rules_file = config_root / "rules" / f"{_safe_name(rules_id, 'rules', scenario_file)}.yaml"
    if not rules_file.is_file():
        raise ConfigError(f"Unknown RuleSet id `{rules_id}`: 找不到规则配置文件 {rules_file}")
    rule_document = load_rule_document(rules_file, rules_id)

    setup = _mapping(scenario_data, "setup", "setup", scenario_file)
    field_geometry_id = scenario_data.get("field_geometry")
    field_geometry_data: dict[str, Any] | None = None
    terrain_features: tuple[TerrainFeature, ...] = ()
    terrain_connections: tuple[TerrainConnection, ...] = ()
    if field_geometry_id is not None:
        if not isinstance(field_geometry_id, str) or not field_geometry_id.strip():
            raise ConfigError(f"{scenario_file}: `field_geometry` 必须是非空 id")
        field_geometry_file = (
            config_root
            / "fields"
            / f"{_safe_name(field_geometry_id, 'field_geometry', scenario_file)}.yaml"
        )
        field_geometry_data = _read_yaml(field_geometry_file)
        if _string(field_geometry_data, "id", "id", field_geometry_file) != field_geometry_id:
            raise ConfigError(
                f"{field_geometry_file}: `id` 必须与场景引用的 `{field_geometry_id}` 一致"
            )
        if _string(field_geometry_data, "units", "units", field_geometry_file) != "mm":
            raise ConfigError(f"{field_geometry_file}: 官方场地坐标必须使用 mm")
        size = _mapping(field_geometry_data, "size_mm", "size_mm", field_geometry_file)
        map_width = _number(size, "length", "size_mm.length", field_geometry_file)
        map_height = _number(size, "width", "size_mm.width", field_geometry_file)
        path_grid_size = 200.0
        obstacles = _field_obstacles(
            field_geometry_data, field_geometry_file, map_width, map_height
        )
        zones = _zones(
            field_geometry_data, field_geometry_file, map_width, map_height,
            field="zones",
        )
        if field_geometry_data.get("team_symmetry") == "rotate_180":
            zones = _mirror_team_zones(zones, map_width, map_height)
        terrain_features, terrain_connections = _terrain(
            field_geometry_data, field_geometry_file
        )
    else:
        map_data = _mapping(setup, "map", "setup.map", scenario_file)
        map_width = _number(map_data, "width", "setup.map.width", scenario_file)
        map_height = _number(map_data, "height", "setup.map.height", scenario_file)
        obstacles = _obstacles(map_data, scenario_file, map_width, map_height)
        zones = _zones(map_data, scenario_file, map_width, map_height)
        path_grid_size = 20.0

    team_refs = _mapping(setup, "teams", "setup.teams", scenario_file)
    teams: dict[str, TeamDefinition] = {}
    for side in ("red", "blue"):
        team_id = _string(team_refs, side, f"setup.teams.{side}", scenario_file)
        team_file = config_root / "teams" / f"{_safe_name(team_id, 'team id', scenario_file)}.yaml"
        team = _load_team(team_file)
        if team.team_id != team_id:
            raise ConfigError(f"{team_file}: `team_id` 必须与场景引用的 `{team_id}` 一致")
        teams[side] = team
    if teams["red"].team_id == teams["blue"].team_id:
        raise ConfigError(f"{scenario_file}: 红蓝双方必须引用不同的队伍")
    if player_team not in {team.team_id for team in teams.values()}:
        raise ConfigError(f"{scenario_file}: `player_team` 必须是 setup.teams 中的一支队伍")

    structures = (
        _field_structures(
            field_geometry_data,
            config_root / "fields" / f"{field_geometry_id}.yaml",
            map_width,
            map_height,
            teams,
        )
        if field_geometry_data is not None
        else _structures(setup, scenario_file, map_width, map_height, teams)
    )

    player_controlled_values = _required(
        scenario_data, "player_controlled", "player_controlled", scenario_file
    )
    if (
        not isinstance(player_controlled_values, list)
        or not player_controlled_values
        or not all(
            isinstance(robot_id, str) and robot_id.strip()
            for robot_id in player_controlled_values
        )
    ):
        raise ConfigError(f"{scenario_file}: `player_controlled` 必须是非空字符串列表")
    player_controlled_list = [robot_id.strip() for robot_id in player_controlled_values]
    if len(player_controlled_list) != len(set(player_controlled_list)):
        raise ConfigError(f"{scenario_file}: `player_controlled` 中的机器人 id 必须唯一")

    spawn_data = _mapping(setup, "spawns", "setup.spawns", scenario_file)
    robot_ids = [robot.id for team in teams.values() for robot in team.robots]
    robot_teams_by_id = {
        robot.id: team.team_id
        for team in teams.values()
        for robot in team.robots
    }
    if len(set(robot_ids)) != len(robot_ids):
        raise ConfigError(f"{scenario_file}: 比赛内所有机器人 id 必须全局唯一")
    duplicate_damageable_ids = set(robot_ids) & {structure.id for structure in structures}
    if duplicate_damageable_ids:
        duplicates = ", ".join(sorted(duplicate_damageable_ids))
        raise ConfigError(f"{scenario_file}: 机器人与结构 id 不得重复：{duplicates}")
    unknown_controlled = set(player_controlled_list) - set(robot_ids)
    if unknown_controlled:
        unknown = ", ".join(sorted(unknown_controlled))
        raise ConfigError(f"{scenario_file}: `player_controlled` 引用了未配置的机器人：{unknown}")
    wrong_team = sorted(
        robot_id
        for robot_id in player_controlled_list
        if robot_teams_by_id[robot_id] != player_team
    )
    if wrong_team:
        raise ConfigError(
            f"{scenario_file}: `player_controlled` 只能包含 `player_team` 的机器人："
            f"{', '.join(wrong_team)}"
        )
    unknown_spawns = set(spawn_data) - set(robot_ids)
    if unknown_spawns:
        unknown = ", ".join(sorted(str(robot_id) for robot_id in unknown_spawns))
        raise ConfigError(f"{scenario_file}: 出生点引用了未配置的机器人：{unknown}")
    spawns = {robot_id: _point(spawn_data, robot_id, scenario_file) for robot_id in robot_ids}

    scenario = ScenarioDefinition(
        player_team=player_team,
        player_controlled=frozenset(player_controlled_list),
        map_width=map_width,
        map_height=map_height,
        obstacles=obstacles,
        zones=zones,
        teams=teams,
        structures=structures,
        spawns=spawns,
        path_grid_size=path_grid_size,
        terrain_features=terrain_features,
        terrain_connections=terrain_connections,
    )
    return MatchConfig(rule_document, scenario)


def load_rule_document(rule_path: str | Path, expected_id: str | None = None) -> RuleDocument:
    """Load one shared rule document for explicit RuleSet composition."""
    path = Path(rule_path).resolve()
    data = _read_yaml(path)
    rule_id = expected_id or _string(data, "id", "id", path)
    return _load_rule_document(data, path, rule_id)


def _load_rule_document(
    data: dict[str, Any], path: Path, expected_id: str
) -> RuleDocument:
    """Validate shared metadata while leaving rule-specific payloads to RuleSets."""
    version = _required(data, "schema_version", "schema_version", path)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ConfigError(f"{path}: schema_version 当前只支持整数 1")
    rule_id = _string(data, "id", "id", path)
    if rule_id != expected_id:
        raise ConfigError(f"{path}: `id` 必须与场景引用的规则 id `{expected_id}` 一致")
    status = _string(data, "status", "status", path)

    competition = _optional_string(data, "competition", path)
    season = data.get("season")
    if season is not None and (
        not isinstance(season, int) or isinstance(season, bool) or season < 1
    ):
        raise ConfigError(f"{path}: `season` 必须是正整数")
    metadata = RuleMetadata(
        schema_version=version,
        id=rule_id,
        status=status,
        competition=competition,
        season=season,
        format=_optional_string(data, "format", path),
        official_version=_optional_string(data, "official_version", path),
        source_url=_optional_string(data, "source_url", path),
        last_verified=_optional_string(data, "last_verified", path),
        stage=_optional_string(data, "stage", path),
    )
    return RuleDocument(metadata, data, path)


def _optional_string(data: dict[str, Any], key: str, path: Path) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}: `{key}` 必须是非空字符串或 null")
    return value.strip()


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"找不到配置文件：{path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 格式错误：{path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"读取配置失败：{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: 根节点必须是 YAML 字典")
    return data


def _check_schema(data: dict[str, Any], path: Path) -> None:
    version = _required(data, "schema_version", "schema_version", path)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ConfigError(f"{path}: schema_version 当前只支持整数 1")


def _required(data: dict[str, Any], key: str, field: str, path: Path) -> Any:
    if key not in data:
        raise ConfigError(f"{path}: 缺少必要字段 `{field}`")
    return data[key]


def _mapping(data: dict[str, Any], key: str, field: str, path: Path) -> dict[str, Any]:
    value = _required(data, key, field, path)
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: `{field}` 必须是 YAML 字典")
    return value


def _string(data: dict[str, Any], key: str, field: str, path: Path) -> str:
    value = _required(data, key, field, path)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}: `{field}` 必须是非空字符串")
    return value.strip()


def _number(
    data: dict[str, Any],
    key: str,
    field: str,
    path: Path,
    *,
    integer: bool = False,
    allow_zero: bool = False,
) -> int | float:
    value = _required(data, key, field, path)
    valid_type = isinstance(value, int) if integer else isinstance(value, (int, float))
    valid = valid_type and not isinstance(value, bool) and math.isfinite(value)
    valid = valid and (value >= 0 if allow_zero else value > 0)
    if not valid:
        qualifier = "非负" if allow_zero else "大于 0 的"
        kind = "整数" if integer else "数字"
        raise ConfigError(f"{path}: `{field}` 必须是{qualifier}{kind}")
    return value


def _point(data: dict[str, Any], robot_id: str, path: Path) -> tuple[float, float]:
    value = _required(data, robot_id, f"setup.spawns.{robot_id}", path)
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigError(f"{path}: `setup.spawns.{robot_id}` 必须是 [x, y]")
    point = tuple(value)
    if any(
        not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item)
        for item in point
    ):
        raise ConfigError(f"{path}: `setup.spawns.{robot_id}` 必须是数字坐标")
    return float(point[0]), float(point[1])


def _obstacles(
    map_data: dict[str, Any],
    path: Path,
    map_width: float,
    map_height: float,
) -> tuple[Rectangle, ...]:
    values = _required(map_data, "obstacles", "setup.map.obstacles", path)
    if not isinstance(values, list):
        raise ConfigError(f"{path}: `setup.map.obstacles` 必须是列表")

    result = []
    for index, value in enumerate(values):
        field = f"setup.map.obstacles[{index}]"
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: `{field}` 必须是 YAML 字典")
        obstacle = Rectangle(
            x=_number(value, "x", f"{field}.x", path, allow_zero=True),
            y=_number(value, "y", f"{field}.y", path, allow_zero=True),
            width=_number(value, "width", f"{field}.width", path),
            height=_number(value, "height", f"{field}.height", path),
        )
        if obstacle.right > map_width or obstacle.bottom > map_height:
            raise ConfigError(f"{path}: `{field}` 超出地图边界")
        result.append(obstacle)
    return tuple(result)


def _zones(
    map_data: dict[str, Any],
    path: Path,
    map_width: float,
    map_height: float,
    *,
    field: str = "zones",
) -> tuple[Zone, ...]:
    values = map_data.get(field, [])
    if not isinstance(values, list):
        raise ConfigError(f"{path}: `{field}` 必须是列表")

    result = []
    zone_ids: set[str] = set()
    for index, value in enumerate(values):
        item_field = f"{field}[{index}]"
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: `{item_field}` 必须是 YAML 字典")
        zone_id = _string(value, "id", f"{item_field}.id", path)
        if zone_id in zone_ids:
            raise ConfigError(f"{path}: 区域 id `{zone_id}` 重复")
        if "points" in value:
            vertices = _vertices(value, item_field, path, map_width, map_height)
            xs = [point[0] for point in vertices]
            ys = [point[1] for point in vertices]
            zone = Zone(
                id=zone_id,
                x=min(xs),
                y=min(ys),
                width=max(xs) - min(xs),
                height=max(ys) - min(ys),
                vertices=vertices,
            )
        else:
            zone = Zone(
                id=zone_id,
                x=_number(value, "x", f"{item_field}.x", path, allow_zero=True),
                y=_number(value, "y", f"{item_field}.y", path, allow_zero=True),
                width=_number(value, "width", f"{item_field}.width", path),
                height=_number(value, "height", f"{item_field}.height", path),
            )
        if zone.right > map_width or zone.bottom > map_height:
            raise ConfigError(f"{path}: `{field}` 超出地图边界")
        zone_ids.add(zone_id)
        result.append(zone)
    return tuple(result)


def _vertices(
    data: dict[str, Any],
    field: str,
    path: Path,
    map_width: float,
    map_height: float,
) -> tuple[tuple[float, float], ...]:
    raw = _required(data, "points", f"{field}.points", path)
    if not isinstance(raw, list) or len(raw) < 3:
        raise ConfigError(f"{path}: `{field}.points` 必须至少包含三个 [x, y]")
    vertices: list[tuple[float, float]] = []
    for index, value in enumerate(raw):
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(
                not isinstance(item, (int, float))
                or isinstance(item, bool)
                or not math.isfinite(item)
                for item in value
            )
        ):
            raise ConfigError(f"{path}: `{field}.points[{index}]` 必须是数字 [x, y]")
        point = (float(value[0]), float(value[1]))
        if not (0 <= point[0] <= map_width and 0 <= point[1] <= map_height):
            raise ConfigError(f"{path}: `{field}.points[{index}]` 超出场地边界")
        vertices.append(point)
    return tuple(vertices)


def _field_obstacles(
    data: dict[str, Any],
    path: Path,
    map_width: float,
    map_height: float,
) -> tuple[Rectangle, ...]:
    values = data.get("obstacles", [])
    if not isinstance(values, list):
        raise ConfigError(f"{path}: `obstacles` 必须是列表")
    map_data = {"obstacles": values}
    return _obstacles(map_data, path, map_width, map_height)


def _field_structures(
    data: dict[str, Any],
    path: Path,
    map_width: float,
    map_height: float,
    teams: dict[str, TeamDefinition],
) -> tuple[StructureDefinition, ...]:
    values = _required(data, "structures", "structures", path)
    if not isinstance(values, list):
        raise ConfigError(f"{path}: `structures` 必须是列表")
    result = []
    for index, value in enumerate(values):
        field = f"structures[{index}]"
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: `{field}` 必须是 YAML 字典")
        side = _string(value, "side", f"{field}.side", path)
        if side not in teams:
            raise ConfigError(f"{path}: `{field}.side` 必须是 red 或 blue")
        raw_position = _required(value, "position", f"{field}.position", path)
        if (
            not isinstance(raw_position, list)
            or len(raw_position) != 2
            or any(
                not isinstance(item, (int, float))
                or isinstance(item, bool)
                or not math.isfinite(item)
                for item in raw_position
            )
        ):
            raise ConfigError(f"{path}: `{field}.position` 必须是数字 [x, y]")
        position = (float(raw_position[0]), float(raw_position[1]))
        if not (0 <= position[0] <= map_width and 0 <= position[1] <= map_height):
            raise ConfigError(f"{path}: `{field}.position` 超出场地边界")
        dimensions = _required(value, "footprint", f"{field}.footprint", path)
        if not isinstance(dimensions, dict):
            raise ConfigError(f"{path}: `{field}.footprint` 必须是 YAML 字典")
        footprint = (
            float(_number(dimensions, "width", f"{field}.footprint.width", path)),
            float(_number(dimensions, "height", f"{field}.footprint.height", path)),
        )
        footprint_shape = dimensions.get("shape", "rectangle")
        if not isinstance(footprint_shape, str) or footprint_shape not in {
            "rectangle",
            "circle",
            "polygon",
        }:
            raise ConfigError(
                f"{path}: `{field}.footprint.shape` 必须是 rectangle、circle 或 polygon"
            )
        if footprint_shape == "circle" and footprint[0] != footprint[1]:
            raise ConfigError(f"{path}: `{field}.footprint` 圆形的宽高必须相同")
        footprint_vertices = (
            _local_footprint_vertices(
                dimensions,
                f"{field}.footprint",
                path,
                footprint,
            )
            if footprint_shape == "polygon"
            else ()
        )
        if footprint_vertices:
            xs = [x for x, _y in footprint_vertices]
            ys = [y for _x, y in footprint_vertices]
            if not (
                math.isclose(max(xs) - min(xs), footprint[0], abs_tol=1e-6)
                and math.isclose(max(ys) - min(ys), footprint[1], abs_tol=1e-6)
            ):
                raise ConfigError(
                    f"{path}: `{field}.footprint.points` 的包围尺寸必须与 width/height 一致"
                )
        structure_type = _string(value, "type", f"{field}.type", path)
        structure_id = f"{side}-{structure_type}"
        if any(item.id == structure_id for item in result):
            raise ConfigError(f"{path}: `{field}` 生成了重复结构 id `{structure_id}`")
        result.append(
            StructureDefinition(
                id=structure_id,
                type=structure_type,
                side=side,
                team=teams[side].team_id,
                position=position,
                footprint=footprint,
                footprint_shape=footprint_shape,
                footprint_vertices=footprint_vertices,
            )
        )
        if data.get("team_symmetry") == "rotate_180" and side == "red":
            blue_id = f"blue-{structure_type}"
            if any(item.id == blue_id for item in result):
                raise ConfigError(f"{path}: `{field}` 生成了重复结构 id `{blue_id}`")
            result.append(
                StructureDefinition(
                    id=blue_id,
                    type=structure_type,
                    side="blue",
                    team=teams["blue"].team_id,
                    position=(map_width - position[0], map_height - position[1]),
                    footprint=footprint,
                    footprint_shape=footprint_shape,
                    footprint_vertices=tuple(
                        (-x, -y) for x, y in footprint_vertices
                    ),
                )
            )
    return tuple(result)


def _terrain(
    data: Mapping[str, Any], path: Path
) -> tuple[tuple[TerrainFeature, ...], tuple[TerrainConnection, ...]]:
    raw = data.get("terrain", {})
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: `terrain` 必须是映射")
    raw_features = raw.get("features", [])
    raw_connections = raw.get("connections", [])
    if not isinstance(raw_features, list) or not isinstance(raw_connections, list):
        raise ConfigError(f"{path}: terrain.features/connections 必须是列表")

    features: list[TerrainFeature] = []
    feature_ids: set[str] = set()
    allowed_kinds = {"ground", "elevated", "surface", "ramp", "tunnel"}
    for index, item in enumerate(raw_features):
        label = f"terrain.features[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{path}: `{label}` 必须是映射")
        feature_id = _string(item, "id", f"{label}.id", path)
        kind = _string(item, "kind", f"{label}.kind", path)
        if feature_id in feature_ids:
            raise ConfigError(f"{path}: terrain feature id 重复：{feature_id}")
        if kind not in allowed_kinds:
            raise ConfigError(f"{path}: `{label}.kind` 无效：{kind}")
        feature_ids.add(feature_id)

        raw_height = item.get("relative_height_mm")
        height: tuple[float, float] | None = None
        if raw_height is not None:
            if (
                not isinstance(raw_height, list)
                or len(raw_height) != 2
                or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    for value in raw_height
                )
                or raw_height[0] > raw_height[1]
            ):
                raise ConfigError(
                    f"{path}: `{label}.relative_height_mm` 必须是有序的两元素数值列表"
                )
            height = (float(raw_height[0]), float(raw_height[1]))
        raw_slope = item.get("slope_degrees")
        slope: float | None = None
        if raw_slope is not None:
            if (
                not isinstance(raw_slope, (int, float))
                or isinstance(raw_slope, bool)
                or not math.isfinite(raw_slope)
                or not 0 < raw_slope < 90
            ):
                raise ConfigError(
                    f"{path}: `{label}.slope_degrees` 必须介于 0° 与 90°"
                )
            slope = float(raw_slope)
        source = item.get("source", "")
        if not isinstance(source, str):
            raise ConfigError(f"{path}: `{label}.source` 必须是字串")
        features.append(
            TerrainFeature(feature_id, kind, height, slope, source.strip())
        )

    feature_by_id = {feature.id: feature for feature in features}
    connections: list[TerrainConnection] = []
    seen_connections: set[tuple[str, str, str]] = set()
    used_connectors: set[str] = set()
    for index, item in enumerate(raw_connections):
        label = f"terrain.connections[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{path}: `{label}` 必须是映射")
        from_surface = _string(item, "from", f"{label}.from", path)
        to_surface = _string(item, "to", f"{label}.to", path)
        via_feature = _string(item, "via", f"{label}.via", path)
        missing = {from_surface, to_surface, via_feature} - feature_by_id.keys()
        if missing:
            raise ConfigError(
                f"{path}: `{label}` 引用了未知地形：{', '.join(sorted(missing))}"
            )
        if from_surface == to_surface:
            raise ConfigError(f"{path}: `{label}` 起点与终点不能相同")
        if feature_by_id[via_feature].kind not in {"ramp", "tunnel"}:
            raise ConfigError(f"{path}: `{label}.via` 必须是坡道或隧道")
        if (
            feature_by_id[from_surface].kind not in {"ground", "elevated", "surface"}
            or feature_by_id[to_surface].kind not in {"ground", "elevated", "surface"}
        ):
            raise ConfigError(
                f"{path}: `{label}` 起点与终点必须是地面、高地或未定层级表面"
            )
        if via_feature in used_connectors:
            raise ConfigError(f"{path}: connector `{via_feature}` 只能连接一组表面")
        key = (from_surface, to_surface, via_feature)
        if key in seen_connections:
            raise ConfigError(f"{path}: terrain connection 重复：{key}")
        seen_connections.add(key)
        used_connectors.add(via_feature)
        connections.append(TerrainConnection(*key))
    return tuple(features), tuple(connections)


def _local_footprint_vertices(
    data: dict[str, Any],
    field: str,
    path: Path,
    footprint: tuple[float, float],
) -> tuple[tuple[float, float], ...]:
    raw = _required(data, "points", f"{field}.points", path)
    if not isinstance(raw, list) or len(raw) < 3:
        raise ConfigError(f"{path}: `{field}.points` 必须至少包含三个 [x, y]")
    vertices: list[tuple[float, float]] = []
    for index, value in enumerate(raw):
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(
                not isinstance(item, (int, float))
                or isinstance(item, bool)
                or not math.isfinite(item)
                for item in value
            )
        ):
            raise ConfigError(f"{path}: `{field}.points[{index}]` 必须是数字 [x, y]")
        point = (float(value[0]), float(value[1]))
        if abs(point[0]) > footprint[0] / 2 or abs(point[1]) > footprint[1] / 2:
            raise ConfigError(f"{path}: `{field}.points[{index}]` 超出 footprint 尺寸")
        vertices.append(point)
    return tuple(vertices)


def _mirror_team_zones(
    zones: tuple[Zone, ...], map_width: float, map_height: float
) -> tuple[Zone, ...]:
    mirrored = list(zones)
    for zone in zones:
        if not zone.id.startswith("red-"):
            continue
        vertices = tuple(
            (map_width - x, map_height - y)
            for x, y in zone.polygon
        )
        xs = [x for x, _y in vertices]
        ys = [y for _x, y in vertices]
        mirrored.append(
            Zone(
                id=f"blue-{zone.id.removeprefix('red-')}",
                x=min(xs),
                y=min(ys),
                width=max(xs) - min(xs),
                height=max(ys) - min(ys),
                vertices=vertices,
            )
        )
    return tuple(mirrored)


def _structures(
    setup: dict[str, Any],
    path: Path,
    map_width: float,
    map_height: float,
    teams: dict[str, TeamDefinition],
) -> tuple[StructureDefinition, ...]:
    values = setup.get("structures", [])
    if not isinstance(values, list):
        raise ConfigError(f"{path}: `setup.structures` 必须是列表")

    result = []
    structure_ids: set[str] = set()
    for index, value in enumerate(values):
        field = f"setup.structures[{index}]"
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: `{field}` 必须是 YAML 字典")
        if set(value) != {"id", "type", "side", "position"}:
            raise ConfigError(
                f"{path}: `{field}` 只能包含 id、type、side、position"
            )
        structure_id = _string(value, "id", f"{field}.id", path)
        if structure_id in structure_ids:
            raise ConfigError(f"{path}: 结构 id `{structure_id}` 重复")
        side = _string(value, "side", f"{field}.side", path)
        if side not in teams:
            raise ConfigError(f"{path}: `{field}.side` 必须是 red 或 blue")
        raw_position = _required(value, "position", f"{field}.position", path)
        if not isinstance(raw_position, list) or len(raw_position) != 2:
            raise ConfigError(f"{path}: `{field}.position` 必须是 [x, y]")
        if any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(item)
            for item in raw_position
        ):
            raise ConfigError(f"{path}: `{field}.position` 必须是数字坐标")
        position = (float(raw_position[0]), float(raw_position[1]))
        if not (0 <= position[0] <= map_width and 0 <= position[1] <= map_height):
            raise ConfigError(f"{path}: `{field}.position` 超出地图边界")
        structure_ids.add(structure_id)
        result.append(
            StructureDefinition(
                id=structure_id,
                type=_string(value, "type", f"{field}.type", path),
                side=side,
                team=teams[side].team_id,
                position=position,
            )
        )
    return tuple(result)


def _load_team(path: Path) -> TeamDefinition:
    data = _read_yaml(path)
    _check_schema(data, path)
    team_id = _string(data, "team_id", "team_id", path)
    display_name = _string(data, "display_name", "display_name", path)
    robots = _required(data, "robots", "robots", path)
    if not isinstance(robots, list) or not robots:
        raise ConfigError(f"{path}: `robots` 必须是非空列表")

    definitions = []
    robot_ids: set[str] = set()
    for index, value in enumerate(robots):
        field = f"robots[{index}]"
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: `{field}` 必须是 YAML 字典")
        robot_id = _string(value, "id", f"{field}.id", path)
        robot_type = _string(value, "type", f"{field}.type", path)
        if robot_id in robot_ids:
            raise ConfigError(f"{path}: 机器人 id `{robot_id}` 在同一队中重复")
        robot_ids.add(robot_id)
        definitions.append(RobotDefinition(robot_id, robot_type))

    return TeamDefinition(team_id, display_name, tuple(definitions))


def _safe_name(value: str, field: str, path: Path) -> str:
    if Path(value).name != value or value in {".", ".."}:
        raise ConfigError(f"{path}: `{field}` 只能是文件名")
    return value
