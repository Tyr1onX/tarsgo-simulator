"""Partial RMUC 2026 Regional V1.4.0 rules including Experience/Performance."""

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING, Any, Mapping

from tarsgo_simulator.core.config import ConfigError, RuleDocument
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.map import Zone
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure
from tarsgo_simulator.rules.protocol import (
    DamageableTarget,
    MatchResult,
    RobotParameters,
    RuleSetDisplayState,
    StructureParameters,
)


_RMUC_ROBOT_TYPES = ("hero", "engineer", "infantry", "sentry")
_REBUILD_ROBOT_TYPES = {"hero", "engineer", "infantry", "sentry"}
_EXPERIENCE_ROBOT_TYPES = {"hero", "infantry"}


@dataclass
class _RobotProgressionState:
    experience: float = 0.0
    level: int = 1


@dataclass(frozen=True)
class _EffectivePerformance:
    max_hp: int
    chassis_power_limit: int
    heat_limit: int
    cooling_per_second: int


@dataclass
class _EngineerResourceState:
    carrying_energy_unit: bool = False


@dataclass
class _TechCoreAttempt:
    engineer_id: str
    difficulty: int
    outside_zone_elapsed: float = 0.0


@dataclass(frozen=True)
class _TechCoreDifficultyRule:
    available_after: float
    prerequisite: int | None
    first_level_cap: int | None
    first_periodic_gold_per_10s: int
    repeat_periodic_gold_per_10s: int
    first_defense_bonus: float | None = None


@dataclass
class _TechCoreTeamState:
    completion_count_by_difficulty: dict[int, int] = field(
        default_factory=lambda: {1: 0, 2: 0, 3: 0}
    )
    active_attempt: _TechCoreAttempt | None = None


@dataclass
class _TeamStructureState:
    outpost_ever_destroyed: bool = False
    base_damage_lost: int = 0
    outpost_rebuild_opportunities: int = 0
    rebuild_progress_by_robot: dict[str, float] = field(default_factory=dict)
    base_armor_deployed: bool = False


class RMUC2026RegionalRules:
    """V1.4.0 regional Rules Lab slice with progression and Tech Core D1-D3."""

    def __init__(self, document: RuleDocument) -> None:
        metadata = document.metadata
        if metadata.status != "official-partial":
            raise ConfigError(
                f"{document.path}: rmuc-2026-region-v1.4.0 requires "
                "`status: official-partial`"
            )
        if metadata.competition != "RMUC":
            raise ConfigError(f"{document.path}: `competition` 必须是 RMUC")
        if metadata.season != 2026:
            raise ConfigError(f"{document.path}: `season` 必须是 2026")
        if metadata.stage != "regional":
            raise ConfigError(f"{document.path}: `stage` 必须是 regional")
        if metadata.official_version != "1.4.0":
            raise ConfigError(
                f"{document.path}: this implementation is verified against manual V1.4.0"
            )

        self._document = document
        self._time_limit = _number(
            document.data, "match_duration", document, "match_duration"
        )

        structures = _mapping(document.data, "structures", document)
        if set(structures) != {"base", "outpost"}:
            raise ConfigError(
                f"{document.path}: `structures` 必须只包含 base、outpost"
            )
        self._structure_parameters = {
            structure_type: StructureParameters(
                max_hp=_positive_integer(
                    _mapping(structures, structure_type, document),
                    "max_hp",
                    document,
                    f"structures.{structure_type}.max_hp",
                )
            )
            for structure_type in ("base", "outpost")
        }

        rebuild = _mapping(document.data, "outpost_rebuild", document)
        self._base_damage_threshold = _positive_integer(
            rebuild,
            "base_damage_threshold",
            document,
            "outpost_rebuild.base_damage_threshold",
        )
        self._rebuilt_outpost_hp = _positive_integer(
            rebuild,
            "restored_hp",
            document,
            "outpost_rebuild.restored_hp",
        )
        self._rebuild_cutoff = _number(
            rebuild,
            "cutoff_seconds",
            document,
            "outpost_rebuild.cutoff_seconds",
        )
        durations = _mapping(rebuild, "durations", document)
        self._default_rebuild_duration = _number(
            durations,
            "default",
            document,
            "outpost_rebuild.durations.default",
        )
        self._engineer_rebuild_duration = _number(
            durations,
            "engineer",
            document,
            "outpost_rebuild.durations.engineer",
        )
        zones = _mapping(rebuild, "zones", document)
        self._rebuild_zone_ids = {
            side: _string(zones, side, document, f"outpost_rebuild.zones.{side}")
            for side in ("red", "blue")
        }
        if len(set(self._rebuild_zone_ids.values())) != 2:
            raise ConfigError(
                f"{document.path}: red / blue 前哨站重建区必须使用不同 zone id"
            )

        tech_core = _mapping(document.data, "tech_core", document)
        if set(tech_core) != {"leave_zone_fail_after", "zones", "difficulties"}:
            raise ConfigError(
                f"{document.path}: `tech_core` 字段不完整或包含未知字段"
            )
        self._tech_core_leave_zone_fail_after = _number(
            tech_core,
            "leave_zone_fail_after",
            document,
            "tech_core.leave_zone_fail_after",
        )

        tech_core_zones = _mapping(tech_core, "zones", document)
        if set(tech_core_zones) != {"red", "blue"}:
            raise ConfigError(
                f"{document.path}: `tech_core.zones` 必须包含 red、blue"
            )
        self._tech_core_zone_ids: dict[str, dict[str, str]] = {}
        for side in ("red", "blue"):
            side_zones = _mapping(tech_core_zones, side, document)
            if set(side_zones) != {"resource", "assembly"}:
                raise ConfigError(
                    f"{document.path}: `tech_core.zones.{side}` "
                    "必须只包含 resource、assembly"
                )
            self._tech_core_zone_ids[side] = {
                zone_type: _string(
                    side_zones,
                    zone_type,
                    document,
                    f"tech_core.zones.{side}.{zone_type}",
                )
                for zone_type in ("resource", "assembly")
            }
        all_tech_core_zone_ids = {
            zone_id
            for side_zones in self._tech_core_zone_ids.values()
            for zone_id in side_zones.values()
        }
        if len(all_tech_core_zone_ids) != 4:
            raise ConfigError(
                f"{document.path}: Tech Core resource / assembly zone id 必须互不相同"
            )

        raw_difficulties = _mapping(tech_core, "difficulties", document)
        if set(raw_difficulties) != {1, 2, 3}:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulties` 本轮必须且只能包含 1、2、3"
            )
        self._tech_core_difficulties: dict[int, _TechCoreDifficultyRule] = {}
        for difficulty in (1, 2, 3):
            raw_rule = raw_difficulties.get(difficulty)
            if not isinstance(raw_rule, dict) or set(raw_rule) != {
                "available_after",
                "prerequisite",
                "first",
                "repeat",
            }:
                raise ConfigError(
                    f"{document.path}: `tech_core.difficulties.{difficulty}` "
                    "字段不完整或包含未知字段"
                )
            available_after = _nonnegative_number(
                raw_rule,
                "available_after",
                document,
                f"tech_core.difficulties.{difficulty}.available_after",
            )
            prerequisite = raw_rule.get("prerequisite")
            expected_prerequisite = None if difficulty == 1 else difficulty - 1
            if prerequisite != expected_prerequisite:
                raise ConfigError(
                    f"{document.path}: `tech_core.difficulties.{difficulty}.prerequisite` "
                    f"必须是 {expected_prerequisite}"
                )

            first = _mapping(
                raw_rule,
                "first",
                document,
            )
            repeat = _mapping(
                raw_rule,
                "repeat",
                document,
            )
            if set(repeat) != {"periodic_gold_per_10s"}:
                raise ConfigError(
                    f"{document.path}: `tech_core.difficulties.{difficulty}.repeat` "
                    "本轮只保存 periodic_gold_per_10s metadata"
                )
            repeat_gold = _positive_integer(
                repeat,
                "periodic_gold_per_10s",
                document,
                f"tech_core.difficulties.{difficulty}.repeat.periodic_gold_per_10s",
            )

            expected_first_fields = {"periodic_gold_per_10s"}
            if difficulty in {2, 3}:
                expected_first_fields.add("level_cap")
            if difficulty == 3:
                expected_first_fields.add("defense_bonus")
            if set(first) != expected_first_fields:
                raise ConfigError(
                    f"{document.path}: `tech_core.difficulties.{difficulty}.first` "
                    "字段与当前 V1.4.0 slice 不匹配"
                )
            first_gold = _positive_integer(
                first,
                "periodic_gold_per_10s",
                document,
                f"tech_core.difficulties.{difficulty}.first.periodic_gold_per_10s",
            )
            first_level_cap = None
            if difficulty in {2, 3}:
                first_level_cap = _positive_integer(
                    first,
                    "level_cap",
                    document,
                    f"tech_core.difficulties.{difficulty}.first.level_cap",
                )
            first_defense_bonus = None
            if difficulty == 3:
                first_defense_bonus = _fraction(
                    first,
                    "defense_bonus",
                    document,
                    "tech_core.difficulties.3.first.defense_bonus",
                )

            self._tech_core_difficulties[difficulty] = _TechCoreDifficultyRule(
                available_after=available_after,
                prerequisite=prerequisite,
                first_level_cap=first_level_cap,
                first_periodic_gold_per_10s=first_gold,
                repeat_periodic_gold_per_10s=repeat_gold,
                first_defense_bonus=first_defense_bonus,
            )

        if self._tech_core_difficulties[2].first_level_cap != 7:
            raise ConfigError(
                f"{document.path}: Tech Core Difficulty 2 first level_cap 必须为 7"
            )
        if self._tech_core_difficulties[3].first_level_cap != 10:
            raise ConfigError(
                f"{document.path}: Tech Core Difficulty 3 first level_cap 必须为 10"
            )

        experience = _mapping(document.data, "experience", document)
        expected_experience_keys = {
            "level_thresholds",
            "initial_level_cap",
            "shot",
            "damage",
            "kill",
        }
        if set(experience) != expected_experience_keys:
            raise ConfigError(
                f"{document.path}: `experience` 字段不完整或包含未知字段"
            )
        self._level_thresholds = _parse_level_thresholds(
            experience.get("level_thresholds"), document
        )
        self._initial_level_cap = _positive_integer(
            experience,
            "initial_level_cap",
            document,
            "experience.initial_level_cap",
        )
        if self._initial_level_cap not in self._level_thresholds:
            raise ConfigError(
                f"{document.path}: `experience.initial_level_cap` 必须对应有效等级"
            )
        if self._initial_level_cap != 5:
            raise ConfigError(
                f"{document.path}: 当前 Regional V1.4.0 slice 的初始等级上限必须为 5"
            )

        shot = _mapping(experience, "shot", document)
        if set(shot) != {"hero", "infantry"}:
            raise ConfigError(
                f"{document.path}: `experience.shot` 必须只包含 hero、infantry"
            )
        self._shot_experience = {
            robot_type: float(
                _positive_integer(
                    shot,
                    robot_type,
                    document,
                    f"experience.shot.{robot_type}",
                )
            )
            for robot_type in ("hero", "infantry")
        }

        damage = _mapping(experience, "damage", document)
        if set(damage) != {
            "robot_per_hp",
            "outpost_per_hp",
            "base_hp_per_experience",
        }:
            raise ConfigError(
                f"{document.path}: `experience.damage` 字段不完整或包含未知字段"
            )
        self._robot_damage_experience_per_hp = float(
            _positive_integer(
                damage,
                "robot_per_hp",
                document,
                "experience.damage.robot_per_hp",
            )
        )
        self._outpost_damage_experience_per_hp = float(
            _positive_integer(
                damage,
                "outpost_per_hp",
                document,
                "experience.damage.outpost_per_hp",
            )
        )
        self._base_hp_per_experience = _positive_integer(
            damage,
            "base_hp_per_experience",
            document,
            "experience.damage.base_hp_per_experience",
        )

        kill = _mapping(experience, "kill", document)
        if set(kill) != {"base_factor", "level_difference_factor"}:
            raise ConfigError(
                f"{document.path}: `experience.kill` 字段不完整或包含未知字段"
            )
        self._kill_base_factor = float(
            _positive_integer(
                kill,
                "base_factor",
                document,
                "experience.kill.base_factor",
            )
        )
        self._kill_level_difference_factor = _number(
            kill,
            "level_difference_factor",
            document,
            "experience.kill.level_difference_factor",
        )

        performance = _mapping(document.data, "performance", document)
        if set(performance) != {"lab_selection", "hero", "infantry"}:
            raise ConfigError(
                f"{document.path}: `performance` 必须只包含 lab_selection、hero、infantry"
            )
        hero_performance = _mapping(performance, "hero", document)
        expected_hero_profiles = {"close-range-priority", "long-range-priority"}
        if set(hero_performance) != expected_hero_profiles:
            raise ConfigError(
                f"{document.path}: `performance.hero` 必须包含完整的近战/远程优先表"
            )
        self._hero_performance = {
            profile: _parse_performance_rows(
                hero_performance.get(profile),
                ("max_hp", "chassis_power_limit", "heat_limit", "cooling_per_second"),
                document,
                f"performance.hero.{profile}",
            )
            for profile in sorted(expected_hero_profiles)
        }

        infantry_performance = _mapping(performance, "infantry", document)
        if set(infantry_performance) != {"chassis", "launcher"}:
            raise ConfigError(
                f"{document.path}: `performance.infantry` 必须只包含 chassis、launcher"
            )
        chassis_profiles = _mapping(infantry_performance, "chassis", document)
        expected_chassis_profiles = {"power-priority", "hp-priority"}
        if set(chassis_profiles) != expected_chassis_profiles:
            raise ConfigError(
                f"{document.path}: `performance.infantry.chassis` "
                "必须包含 power-priority、hp-priority"
            )
        self._infantry_chassis_performance = {
            profile: _parse_performance_rows(
                chassis_profiles.get(profile),
                ("max_hp", "chassis_power_limit"),
                document,
                f"performance.infantry.chassis.{profile}",
            )
            for profile in sorted(expected_chassis_profiles)
        }

        launcher_profiles = _mapping(infantry_performance, "launcher", document)
        expected_launcher_profiles = {"burst-priority", "cooling-priority"}
        if set(launcher_profiles) != expected_launcher_profiles:
            raise ConfigError(
                f"{document.path}: `performance.infantry.launcher` "
                "必须包含 burst-priority、cooling-priority"
            )
        self._infantry_launcher_performance = {
            profile: _parse_performance_rows(
                launcher_profiles.get(profile),
                ("heat_limit", "cooling_per_second"),
                document,
                f"performance.infantry.launcher.{profile}",
            )
            for profile in sorted(expected_launcher_profiles)
        }

        lab_selection = _mapping(performance, "lab_selection", document)
        if set(lab_selection) != {"hero", "infantry"}:
            raise ConfigError(
                f"{document.path}: `performance.lab_selection` 必须包含 hero、infantry"
            )
        hero_selection = _mapping(lab_selection, "hero", document)
        infantry_selection = _mapping(lab_selection, "infantry", document)
        if set(hero_selection) != {"profile"}:
            raise ConfigError(
                f"{document.path}: `performance.lab_selection.hero` 只能包含 profile"
            )
        if set(infantry_selection) != {"chassis", "launcher"}:
            raise ConfigError(
                f"{document.path}: `performance.lab_selection.infantry` "
                "必须包含 chassis、launcher"
            )
        self._hero_profile = _string(
            hero_selection,
            "profile",
            document,
            "performance.lab_selection.hero.profile",
        )
        self._infantry_chassis_profile = _string(
            infantry_selection,
            "chassis",
            document,
            "performance.lab_selection.infantry.chassis",
        )
        self._infantry_launcher_profile = _string(
            infantry_selection,
            "launcher",
            document,
            "performance.lab_selection.infantry.launcher",
        )
        if self._hero_profile not in self._hero_performance:
            raise ConfigError(
                f"{document.path}: 未知 Hero performance profile `{self._hero_profile}`"
            )
        if self._infantry_chassis_profile not in self._infantry_chassis_performance:
            raise ConfigError(
                f"{document.path}: 未知 Infantry chassis profile "
                f"`{self._infantry_chassis_profile}`"
            )
        if self._infantry_launcher_profile not in self._infantry_launcher_performance:
            raise ConfigError(
                f"{document.path}: 未知 Infantry launcher profile "
                f"`{self._infantry_launcher_profile}`"
            )

        lab_parameters = _mapping(document.data, "lab_robot_parameters", document)
        common = _mapping(lab_parameters, "common", document)
        common_values = {
            "move_speed": _number(
                common,
                "move_speed",
                document,
                "lab_robot_parameters.common.move_speed",
            ),
            "collision_radius": _number(
                common,
                "collision_radius",
                document,
                "lab_robot_parameters.common.collision_radius",
            ),
            "attack_range": _number(
                common,
                "attack_range",
                document,
                "lab_robot_parameters.common.attack_range",
            ),
            "attack_interval": _number(
                common,
                "attack_interval",
                document,
                "lab_robot_parameters.common.attack_interval",
            ),
        }
        if set(lab_parameters) != {"common", *_RMUC_ROBOT_TYPES}:
            raise ConfigError(
                f"{document.path}: `lab_robot_parameters` 必须只包含 "
                "common、hero、engineer、infantry、sentry"
            )
        self._lab_parameters: dict[str, RobotParameters] = {}
        self._projectile_by_type: dict[str, str | None] = {}
        self._chassis_power_limit_by_type: dict[str, int] = {}
        for robot_type in _RMUC_ROBOT_TYPES:
            profile = _mapping(lab_parameters, robot_type, document)
            expected = (
                {"damage", "projectile"}
                if robot_type in _EXPERIENCE_ROBOT_TYPES
                else {"max_hp", "damage", "projectile", "chassis_power_limit"}
            )
            if set(profile) != expected:
                raise ConfigError(
                    f"{document.path}: `lab_robot_parameters.{robot_type}` "
                    "字段不完整或包含未知字段"
                )
            projectile = profile.get("projectile")
            if projectile is not None and (
                not isinstance(projectile, str) or not projectile.strip()
            ):
                raise ConfigError(
                    f"{document.path}: `lab_robot_parameters.{robot_type}.projectile` "
                    "必须是字符串或 null"
                )
            damage = _nonnegative_integer(
                profile,
                "damage",
                document,
                f"lab_robot_parameters.{robot_type}.damage",
            )
            if robot_type == "engineer":
                if projectile is not None or damage != 0:
                    raise ConfigError(
                        f"{document.path}: engineer 本轮必须无 launcher 且 damage=0"
                    )
            elif projectile not in {"17mm", "42mm"} or damage <= 0:
                raise ConfigError(
                    f"{document.path}: {robot_type} 必须配置 17mm/42mm synthetic damage"
                )

            if robot_type in _EXPERIENCE_ROBOT_TYPES:
                initial_performance = self._effective_performance_for_type(
                    robot_type, 1
                )
                max_hp = initial_performance.max_hp
                chassis_power_limit = initial_performance.chassis_power_limit
            else:
                max_hp = _positive_integer(
                    profile,
                    "max_hp",
                    document,
                    f"lab_robot_parameters.{robot_type}.max_hp",
                )
                chassis_power_limit = _positive_integer(
                    profile,
                    "chassis_power_limit",
                    document,
                    f"lab_robot_parameters.{robot_type}.chassis_power_limit",
                )

            self._lab_parameters[robot_type] = RobotParameters(
                max_hp=max_hp,
                damage=damage,
                **common_values,
            )
            self._projectile_by_type[robot_type] = projectile
            self._chassis_power_limit_by_type[robot_type] = chassis_power_limit

        self.attack_damage_by_team: dict[str, int] = {}
        self._team_states: dict[str, _TeamStructureState] = {}
        self._base_by_team: dict[str, Structure] = {}
        self._outpost_by_team: dict[str, Structure] = {}
        self._rebuild_zone_by_team: dict[str, Zone] = {}
        self._robot_types_by_id: dict[str, str] = {}
        self._robots_by_id: dict[str, Robot] = {}
        self._progression_by_robot: dict[str, _RobotProgressionState] = {}
        self._level_cap_by_team: dict[str, int] = {}
        self._engineer_resources_by_id: dict[str, _EngineerResourceState] = {}
        self._tech_core_by_team: dict[str, _TechCoreTeamState] = {}
        self._resource_zone_by_team: dict[str, Zone] = {}
        self._assembly_zone_by_team: dict[str, Zone] = {}

    @property
    def time_limit(self) -> float:
        return self._time_limit

    @property
    def display_state(self) -> RuleSetDisplayState:
        structure_statuses = []
        for team_id in sorted(self._base_by_team):
            base = self._base_by_team[team_id]
            outpost = self._outpost_by_team[team_id]
            state = self._team_states[team_id]
            structure_statuses.append(
                (
                    base.id,
                    base.hp,
                    base.max_hp,
                    "ARMOR" if state.base_armor_deployed else "",
                )
            )
            outpost_status = ""
            if not outpost.alive:
                outpost_status = "DESTROYED"
            elif state.outpost_ever_destroyed:
                outpost_status = "REBUILT"
            structure_statuses.append(
                (outpost.id, outpost.hp, outpost.max_hp, outpost_status)
            )

        rebuild_progress = []
        for team_id, state in sorted(self._team_states.items()):
            for robot_id, progress in sorted(state.rebuild_progress_by_robot.items()):
                if progress <= 0:
                    continue
                duration = self._rebuild_duration(self._robot_types_by_id[robot_id])
                rebuild_progress.append((team_id, robot_id, progress, duration))

        return RuleSetDisplayState(
            victory_points=(),
            control_owner=None,
            attack_damage=tuple(sorted(self.attack_damage_by_team.items())),
            structure_statuses=tuple(structure_statuses),
            rebuild_opportunities=tuple(
                (team_id, state.outpost_rebuild_opportunities)
                for team_id, state in sorted(self._team_states.items())
            ),
            rebuild_progress=tuple(rebuild_progress),
            robot_progression=tuple(
                (
                    robot_id,
                    state.level,
                    state.experience,
                    self._level_cap_by_team[self._robots_by_id[robot_id].team],
                )
                for robot_id, state in sorted(self._progression_by_robot.items())
            ),
            robot_performance=tuple(
                (
                    robot_id,
                    performance.max_hp,
                    performance.chassis_power_limit,
                    performance.heat_limit,
                    performance.cooling_per_second,
                )
                for robot_id, performance in (
                    (
                        robot_id,
                        self._effective_performance(robot_id),
                    )
                    for robot_id in sorted(self._progression_by_robot)
                )
            ),
            tech_core_status=tuple(
                (
                    team_id,
                    self._level_cap_by_team[team_id],
                    state.completion_count_by_difficulty[1],
                    state.completion_count_by_difficulty[2],
                    state.completion_count_by_difficulty[3],
                    (
                        state.active_attempt.difficulty
                        if state.active_attempt is not None
                        else None
                    ),
                    (
                        state.active_attempt.outside_zone_elapsed
                        if state.active_attempt is not None
                        else 0.0
                    ),
                )
                for team_id, state in sorted(self._tech_core_by_team.items())
            ),
            engineer_energy_units=tuple(
                (
                    engineer_id,
                    state.carrying_energy_unit,
                )
                for engineer_id, state in sorted(
                    self._engineer_resources_by_id.items()
                )
            ),
        )

    def robot_parameters(self, robot_type: str) -> RobotParameters:
        try:
            return self._lab_parameters[robot_type]
        except KeyError as exc:
            raise ConfigError(
                f"{self._document.path}: rmuc-2026-region-v1.4.0 "
                f"不支持机器人类型 `{robot_type}`"
            ) from exc

    def structure_parameters(self, structure_type: str) -> StructureParameters:
        try:
            return self._structure_parameters[structure_type]
        except KeyError as exc:
            raise ConfigError(
                f"{self._document.path}: rmuc-2026-region-v1.4.0 "
                f"不支持结构类型 `{structure_type}`"
            ) from exc

    def can_move(self, robot: Robot) -> bool:
        return robot.alive

    def can_attack(self, robot: Robot) -> bool:
        return robot.alive and robot.damage > 0

    def can_target(self, target: DamageableTarget) -> bool:
        if isinstance(target, Structure):
            # Unlike RMUL robot invincibility, an invincible RMUC Base must not
            # consume target selection while its Outpost is alive.
            return self.can_receive_damage(target)
        return target.alive

    def on_attack_committed(self, robot: Robot) -> None:
        """Grant shot Experience when Combat commits a legal attack intent."""
        shot_experience = self._shot_experience.get(robot.type)
        if shot_experience is not None:
            self._grant_experience(robot.id, shot_experience)

    def exchange_projectiles(self, match: "Match", robot: Robot) -> bool:
        """RMUC economy is intentionally outside this slice."""
        return False

    def pickup_energy_unit(self, match: "Match", engineer: Robot) -> bool:
        """Pick up the Rules Lab's synthetic renewable Energy Unit."""
        if (
            match.finished
            or engineer.type != "engineer"
            or not engineer.alive
            or self._robots_by_id.get(engineer.id) is not engineer
        ):
            return False
        resource_state = self._engineer_resources_by_id.get(engineer.id)
        resource_zone = self._resource_zone_by_team.get(engineer.team)
        if (
            resource_state is None
            or resource_state.carrying_energy_unit
            or resource_zone is None
            or not resource_zone.contains(engineer.position)
        ):
            return False
        resource_state.carrying_energy_unit = True
        return True

    def start_tech_core_assembly(
        self,
        match: "Match",
        engineer: Robot,
        difficulty: int,
    ) -> bool:
        """Start one explicit Rules Lab Tech Core D1-D3 assembly attempt."""
        if (
            match.finished
            or engineer.type != "engineer"
            or not engineer.alive
            or self._robots_by_id.get(engineer.id) is not engineer
            or difficulty not in self._tech_core_difficulties
        ):
            return False

        team_state = self._tech_core_by_team.get(engineer.team)
        resource_state = self._engineer_resources_by_id.get(engineer.id)
        assembly_zone = self._assembly_zone_by_team.get(engineer.team)
        rule = self._tech_core_difficulties[difficulty]
        if (
            team_state is None
            or resource_state is None
            or not resource_state.carrying_energy_unit
            or assembly_zone is None
            or not assembly_zone.contains(engineer.position)
            or team_state.active_attempt is not None
            or match.elapsed_time + 1e-9 < rule.available_after
        ):
            return False

        if (
            rule.prerequisite is not None
            and team_state.completion_count_by_difficulty[rule.prerequisite] < 1
        ):
            return False

        team_state.active_attempt = _TechCoreAttempt(
            engineer_id=engineer.id,
            difficulty=difficulty,
        )
        return True

    def confirm_tech_core_assembly(
        self,
        match: "Match",
        engineer: Robot,
    ) -> bool:
        """Confirm that the abstracted physical D1-D3 assembly succeeded."""
        if (
            match.finished
            or engineer.type != "engineer"
            or not engineer.alive
            or self._robots_by_id.get(engineer.id) is not engineer
        ):
            return False

        team_state = self._tech_core_by_team.get(engineer.team)
        resource_state = self._engineer_resources_by_id.get(engineer.id)
        assembly_zone = self._assembly_zone_by_team.get(engineer.team)
        if (
            team_state is None
            or team_state.active_attempt is None
            or team_state.active_attempt.engineer_id != engineer.id
            or resource_state is None
            or not resource_state.carrying_energy_unit
            or assembly_zone is None
            or not assembly_zone.contains(engineer.position)
        ):
            return False

        difficulty = team_state.active_attempt.difficulty
        previous_count = team_state.completion_count_by_difficulty[difficulty]
        team_state.completion_count_by_difficulty[difficulty] = previous_count + 1
        team_state.active_attempt = None
        resource_state.carrying_energy_unit = False

        if previous_count == 0:
            level_cap = self._tech_core_difficulties[difficulty].first_level_cap
            if level_cap is not None:
                self._level_cap_by_team[engineer.team] = max(
                    self._level_cap_by_team[engineer.team],
                    level_cap,
                )
        return True

    def can_receive_damage(self, target: DamageableTarget) -> bool:
        if not target.alive:
            return False
        if isinstance(target, Structure) and target.type == "base":
            outpost = self._outpost_by_team.get(target.team)
            return outpost is None or not outpost.alive
        return True

    def prepare_movement(self, match: "Match", dt: float) -> None:
        """No RMUC chassis performance simulation in this slice."""

    def prepare_combat(self, match: "Match", dt: float) -> None:
        """No heat/projectile physics in this slice."""

    def reset(self, match: "Match") -> None:
        expected_roster = {
            "hero": 1,
            "engineer": 1,
            "infantry": 2,
            "sentry": 1,
        }
        for team in match.config.scenario.teams.values():
            actual_roster = {
                robot_type: sum(robot.type == robot_type for robot in team.robots)
                for robot_type in _RMUC_ROBOT_TYPES
            }
            if actual_roster != expected_roster:
                raise ConfigError(
                    f"{self._document.path}: 队伍 `{team.team_id}` 必须恰好包含 "
                    "1 hero、1 engineer、2 infantry、1 sentry"
                )

        player_team = match.config.scenario.player_team
        player_definitions = next(
            team.robots
            for team in match.config.scenario.teams.values()
            if team.team_id == player_team
        )
        expected_player_controlled = {
            robot.id for robot in player_definitions if robot.type != "sentry"
        }
        if match.config.scenario.player_controlled != expected_player_controlled:
            raise ConfigError(
                f"{self._document.path}: player_controlled 必须包含 player_team 的 "
                "hero、engineer、两台 infantry；sentry 由 AI 控制"
            )

        team_by_side = {
            side: match.config.scenario.teams[side].team_id for side in ("red", "blue")
        }
        self.attack_damage_by_team = {
            team_id: 0 for team_id in team_by_side.values()
        }
        self._team_states = {
            team_id: _TeamStructureState() for team_id in team_by_side.values()
        }
        self._robot_types_by_id = {robot.id: robot.type for robot in match.robots}
        self._robots_by_id = {robot.id: robot for robot in match.robots}
        self._level_cap_by_team = {
            team_id: self._initial_level_cap for team_id in team_by_side.values()
        }
        self._engineer_resources_by_id = {
            robot.id: _EngineerResourceState()
            for robot in match.robots
            if robot.type == "engineer"
        }
        self._tech_core_by_team = {
            team_id: _TechCoreTeamState() for team_id in team_by_side.values()
        }
        self._progression_by_robot = {
            robot.id: _RobotProgressionState()
            for robot in match.robots
            if robot.type in _EXPERIENCE_ROBOT_TYPES
        }
        for robot_id in self._progression_by_robot:
            robot = self._robots_by_id[robot_id]
            performance = self._effective_performance(robot_id)
            robot.max_hp = performance.max_hp
            robot.hp = performance.max_hp

        self._base_by_team = {}
        self._outpost_by_team = {}
        for team_id in team_by_side.values():
            team_structures = [
                structure for structure in match.structures if structure.team == team_id
            ]
            bases = [structure for structure in team_structures if structure.type == "base"]
            outposts = [
                structure for structure in team_structures if structure.type == "outpost"
            ]
            if len(bases) != 1 or len(outposts) != 1 or len(team_structures) != 2:
                raise ConfigError(
                    f"{self._document.path}: 队伍 `{team_id}` 必须恰好有 1 Base 和 1 Outpost"
                )
            self._base_by_team[team_id] = bases[0]
            self._outpost_by_team[team_id] = outposts[0]

        zones_by_id = {zone.id: zone for zone in match.map.zones}
        required_zone_ids = set(self._rebuild_zone_ids.values()) | {
            zone_id
            for side_zones in self._tech_core_zone_ids.values()
            for zone_id in side_zones.values()
        }
        missing_zones = sorted(required_zone_ids - set(zones_by_id))
        if missing_zones:
            raise ConfigError(
                f"{self._document.path}: scenario 缺少 RMUC Rules Lab zone："
                + ", ".join(missing_zones)
            )
        self._rebuild_zone_by_team = {
            team_by_side[side]: zones_by_id[zone_id]
            for side, zone_id in self._rebuild_zone_ids.items()
        }
        self._resource_zone_by_team = {
            team_by_side[side]: zones_by_id[
                self._tech_core_zone_ids[side]["resource"]
            ]
            for side in ("red", "blue")
        }
        self._assembly_zone_by_team = {
            team_by_side[side]: zones_by_id[
                self._tech_core_zone_ids[side]["assembly"]
            ]
            for side in ("red", "blue")
        }

    def update(self, match: "Match", dt: float) -> None:
        self._consume_events(match)
        self._advance_tech_core_attempts(match, dt)

        frame_start = match.elapsed_time - dt
        active_rebuild_dt = max(
            0.0, min(dt, self._rebuild_cutoff - frame_start)
        )
        if active_rebuild_dt > 0:
            self._advance_rebuild(match, active_rebuild_dt)

        if match.elapsed_time >= self._rebuild_cutoff - 1e-9:
            for state in self._team_states.values():
                state.rebuild_progress_by_robot.clear()

    def _effective_performance_for_type(
        self, robot_type: str, level: int
    ) -> _EffectivePerformance:
        if robot_type == "hero":
            row = self._hero_performance[self._hero_profile][level]
            return _EffectivePerformance(
                max_hp=row["max_hp"],
                chassis_power_limit=row["chassis_power_limit"],
                heat_limit=row["heat_limit"],
                cooling_per_second=row["cooling_per_second"],
            )
        if robot_type == "infantry":
            chassis = self._infantry_chassis_performance[
                self._infantry_chassis_profile
            ][level]
            launcher = self._infantry_launcher_performance[
                self._infantry_launcher_profile
            ][level]
            return _EffectivePerformance(
                max_hp=chassis["max_hp"],
                chassis_power_limit=chassis["chassis_power_limit"],
                heat_limit=launcher["heat_limit"],
                cooling_per_second=launcher["cooling_per_second"],
            )
        raise KeyError(robot_type)

    def _effective_performance(self, robot_id: str) -> _EffectivePerformance:
        state = self._progression_by_robot[robot_id]
        robot_type = self._robot_types_by_id[robot_id]
        return self._effective_performance_for_type(robot_type, state.level)

    def _grant_experience(self, robot_id: str, amount: float) -> None:
        state = self._progression_by_robot.get(robot_id)
        robot = self._robots_by_id.get(robot_id)
        if (
            state is None
            or robot is None
            or not math.isfinite(amount)
            or amount <= 0
        ):
            return

        level_cap = self._level_cap_by_team[robot.team]
        cap_experience = float(self._level_thresholds[level_cap])
        if state.level >= level_cap or state.experience >= cap_experience:
            state.level = level_cap
            state.experience = cap_experience
            return

        old_level = state.level
        state.experience = min(cap_experience, state.experience + float(amount))
        state.level = max(
            level
            for level, threshold in self._level_thresholds.items()
            if level <= level_cap and threshold <= state.experience + 1e-9
        )
        if state.level == old_level:
            return

        performance = self._effective_performance(robot_id)
        previous_max_hp = robot.max_hp
        hp_increase = max(0, performance.max_hp - previous_max_hp)
        robot.max_hp = performance.max_hp
        if robot.alive:
            robot.hp = min(robot.max_hp, robot.hp + hp_increase)
        else:
            robot.hp = 0

    def _robot_level(self, robot_id: str | None) -> int:
        if robot_id is None:
            return 1
        progression = self._progression_by_robot.get(robot_id)
        return progression.level if progression is not None else 1

    def _grant_kill_experience(self, event) -> None:
        if (
            event.attacker_id not in self._progression_by_robot
            or event.robot_id not in self._robots_by_id
            or event.attacker_team_id == event.team_id
        ):
            return
        attacker_level = self._robot_level(event.attacker_id)
        victim_level = self._robot_level(event.robot_id)
        level_difference = max(0, victim_level - attacker_level)
        amount = (
            self._kill_base_factor
            * victim_level
            * (1 + self._kill_level_difference_factor * level_difference)
        )
        self._grant_experience(event.attacker_id, amount)

    def _consume_events(self, match: "Match") -> None:
        structure_by_id = {structure.id: structure for structure in match.structures}
        for event in match.current_events:
            is_enemy_damage = (
                event.attacker_team_id in self.attack_damage_by_team
                and event.attacker_team_id != event.team_id
                and event.damage > 0
            )
            if (
                event.type
                in {MatchEventType.ROBOT_DAMAGED, MatchEventType.STRUCTURE_DAMAGED}
                and is_enemy_damage
            ):
                self.attack_damage_by_team[event.attacker_team_id] += event.damage

            known_experience_source = (
                is_enemy_damage and event.attacker_id in self._progression_by_robot
            )
            if event.type == MatchEventType.ROBOT_DAMAGED:
                if known_experience_source:
                    self._grant_experience(
                        event.attacker_id,
                        event.damage * self._robot_damage_experience_per_hp,
                    )
                continue

            if event.type == MatchEventType.ROBOT_DESTROYED:
                self._grant_kill_experience(event)
                resource_state = self._engineer_resources_by_id.get(event.robot_id)
                if resource_state is not None:
                    resource_state.carrying_energy_unit = False
                    team_state = self._tech_core_by_team.get(event.team_id)
                    if (
                        team_state is not None
                        and team_state.active_attempt is not None
                        and team_state.active_attempt.engineer_id == event.robot_id
                    ):
                        team_state.active_attempt = None
                continue

            if event.type == MatchEventType.STRUCTURE_DAMAGED:
                structure = structure_by_id.get(event.structure_id)
                if structure is None:
                    continue

                if known_experience_source:
                    if structure.type == "outpost":
                        self._grant_experience(
                            event.attacker_id,
                            event.damage * self._outpost_damage_experience_per_hp,
                        )
                    elif structure.type == "base":
                        self._grant_experience(
                            event.attacker_id,
                            math.ceil(event.damage / self._base_hp_per_experience),
                        )

                if structure.type != "base":
                    continue
                state = self._team_states[structure.team]
                previous_damage = state.base_damage_lost
                state.base_damage_lost += event.damage
                crossed = (
                    state.base_damage_lost // self._base_damage_threshold
                    - previous_damage // self._base_damage_threshold
                )
                if crossed > 0:
                    state.outpost_rebuild_opportunities += crossed
                if structure.hp <= 2000:
                    state.base_armor_deployed = True
                continue

            if event.type == MatchEventType.STRUCTURE_DESTROYED:
                structure = structure_by_id.get(event.structure_id)
                if structure is None or structure.type != "outpost":
                    continue
                state = self._team_states[structure.team]
                state.outpost_ever_destroyed = True
                state.rebuild_progress_by_robot.clear()

    def _advance_tech_core_attempts(self, match: "Match", dt: float) -> None:
        if dt <= 0:
            return
        for team_id, team_state in self._tech_core_by_team.items():
            attempt = team_state.active_attempt
            if attempt is None:
                continue
            engineer = self._robots_by_id.get(attempt.engineer_id)
            if engineer is None or not engineer.alive:
                self._fail_tech_core_attempt(team_id)
                continue
            assembly_zone = self._assembly_zone_by_team[team_id]
            if assembly_zone.contains(engineer.position):
                attempt.outside_zone_elapsed = 0.0
                continue
            attempt.outside_zone_elapsed += dt
            if (
                attempt.outside_zone_elapsed + 1e-9
                >= self._tech_core_leave_zone_fail_after
            ):
                self._fail_tech_core_attempt(team_id)

    def _fail_tech_core_attempt(self, team_id: str) -> None:
        team_state = self._tech_core_by_team.get(team_id)
        if team_state is None or team_state.active_attempt is None:
            return
        engineer_id = team_state.active_attempt.engineer_id
        team_state.active_attempt = None
        resource_state = self._engineer_resources_by_id.get(engineer_id)
        if resource_state is not None:
            resource_state.carrying_energy_unit = False

    def _advance_rebuild(self, match: "Match", dt: float) -> None:
        if dt <= 0:
            return
        for team_id in sorted(self._team_states):
            state = self._team_states[team_id]
            outpost = self._outpost_by_team[team_id]
            if outpost.alive or state.outpost_rebuild_opportunities <= 0:
                state.rebuild_progress_by_robot.clear()
                continue

            zone = self._rebuild_zone_by_team[team_id]
            eligible = [
                robot
                for robot in match.robots
                if robot.team == team_id
                and robot.alive
                and robot.type in _REBUILD_ROBOT_TYPES
                and zone.contains(robot.position)
            ]
            eligible_ids = {robot.id for robot in eligible}
            for robot_id in list(state.rebuild_progress_by_robot):
                if robot_id not in eligible_ids:
                    del state.rebuild_progress_by_robot[robot_id]

            for robot in sorted(eligible, key=lambda item: item.id):
                progress = state.rebuild_progress_by_robot.get(robot.id, 0.0) + dt
                state.rebuild_progress_by_robot[robot.id] = progress
                if progress + 1e-9 < self._rebuild_duration(robot.type):
                    continue

                outpost.alive = True
                outpost.hp = min(self._rebuilt_outpost_hp, outpost.max_hp)
                state.outpost_rebuild_opportunities -= 1
                state.rebuild_progress_by_robot.clear()
                break

    def _rebuild_duration(self, robot_type: str) -> float:
        if robot_type == "engineer":
            return self._engineer_rebuild_duration
        return self._default_rebuild_duration

    def evaluate_result(self, match: "Match") -> MatchResult | None:
        bases = self._base_by_team
        if (
            match.elapsed_time < self.time_limit
            and all(base.alive for base in bases.values())
        ):
            return None

        team_ids = (
            match.config.scenario.teams["red"].team_id,
            match.config.scenario.teams["blue"].team_id,
        )
        first, second = team_ids
        base_hp = {team_id: bases[team_id].hp for team_id in team_ids}
        if base_hp[first] != base_hp[second]:
            return MatchResult(first if base_hp[first] > base_hp[second] else second)

        first_state = self._team_states[first]
        second_state = self._team_states[second]
        if (
            not first_state.outpost_ever_destroyed
            and not second_state.outpost_ever_destroyed
        ):
            outpost_hp = {
                team_id: self._outpost_by_team[team_id].hp for team_id in team_ids
            }
            if outpost_hp[first] != outpost_hp[second]:
                return MatchResult(
                    first if outpost_hp[first] > outpost_hp[second] else second
                )

        if (
            first_state.outpost_ever_destroyed
            != second_state.outpost_ever_destroyed
        ):
            return MatchResult(
                second if first_state.outpost_ever_destroyed else first
            )

        first_damage = self.attack_damage_by_team[first]
        second_damage = self.attack_damage_by_team[second]
        if first_damage != second_damage:
            return MatchResult(first if first_damage > second_damage else second)

        remaining_hp = {
            team_id: sum(
                robot.hp for robot in match.robots if robot.team == team_id
            )
            for team_id in team_ids
        }
        if remaining_hp[first] != remaining_hp[second]:
            return MatchResult(
                first if remaining_hp[first] > remaining_hp[second] else second
            )
        return MatchResult(None)


def _parse_level_thresholds(
    value: Any, document: RuleDocument
) -> dict[int, float]:
    field = "experience.level_thresholds"
    if not isinstance(value, list) or len(value) != 10:
        raise ConfigError(f"{document.path}: `{field}` 必须包含 Lv1～Lv10 共 10 行")

    parsed: dict[int, float] = {}
    for index, row in enumerate(value):
        row_field = f"{field}[{index}]"
        if not isinstance(row, dict) or set(row) != {"level", "experience"}:
            raise ConfigError(
                f"{document.path}: `{row_field}` 必须只包含 level、experience"
            )
        level = row.get("level")
        experience = row.get("experience")
        if not isinstance(level, int) or isinstance(level, bool) or level <= 0:
            raise ConfigError(f"{document.path}: `{row_field}.level` 必须是正整数")
        if level in parsed:
            raise ConfigError(f"{document.path}: `{field}` 等级 {level} 重复")
        if (
            not isinstance(experience, (int, float))
            or isinstance(experience, bool)
            or not math.isfinite(experience)
            or experience < 0
        ):
            raise ConfigError(
                f"{document.path}: `{row_field}.experience` 必须是非负数字"
            )
        parsed[level] = float(experience)

    if set(parsed) != set(range(1, 11)):
        raise ConfigError(f"{document.path}: `{field}` 必须完整覆盖 Lv1～Lv10")
    if parsed[1] != 0:
        raise ConfigError(f"{document.path}: `{field}` Lv1 必须从 0 XP 开始")
    if any(parsed[level] <= parsed[level - 1] for level in range(2, 11)):
        raise ConfigError(f"{document.path}: `{field}` 必须随等级严格递增")
    return parsed


def _parse_performance_rows(
    value: Any,
    stat_fields: tuple[str, ...],
    document: RuleDocument,
    field: str,
) -> dict[int, dict[str, int]]:
    if not isinstance(value, list) or len(value) != 10:
        raise ConfigError(f"{document.path}: `{field}` 必须包含 Lv1～Lv10 共 10 行")

    parsed: dict[int, dict[str, int]] = {}
    expected_keys = {"level", *stat_fields}
    for index, row in enumerate(value):
        row_field = f"{field}[{index}]"
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise ConfigError(
                f"{document.path}: `{row_field}` 字段不完整或包含未知字段"
            )
        level = row.get("level")
        if not isinstance(level, int) or isinstance(level, bool) or level <= 0:
            raise ConfigError(f"{document.path}: `{row_field}.level` 必须是正整数")
        if level in parsed:
            raise ConfigError(f"{document.path}: `{field}` 等级 {level} 重复")

        stats: dict[str, int] = {}
        for stat in stat_fields:
            value_at_level = row.get(stat)
            if (
                not isinstance(value_at_level, int)
                or isinstance(value_at_level, bool)
                or value_at_level <= 0
            ):
                raise ConfigError(
                    f"{document.path}: `{row_field}.{stat}` 必须是正整数"
                )
            stats[stat] = value_at_level
        parsed[level] = stats

    if set(parsed) != set(range(1, 11)):
        raise ConfigError(f"{document.path}: `{field}` 必须完整覆盖 Lv1～Lv10")
    return parsed


def _mapping(
    data: Mapping[str, Any], key: str, document: RuleDocument
) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{document.path}: `{key}` 必须是 YAML 字典")
    return value


def _string(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{document.path}: `{field}` 必须是非空字符串")
    return value.strip()


def _nonnegative_number(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> float:
    value = data.get(key)
    valid = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
    if not valid:
        raise ConfigError(f"{document.path}: `{field}` 必须是非负数字")
    return float(value)


def _fraction(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> float:
    value = data.get(key)
    valid = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 < value <= 1
    )
    if not valid:
        raise ConfigError(f"{document.path}: `{field}` 必须在 (0, 1] 范围内")
    return float(value)


def _number(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> float:
    value = data.get(key)
    valid = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )
    if not valid:
        raise ConfigError(f"{document.path}: `{field}` 必须是大于 0 的数字")
    return float(value)


def _positive_integer(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{document.path}: `{field}` 必须是正整数")
    return value


def _nonnegative_integer(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{document.path}: `{field}` 必须是非负整数")
    return value


if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match
