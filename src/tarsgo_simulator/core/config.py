"""Load and validate the small set of YAML files used by the V0 match."""

from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any

import yaml

from tarsgo_simulator.core.map import Rectangle


class ConfigError(ValueError):
    """Raised when a required training configuration value is invalid."""


@dataclass(frozen=True)
class InfantryRules:
    max_hp: int
    move_speed: float
    collision_radius: float
    attack_range: float
    attack_interval: float
    damage: int


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
    map_width: float
    map_height: float
    obstacles: tuple[Rectangle, ...]
    teams: dict[str, TeamDefinition]
    spawns: dict[str, tuple[float, float]]


@dataclass(frozen=True)
class MatchConfig:
    rules_id: str
    match_duration: float
    infantry: InfantryRules
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
    rules_data = _read_yaml(rules_file)
    _check_schema(rules_data, rules_file)
    actual_rules_id = _string(rules_data, "id", "id", rules_file)
    if actual_rules_id != rules_id:
        raise ConfigError(f"{rules_file}: `id` 必须与场景引用的规则 id `{rules_id}` 一致")
    if _string(rules_data, "status", "status", rules_file) != "synthetic":
        raise ConfigError(f"{rules_file}: `status` 必须为 `synthetic`，不能冒充官方参数")

    infantry_data = _mapping(rules_data, "infantry", "infantry", rules_file)
    infantry = InfantryRules(
        max_hp=_number(infantry_data, "max_hp", "infantry.max_hp", rules_file, integer=True),
        move_speed=_number(infantry_data, "move_speed", "infantry.move_speed", rules_file),
        collision_radius=_number(
            infantry_data, "collision_radius", "infantry.collision_radius", rules_file
        ),
        attack_range=_number(infantry_data, "attack_range", "infantry.attack_range", rules_file),
        attack_interval=_number(
            infantry_data, "attack_interval", "infantry.attack_interval", rules_file
        ),
        damage=_number(infantry_data, "damage", "infantry.damage", rules_file, integer=True),
    )
    match_duration = _number(rules_data, "match_duration", "match_duration", rules_file)

    setup = _mapping(scenario_data, "setup", "setup", scenario_file)
    map_data = _mapping(setup, "map", "setup.map", scenario_file)
    map_width = _number(map_data, "width", "setup.map.width", scenario_file)
    map_height = _number(map_data, "height", "setup.map.height", scenario_file)
    obstacles = _obstacles(map_data, scenario_file, map_width, map_height)

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

    spawn_data = _mapping(setup, "spawns", "setup.spawns", scenario_file)
    robot_ids = [robot.id for team in teams.values() for robot in team.robots]
    if len(set(robot_ids)) != len(robot_ids):
        raise ConfigError(f"{scenario_file}: 比赛内所有机器人 id 必须全局唯一")
    unknown_spawns = set(spawn_data) - set(robot_ids)
    if unknown_spawns:
        unknown = ", ".join(sorted(str(robot_id) for robot_id in unknown_spawns))
        raise ConfigError(f"{scenario_file}: 出生点引用了未配置的机器人：{unknown}")
    spawns = {robot_id: _point(spawn_data, robot_id, scenario_file) for robot_id in robot_ids}

    scenario = ScenarioDefinition(
        player_team=player_team,
        map_width=map_width,
        map_height=map_height,
        obstacles=obstacles,
        teams=teams,
        spawns=spawns,
    )
    return MatchConfig(rules_id, match_duration, infantry, scenario)


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
        if robot_type != "infantry":
            raise ConfigError(f"{path}: `{field}.type` 当前只支持 `infantry`")
        robot_ids.add(robot_id)
        definitions.append(RobotDefinition(robot_id, robot_type))

    return TeamDefinition(team_id, display_name, tuple(definitions))


def _safe_name(value: str, field: str, path: Path) -> str:
    if Path(value).name != value or value in {".", ".."}:
        raise ConfigError(f"{path}: `{field}` 只能是文件名")
    return value
