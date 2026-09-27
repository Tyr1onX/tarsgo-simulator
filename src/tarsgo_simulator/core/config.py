"""Load shared metadata and scenario data from the project's YAML files."""

from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml

from tarsgo_simulator.core.map import Rectangle, Zone


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
class ScenarioDefinition:
    player_team: str
    player_controlled: frozenset[str]
    map_width: float
    map_height: float
    obstacles: tuple[Rectangle, ...]
    zones: tuple[Zone, ...]
    teams: dict[str, TeamDefinition]
    spawns: dict[str, tuple[float, float]]


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
    map_data = _mapping(setup, "map", "setup.map", scenario_file)
    map_width = _number(map_data, "width", "setup.map.width", scenario_file)
    map_height = _number(map_data, "height", "setup.map.height", scenario_file)
    obstacles = _obstacles(map_data, scenario_file, map_width, map_height)
    zones = _zones(map_data, scenario_file, map_width, map_height)

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
        spawns=spawns,
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
) -> tuple[Zone, ...]:
    values = map_data.get("zones", [])
    if not isinstance(values, list):
        raise ConfigError(f"{path}: `setup.map.zones` 必须是列表")

    result = []
    zone_ids: set[str] = set()
    for index, value in enumerate(values):
        field = f"setup.map.zones[{index}]"
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: `{field}` 必须是 YAML 字典")
        zone_id = _string(value, "id", f"{field}.id", path)
        if zone_id in zone_ids:
            raise ConfigError(f"{path}: 区域 id `{zone_id}` 重复")
        zone = Zone(
            id=zone_id,
            x=_number(value, "x", f"{field}.x", path, allow_zero=True),
            y=_number(value, "y", f"{field}.y", path, allow_zero=True),
            width=_number(value, "width", f"{field}.width", path),
            height=_number(value, "height", f"{field}.height", path),
        )
        if zone.right > map_width or zone.bottom > map_height:
            raise ConfigError(f"{path}: `{field}` 超出地图边界")
        zone_ids.add(zone_id)
        result.append(zone)
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
