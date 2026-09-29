"""Partial RMUC 2026 Regional V1.4.0 rules including progression, economy, and Heat."""

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
    energy_unit_credits: int = 0


@dataclass
class _TechCoreAttempt:
    engineer_id: str
    difficulty: int
    outside_zone_elapsed: float = 0.0


@dataclass
class _D4Attempt:
    engineer_id: str
    activated_at: float
    current_step: int = 1
    completed_core_slots: set[str] = field(default_factory=set)
    first_core_completed_at: float | None = None
    outside_zone_elapsed: float = 0.0
    priority_takeover: bool = False


@dataclass
class _D4CoordinatorState:
    active_team_id: str | None = None
    pending_team_id: str | None = None
    pending_engineer_id: str | None = None
    priority_buffer_remaining: float = 0.0
    priority_takeover: bool = False


@dataclass(frozen=True)
class _TechCoreDifficultyRule:
    available_after: float
    prerequisite: int | None
    first_level_cap: int | None
    first_periodic_gold_per_10s: int
    repeat_periodic_gold_per_10s: int | None
    first_defense_bonus: float | None = None
    first_base_hp_bonus: int | None = None
    only_once: bool = False


@dataclass
class _TechCoreTeamState:
    completion_count_by_difficulty: dict[int, int] = field(
        default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0}
    )
    active_attempt: _TechCoreAttempt | None = None
    d4_attempt: _D4Attempt | None = None
    d4_retry_after: float = 0.0
    permanently_locked_out_of_d4: bool = False
    d4_priority_failure_gold_penalty: int = 0


@dataclass
class _TeamStructureState:
    outpost_ever_destroyed: bool = False
    base_damage_lost: int = 0
    outpost_rebuild_opportunities: int = 0
    rebuild_progress_by_robot: dict[str, float] = field(default_factory=dict)
    base_armor_deployed: bool = False


@dataclass
class _TeamEconomyState:
    coins: int = 0
    tech_core_periodic_gold_per_10s: int = 0
    d4_priority_penalty_active_from: float | None = None


@dataclass(frozen=True)
class _ProjectilePurchaseRule:
    team_cap: int
    nonremote_coins: int
    nonremote_allowance: int
    remote_coins: int
    remote_allowance: int


@dataclass(frozen=True)
class _PendingProjectileDelivery:
    amount: int
    effective_at: float


@dataclass
class _ProjectileAllowanceState:
    projectile_type: str
    allowed: int
    disengaged_elapsed: float
    combat_activity_this_frame: bool = False
    pending_remote_deliveries: list[_PendingProjectileDelivery] = field(
        default_factory=list
    )


@dataclass
class _TeamProjectilePurchaseState:
    purchased_17mm: int = 0
    purchased_42mm: int = 0
    pending_sentry_supply: int = 0


@dataclass
class _ShootingHeatState:
    heat: float = 0.0
    temporarily_locked: bool = False
    permanently_locked: bool = False


@dataclass(frozen=True)
class _EffectiveHeatParameters:
    projectile_type: str
    heat_limit: float
    cooling_per_second: float
    permanent_threshold: float


@dataclass
class _ChassisPowerState:
    buffer_energy: float
    power_off_remaining: float = 0.0
    blocked_this_frame: bool = False


class RMUC2026RegionalRules:
    """V1.4.0 Regional Rules Lab with progression, economy, allowance, and Heat."""

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

        economy = _mapping(document.data, "economy", document)
        if set(economy) != {
            "initial_coins",
            "periodic_interval",
            "qualification_modifiers",
            "lab_pre_match_rating",
            "timed_grants",
        }:
            raise ConfigError(
                f"{document.path}: `economy` 字段不完整或包含未知字段"
            )
        self._economy_initial_coins = _nonnegative_integer(
            economy,
            "initial_coins",
            document,
            "economy.initial_coins",
        )
        if self._economy_initial_coins != 400:
            raise ConfigError(
                f"{document.path}: RMUC 2026 Regional 初始金币必须为 400"
            )

        periodic_interval = _positive_integer(
            economy,
            "periodic_interval",
            document,
            "economy.periodic_interval",
        )
        if periodic_interval != 10:
            raise ConfigError(
                f"{document.path}: `economy.periodic_interval` 必须为 10 秒"
            )
        self._economy_periodic_interval = float(periodic_interval)

        qualification_modifiers = _mapping(
            economy, "qualification_modifiers", document
        )
        if set(qualification_modifiers) != {
            "project_document",
            "technical_solution",
        }:
            raise ConfigError(
                f"{document.path}: `economy.qualification_modifiers` "
                "必须包含 project_document、technical_solution"
            )
        expected_rating_modifiers = {
            "project_document": {"S": 50, "A": 25, "B": 0, "C": -25, "D": -50},
            "technical_solution": {"S": 150, "A": 75, "B": 0, "C": -25, "D": -50},
        }
        self._economy_rating_modifiers: dict[str, dict[str, int]] = {}
        for category, expected in expected_rating_modifiers.items():
            raw_table = _mapping(
                qualification_modifiers,
                category,
                document,
            )
            if set(raw_table) != {"S", "A", "B", "C", "D"}:
                raise ConfigError(
                    f"{document.path}: `economy.qualification_modifiers.{category}` "
                    "必须完整包含 S/A/B/C/D"
                )
            parsed = {
                rating: _integer(
                    raw_table,
                    rating,
                    document,
                    f"economy.qualification_modifiers.{category}.{rating}",
                )
                for rating in ("S", "A", "B", "C", "D")
            }
            if parsed != expected:
                raise ConfigError(
                    f"{document.path}: `economy.qualification_modifiers.{category}` "
                    "与 RMUC 2026 Regional V1.4.0 不匹配"
                )
            self._economy_rating_modifiers[category] = parsed

        lab_rating = _mapping(economy, "lab_pre_match_rating", document)
        if set(lab_rating) != {"project_document", "technical_solution"}:
            raise ConfigError(
                f"{document.path}: `economy.lab_pre_match_rating` "
                "必须包含 project_document、technical_solution"
            )
        self._economy_lab_rating = {}
        for category in ("project_document", "technical_solution"):
            rating = _string(
                lab_rating,
                category,
                document,
                f"economy.lab_pre_match_rating.{category}",
            )
            if rating not in {"S", "A", "B", "C", "D"}:
                raise ConfigError(
                    f"{document.path}: `economy.lab_pre_match_rating.{category}` "
                    "必须是 S/A/B/C/D"
                )
            self._economy_lab_rating[category] = rating
        if self._economy_lab_rating != {
            "project_document": "B",
            "technical_solution": "B",
        }:
            raise ConfigError(
                f"{document.path}: Rules Lab 默认完整形态考核评级必须显式为 B/B"
            )

        raw_timed_grants = economy.get("timed_grants")
        if not isinstance(raw_timed_grants, list) or not raw_timed_grants:
            raise ConfigError(
                f"{document.path}: `economy.timed_grants` 必须是非空列表"
            )
        timed_grants: list[tuple[float, int]] = []
        previous_elapsed = -1.0
        for index, row in enumerate(raw_timed_grants):
            field = f"economy.timed_grants[{index}]"
            if not isinstance(row, dict) or set(row) != {"elapsed", "coins"}:
                raise ConfigError(
                    f"{document.path}: `{field}` 必须只包含 elapsed、coins"
                )
            elapsed = _number(row, "elapsed", document, f"{field}.elapsed")
            coins = _positive_integer(row, "coins", document, f"{field}.coins")
            if elapsed <= previous_elapsed:
                raise ConfigError(
                    f"{document.path}: `economy.timed_grants` elapsed 必须严格递增"
                )
            if elapsed >= self._time_limit:
                raise ConfigError(
                    f"{document.path}: `{field}.elapsed` 必须小于比赛时长"
                )
            timed_grants.append((elapsed, coins))
            previous_elapsed = elapsed
        expected_timed_grants = (
            (60.0, 50),
            (120.0, 50),
            (180.0, 50),
            (240.0, 50),
            (300.0, 50),
            (360.0, 150),
        )
        if tuple(timed_grants) != expected_timed_grants:
            raise ConfigError(
                f"{document.path}: `economy.timed_grants` "
                "与 RMUC 2026 Regional V1.4.0 不匹配"
            )
        self._economy_timed_grants = tuple(timed_grants)

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
        if set(tech_core) != {
            "leave_zone_fail_after",
            "zones",
            "difficulties",
            "difficulty4",
        }:
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
        if set(raw_difficulties) != {1, 2, 3, 4}:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulties` 必须完整包含 1～4"
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

            first = _mapping(raw_rule, "first", document)
            repeat = _mapping(raw_rule, "repeat", document)
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

        raw_d4 = raw_difficulties.get(4)
        if not isinstance(raw_d4, dict) or set(raw_d4) != {
            "available_after",
            "prerequisite",
            "only_once",
            "first",
            "repeat",
        }:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulties.4` 字段不完整或包含未知字段"
            )
        if raw_d4.get("prerequisite") != 3:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulties.4.prerequisite` 必须是 3"
            )
        if raw_d4.get("only_once") is not True:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulties.4.only_once` 必须为 true"
            )
        if raw_d4.get("repeat") is not None:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulties.4.repeat` 必须为 null"
            )
        d4_first = _mapping(raw_d4, "first", document)
        if set(d4_first) != {
            "defense_bonus",
            "base_hp_bonus",
            "periodic_gold_per_10s",
        }:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulties.4.first` "
                "必须保存 defense/base/gold metadata"
            )
        self._tech_core_difficulties[4] = _TechCoreDifficultyRule(
            available_after=_nonnegative_number(
                raw_d4,
                "available_after",
                document,
                "tech_core.difficulties.4.available_after",
            ),
            prerequisite=3,
            first_level_cap=None,
            first_periodic_gold_per_10s=_positive_integer(
                d4_first,
                "periodic_gold_per_10s",
                document,
                "tech_core.difficulties.4.first.periodic_gold_per_10s",
            ),
            repeat_periodic_gold_per_10s=None,
            first_defense_bonus=_fraction(
                d4_first,
                "defense_bonus",
                document,
                "tech_core.difficulties.4.first.defense_bonus",
            ),
            first_base_hp_bonus=_positive_integer(
                d4_first,
                "base_hp_bonus",
                document,
                "tech_core.difficulties.4.first.base_hp_bonus",
            ),
            only_once=True,
        )

        if self._tech_core_difficulties[2].first_level_cap != 7:
            raise ConfigError(
                f"{document.path}: Tech Core Difficulty 2 first level_cap 必须为 7"
            )
        if self._tech_core_difficulties[3].first_level_cap != 10:
            raise ConfigError(
                f"{document.path}: Tech Core Difficulty 3 first level_cap 必须为 10"
            )
        if self._tech_core_difficulties[4].available_after != 180:
            raise ConfigError(
                f"{document.path}: Tech Core Difficulty 4 available_after 必须为 180"
            )
        if (
            self._tech_core_difficulties[4].first_defense_bonus != 0.5
            or self._tech_core_difficulties[4].first_base_hp_bonus != 2000
            or self._tech_core_difficulties[4].first_periodic_gold_per_10s != 50
        ):
            raise ConfigError(
                f"{document.path}: Tech Core Difficulty 4 reward metadata 不匹配 V1.4.0"
            )

        difficulty4 = _mapping(tech_core, "difficulty4", document)
        if set(difficulty4) != {
            "total_window",
            "paired_step_window",
            "paired_steps",
            "priority_buffer",
            "retry_lockout",
            "priority_failure",
        }:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulty4` 字段不完整或包含未知字段"
            )
        self._d4_total_window = _number(
            difficulty4,
            "total_window",
            document,
            "tech_core.difficulty4.total_window",
        )
        self._d4_paired_step_window = _number(
            difficulty4,
            "paired_step_window",
            document,
            "tech_core.difficulty4.paired_step_window",
        )
        paired_steps = difficulty4.get("paired_steps")
        if (
            not isinstance(paired_steps, list)
            or any(
                not isinstance(step, int) or isinstance(step, bool)
                for step in paired_steps
            )
            or set(paired_steps) != {2, 3, 5, 6}
            or len(paired_steps) != 4
        ):
            raise ConfigError(
                f"{document.path}: `tech_core.difficulty4.paired_steps` "
                "必须恰好是 2、3、5、6"
            )
        self._d4_paired_steps = frozenset(paired_steps)
        self._d4_priority_buffer = _number(
            difficulty4,
            "priority_buffer",
            document,
            "tech_core.difficulty4.priority_buffer",
        )
        self._d4_retry_lockout = _number(
            difficulty4,
            "retry_lockout",
            document,
            "tech_core.difficulty4.retry_lockout",
        )
        priority_failure = _mapping(difficulty4, "priority_failure", document)
        if set(priority_failure) != {
            "permanent_lockout",
            "periodic_gold_penalty_per_10s",
        }:
            raise ConfigError(
                f"{document.path}: `tech_core.difficulty4.priority_failure` "
                "字段不完整或包含未知字段"
            )
        if priority_failure.get("permanent_lockout") is not True:
            raise ConfigError(
                f"{document.path}: D4 priority failure permanent_lockout 必须为 true"
            )
        self._d4_priority_failure_gold_penalty = _positive_integer(
            priority_failure,
            "periodic_gold_penalty_per_10s",
            document,
            "tech_core.difficulty4.priority_failure.periodic_gold_penalty_per_10s",
        )
        if (
            self._d4_total_window != 45
            or self._d4_paired_step_window != 5
            or self._d4_priority_buffer != 15
            or self._d4_retry_lockout != 90
            or self._d4_priority_failure_gold_penalty != 25
        ):
            raise ConfigError(
                f"{document.path}: Tech Core Difficulty 4 timing/penalty metadata "
                "不匹配 V1.4.0"
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

        projectile_allowance = _mapping(
            document.data, "projectile_allowance", document
        )
        if set(projectile_allowance) != {
            "disengaged_after",
            "remote_effective_delay",
            "zones",
            "initial",
            "purchase",
            "sentry_supply",
        }:
            raise ConfigError(
                f"{document.path}: `projectile_allowance` 字段不完整或包含未知字段"
            )
        self._projectile_disengaged_after = _number(
            projectile_allowance,
            "disengaged_after",
            document,
            "projectile_allowance.disengaged_after",
        )
        self._projectile_remote_effective_delay = _number(
            projectile_allowance,
            "remote_effective_delay",
            document,
            "projectile_allowance.remote_effective_delay",
        )
        if self._projectile_disengaged_after != 6:
            raise ConfigError(
                f"{document.path}: RMUC 脱战时长必须为 6 秒"
            )
        if self._projectile_remote_effective_delay != 6:
            raise ConfigError(
                f"{document.path}: RMUC 远程允许发弹量生效延迟必须为 6 秒"
            )

        projectile_zones = _mapping(projectile_allowance, "zones", document)
        if set(projectile_zones) != {"red", "blue"}:
            raise ConfigError(
                f"{document.path}: `projectile_allowance.zones` 必须包含 red、blue"
            )
        self._projectile_zone_ids: dict[str, dict[str, str]] = {}
        all_projectile_zone_ids: set[str] = set()
        for side in ("red", "blue"):
            side_zones = _mapping(projectile_zones, side, document)
            if set(side_zones) != {"supply", "base", "outpost"}:
                raise ConfigError(
                    f"{document.path}: `projectile_allowance.zones.{side}` "
                    "必须只包含 supply、base、outpost"
                )
            self._projectile_zone_ids[side] = {}
            for zone_type in ("supply", "base", "outpost"):
                zone_id = _string(
                    side_zones,
                    zone_type,
                    document,
                    f"projectile_allowance.zones.{side}.{zone_type}",
                )
                if zone_id in all_projectile_zone_ids:
                    raise ConfigError(
                        f"{document.path}: projectile allowance zone id 必须互不相同"
                    )
                all_projectile_zone_ids.add(zone_id)
                self._projectile_zone_ids[side][zone_type] = zone_id

        initial = _mapping(projectile_allowance, "initial", document)
        if set(initial) != {"hero", "infantry", "sentry", "drone"}:
            raise ConfigError(
                f"{document.path}: `projectile_allowance.initial` "
                "必须包含 hero、infantry、sentry、drone"
            )
        expected_initial = {
            "hero": ("42mm", 0),
            "infantry": ("17mm", 0),
            "sentry": ("17mm", 300),
            "drone": ("17mm", 750),
        }
        self._projectile_initial: dict[str, tuple[str, int]] = {}
        for robot_type, (expected_projectile, expected_allowance) in (
            expected_initial.items()
        ):
            item = _mapping(initial, robot_type, document)
            expected_keys = {"projectile", "allowance"}
            if robot_type == "drone":
                expected_keys.add("additional_acquisition")
            if set(item) != expected_keys:
                raise ConfigError(
                    f"{document.path}: `projectile_allowance.initial.{robot_type}` "
                    "字段不完整或包含未知字段"
                )
            projectile = _string(
                item,
                "projectile",
                document,
                f"projectile_allowance.initial.{robot_type}.projectile",
            )
            if projectile not in {"17mm", "42mm"}:
                raise ConfigError(
                    f"{document.path}: `projectile_allowance.initial.{robot_type}.projectile` "
                    "只能是 17mm / 42mm"
                )
            allowance = _nonnegative_integer(
                item,
                "allowance",
                document,
                f"projectile_allowance.initial.{robot_type}.allowance",
            )
            if (projectile, allowance) != (
                expected_projectile,
                expected_allowance,
            ):
                raise ConfigError(
                    f"{document.path}: `projectile_allowance.initial.{robot_type}` "
                    "与 RMUC 2026 Regional V1.4.0 不匹配"
                )
            if robot_type == "drone" and item.get("additional_acquisition") is not False:
                raise ConfigError(
                    f"{document.path}: Drone additional_acquisition 必须为 false"
                )
            self._projectile_initial[robot_type] = (projectile, allowance)

        for robot_type in ("hero", "infantry", "sentry"):
            configured_projectile = self._projectile_by_type[robot_type]
            if configured_projectile != self._projectile_initial[robot_type][0]:
                raise ConfigError(
                    f"{document.path}: {robot_type} launcher 与 projectile allowance 类型不一致"
                )
        if self._projectile_by_type["engineer"] is not None:
            raise ConfigError(
                f"{document.path}: engineer 不得拥有 projectile allowance launcher"
            )

        purchase = _mapping(projectile_allowance, "purchase", document)
        if set(purchase) != {"17mm", "42mm"}:
            raise ConfigError(
                f"{document.path}: `projectile_allowance.purchase` 必须包含 17mm、42mm"
            )
        expected_purchase = {
            "17mm": (1000, 10, 10, 150, 100),
            "42mm": (100, 10, 1, 150, 10),
        }
        self._projectile_purchase_rules: dict[str, _ProjectilePurchaseRule] = {}
        for projectile, expected in expected_purchase.items():
            item = _mapping(purchase, projectile, document)
            if set(item) != {"team_cap", "nonremote", "remote"}:
                raise ConfigError(
                    f"{document.path}: `projectile_allowance.purchase.{projectile}` "
                    "字段不完整或包含未知字段"
                )
            nonremote = _mapping(item, "nonremote", document)
            remote = _mapping(item, "remote", document)
            if set(nonremote) != {"coins", "allowance"} or set(remote) != {
                "coins",
                "allowance",
            }:
                raise ConfigError(
                    f"{document.path}: {projectile} purchase unit 字段必须为 coins、allowance"
                )
            parsed = (
                _positive_integer(
                    item,
                    "team_cap",
                    document,
                    f"projectile_allowance.purchase.{projectile}.team_cap",
                ),
                _positive_integer(
                    nonremote,
                    "coins",
                    document,
                    f"projectile_allowance.purchase.{projectile}.nonremote.coins",
                ),
                _positive_integer(
                    nonremote,
                    "allowance",
                    document,
                    f"projectile_allowance.purchase.{projectile}.nonremote.allowance",
                ),
                _positive_integer(
                    remote,
                    "coins",
                    document,
                    f"projectile_allowance.purchase.{projectile}.remote.coins",
                ),
                _positive_integer(
                    remote,
                    "allowance",
                    document,
                    f"projectile_allowance.purchase.{projectile}.remote.allowance",
                ),
            )
            if parsed != expected:
                raise ConfigError(
                    f"{document.path}: {projectile} projectile allowance purchase "
                    "与 RMUC 2026 Regional V1.4.0 不匹配"
                )
            self._projectile_purchase_rules[projectile] = _ProjectilePurchaseRule(
                team_cap=parsed[0],
                nonremote_coins=parsed[1],
                nonremote_allowance=parsed[2],
                remote_coins=parsed[3],
                remote_allowance=parsed[4],
            )

        sentry_supply = _mapping(
            projectile_allowance, "sentry_supply", document
        )
        if set(sentry_supply) != {"interval", "allowance"}:
            raise ConfigError(
                f"{document.path}: `projectile_allowance.sentry_supply` "
                "必须只包含 interval、allowance"
            )
        self._sentry_supply_interval = _number(
            sentry_supply,
            "interval",
            document,
            "projectile_allowance.sentry_supply.interval",
        )
        self._sentry_supply_allowance = _positive_integer(
            sentry_supply,
            "allowance",
            document,
            "projectile_allowance.sentry_supply.allowance",
        )
        if self._sentry_supply_interval != 60 or self._sentry_supply_allowance != 100:
            raise ConfigError(
                f"{document.path}: Sentry supply 必须为每 60 秒 100 发"
            )

        shooting_heat = _mapping(document.data, "shooting_heat", document)
        if set(shooting_heat) != {
            "detection_hz",
            "per_shot",
            "permanent_margin",
            "sentry",
        }:
            raise ConfigError(
                f"{document.path}: `shooting_heat` 字段不完整或包含未知字段"
            )
        detection_hz = _positive_integer(
            shooting_heat,
            "detection_hz",
            document,
            "shooting_heat.detection_hz",
        )
        if detection_hz != 10:
            raise ConfigError(
                f"{document.path}: RMUC shooting heat detection_hz 必须为 10"
            )
        self._shooting_heat_detection_hz = float(detection_hz)

        per_shot = _mapping(shooting_heat, "per_shot", document)
        permanent_margin = _mapping(
            shooting_heat, "permanent_margin", document
        )
        if set(per_shot) != {"17mm", "42mm"}:
            raise ConfigError(
                f"{document.path}: `shooting_heat.per_shot` 必须包含 17mm、42mm"
            )
        if set(permanent_margin) != {"17mm", "42mm"}:
            raise ConfigError(
                f"{document.path}: `shooting_heat.permanent_margin` "
                "必须包含 17mm、42mm"
            )
        self._shooting_heat_per_shot = {
            projectile: _positive_integer(
                per_shot,
                projectile,
                document,
                f"shooting_heat.per_shot.{projectile}",
            )
            for projectile in ("17mm", "42mm")
        }
        self._shooting_heat_permanent_margin = {
            projectile: _positive_integer(
                permanent_margin,
                projectile,
                document,
                f"shooting_heat.permanent_margin.{projectile}",
            )
            for projectile in ("17mm", "42mm")
        }
        if self._shooting_heat_per_shot != {"17mm": 10, "42mm": 100}:
            raise ConfigError(
                f"{document.path}: RMUC 每发热量必须为 17mm=10、42mm=100"
            )
        if self._shooting_heat_permanent_margin != {
            "17mm": 100,
            "42mm": 200,
        }:
            raise ConfigError(
                f"{document.path}: RMUC Q2 margin 必须为 17mm=100、42mm=200"
            )

        sentry_heat = _mapping(shooting_heat, "sentry", document)
        if set(sentry_heat) != {"mode", "heat_limit", "cooling_per_second"}:
            raise ConfigError(
                f"{document.path}: `shooting_heat.sentry` "
                "必须只包含 mode、heat_limit、cooling_per_second"
            )
        sentry_mode = _string(
            sentry_heat,
            "mode",
            document,
            "shooting_heat.sentry.mode",
        )
        sentry_heat_limit = _positive_integer(
            sentry_heat,
            "heat_limit",
            document,
            "shooting_heat.sentry.heat_limit",
        )
        sentry_cooling = _positive_integer(
            sentry_heat,
            "cooling_per_second",
            document,
            "shooting_heat.sentry.cooling_per_second",
        )
        if (
            sentry_mode != "automatic"
            or sentry_heat_limit != 260
            or sentry_cooling != 30
        ):
            raise ConfigError(
                f"{document.path}: 当前 Rules Lab Sentry Heat 必须为 "
                "automatic / limit 260 / cooling 30"
            )
        self._sentry_heat_limit = float(sentry_heat_limit)
        self._sentry_cooling_per_second = float(sentry_cooling)

        chassis_power = _mapping(document.data, "chassis_power", document)
        if set(chassis_power) != {
            "detection_hz",
            "buffer_energy_max",
            "power_off_duration",
            "lab_power_demand",
        }:
            raise ConfigError(
                f"{document.path}: `chassis_power` 字段不完整或包含未知字段"
            )
        detection_hz = _positive_integer(
            chassis_power,
            "detection_hz",
            document,
            "chassis_power.detection_hz",
        )
        if detection_hz != 10:
            raise ConfigError(
                f"{document.path}: RMUC chassis power detection_hz 必须为 10"
            )
        self._chassis_power_detection_hz = float(detection_hz)

        buffer_energy_max = _number(
            chassis_power,
            "buffer_energy_max",
            document,
            "chassis_power.buffer_energy_max",
        )
        power_off_duration = _number(
            chassis_power,
            "power_off_duration",
            document,
            "chassis_power.power_off_duration",
        )
        if buffer_energy_max != 60:
            raise ConfigError(
                f"{document.path}: RMUC 基础 Buffer Energy 上限必须为 60 J"
            )
        if power_off_duration != 5:
            raise ConfigError(
                f"{document.path}: RMUC Buffer 耗尽底盘断电必须为 5 秒"
            )
        self._chassis_buffer_energy_max = float(buffer_energy_max)
        self._chassis_power_off_duration = float(power_off_duration)

        lab_power_demand = _mapping(
            chassis_power,
            "lab_power_demand",
            document,
        )
        if set(lab_power_demand) != {"stationary", "moving_over_limit"}:
            raise ConfigError(
                f"{document.path}: `chassis_power.lab_power_demand` "
                "必须只包含 stationary、moving_over_limit"
            )
        stationary = _number(
            lab_power_demand,
            "stationary",
            document,
            "chassis_power.lab_power_demand.stationary",
        )
        moving_over_limit = _number(
            lab_power_demand,
            "moving_over_limit",
            document,
            "chassis_power.lab_power_demand.moving_over_limit",
        )
        if stationary != 0 or moving_over_limit != 5:
            raise ConfigError(
                f"{document.path}: Rules Lab synthetic power 必须为 "
                "stationary=0、moving_over_limit=5"
            )
        self._chassis_stationary_power_demand = float(stationary)
        self._chassis_moving_over_limit = float(moving_over_limit)

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
        self._d4_coordinator = _D4CoordinatorState()
        self._economy_by_team: dict[str, _TeamEconomyState] = {}
        self._next_timed_gold_grant_index = 0
        self._next_periodic_gold_tick = self._economy_periodic_interval
        self._projectile_allowance_by_robot: dict[
            str, _ProjectileAllowanceState
        ] = {}
        self._projectile_purchase_by_team: dict[
            str, _TeamProjectilePurchaseState
        ] = {}
        self._shooting_heat_by_robot: dict[str, _ShootingHeatState] = {}
        self._heat_cooling_accumulator = 0.0
        self._chassis_power_by_robot: dict[str, _ChassisPowerState] = {}
        self._chassis_power_accumulator = 0.0
        self._current_synthetic_power_by_robot: dict[str, float] = {}
        self._next_sentry_supply_grant = self._sentry_supply_interval
        self._projectile_exchange_zones_by_team: dict[str, tuple[Zone, ...]] = {}
        self._supply_buff_zone_by_team: dict[str, Zone] = {}
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
            coins=tuple(
                (team_id, state.coins)
                for team_id, state in sorted(self._economy_by_team.items())
            ),
            team_economy=tuple(
                (
                    team_id,
                    state.coins,
                    *self._periodic_gold_rate(team_id),
                )
                for team_id, state in sorted(self._economy_by_team.items())
            ),
            robot_projectiles=tuple(
                (
                    robot_id,
                    state.projectile_type,
                    state.allowed,
                )
                for robot_id, state in sorted(
                    self._projectile_allowance_by_robot.items()
                )
            ),
            robot_shooting_heat=tuple(
                (
                    robot_id,
                    state.heat,
                    self._effective_heat_parameters(robot_id).heat_limit,
                    state.temporarily_locked,
                    state.permanently_locked,
                )
                for robot_id, state in sorted(
                    self._shooting_heat_by_robot.items()
                )
            ),
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
                    state.completion_count_by_difficulty[4],
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
                    state.energy_unit_credits,
                )
                for engineer_id, state in sorted(
                    self._engineer_resources_by_id.items()
                )
            ),
            d4_status=tuple(
                (
                    team_id,
                    (
                        "complete"
                        if state.completion_count_by_difficulty[4] >= 1
                        else "active"
                        if self._d4_coordinator.active_team_id == team_id
                        else "pending"
                        if self._d4_coordinator.pending_team_id == team_id
                        else "locked"
                        if state.permanently_locked_out_of_d4
                        else "idle"
                    ),
                    state.d4_attempt.current_step if state.d4_attempt is not None else 0,
                    state.d4_attempt.activated_at if state.d4_attempt is not None else 0.0,
                    (
                        state.d4_attempt.first_core_completed_at
                        if state.d4_attempt is not None
                        and state.d4_attempt.first_core_completed_at is not None
                        else -1.0
                    ),
                    (
                        self._d4_coordinator.priority_buffer_remaining
                        if self._d4_coordinator.pending_team_id == team_id
                        else 0.0
                    ),
                    state.d4_retry_after,
                    state.permanently_locked_out_of_d4,
                    state.d4_priority_failure_gold_penalty,
                )
                for team_id, state in sorted(self._tech_core_by_team.items())
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
        allowance = self._projectile_allowance_by_robot.get(robot.id)
        shooting_heat = self._shooting_heat_by_robot.get(robot.id)
        return (
            robot.alive
            and robot.damage > 0
            and allowance is not None
            and allowance.allowed > 0
            and shooting_heat is not None
            and not shooting_heat.temporarily_locked
            and not shooting_heat.permanently_locked
        )

    def can_target(self, target: DamageableTarget) -> bool:
        if isinstance(target, Structure):
            # Unlike RMUL robot invincibility, an invincible RMUC Base must not
            # consume target selection while its Outpost is alive.
            return self.can_receive_damage(target)
        return target.alive

    def on_attack_committed(self, robot: Robot) -> None:
        """Commit one legal shot using pre-shot effective Heat parameters."""
        allowance = self._projectile_allowance_by_robot.get(robot.id)
        shooting_heat = self._shooting_heat_by_robot.get(robot.id)
        if (
            allowance is None
            or allowance.allowed <= 0
            or shooting_heat is None
            or shooting_heat.temporarily_locked
            or shooting_heat.permanently_locked
        ):
            return

        allowance.allowed -= 1
        allowance.disengaged_elapsed = 0.0
        allowance.combat_activity_this_frame = True

        heat_parameters = self._effective_heat_parameters(robot.id)
        shooting_heat.heat += self._shooting_heat_per_shot[
            heat_parameters.projectile_type
        ]
        if shooting_heat.heat + 1e-9 >= heat_parameters.permanent_threshold:
            shooting_heat.permanently_locked = True
            shooting_heat.temporarily_locked = False
        elif shooting_heat.heat > heat_parameters.heat_limit + 1e-9:
            shooting_heat.temporarily_locked = True

        shot_experience = self._shot_experience.get(robot.type)
        if shot_experience is not None:
            self._grant_experience(robot.id, shot_experience)

    def exchange_projectiles(self, match: "Match", robot: Robot) -> bool:
        """Perform the non-remote exchange at an eligible own-side buff point."""
        return self._purchase_projectile_allowance(match, robot, remote=False)

    def remote_exchange_projectiles(self, match: "Match", robot: Robot) -> bool:
        """Accept a remote exchange now and deliver its allowance six seconds later."""
        return self._purchase_projectile_allowance(match, robot, remote=True)

    def _purchase_projectile_allowance(
        self,
        match: "Match",
        robot: Robot,
        *,
        remote: bool,
    ) -> bool:
        allowance_state = self._projectile_allowance_by_robot.get(robot.id)
        economy_state = self._economy_by_team.get(robot.team)
        purchase_state = self._projectile_purchase_by_team.get(robot.team)
        if (
            match.finished
            or not robot.alive
            or self._robots_by_id.get(robot.id) is not robot
            or allowance_state is None
            or economy_state is None
            or purchase_state is None
        ):
            return False

        projectile = allowance_state.projectile_type
        rule = self._projectile_purchase_rules.get(projectile)
        if rule is None or self._projectile_by_type.get(robot.type) != projectile:
            return False

        if remote:
            if allowance_state.disengaged_elapsed + 1e-9 < self._projectile_disengaged_after:
                return False
            cost = rule.remote_coins
            amount = rule.remote_allowance
        else:
            zones = self._projectile_exchange_zones_by_team.get(robot.team, ())
            if not any(zone.contains(robot.position) for zone in zones):
                return False
            cost = rule.nonremote_coins
            amount = rule.nonremote_allowance

        purchased = (
            purchase_state.purchased_17mm
            if projectile == "17mm"
            else purchase_state.purchased_42mm
        )
        if economy_state.coins < cost or purchased + amount > rule.team_cap:
            return False

        economy_state.coins -= cost
        if projectile == "17mm":
            purchase_state.purchased_17mm += amount
        else:
            purchase_state.purchased_42mm += amount

        if remote:
            allowance_state.pending_remote_deliveries.append(
                _PendingProjectileDelivery(
                    amount=amount,
                    effective_at=match.elapsed_time
                    + self._projectile_remote_effective_delay,
                )
            )
        else:
            allowance_state.allowed += amount
        return True

    def pickup_energy_unit(self, match: "Match", engineer: Robot) -> bool:
        """Add one Rules Lab Energy Unit resource credit, up to the D4 cap of two."""
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
            or resource_state.energy_unit_credits >= 2
            or resource_zone is None
            or not resource_zone.contains(engineer.position)
        ):
            return False
        resource_state.energy_unit_credits += 1
        return True

    def start_tech_core_assembly(
        self,
        match: "Match",
        engineer: Robot,
        difficulty: int,
    ) -> bool:
        """Start D1-D3 directly or request D4 through the global coordinator."""
        if difficulty == 4:
            return self._request_d4_assembly(match, engineer)
        if (
            match.finished
            or engineer.type != "engineer"
            or not engineer.alive
            or self._robots_by_id.get(engineer.id) is not engineer
            or difficulty not in {1, 2, 3}
            or self._d4_coordinator.active_team_id is not None
            or self._d4_coordinator.pending_team_id is not None
        ):
            return False

        team_state = self._tech_core_by_team.get(engineer.team)
        resource_state = self._engineer_resources_by_id.get(engineer.id)
        assembly_zone = self._assembly_zone_by_team.get(engineer.team)
        rule = self._tech_core_difficulties[difficulty]
        if (
            team_state is None
            or resource_state is None
            or resource_state.energy_unit_credits < 1
            or assembly_zone is None
            or not assembly_zone.contains(engineer.position)
            or team_state.active_attempt is not None
            or team_state.d4_attempt is not None
            or match.elapsed_time + 1e-9 < rule.available_after
        ):
            return False

        if (
            rule.prerequisite is not None
            and team_state.completion_count_by_difficulty[rule.prerequisite] < 1
        ):
            return False

        resource_state.energy_unit_credits -= 1
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
        assembly_zone = self._assembly_zone_by_team.get(engineer.team)
        if (
            team_state is None
            or team_state.active_attempt is None
            or team_state.active_attempt.engineer_id != engineer.id
            or assembly_zone is None
            or not assembly_zone.contains(engineer.position)
        ):
            return False

        difficulty = team_state.active_attempt.difficulty
        previous_count = team_state.completion_count_by_difficulty[difficulty]
        team_state.completion_count_by_difficulty[difficulty] = previous_count + 1
        team_state.active_attempt = None
        self._add_tech_core_periodic_gold(
            engineer.team,
            difficulty,
            first_completion=previous_count == 0,
        )

        if previous_count == 0:
            level_cap = self._tech_core_difficulties[difficulty].first_level_cap
            if level_cap is not None:
                self._level_cap_by_team[engineer.team] = max(
                    self._level_cap_by_team[engineer.team],
                    level_cap,
                )
        return True

    def confirm_d4_step(
        self,
        match: "Match",
        engineer: Robot,
        core_slot: str,
        step: int,
    ) -> bool:
        """Confirm one abstracted D4 mechanical step on one of the two Core slots."""
        if (
            match.finished
            or core_slot not in {"own", "opponent"}
            or engineer.type != "engineer"
            or not engineer.alive
            or self._robots_by_id.get(engineer.id) is not engineer
            or self._d4_coordinator.active_team_id != engineer.team
        ):
            return False

        team_state = self._tech_core_by_team.get(engineer.team)
        assembly_zone = self._assembly_zone_by_team.get(engineer.team)
        attempt = team_state.d4_attempt if team_state is not None else None
        if (
            attempt is None
            or attempt.engineer_id != engineer.id
            or step != attempt.current_step
            or core_slot in attempt.completed_core_slots
            or assembly_zone is None
            or not assembly_zone.contains(engineer.position)
        ):
            return False

        total_deadline = attempt.activated_at + self._d4_total_window
        if match.elapsed_time > total_deadline + 1e-9:
            self._fail_d4_attempt(engineer.team, total_deadline, "total-timeout")
            return False

        if step in self._d4_paired_steps and attempt.first_core_completed_at is not None:
            pair_deadline = (
                attempt.first_core_completed_at + self._d4_paired_step_window
            )
            if match.elapsed_time > pair_deadline + 1e-9:
                self._fail_d4_attempt(engineer.team, pair_deadline, "pair-timeout")
                return False

        attempt.completed_core_slots.add(core_slot)
        if (
            step in self._d4_paired_steps
            and attempt.first_core_completed_at is None
        ):
            attempt.first_core_completed_at = match.elapsed_time

        if len(attempt.completed_core_slots) < 2:
            return True

        if step == 6:
            self._complete_d4_attempt(engineer.team)
            return True

        attempt.current_step += 1
        attempt.completed_core_slots.clear()
        attempt.first_core_completed_at = None
        return True

    def _request_d4_assembly(self, match: "Match", engineer: Robot) -> bool:
        if (
            match.finished
            or engineer.type != "engineer"
            or not engineer.alive
            or self._robots_by_id.get(engineer.id) is not engineer
            or self._d4_coordinator.active_team_id is not None
            or self._d4_coordinator.pending_team_id is not None
        ):
            return False

        team_state = self._tech_core_by_team.get(engineer.team)
        resource_state = self._engineer_resources_by_id.get(engineer.id)
        assembly_zone = self._assembly_zone_by_team.get(engineer.team)
        rule = self._tech_core_difficulties[4]
        if (
            team_state is None
            or resource_state is None
            or resource_state.energy_unit_credits < 2
            or assembly_zone is None
            or not assembly_zone.contains(engineer.position)
            or team_state.active_attempt is not None
            or team_state.d4_attempt is not None
            or team_state.completion_count_by_difficulty[4] >= 1
            or team_state.permanently_locked_out_of_d4
            or match.elapsed_time + 1e-9 < team_state.d4_retry_after
            or match.elapsed_time + 1e-9 < rule.available_after
            or team_state.completion_count_by_difficulty[3] < 1
        ):
            return False

        other_team_id = next(
            team_id
            for team_id in self._tech_core_by_team
            if team_id != engineer.team
        )
        other_state = self._tech_core_by_team[other_team_id]

        resource_state.energy_unit_credits -= 2
        if other_state.active_attempt is not None:
            self._d4_coordinator.pending_team_id = engineer.team
            self._d4_coordinator.pending_engineer_id = engineer.id
            self._d4_coordinator.priority_buffer_remaining = self._d4_priority_buffer
            self._d4_coordinator.priority_takeover = True
            return True

        self._activate_d4(
            team_id=engineer.team,
            engineer_id=engineer.id,
            activated_at=match.elapsed_time,
            priority_takeover=False,
        )
        return True

    def _activate_d4(
        self,
        *,
        team_id: str,
        engineer_id: str,
        activated_at: float,
        priority_takeover: bool,
    ) -> None:
        team_state = self._tech_core_by_team[team_id]
        team_state.d4_attempt = _D4Attempt(
            engineer_id=engineer_id,
            activated_at=activated_at,
            priority_takeover=priority_takeover,
        )
        self._d4_coordinator.active_team_id = team_id
        self._d4_coordinator.pending_team_id = None
        self._d4_coordinator.pending_engineer_id = None
        self._d4_coordinator.priority_buffer_remaining = 0.0
        self._d4_coordinator.priority_takeover = False

    def _complete_d4_attempt(self, team_id: str) -> None:
        team_state = self._tech_core_by_team[team_id]
        if team_state.completion_count_by_difficulty[4] != 0:
            raise RuntimeError("D4 completion count must be zero before success")
        team_state.completion_count_by_difficulty[4] = 1
        self._add_tech_core_periodic_gold(
            team_id,
            4,
            first_completion=True,
        )
        team_state.d4_attempt = None
        self._d4_coordinator.active_team_id = None

    def _fail_d4_attempt(
        self,
        team_id: str,
        failure_time: float,
        reason: str,
    ) -> None:
        del reason  # Reserved for deterministic tests/debugging without a failure engine.
        team_state = self._tech_core_by_team[team_id]
        attempt = team_state.d4_attempt
        if attempt is None:
            return

        priority_takeover = attempt.priority_takeover
        team_state.d4_attempt = None
        self._d4_coordinator.active_team_id = None
        if priority_takeover:
            team_state.permanently_locked_out_of_d4 = True
            team_state.d4_priority_failure_gold_penalty = (
                self._d4_priority_failure_gold_penalty
            )
            economy_state = self._economy_by_team.get(team_id)
            if economy_state is not None:
                economy_state.d4_priority_penalty_active_from = failure_time
        else:
            team_state.d4_retry_after = max(
                team_state.d4_retry_after,
                failure_time + self._d4_retry_lockout,
            )

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
        """Cool RMUC shooting Heat at 10 Hz before this frame commits shots."""
        if dt <= 0:
            return

        self._heat_cooling_accumulator += dt
        ticks = math.floor(
            self._heat_cooling_accumulator * self._shooting_heat_detection_hz
            + 1e-9
        )
        if ticks <= 0:
            return

        tick_duration = 1.0 / self._shooting_heat_detection_hz
        self._heat_cooling_accumulator = max(
            0.0,
            self._heat_cooling_accumulator - ticks * tick_duration,
        )
        for _ in range(ticks):
            for robot_id, state in self._shooting_heat_by_robot.items():
                robot = self._robots_by_id[robot_id]
                if not robot.alive or state.heat <= 0:
                    continue
                parameters = self._effective_heat_parameters(robot_id)
                state.heat = max(
                    0.0,
                    state.heat
                    - parameters.cooling_per_second
                    / self._shooting_heat_detection_hz,
                )
                if state.heat <= 1e-9:
                    state.heat = 0.0
                    state.temporarily_locked = False

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
        self._d4_coordinator = _D4CoordinatorState()
        initial_coins = self._initial_coins_for_ratings(
            self._economy_lab_rating["project_document"],
            self._economy_lab_rating["technical_solution"],
        )
        self._economy_by_team = {
            team_id: _TeamEconomyState(coins=initial_coins)
            for team_id in team_by_side.values()
        }
        self._next_timed_gold_grant_index = 0
        self._next_periodic_gold_tick = self._economy_periodic_interval
        self._projectile_allowance_by_robot = {}
        for robot in match.robots:
            initial_rule = self._projectile_initial.get(robot.type)
            if initial_rule is None or robot.type == "engineer":
                continue
            projectile, initial_allowance = initial_rule
            self._projectile_allowance_by_robot[robot.id] = (
                _ProjectileAllowanceState(
                    projectile_type=projectile,
                    allowed=initial_allowance,
                    disengaged_elapsed=self._projectile_disengaged_after,
                )
            )
        self._projectile_purchase_by_team = {
            team_id: _TeamProjectilePurchaseState()
            for team_id in team_by_side.values()
        }
        self._shooting_heat_by_robot = {
            robot_id: _ShootingHeatState()
            for robot_id in self._projectile_allowance_by_robot
        }
        self._heat_cooling_accumulator = 0.0
        self._next_sentry_supply_grant = self._sentry_supply_interval
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
        required_zone_ids = (
            set(self._rebuild_zone_ids.values())
            | {
                zone_id
                for side_zones in self._tech_core_zone_ids.values()
                for zone_id in side_zones.values()
            }
            | {
                zone_id
                for side_zones in self._projectile_zone_ids.values()
                for zone_id in side_zones.values()
            }
        )
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
        self._projectile_exchange_zones_by_team = {
            team_by_side[side]: tuple(
                zones_by_id[self._projectile_zone_ids[side][zone_type]]
                for zone_type in ("supply", "base", "outpost")
            )
            for side in ("red", "blue")
        }
        self._supply_buff_zone_by_team = {
            team_by_side[side]: zones_by_id[
                self._projectile_zone_ids[side]["supply"]
            ]
            for side in ("red", "blue")
        }

    def update(self, match: "Match", dt: float) -> None:
        self._consume_events(match)
        self._advance_projectile_allowance(match, dt)
        self._advance_tech_core_attempts(match, dt)
        self._advance_d4(match, dt)
        self._advance_economy(match)

        frame_start = match.elapsed_time - dt
        active_rebuild_dt = max(
            0.0, min(dt, self._rebuild_cutoff - frame_start)
        )
        if active_rebuild_dt > 0:
            self._advance_rebuild(match, active_rebuild_dt)

        if match.elapsed_time >= self._rebuild_cutoff - 1e-9:
            for state in self._team_states.values():
                state.rebuild_progress_by_robot.clear()

    def _advance_projectile_allowance(
        self,
        match: "Match",
        dt: float,
    ) -> None:
        settlement_end = min(match.elapsed_time, self._time_limit)

        for robot_id, state in self._projectile_allowance_by_robot.items():
            robot = self._robots_by_id[robot_id]
            if state.combat_activity_this_frame:
                state.disengaged_elapsed = 0.0
            elif robot.alive:
                state.disengaged_elapsed += max(0.0, dt)
            else:
                state.disengaged_elapsed = 0.0
            state.combat_activity_this_frame = False

            if not state.pending_remote_deliveries:
                continue
            remaining: list[_PendingProjectileDelivery] = []
            for delivery in state.pending_remote_deliveries:
                if (
                    delivery.effective_at < self._time_limit - 1e-9
                    and delivery.effective_at <= settlement_end + 1e-9
                ):
                    state.allowed += delivery.amount
                else:
                    remaining.append(delivery)
            state.pending_remote_deliveries = remaining

        while (
            self._next_sentry_supply_grant <= settlement_end + 1e-9
            and self._next_sentry_supply_grant < self._time_limit - 1e-9
        ):
            for purchase_state in self._projectile_purchase_by_team.values():
                purchase_state.pending_sentry_supply += self._sentry_supply_allowance
            self._next_sentry_supply_grant += self._sentry_supply_interval

        for team_id, purchase_state in self._projectile_purchase_by_team.items():
            if purchase_state.pending_sentry_supply <= 0:
                continue
            sentry = next(
                (
                    robot
                    for robot in match.robots
                    if robot.team == team_id and robot.type == "sentry"
                ),
                None,
            )
            supply_zone = self._supply_buff_zone_by_team.get(team_id)
            if (
                sentry is None
                or not sentry.alive
                or supply_zone is None
                or not supply_zone.contains(sentry.position)
            ):
                continue
            state = self._projectile_allowance_by_robot[sentry.id]
            state.allowed += purchase_state.pending_sentry_supply
            purchase_state.pending_sentry_supply = 0

    def _initial_coins_for_ratings(
        self,
        project_document: str,
        technical_solution: str,
    ) -> int:
        return max(
            0,
            self._economy_initial_coins
            + self._economy_rating_modifiers["project_document"][project_document]
            + self._economy_rating_modifiers["technical_solution"][technical_solution],
        )

    def _add_tech_core_periodic_gold(
        self,
        team_id: str,
        difficulty: int,
        *,
        first_completion: bool,
    ) -> None:
        rule = self._tech_core_difficulties[difficulty]
        amount = (
            rule.first_periodic_gold_per_10s
            if first_completion
            else rule.repeat_periodic_gold_per_10s
        )
        if amount is None:
            raise RuntimeError(
                f"Tech Core D{difficulty} has no repeat periodic-gold reward"
            )
        self._economy_by_team[
            team_id
        ].tech_core_periodic_gold_per_10s += amount

    def _periodic_gold_rate(self, team_id: str) -> tuple[int, int, int]:
        economy_state = self._economy_by_team[team_id]
        gross = economy_state.tech_core_periodic_gold_per_10s
        penalty = (
            self._tech_core_by_team[team_id].d4_priority_failure_gold_penalty
            if economy_state.d4_priority_penalty_active_from is not None
            else 0
        )
        return gross, penalty, gross - penalty

    def _periodic_gold_net_at(self, team_id: str, tick_time: float) -> int:
        economy_state = self._economy_by_team[team_id]
        gross = economy_state.tech_core_periodic_gold_per_10s
        active_from = economy_state.d4_priority_penalty_active_from
        penalty = (
            self._tech_core_by_team[team_id].d4_priority_failure_gold_penalty
            if active_from is not None and tick_time + 1e-9 >= active_from
            else 0
        )
        return gross - penalty

    def _advance_economy(self, match: "Match") -> None:
        if match.finished:
            return
        settlement_end = min(match.elapsed_time, self._time_limit)

        while self._next_timed_gold_grant_index < len(self._economy_timed_grants):
            grant_time, amount = self._economy_timed_grants[
                self._next_timed_gold_grant_index
            ]
            if grant_time > settlement_end + 1e-9:
                break
            for state in self._economy_by_team.values():
                state.coins += amount
            self._next_timed_gold_grant_index += 1

        while (
            self._next_periodic_gold_tick <= settlement_end + 1e-9
            and self._next_periodic_gold_tick < self._time_limit - 1e-9
        ):
            tick_time = self._next_periodic_gold_tick
            for team_id, state in self._economy_by_team.items():
                state.coins = max(
                    0,
                    state.coins + self._periodic_gold_net_at(team_id, tick_time),
                )
            self._next_periodic_gold_tick += self._economy_periodic_interval

    def _effective_heat_parameters(
        self,
        robot_id: str,
    ) -> _EffectiveHeatParameters:
        robot_type = self._robot_types_by_id[robot_id]
        projectile_type = self._projectile_by_type.get(robot_type)
        if projectile_type not in {"17mm", "42mm"}:
            raise KeyError(robot_id)

        if robot_type in _EXPERIENCE_ROBOT_TYPES:
            performance = self._effective_performance(robot_id)
            heat_limit = float(performance.heat_limit)
            cooling_per_second = float(performance.cooling_per_second)
        elif robot_type == "sentry":
            heat_limit = self._sentry_heat_limit
            cooling_per_second = self._sentry_cooling_per_second
        else:
            raise KeyError(robot_id)

        return _EffectiveHeatParameters(
            projectile_type=projectile_type,
            heat_limit=heat_limit,
            cooling_per_second=cooling_per_second,
            permanent_threshold=(
                heat_limit
                + self._shooting_heat_permanent_margin[projectile_type]
            ),
        )

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
                allowance_state = self._projectile_allowance_by_robot.get(
                    event.robot_id
                )
                if allowance_state is not None:
                    allowance_state.combat_activity_this_frame = True
                if known_experience_source:
                    self._grant_experience(
                        event.attacker_id,
                        event.damage * self._robot_damage_experience_per_hp,
                    )
                continue

            if event.type == MatchEventType.ROBOT_DESTROYED:
                self._grant_kill_experience(event)
                shooting_heat = self._shooting_heat_by_robot.get(event.robot_id)
                if shooting_heat is not None:
                    shooting_heat.heat = 0.0
                    shooting_heat.temporarily_locked = False
                resource_state = self._engineer_resources_by_id.get(event.robot_id)
                if resource_state is not None:
                    resource_state.energy_unit_credits = 0
                    team_state = self._tech_core_by_team.get(event.team_id)
                    if (
                        team_state is not None
                        and team_state.active_attempt is not None
                        and team_state.active_attempt.engineer_id == event.robot_id
                    ):
                        self._fail_tech_core_attempt(event.team_id)
                    if (
                        team_state is not None
                        and team_state.d4_attempt is not None
                        and team_state.d4_attempt.engineer_id == event.robot_id
                    ):
                        self._fail_d4_attempt(
                            event.team_id,
                            event.time,
                            "engineer-destroyed",
                        )
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
        # The attempt's one Energy Unit credit was reserved at start.
        # Failure consumes that reservation but preserves any unreserved credit.
        team_state.active_attempt = None

    def _advance_d4(self, match: "Match", dt: float) -> None:
        coordinator = self._d4_coordinator
        if coordinator.pending_team_id is not None:
            remaining_before = coordinator.priority_buffer_remaining
            if dt + 1e-9 < remaining_before:
                coordinator.priority_buffer_remaining = max(
                    0.0,
                    remaining_before - dt,
                )
                return

            pending_team_id = coordinator.pending_team_id
            pending_engineer_id = coordinator.pending_engineer_id
            priority_takeover = coordinator.priority_takeover
            leftover_dt = max(0.0, dt - remaining_before)
            activation_time = match.elapsed_time - leftover_dt

            other_team_id = next(
                team_id
                for team_id in self._tech_core_by_team
                if team_id != pending_team_id
            )
            if self._tech_core_by_team[other_team_id].active_attempt is not None:
                self._fail_tech_core_attempt(other_team_id)

            if pending_engineer_id is None:
                raise RuntimeError("D4 pending request missing engineer id")
            self._activate_d4(
                team_id=pending_team_id,
                engineer_id=pending_engineer_id,
                activated_at=activation_time,
                priority_takeover=priority_takeover,
            )
            self._advance_active_d4(match, leftover_dt)
            return

        if coordinator.active_team_id is not None:
            self._advance_active_d4(match, dt)

    def _advance_active_d4(self, match: "Match", dt: float) -> None:
        team_id = self._d4_coordinator.active_team_id
        if team_id is None:
            return
        team_state = self._tech_core_by_team[team_id]
        attempt = team_state.d4_attempt
        if attempt is None:
            self._d4_coordinator.active_team_id = None
            return

        engineer = self._robots_by_id.get(attempt.engineer_id)
        if engineer is None or not engineer.alive:
            self._fail_d4_attempt(team_id, match.elapsed_time, "engineer-destroyed")
            return

        frame_start = match.elapsed_time - max(0.0, dt)
        failure_candidates: list[tuple[float, str]] = []

        assembly_zone = self._assembly_zone_by_team[team_id]
        if assembly_zone.contains(engineer.position):
            attempt.outside_zone_elapsed = 0.0
        else:
            outside_before = attempt.outside_zone_elapsed
            attempt.outside_zone_elapsed += max(0.0, dt)
            if (
                attempt.outside_zone_elapsed + 1e-9
                >= self._tech_core_leave_zone_fail_after
            ):
                time_to_failure = max(
                    0.0,
                    self._tech_core_leave_zone_fail_after - outside_before,
                )
                failure_candidates.append(
                    (frame_start + time_to_failure, "left-assembly")
                )

        if attempt.first_core_completed_at is not None:
            pair_deadline = (
                attempt.first_core_completed_at + self._d4_paired_step_window
            )
            if match.elapsed_time > pair_deadline + 1e-9:
                failure_candidates.append((pair_deadline, "pair-timeout"))

        total_deadline = attempt.activated_at + self._d4_total_window
        if match.elapsed_time > total_deadline + 1e-9:
            failure_candidates.append((total_deadline, "total-timeout"))

        if failure_candidates:
            failure_time, reason = min(failure_candidates, key=lambda item: item[0])
            self._fail_d4_attempt(team_id, failure_time, reason)

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


def _integer(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{document.path}: `{field}` 必须是整数")
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
