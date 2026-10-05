"""Partial RMUC 2026 Regional V1.4.0 rules including progression, economy, Heat, and chassis power."""

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


_RMUC_ROBOT_TYPES = ("hero", "engineer", "infantry", "sentry", "drone")
_GROUND_ROBOT_TYPES = {"hero", "engineer", "infantry", "sentry"}
_REBUILD_ROBOT_TYPES = set(_GROUND_ROBOT_TYPES)
_EXPERIENCE_ROBOT_TYPES = {"hero", "infantry", "drone"}
_HP_PERFORMANCE_ROBOT_TYPES = {"hero", "infantry"}
# V1.4.0 Radar marking can track Drone, but the vulnerability effect itself
# is explicitly limited to ground robots.
_RADAR_VULNERABILITY_ROBOT_TYPES = set(_GROUND_ROBOT_TYPES)


@dataclass
class _RobotProgressionState:
    experience: float = 0.0
    level: int = 1


@dataclass
class _DroneAirSupportState:
    free_seconds: float
    active: bool = False
    next_grant_at: float = 60.0


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
    tech_core_defense: float = 0.0
    base_virtual_shield: int = 0


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
class _TimedAttackBuff:
    multiplier: float
    remaining: float


@dataclass
class _TimedEnergyMechanismBuff:
    defense: float
    cooling_multiplier: float
    remaining: float


@dataclass(frozen=True)
class _RadarVulnerabilityState:
    source_team_id: str
    base_vulnerability: float


@dataclass
class _RadarDoubleVulnerabilityState:
    remaining: float = 0.0
    activations: int = 0


@dataclass
class _RobotLifecycleState:
    disengaged_elapsed: float
    combat_activity_this_frame: bool = False
    respawn_progress: float = 0.0
    respawn_required: int | None = None
    immediate_respawn_count: int = 0
    weak: bool = False
    invincible_remaining: float = 0.0
    minimum_invincible_remaining: float = 0.0
    immediate_power_boost_remaining: float = 0.0
    pending_remote_healing_effective_at: float | None = None
    healing_rounding_residual: float = 0.0


@dataclass
class _ProjectileAllowanceState:
    projectile_type: str
    allowed: int
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


@dataclass
class _CentralDefenseBuffState:
    owner_team_id: str | None = None
    release_remaining: float = 0.0


@dataclass
class _FortressBuffState:
    owner_robot_id: str | None = None
    release_remaining: float = 0.0


@dataclass
class _FortressReservedProjectileState:
    reserved: int = 0
    last_limit: int = 0
    initialized: bool = False


@dataclass
class _EnemyFortressOccupationState:
    occupy_remaining: float = 0.0
    occupation_elapsed: float = 0.0
    retention_remaining: float = 0.0


@dataclass(frozen=True)
class _TerrainCrossingRule:
    sequence_window: float
    defense: float
    defense_duration: float
    reacquire_cooldown: float = 0.0
    cooling_multiplier: float = 1.0
    cooling_duration: float = 0.0


@dataclass
class _TerrainSequenceState:
    terrain_type: str | None = None
    expected_zone_ids: tuple[str, ...] = ()
    next_index: int = 0
    expires_at: float = 0.0


@dataclass
class _TerrainCrossingState:
    standard_defense: float = 0.0
    standard_defense_remaining: float = 0.0
    tunnel_defense_remaining: float = 0.0
    tunnel_cooling_remaining: float = 0.0
    road_reacquire_remaining: float = 0.0
    sequence: _TerrainSequenceState = field(
        default_factory=_TerrainSequenceState
    )
    first_acquired_types: set[str] = field(default_factory=set)
    occupied_rfid_zone_ids: set[str] = field(default_factory=set)


class RMUC2026RegionalRules:
    """V1.4.0 Regional Rules Lab with progression, economy, Heat, and chassis power."""

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

        drone = _mapping(document.data, "drone_foundation", document)
        if set(drone) != {
            "projectile_muzzle_velocity_limit_mps",
            "initial_free_air_support_seconds",
            "periodic_free_grant_interval_seconds",
            "periodic_free_grant_seconds",
            "damage_applicable",
            "recovery_and_respawn",
            "chassis_power_overlimit",
            "capturable_buff_points",
        }:
            raise ConfigError(
                f"{document.path}: drone_foundation 字段不完整或包含未知字段"
            )
        self._drone_projectile_muzzle_velocity_limit_mps = _number(
            drone,
            "projectile_muzzle_velocity_limit_mps",
            document,
            "drone_foundation.projectile_muzzle_velocity_limit_mps",
        )
        self._drone_initial_free_air_support = _number(
            drone,
            "initial_free_air_support_seconds",
            document,
            "drone_foundation.initial_free_air_support_seconds",
        )
        self._drone_periodic_grant_interval = _number(
            drone,
            "periodic_free_grant_interval_seconds",
            document,
            "drone_foundation.periodic_free_grant_interval_seconds",
        )
        self._drone_periodic_grant = _number(
            drone,
            "periodic_free_grant_seconds",
            document,
            "drone_foundation.periodic_free_grant_seconds",
        )
        if (
            self._drone_projectile_muzzle_velocity_limit_mps != 25
            or self._drone_initial_free_air_support != 30
            or self._drone_periodic_grant_interval != 60
            or self._drone_periodic_grant != 20
            or drone.get("damage_applicable") is not False
            or drone.get("recovery_and_respawn") is not False
            or drone.get("chassis_power_overlimit") is not False
            or drone.get("capturable_buff_points") is not False
        ):
            raise ConfigError(
                f"{document.path}: drone_foundation 必须匹配 RMUC 2026 Regional V1.4.0"
            )

        economy = _mapping(document.data, "economy", document)
        if set(economy) != {
            "initial_coins",
            "periodic_interval",
            "qualification_modifiers",
            "lab_pre_match_rating",
            "immediate_respawn",
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

        immediate_respawn_economy = _mapping(
            economy, "immediate_respawn", document
        )
        if set(immediate_respawn_economy) != {
            "elapsed_interval",
            "elapsed_step_coins",
            "level_coins",
        }:
            raise ConfigError(
                f"{document.path}: `economy.immediate_respawn` "
                "字段不完整或包含未知字段"
            )
        self._immediate_respawn_elapsed_interval = _positive_integer(
            immediate_respawn_economy,
            "elapsed_interval",
            document,
            "economy.immediate_respawn.elapsed_interval",
        )
        self._immediate_respawn_elapsed_step_coins = _positive_integer(
            immediate_respawn_economy,
            "elapsed_step_coins",
            document,
            "economy.immediate_respawn.elapsed_step_coins",
        )
        self._immediate_respawn_level_coins = _positive_integer(
            immediate_respawn_economy,
            "level_coins",
            document,
            "economy.immediate_respawn.level_coins",
        )
        if (
            self._immediate_respawn_elapsed_interval != 60
            or self._immediate_respawn_elapsed_step_coins != 80
            or self._immediate_respawn_level_coins != 20
        ):
            raise ConfigError(
                f"{document.path}: RMUC 立即复活价格必须为 "
                "ceil(elapsed/60)*80 + level*20"
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
            raise ConfigError(                f"{document.path}: Tech Core Difficulty 2 first level_cap 必须为 7"
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
        if set(shot) != {"hero", "infantry", "drone"}:
            raise ConfigError(
                f"{document.path}: `experience.shot` 必须只包含 hero、infantry、drone"
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
            for robot_type in ("hero", "infantry", "drone")
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
        if set(performance) != {"lab_selection", "hero", "infantry", "drone"}:
            raise ConfigError(
                f"{document.path}: `performance` 必须只包含 lab_selection、hero、infantry、drone"
            )
        self._drone_performance = _parse_performance_rows(
            performance.get("drone"),
            ("heat_limit", "cooling_per_second"),
            document,
            "performance.drone",
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
                "common、hero、engineer、infantry、sentry、drone"
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

        robot_lifecycle = _mapping(document.data, "robot_lifecycle", document)
        if set(robot_lifecycle) != {"disengaged_after", "resupply", "respawn"}:
            raise ConfigError(
                f"{document.path}: `robot_lifecycle` 字段不完整或包含未知字段"
            )

        self._disengaged_after = _number(
            robot_lifecycle,
            "disengaged_after",
            document,
            "robot_lifecycle.disengaged_after",
        )
        if self._disengaged_after != 6:
            raise ConfigError(
                f"{document.path}: RMUC 脱战时长必须为 6 秒"
            )

        resupply = _mapping(robot_lifecycle, "resupply", document)
        if set(resupply) != {
            "heal_fraction_per_second",
            "enhanced_after",
            "enhanced_heal_fraction_per_second",
        }:
            raise ConfigError(
                f"{document.path}: `robot_lifecycle.resupply` "
                "字段不完整或包含未知字段"
            )
        self._resupply_heal_fraction_per_second = _fraction(
            resupply,
            "heal_fraction_per_second",
            document,
            "robot_lifecycle.resupply.heal_fraction_per_second",
        )
        self._resupply_enhanced_after = _number(
            resupply,
            "enhanced_after",
            document,
            "robot_lifecycle.resupply.enhanced_after",
        )
        self._resupply_enhanced_heal_fraction_per_second = _fraction(
            resupply,
            "enhanced_heal_fraction_per_second",
            document,
            "robot_lifecycle.resupply.enhanced_heal_fraction_per_second",
        )
        if (
            self._resupply_heal_fraction_per_second != 0.10
            or self._resupply_enhanced_after != 240
            or self._resupply_enhanced_heal_fraction_per_second != 0.25
        ):
            raise ConfigError(
                f"{document.path}: RMUC 补给区治疗必须为基础 10%/s，"
                "240 秒后脱战状态 25%/s"
            )

        respawn = _mapping(robot_lifecycle, "respawn", document)
        if set(respawn) != {
            "base_progress_required",
            "elapsed_seconds_per_progress",
            "immediate_respawn_progress_penalty",
            "progress_per_second",
            "accelerated_progress_per_second",
            "accelerated_base_hp_below",
            "hp_fraction",
            "invincibility_duration",
            "weak_release_min_invincibility",
            "immediate_hp_fraction",
            "immediate_invincibility_duration",
            "immediate_power_multiplier",
            "immediate_power_cap",
            "immediate_power_duration",
        }:
            raise ConfigError(
                f"{document.path}: `robot_lifecycle.respawn` "
                "字段不完整或包含未知字段"
            )
        self._respawn_base_progress_required = _positive_integer(
            respawn,
            "base_progress_required",
            document,
            "robot_lifecycle.respawn.base_progress_required",
        )
        self._respawn_elapsed_seconds_per_progress = _positive_integer(
            respawn,
            "elapsed_seconds_per_progress",
            document,
            "robot_lifecycle.respawn.elapsed_seconds_per_progress",
        )
        self._respawn_immediate_progress_penalty = _positive_integer(
            respawn,
            "immediate_respawn_progress_penalty",
            document,
            "robot_lifecycle.respawn.immediate_respawn_progress_penalty",
        )
        self._respawn_progress_per_second = _number(
            respawn,
            "progress_per_second",
            document,
            "robot_lifecycle.respawn.progress_per_second",
        )
        self._respawn_accelerated_progress_per_second = _number(
            respawn,
            "accelerated_progress_per_second",
            document,
            "robot_lifecycle.respawn.accelerated_progress_per_second",
        )
        self._respawn_accelerated_base_hp_below = _positive_integer(
            respawn,
            "accelerated_base_hp_below",
            document,
            "robot_lifecycle.respawn.accelerated_base_hp_below",
        )
        self._respawn_hp_fraction = _fraction(
            respawn,
            "hp_fraction",
            document,
            "robot_lifecycle.respawn.hp_fraction",
        )
        self._respawn_invincibility_duration = _number(
            respawn,
            "invincibility_duration",
            document,
            "robot_lifecycle.respawn.invincibility_duration",
        )
        self._weak_release_min_invincibility = _number(
            respawn,
            "weak_release_min_invincibility",
            document,
            "robot_lifecycle.respawn.weak_release_min_invincibility",
        )
        self._immediate_respawn_hp_fraction = _fraction(
            respawn,
            "immediate_hp_fraction",
            document,
            "robot_lifecycle.respawn.immediate_hp_fraction",
        )
        self._immediate_respawn_invincibility_duration = _number(
            respawn,
            "immediate_invincibility_duration",
            document,
            "robot_lifecycle.respawn.immediate_invincibility_duration",
        )
        self._immediate_respawn_power_multiplier = _number(
            respawn,
            "immediate_power_multiplier",
            document,
            "robot_lifecycle.respawn.immediate_power_multiplier",
        )
        self._immediate_respawn_power_cap = _positive_integer(
            respawn,
            "immediate_power_cap",
            document,
            "robot_lifecycle.respawn.immediate_power_cap",
        )
        self._immediate_respawn_power_duration = _number(
            respawn,
            "immediate_power_duration",
            document,
            "robot_lifecycle.respawn.immediate_power_duration",
        )
        if (
            self._respawn_base_progress_required != 10
            or self._respawn_elapsed_seconds_per_progress != 10
            or self._respawn_immediate_progress_penalty != 20
            or self._respawn_progress_per_second != 1
            or self._respawn_accelerated_progress_per_second != 4
            or self._respawn_accelerated_base_hp_below != 2000
            or self._respawn_hp_fraction != 0.10
            or self._respawn_invincibility_duration != 30
            or self._weak_release_min_invincibility != 10
            or self._immediate_respawn_hp_fraction != 1.0
            or self._immediate_respawn_invincibility_duration != 3
            or self._immediate_respawn_power_multiplier != 2.0
            or self._immediate_respawn_power_cap != 200
            or self._immediate_respawn_power_duration != 4
        ):
            raise ConfigError(
                f"{document.path}: RMUC 自动复活参数与 Regional V1.4.0 不匹配"
            )

        remote_healing = _mapping(document.data, "remote_healing", document)
        if set(remote_healing) != {
            "eligible_types",
            "effective_delay",
            "hp_fraction",
            "base_coins",
            "elapsed_seconds",
            "elapsed_coins_multiplier",
        }:
            raise ConfigError(
                f"{document.path}: `remote_healing` 字段不完整或包含未知字段"
            )
        eligible_types = remote_healing.get("eligible_types")
        if (
            not isinstance(eligible_types, list)
            or eligible_types != ["hero", "infantry", "sentry"]
        ):
            raise ConfigError(
                f"{document.path}: 远程回血仅适用于 hero、infantry、sentry"
            )
        self._remote_healing_eligible_types = frozenset(eligible_types)
        self._remote_healing_effective_delay = _number(
            remote_healing,
            "effective_delay",
            document,
            "remote_healing.effective_delay",
        )
        self._remote_healing_hp_fraction = _fraction(
            remote_healing,
            "hp_fraction",
            document,
            "remote_healing.hp_fraction",
        )
        self._remote_healing_base_coins = _positive_integer(
            remote_healing,
            "base_coins",
            document,
            "remote_healing.base_coins",
        )
        self._remote_healing_elapsed_seconds = _positive_integer(
            remote_healing,
            "elapsed_seconds",
            document,
            "remote_healing.elapsed_seconds",
        )
        self._remote_healing_elapsed_coins_multiplier = _positive_integer(
            remote_healing,
            "elapsed_coins_multiplier",
            document,
            "remote_healing.elapsed_coins_multiplier",
        )
        if (
            self._remote_healing_effective_delay != 6
            or self._remote_healing_hp_fraction != 0.60
            or self._remote_healing_base_coins != 50
            or self._remote_healing_elapsed_seconds != 60
            or self._remote_healing_elapsed_coins_multiplier != 20
        ):
            raise ConfigError(
                f"{document.path}: RMUC 远程回血参数与 Regional V1.4.0 不匹配"
            )

        projectile_allowance = _mapping(
            document.data, "projectile_allowance", document
        )
        if set(projectile_allowance) != {
            "remote_effective_delay",
            "zones",
            "initial",
            "purchase",
            "sentry_supply",
        }:
            raise ConfigError(
                f"{document.path}: `projectile_allowance` 字段不完整或包含未知字段"
            )
        self._projectile_remote_effective_delay = _number(
            projectile_allowance,
            "remote_effective_delay",
            document,
            "projectile_allowance.remote_effective_delay",
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

        for robot_type in ("hero", "infantry", "sentry", "drone"):
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
            }:                raise ConfigError(
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
        stationary = _nonnegative_integer(
            lab_power_demand,
            "stationary",
            document,
            "chassis_power.lab_power_demand.stationary",
        )
        moving_over_limit = _positive_integer(
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

        field_defense = _mapping(document.data, "field_defense_buffs", document)
        if set(field_defense) != {
            "occupy_release_delay",
            "defense",
            "zones",
        }:
            raise ConfigError(
                f"{document.path}: `field_defense_buffs` 字段不完整或包含未知字段"
            )
        occupy_release_delay = _number(
            field_defense,
            "occupy_release_delay",
            document,
            "field_defense_buffs.occupy_release_delay",
        )
        if occupy_release_delay != 2:
            raise ConfigError(
                f"{document.path}: Buff Point Occupy 失效延迟必须为 2 秒"
            )
        self._field_occupy_release_delay = float(occupy_release_delay)
        self._assembly_invincibility_limit = 180.0

        defense = _mapping(field_defense, "defense", document)
        if set(defense) != {"base", "central", "trapezoid", "outpost"}:
            raise ConfigError(
                f"{document.path}: `field_defense_buffs.defense` "
                "必须包含 base、central、trapezoid、outpost"
            )
        expected_field_defense = {
            "base": 0.50,
            "central": 0.25,
            "trapezoid": 0.50,
            "outpost": 0.25,
        }
        self._field_defense_by_type: dict[str, float] = {}
        for buff_type, expected in expected_field_defense.items():
            value = _number(
                defense,
                buff_type,
                document,
                f"field_defense_buffs.defense.{buff_type}",
            )
            if abs(float(value) - expected) > 1e-9:
                raise ConfigError(
                    f"{document.path}: {buff_type} Defense Buff 必须为 "
                    f"{int(expected * 100)}%"
                )
            self._field_defense_by_type[buff_type] = float(value)

        field_zones = _mapping(field_defense, "zones", document)
        if set(field_zones) != {"red", "blue"}:
            raise ConfigError(
                f"{document.path}: `field_defense_buffs.zones` 必须包含 red、blue"
            )
        self._field_zone_ids: dict[str, dict[str, str]] = {}
        all_field_zone_ids: set[str] = set()
        for side in ("red", "blue"):
            side_zones = _mapping(field_zones, side, document)
            if set(side_zones) != {"central", "trapezoid"}:
                raise ConfigError(
                    f"{document.path}: field Defense {side} zones "
                    "必须只包含 central、trapezoid"
                )
            parsed_zones = {
                kind: _string(
                    side_zones,
                    kind,
                    document,
                    f"field_defense_buffs.zones.{side}.{kind}",
                )
                for kind in ("central", "trapezoid")
            }
            if any(zone_id in all_field_zone_ids for zone_id in parsed_zones.values()):
                raise ConfigError(
                    f"{document.path}: field Defense Buff zone id 不得重复"
                )
            all_field_zone_ids.update(parsed_zones.values())
            self._field_zone_ids[side] = parsed_zones

        terrain_crossing = _mapping(document.data, "terrain_crossing", document)
        if set(terrain_crossing) != {
            "first_experience",
            "launch_ramp",
            "elevated_ground",
            "road",
            "tunnel",
            "zones",
        }:
            raise ConfigError(
                f"{document.path}: `terrain_crossing` 字段不完整或包含未知字段"
            )
        first_experience = _positive_integer(
            terrain_crossing,
            "first_experience",
            document,
            "terrain_crossing.first_experience",
        )
        if first_experience != 300:
            raise ConfigError(
                f"{document.path}: Terrain Crossing 首次 Experience 必须为 300"
            )
        self._terrain_first_experience = float(first_experience)

        expected_terrain_rules = {
            "launch_ramp": {
                "keys": {"sequence_window", "defense", "defense_duration"},
                "sequence_window": 10.0,
                "defense": 0.25,
                "defense_duration": 30.0,
            },
            "elevated_ground": {
                "keys": {"sequence_window", "defense", "defense_duration"},
                "sequence_window": 5.0,
                "defense": 0.25,
                "defense_duration": 30.0,
            },
            "road": {
                "keys": {
                    "sequence_window",
                    "defense",
                    "defense_duration",
                    "reacquire_cooldown",
                },
                "sequence_window": 3.0,
                "defense": 0.25,
                "defense_duration": 5.0,
                "reacquire_cooldown": 15.0,
            },
            "tunnel": {
                "keys": {
                    "sequence_window",
                    "defense",
                    "defense_duration",
                    "cooling_multiplier",
                    "cooling_duration",
                },
                "sequence_window": 3.0,
                "defense": 0.50,
                "defense_duration": 10.0,
                "cooling_multiplier": 2.0,
                "cooling_duration": 120.0,
            },
        }
        self._terrain_rules: dict[str, _TerrainCrossingRule] = {}
        for terrain_type, expected in expected_terrain_rules.items():
            item = _mapping(terrain_crossing, terrain_type, document)
            if set(item) != expected["keys"]:
                raise ConfigError(
                    f"{document.path}: `terrain_crossing.{terrain_type}` "
                    "字段不完整或包含未知字段"
                )