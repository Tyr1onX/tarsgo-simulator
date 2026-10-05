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
_SMALL_ENERGY_PHASE_END = 180.0
_SMALL_ENERGY_OPPORTUNITY_INTERVAL = 90.0
_SMALL_ENERGY_ACTIVATION_WINDOW = 20.0
_SMALL_ENERGY_BUFF_DURATION = 45.0
_SMALL_ENERGY_EXPERIENCE_BONUS_CAP = 1200.0
_DART_OPPORTUNITY_TIMES = (30.0, 240.0)
_DART_GATE_OPENING_SECONDS = 7.0
_DART_FIRING_WINDOW_SECONDS = 30.0
_DART_DETECTION_WINDOW_SECONDS = 40.0
_DART_FIRST_CLOSE_COOLDOWN_SECONDS = 15.0
_DART_DETECTION_REOPEN_SECONDS = 2.0
_DART_MAX_PER_MATCH = 4
_DART_TARGET_MODES = {
    "fixed",
    "random-fixed",
    "random-moving",
    "terminal-moving",
}
# V1.4.0 Radar marking can track Drone, but the vulnerability effect itself
# is explicitly limited to ground robots.
_RADAR_VULNERABILITY_ROBOT_TYPES = set(_GROUND_ROBOT_TYPES)


@dataclass
class _RobotProgressionState:
    experience: float = 0.0
    level: int = 1


@dataclass
class _DroneAirSupportState:
    available_seconds: float
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
    mechanism: str | None = None


@dataclass(frozen=True)
class _DartProjectile:
    target_structure_id: str
    target_mode: str
    expires_at: float


@dataclass
class _DartSystemState:
    openings_used: int = 0
    darts_fired: int = 0
    gate_full_open_at: float | None = None
    firing_window_ends_at: float | None = None
    detector_window_ends_at: float | None = None
    cooldown_until: float = 0.0
    target_structure_id: str | None = None
    target_mode: str | None = None
    fixed_target_hits: int = 0
    fixed_base_hits: int = 0
    ai_last_fired_opening: int = 0
    pending_projectiles: list[_DartProjectile] = field(default_factory=list)
    last_result: str = ""
    last_result_remaining: float = 0.0


@dataclass
class _DartEffectsState:
    screen_obscured_remaining: float = 0.0
    terrain_energy_suppressed_remaining: float = 0.0


@dataclass
class _TimedEnergyMechanismBuff:
    mechanism: str
    defense: float
    cooling_multiplier: float
    remaining: float
    experience_bonus_remaining: float = 0.0


@dataclass(frozen=True)
class _RadarVulnerabilityState:
    source_team_id: str
    base_vulnerability: float


@dataclass
class _RadarDoubleVulnerabilityState:
    remaining: float = 0.0
    activations: int = 0


@dataclass
class _RadarAntiDroneState:
    progress: float = 0.0
    continuous_elapsed: float = 0.0
    consecutive_ticks: int = 0
    illuminated_by_team_id: str | None = None
    lock_remaining: float = 0.0
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
            "paid_cost_per_second",
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
        self._drone_paid_cost_per_second = _positive_integer(
            drone,
            "paid_cost_per_second",
            document,
            "drone_foundation.paid_cost_per_second",
        )
        if (
            self._drone_projectile_muzzle_velocity_limit_mps != 25
            or self._drone_initial_free_air_support != 30
            or self._drone_periodic_grant_interval != 60
            or self._drone_periodic_grant != 20
            or self._drone_paid_cost_per_second != 1
            or drone.get("damage_applicable") is not False
            or drone.get("recovery_and_respawn") is not False
            or drone.get("chassis_power_overlimit") is not False
            or drone.get("capturable_buff_points") is not False
        ):
            raise ConfigError(
                f"{document.path}: drone_foundation 必须匹配 RMUC 2026 Regional V1.4.0"
            )

        radar_anti_drone = _mapping(
            document.data, "radar_anti_drone", document
        )
        if set(radar_anti_drone) != {
            "progress_max",
            "thresholds",
            "detection_period_seconds",
            "decay_per_second",
            "lock_duration_seconds",
            "max_locks_per_match",
        }:
            raise ConfigError(
                f"{document.path}: radar_anti_drone 字段不完整或包含未知字段"
            )
        thresholds = radar_anti_drone.get("thresholds")
        if (
            radar_anti_drone.get("progress_max") != 100
            or thresholds != [50, 100, 100]
            or radar_anti_drone.get("detection_period_seconds") != 0.1
            or radar_anti_drone.get("decay_per_second") != 0.5
            or radar_anti_drone.get("lock_duration_seconds") != 45
            or radar_anti_drone.get("max_locks_per_match") != 3
        ):
            raise ConfigError(
                f"{document.path}: radar_anti_drone 必须匹配 RMUC 2026 Regional V1.4.0"
            )
        self._radar_anti_drone_progress_max = 100.0
        self._radar_anti_drone_thresholds = (50.0, 100.0, 100.0)
        self._radar_anti_drone_detection_period = 0.1
        self._radar_anti_drone_decay_per_second = 0.5
        self._radar_anti_drone_lock_duration = 45.0
        self._radar_anti_drone_max_locks = 3

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
            parsed = {
                key: float(
                    _number(
                        item,
                        key,
                        document,
                        f"terrain_crossing.{terrain_type}.{key}",
                    )
                )
                for key in expected["keys"]
            }
            for key, expected_value in expected.items():
                if key == "keys":
                    continue
                if abs(parsed[key] - expected_value) > 1e-9:
                    raise ConfigError(
                        f"{document.path}: terrain_crossing.{terrain_type}.{key} "
                        "与 RMUC 2026 Regional V1.4.0 不匹配"
                    )
            self._terrain_rules[terrain_type] = _TerrainCrossingRule(
                sequence_window=parsed["sequence_window"],
                defense=parsed["defense"],
                defense_duration=parsed["defense_duration"],
                reacquire_cooldown=parsed.get("reacquire_cooldown", 0.0),
                cooling_multiplier=parsed.get("cooling_multiplier", 1.0),
                cooling_duration=parsed.get("cooling_duration", 0.0),
            )

        terrain_zones = _mapping(terrain_crossing, "zones", document)
        if set(terrain_zones) != {"red", "blue"}:
            raise ConfigError(
                f"{document.path}: `terrain_crossing.zones` 必须包含 red、blue"
            )
        self._terrain_zone_ids: dict[
            str, dict[str, tuple[str, ...]]
        ] = {}
        all_terrain_zone_ids: set[str] = set()
        expected_lengths = {
            "road": 2,
            "elevated_ground": 2,
            "launch_ramp": 2,
            "tunnel": 3,
        }
        for side in ("red", "blue"):
            side_zones = _mapping(terrain_zones, side, document)
            if set(side_zones) != set(expected_lengths):
                raise ConfigError(
                    f"{document.path}: terrain_crossing.zones.{side} "
                    "必须包含 road、elevated_ground、launch_ramp、tunnel"
                )
            parsed_side: dict[str, tuple[str, ...]] = {}
            for terrain_type, expected_length in expected_lengths.items():
                raw_zone_ids = side_zones.get(terrain_type)
                if (
                    not isinstance(raw_zone_ids, list)
                    or len(raw_zone_ids) != expected_length
                    or not all(
                        isinstance(zone_id, str) and zone_id
                        for zone_id in raw_zone_ids
                    )
                ):
                    raise ConfigError(
                        f"{document.path}: terrain_crossing.zones.{side}."
                        f"{terrain_type} 必须是 {expected_length} 个非空 zone id"
                    )
                zone_ids = tuple(raw_zone_ids)
                if (
                    len(set(zone_ids)) != len(zone_ids)
                    or any(zone_id in all_terrain_zone_ids for zone_id in zone_ids)
                ):
                    raise ConfigError(
                        f"{document.path}: Terrain Crossing RFID zone id 不得重复"
                    )
                all_terrain_zone_ids.update(zone_ids)
                parsed_side[terrain_type] = zone_ids
            self._terrain_zone_ids[side] = parsed_side

        enemy_fortress = _mapping(
            document.data,
            "fortress_enemy_occupation",
            document,
        )
        if set(enemy_fortress) != {
            "available_after",
            "vulnerability",
            "armor_after",
            "retention",
            "eligible_types",
        }:
            raise ConfigError(
                f"{document.path}: `fortress_enemy_occupation` "
                "字段不完整或包含未知字段"
            )
        enemy_available_after = float(
            _number(
                enemy_fortress,
                "available_after",
                document,
                "fortress_enemy_occupation.available_after",
            )
        )
        enemy_vulnerability = float(
            _number(
                enemy_fortress,
                "vulnerability",
                document,
                "fortress_enemy_occupation.vulnerability",
            )
        )
        enemy_armor_after = float(
            _number(
                enemy_fortress,
                "armor_after",
                document,
                "fortress_enemy_occupation.armor_after",
            )
        )
        enemy_retention = float(
            _number(
                enemy_fortress,
                "retention",
                document,
                "fortress_enemy_occupation.retention",
            )
        )
        enemy_eligible_types = enemy_fortress.get("eligible_types")
        if (
            abs(enemy_available_after - 180.0) > 1e-9
            or abs(enemy_vulnerability - 1.0) > 1e-9
            or abs(enemy_armor_after - 20.0) > 1e-9
            or abs(enemy_retention - 3.0) > 1e-9
            or enemy_eligible_types != ["infantry", "sentry"]
        ):
            raise ConfigError(
                f"{document.path}: enemy Fortress 必须为 "
                "180s 开放、100% Vulnerability、20s Armor、3s retention、"
                "Infantry/Sentry"
            )
        self._enemy_fortress_available_after = enemy_available_after
        self._enemy_fortress_vulnerability = enemy_vulnerability
        self._enemy_fortress_armor_after = enemy_armor_after
        self._enemy_fortress_retention = enemy_retention
        self._enemy_fortress_eligible_types = frozenset(
            enemy_eligible_types
        )

        fortress = _mapping(document.data, "fortress_own_buff", document)
        if set(fortress) != {
            "defense",
            "cooling_hp_step",
            "cooling_cap",
            "eligible_types",
            "reserved_projectiles",
            "zones",
        }:
            raise ConfigError(
                f"{document.path}: `fortress_own_buff` "
                "字段不完整或包含未知字段"
            )
        fortress_defense = float(
            _number(
                fortress,
                "defense",
                document,
                "fortress_own_buff.defense",
            )
        )
        fortress_cooling_hp_step = _positive_integer(
            fortress,
            "cooling_hp_step",
            document,
            "fortress_own_buff.cooling_hp_step",
        )
        fortress_cooling_cap = _positive_integer(
            fortress,
            "cooling_cap",
            document,
            "fortress_own_buff.cooling_cap",
        )
        eligible_types = fortress.get("eligible_types")
        if (
            fortress_defense != 0.50
            or fortress_cooling_hp_step != 40
            or fortress_cooling_cap != 75
            or eligible_types != ["infantry", "sentry"]
        ):
            raise ConfigError(
                f"{document.path}: own Fortress 必须为 "
                "Defense 50%、Δ/40、cap 75、Infantry/Sentry"
            )
        self._fortress_defense = fortress_defense
        self._fortress_cooling_hp_step = fortress_cooling_hp_step
        self._fortress_cooling_cap = fortress_cooling_cap
        self._fortress_eligible_types = frozenset(eligible_types)

        reserved_projectiles = _mapping(
            fortress,
            "reserved_projectiles",
            document,
        )
        if set(reserved_projectiles) != {
            "projectile",
            "base",
            "hp_step",
            "per_step",
            "cap",
        }:
            raise ConfigError(
                f"{document.path}: `fortress_own_buff.reserved_projectiles` "
                "字段不完整或包含未知字段"
            )
        reserve_projectile = _string(
            reserved_projectiles,
            "projectile",
            document,
            "fortress_own_buff.reserved_projectiles.projectile",
        )
        reserve_base = _positive_integer(
            reserved_projectiles,
            "base",
            document,
            "fortress_own_buff.reserved_projectiles.base",
        )
        reserve_hp_step = _positive_integer(
            reserved_projectiles,
            "hp_step",
            document,
            "fortress_own_buff.reserved_projectiles.hp_step",
        )
        reserve_per_step = _positive_integer(
            reserved_projectiles,
            "per_step",
            document,
            "fortress_own_buff.reserved_projectiles.per_step",
        )
        reserve_cap = _positive_integer(
            reserved_projectiles,
            "cap",
            document,
            "fortress_own_buff.reserved_projectiles.cap",
        )
        if (
            reserve_projectile != "17mm"
            or reserve_base != 100
            or reserve_hp_step != 15
            or reserve_per_step != 2
            or reserve_cap != 500
        ):
            raise ConfigError(
                f"{document.path}: Fortress reserve 必须为 "
                "17mm、100+2*floor(Δ/15)、cap 500"
            )
        self._fortress_reserve_projectile = reserve_projectile
        self._fortress_reserve_base = reserve_base
        self._fortress_reserve_hp_step = reserve_hp_step
        self._fortress_reserve_per_step = reserve_per_step
        self._fortress_reserve_cap = reserve_cap

        fortress_zones = _mapping(fortress, "zones", document)
        if set(fortress_zones) != {"red", "blue"}:
            raise ConfigError(
                f"{document.path}: `fortress_own_buff.zones` "
                "必须包含 red、blue"
            )
        self._fortress_zone_ids = {
            side: _string(
                fortress_zones,
                side,
                document,
                f"fortress_own_buff.zones.{side}",
            )
            for side in ("red", "blue")
        }
        if len(set(self._fortress_zone_ids.values())) != 2:
            raise ConfigError(
                f"{document.path}: Fortress zone id 不得重复"
            )

        self.attack_damage_by_team: dict[str, int] = {}
        self._attack_buffs_by_team: dict[str, list[_TimedAttackBuff]] = {}
        self._energy_mechanism_buffs_by_team: dict[
            str, list[_TimedEnergyMechanismBuff]
        ] = {}
        self._dart_system_by_team: dict[str, _DartSystemState] = {}
        self._dart_effects_by_team: dict[str, _DartEffectsState] = {}
        self._dart_detector_closed_until: dict[str, float] = {}
        self._field_buff_disabled_until_by_zone: dict[str, float] = {}
        self._current_time = 0.0
        self._small_energy_mechanism_activation_times_by_team: dict[
            str, list[float]
        ] = {}
        self._radar_vulnerability_by_robot: dict[str, _RadarVulnerabilityState] = {}
        self._radar_double_vulnerability_by_team: dict[
            str, _RadarDoubleVulnerabilityState
        ] = {}
        self._radar_anti_drone_by_robot: dict[str, _RadarAntiDroneState] = {}
        self._team_states: dict[str, _TeamStructureState] = {}
        self._base_by_team: dict[str, Structure] = {}
        self._outpost_by_team: dict[str, Structure] = {}
        self._rebuild_zone_by_team: dict[str, Zone] = {}
        self._robot_types_by_id: dict[str, str] = {}
        self._robots_by_id: dict[str, Robot] = {}
        self._drone_helipad_by_robot: dict[str, tuple[float, float]] = {}
        self._drone_air_support_by_robot: dict[str, _DroneAirSupportState] = {}
        self._progression_by_robot: dict[str, _RobotProgressionState] = {}
        self._level_cap_by_team: dict[str, int] = {}
        self._engineer_resources_by_id: dict[str, _EngineerResourceState] = {}
        self._tech_core_by_team: dict[str, _TechCoreTeamState] = {}
        self._d4_coordinator = _D4CoordinatorState()
        self._economy_by_team: dict[str, _TeamEconomyState] = {}
        self._next_timed_gold_grant_index = 0
        self._next_periodic_gold_tick = self._economy_periodic_interval
        self._robot_lifecycle_by_robot: dict[str, _RobotLifecycleState] = {}
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
        self._assembly_invincibility_elapsed_by_engineer: dict[str, float] = {}
        self._field_buff_elapsed = 0.0
        self._field_base_zone_by_team: dict[str, Zone] = {}
        self._field_outpost_zone_by_team: dict[str, Zone] = {}
        self._field_trapezoid_zone_by_team: dict[str, Zone] = {}
        self._field_central_zones: tuple[Zone, ...] = ()
        self._central_defense_state_by_zone: dict[
            str, _CentralDefenseBuffState
        ] = {}
        self._field_occupy_remaining: dict[tuple[str, str], float] = {}
        self._fortress_zone_by_team: dict[str, Zone] = {}
        self._fortress_state_by_team: dict[str, _FortressBuffState] = {}
        self._fortress_reserved_by_robot: dict[
            str, _FortressReservedProjectileState
        ] = {}
        self._enemy_fortress_occupation: dict[
            tuple[str, str], _EnemyFortressOccupationState
        ] = {}
        self._enemy_fortress_death_retention_started: set[
            tuple[str, str]
        ] = set()
        self._outposts_destroyed_this_frame: set[str] = set()
        self._terrain_crossing_by_robot: dict[
            str, _TerrainCrossingState
        ] = {}
        self._terrain_zones_by_side_and_type: dict[
            str, dict[str, tuple[Zone, ...]]
        ] = {}
        self._terrain_zone_lookup: dict[str, tuple[str, str, int]] = {}
        self._terrain_interrupt_zones_by_id: dict[str, Zone] = {}

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
            defense_label = (
                f"DEF {int(state.tech_core_defense * 100)}%"
                if state.tech_core_defense > 0
                else ""
            )

            base_status_parts = []
            if state.base_armor_deployed:
                base_status_parts.append("ARMOR")
            if defense_label:
                base_status_parts.append(defense_label)
            if state.base_virtual_shield > 0:
                base_status_parts.append(f"SH:{state.base_virtual_shield}")
            structure_statuses.append(
                (
                    base.id,
                    base.hp,
                    base.max_hp,
                    " ".join(base_status_parts),
                )
            )

            outpost_status_parts = []
            if not outpost.alive:
                outpost_status_parts.append("DESTROYED")
            elif state.outpost_ever_destroyed:
                outpost_status_parts.append("REBUILT")
            if defense_label:
                outpost_status_parts.append(defense_label)
            structure_statuses.append(
                (
                    outpost.id,
                    outpost.hp,
                    outpost.max_hp,
                    " ".join(outpost_status_parts),
                )
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
            robot_statuses=tuple(
                (robot.id, status)
                for robot in sorted(
                    self._robots_by_id.values(),
                    key=lambda item: item.id,
                )
                if (status := self._robot_status_label(robot))
            ),
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
            robot_projectile_reserves=tuple(
                (robot_id, state.reserved)
                for robot_id, state in sorted(
                    self._fortress_reserved_by_robot.items()
                )
                if state.initialized
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
            robot_chassis_power=tuple(
                (
                    robot_id,
                    state.buffer_energy,
                    self._effective_buffer_energy_max(robot_id),
                    self._current_synthetic_power_by_robot.get(robot_id, 0.0),
                    self._effective_chassis_power_limit(robot_id),
                    state.power_off_remaining,
                )
                for robot_id, state in sorted(
                    self._chassis_power_by_robot.items()
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
                    if self._robots_by_id[robot_id].type
                    in _HP_PERFORMANCE_ROBOT_TYPES
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
            drone_air_support=tuple(
                (
                    robot_id,
                    state.active,
                    state.available_seconds,
                )
                for robot_id, state in sorted(
                    self._drone_air_support_by_robot.items()
                )
            ),
            radar_anti_drone=tuple(
                (
                    robot_id,
                    next(
                        team_id
                        for team_id in sorted(self._economy_by_team)
                        if team_id != self._robots_by_id[robot_id].team
                    ),
                    state.progress,
                    self._radar_anti_drone_threshold(state),
                    state.lock_remaining,
                    state.activations,
                    self._radar_anti_drone_max_locks - state.activations,
                    state.illuminated_by_team_id is not None,
                )
                for robot_id, state in sorted(
                    self._radar_anti_drone_by_robot.items()
                )
            ),
            energy_mechanism_effect_timers=tuple(
                (team_id, buff.mechanism, buff.remaining)
                for team_id, buffs in sorted(
                    self._energy_mechanism_buffs_by_team.items()
                )
                for buff in buffs
                if buff.remaining > 0
            ),
            dart_system_statuses=tuple(
                self._dart_display_status(team_id, state)
                for team_id, state in sorted(self._dart_system_by_team.items())
            ),
            dart_effect_statuses=tuple(
                (
                    team_id,
                    effects.screen_obscured_remaining,
                    effects.terrain_energy_suppressed_remaining,
                )
                for team_id, effects in sorted(self._dart_effects_by_team.items())
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

    def drone_air_support_active(self, robot_id: str) -> bool:
        state = self._drone_air_support_by_robot.get(robot_id)
        return state is not None and state.active

    def drone_air_support_available(self, robot_id: str) -> float:
        state = self._drone_air_support_by_robot.get(robot_id)
        return state.available_seconds if state is not None else 0.0

    def _radar_anti_drone_threshold(
        self, state: _RadarAntiDroneState
    ) -> float:
        index = min(state.activations, self._radar_anti_drone_max_locks - 1)
        return self._radar_anti_drone_thresholds[index]

    def radar_anti_drone_locked(self, robot_id: str) -> bool:
        state = self._radar_anti_drone_by_robot.get(robot_id)
        return state is not None and state.lock_remaining > 1e-9

    def set_radar_anti_drone_laser(
        self,
        source_team_id: str,
        target: Robot,
        illuminated: bool,
    ) -> bool:
        state = self._radar_anti_drone_by_robot.get(target.id)
        if (
            target.type != "drone"
            or self._robots_by_id.get(target.id) is not target
            or state is None
            or source_team_id not in self._economy_by_team
            or source_team_id == target.team
        ):
            return False

        if not illuminated:
            if (
                state.illuminated_by_team_id is not None
                and state.illuminated_by_team_id != source_team_id
            ):
                return False
            state.illuminated_by_team_id = None
            state.continuous_elapsed = 0.0
            state.consecutive_ticks = 0
            return True

        if (
            state.activations >= self._radar_anti_drone_max_locks
            or not self.drone_air_support_active(target.id)
        ):
            state.illuminated_by_team_id = None
            state.continuous_elapsed = 0.0
            state.consecutive_ticks = 0
            return False

        state.illuminated_by_team_id = source_team_id
        return True

    def _purchase_drone_air_support_second(
        self,
        drone: Robot,
        state: _DroneAirSupportState,
    ) -> bool:
        economy = self._economy_by_team.get(drone.team)
        if economy is None or economy.coins < self._drone_paid_cost_per_second:
            return False
        economy.coins -= self._drone_paid_cost_per_second
        state.available_seconds += 1.0
        return True

    def start_drone_air_support(self, match: "Match", drone: Robot) -> bool:
        state = self._drone_air_support_by_robot.get(drone.id)
        if (
            match.finished
            or drone.type != "drone"
            or self._robots_by_id.get(drone.id) is not drone
            or state is None
            or state.active
        ):
            return False
        if (
            state.available_seconds <= 1e-9
            and not self._purchase_drone_air_support_second(drone, state)
        ):
            return False
        state.active = True
        drone.alive = True
        drone.hp = drone.max_hp
        return True

    def pause_drone_air_support(self, drone: Robot) -> bool:
        state = self._drone_air_support_by_robot.get(drone.id)
        if state is None or not state.active:
            return False
        state.active = False
        drone.alive = False
        drone.path.clear()
        helipad = self._drone_helipad_by_robot.get(drone.id)
        if helipad is not None:
            drone.position = helipad
        return True

    def _drone_on_helipad(self, drone: Robot) -> bool:
        helipad = self._drone_helipad_by_robot.get(drone.id)
        return (
            helipad is not None
            and math.dist(drone.position, helipad) <= 1e-6
        )

    def can_move(self, robot: Robot) -> bool:
        if robot.type == "drone":
            return robot.alive and self.drone_air_support_active(robot.id)
        state = self._chassis_power_by_robot.get(robot.id)
        return (
            robot.alive
            and state is not None
            and not state.blocked_this_frame
            and state.power_off_remaining <= 0
        )

    def _is_weak(self, robot: Robot) -> bool:
        state = self._robot_lifecycle_by_robot.get(robot.id)
        return state is not None and state.weak

    def can_attack(self, robot: Robot) -> bool:
        lifecycle = self._robot_lifecycle_by_robot.get(robot.id)
        allowance = self._projectile_allowance_by_robot.get(robot.id)
        shooting_heat = self._shooting_heat_by_robot.get(robot.id)
        usable_fortress_reserved = (
            0 if robot.type == "drone" else self._usable_fortress_reserved(robot)
        )
        lifecycle_ready = (
            self.drone_air_support_active(robot.id)
            and not self._drone_on_helipad(robot)
            if robot.type == "drone"
            else lifecycle is not None and not lifecycle.weak
        )
        return (
            robot.alive
            and lifecycle_ready
            and robot.damage > 0
            and allowance is not None
            and (allowance.allowed > 0 or usable_fortress_reserved > 0)
            and shooting_heat is not None
            and not shooting_heat.temporarily_locked
            and not shooting_heat.permanently_locked
            and (
                robot.type != "drone"
                or not self.radar_anti_drone_locked(robot.id)
            )
        )

    def can_target(self, target: DamageableTarget) -> bool:
        if isinstance(target, Structure):
            # Unlike RMUL robot invincibility, an invincible RMUC Base must not
            # consume target selection while its Outpost is alive.
            return self.can_receive_damage(target)
        if isinstance(target, Robot) and target.type == "drone":
            return False
        return target.alive

    def open_dart_gate(
        self,
        match: "Match",
        team_id: str,
        target_mode: str | None = None,
    ) -> bool:
        """Start one official seven-second gate opening opportunity.

        Dart flight and physical aiming stay upstream. This API records the
        selected official target and timing; detected hits enter through
        :meth:`record_dart_hit`.
        """
        state = self._dart_system_by_team.get(team_id)
        now = match.elapsed_time
        if (
            match.finished
            or state is None
            or now >= self._time_limit
            or state.openings_used >= len(_DART_OPPORTUNITY_TIMES)
            or now < state.cooldown_until - 1e-9
            or (
                state.firing_window_ends_at is not None
                and now < state.firing_window_ends_at - 1e-9
            )
        ):
            return False

        opportunities = sum(
            now + 1e-9 >= available_at
            for available_at in _DART_OPPORTUNITY_TIMES
        )
        if state.openings_used >= opportunities:
            return False

        enemy_team_id = next(
            (other for other in self._dart_system_by_team if other != team_id),
            None,
        )
        if enemy_team_id is None:
            return False
        enemy_outpost = self._outpost_by_team[enemy_team_id]
        if enemy_outpost.alive:
            if target_mode not in {None, "fixed"}:
                return False
            selected_mode = "fixed"
            target = enemy_outpost
        else:
            if target_mode not in _DART_TARGET_MODES:
                return False
            selected_mode = target_mode
            target = self._base_by_team[enemy_team_id]

        state.openings_used += 1
        state.gate_full_open_at = now + _DART_GATE_OPENING_SECONDS
        state.firing_window_ends_at = (
            state.gate_full_open_at + _DART_FIRING_WINDOW_SECONDS
        )
        state.detector_window_ends_at = (
            state.gate_full_open_at + _DART_DETECTION_WINDOW_SECONDS
        )
        state.cooldown_until = (
            state.firing_window_ends_at + _DART_FIRST_CLOSE_COOLDOWN_SECONDS
            if state.openings_used == 1
            else state.firing_window_ends_at
        )
        state.target_structure_id = target.id
        state.target_mode = selected_mode
        state.last_result = "闸门开启中"
        state.last_result_remaining = _DART_GATE_OPENING_SECONDS
        return True

    def fire_dart(self, match: "Match", team_id: str) -> bool:
        """Consume one of the four loaded darts inside the open firing window."""
        state = self._dart_system_by_team.get(team_id)
        now = match.elapsed_time
        if (
            match.finished
            or state is None
            or state.gate_full_open_at is None
            or state.firing_window_ends_at is None
            or state.detector_window_ends_at is None
            or now + 1e-9 < state.gate_full_open_at
            or now >= state.firing_window_ends_at - 1e-9
            or now >= state.detector_window_ends_at - 1e-9
            or state.darts_fired >= _DART_MAX_PER_MATCH
            or state.target_structure_id is None
            or state.target_mode is None
        ):
            return False

        target = next(
            (
                structure
                for structure in self._base_by_team.values()
                if structure.id == state.target_structure_id
            ),
            None,
        ) or next(
            (
                structure
                for structure in self._outpost_by_team.values()
                if structure.id == state.target_structure_id
            ),
            None,
        )
        if target is None or not target.alive:
            return False
        if target.type == "base" and self._outpost_by_team[target.team].alive:
            return False

        state.darts_fired += 1
        state.pending_projectiles.append(
            _DartProjectile(
                target_structure_id=target.id,
                target_mode=state.target_mode,
                expires_at=state.detector_window_ends_at,
            )
        )
        state.last_result = "飞镖已发射"
        state.last_result_remaining = 3.0
        return True

    def record_dart_miss(self, match: "Match", team_id: str) -> bool:
        """Resolve the oldest launched dart as a miss without applying effects."""
        state = self._dart_system_by_team.get(team_id)
        if state is None:
            return False
        now = match.elapsed_time
        state.pending_projectiles = [
            projectile
            for projectile in state.pending_projectiles
            if projectile.expires_at > now + 1e-9
        ]
        if not state.pending_projectiles:
            return False
        state.pending_projectiles.pop(0)
        state.last_result = "飞镖未命中"
        state.last_result_remaining = 3.0
        return True

    def record_dart_hit(
        self,
        match: "Match",
        team_id: str,
        target_structure_id: str | None = None,
    ) -> bool:
        """Apply V1.4.0 effects after the referee reports a detector hit."""
        state = self._dart_system_by_team.get(team_id)
        if match.finished or state is None:
            return False
        now = match.elapsed_time
        state.pending_projectiles = [
            projectile
            for projectile in state.pending_projectiles
            if projectile.expires_at > now + 1e-9
        ]
        if not state.pending_projectiles:
            return False
        projectile = state.pending_projectiles[0]
        if (
            target_structure_id is not None
            and target_structure_id != projectile.target_structure_id
        ):
            return False
        target = next(
            (
                structure
                for structure in (*self._base_by_team.values(), *self._outpost_by_team.values())
                if structure.id == projectile.target_structure_id
            ),
            None,
        )
        if (
            target is None
            or not target.alive
            or target.team == team_id
            or now < self._dart_detector_closed_until.get(target.id, 0.0) - 1e-9
            or (target.type == "base" and self._outpost_by_team[target.team].alive)
        ):
            return False

        damage = (
            750
            if target.type == "outpost"
            else {
                "fixed": 200,
                "random-fixed": 300,
                "random-moving": 625,
                "terminal-moving": 1000,
            }[projectile.target_mode]
        )
        state.pending_projectiles.pop(0)
        match.apply_damage(
            target,
            damage,
            source_team_id=team_id,
            bypass_attack_defense=True,
            award_experience=False,
        )

        self._dart_detector_closed_until[target.id] = (
            now + _DART_DETECTION_REOPEN_SECONDS
        )
        self._apply_dart_hit_effects(match, team_id, target, projectile.target_mode)
        state.last_result = f"命中{'基地' if target.type == 'base' else '前哨站'}"
        state.last_result_remaining = 3.0
        return True

    def update_dart_ai(self, match: "Match") -> None:
        """Use one shared deterministic policy for both RMUC spectator teams."""
        for team_id, state in sorted(self._dart_system_by_team.items()):
            now = match.elapsed_time
            if state.openings_used < len(_DART_OPPORTUNITY_TIMES):
                next_opportunity = _DART_OPPORTUNITY_TIMES[state.openings_used]
                if now + 1e-9 >= next_opportunity and now >= state.cooldown_until - 1e-9:
                    enemy_team_id = next(
                        other for other in self._dart_system_by_team if other != team_id
                    )
                    mode = (
                        None
                        if self._outpost_by_team[enemy_team_id].alive
                        else "random-moving"
                    )
                    self.open_dart_gate(match, team_id, mode)

            if (
                state.openings_used > 0
                and state.ai_last_fired_opening != state.openings_used
                and state.gate_full_open_at is not None
                and now + 1e-9 >= state.gate_full_open_at
            ):
                if state.darts_fired >= _DART_MAX_PER_MATCH:
                    state.ai_last_fired_opening = state.openings_used
                elif self.fire_dart(match, team_id):
                    state.ai_last_fired_opening = state.openings_used

    def _apply_dart_hit_effects(
        self,
        match: "Match",
        source_team_id: str,
        target: Structure,
        target_mode: str,
    ) -> None:
        state = self._dart_system_by_team[source_team_id]
        effects = self._dart_effects_by_team[target.team]
        moving = target_mode in {"random-moving", "terminal-moving"}
        if moving:
            effects.screen_obscured_remaining += 10.0
        else:
            state.fixed_target_hits += 1
            screen_seconds = {1: 10.0, 2: 5.0, 3: 3.0, 4: 2.0}.get(
                state.fixed_target_hits,
                0.0,
            )
            effects.screen_obscured_remaining = screen_seconds

        if target.type == "base":
            eligible = [
                robot
                for robot in match.robots
                if robot.team == source_team_id
                and robot.alive
                and robot.type in _EXPERIENCE_ROBOT_TYPES
            ]
            experience_pool = (
                2500.0
                if moving
                else 600.0
                if target_mode == "random-fixed"
                else 200.0
            )
            if eligible:
                each = experience_pool / len(eligible)
                for robot in eligible:
                    self._grant_experience(robot.id, each)

            if target_mode == "random-fixed":
                effects.terrain_energy_suppressed_remaining = max(
                    effects.terrain_energy_suppressed_remaining,
                    screen_seconds,
                )
            elif moving:
                percent = 0.25 if target_mode == "terminal-moving" else 0.10
                for robot in tuple(match.robots):
                    if robot.team != target.team or not robot.alive or robot.type not in _GROUND_ROBOT_TYPES:
                        continue
                    robot_damage = int(math.floor(robot.max_hp * percent + 0.5))
                    match.apply_damage(
                        robot,
                        robot_damage,
                        source_team_id=source_team_id,
                        bypass_invincibility=True,
                        bypass_attack_defense=True,
                        award_experience=False,
                    )

            if moving or state.fixed_base_hits >= _DART_MAX_PER_MATCH:
                self._team_states[target.team].base_armor_deployed = True
            if target_mode in {"fixed", "random-fixed"}:
                state.fixed_base_hits += 1
                if state.fixed_base_hits >= _DART_MAX_PER_MATCH:
                    self._team_states[target.team].base_armor_deployed = True

        field_zone = (
            self._field_base_zone_by_team.get(target.team)
            if target.type == "base"
            else self._field_outpost_zone_by_team.get(target.team)
        )
        if field_zone is not None:
            self._field_buff_disabled_until_by_zone[field_zone.id] = max(
                self._field_buff_disabled_until_by_zone.get(field_zone.id, 0.0),
                match.elapsed_time + 30.0,
            )

    def _dart_display_status(
        self,
        team_id: str,
        state: _DartSystemState,
    ) -> tuple[str, int, int, str, float, str, str]:
        now = self._current_time
        opportunities = sum(
            now + 1e-9 >= available_at
            for available_at in _DART_OPPORTUNITY_TIMES
        )
        if state.gate_full_open_at is not None and now < state.gate_full_open_at - 1e-9:
            phase = "opening"
            remaining = state.gate_full_open_at - now
        elif (
            state.firing_window_ends_at is not None
            and now < state.firing_window_ends_at - 1e-9
        ):
            phase = "firing"
            remaining = state.firing_window_ends_at - now
        elif now < state.cooldown_until - 1e-9 and state.openings_used > 0:
            phase = "cooldown"
            remaining = state.cooldown_until - now
        elif state.darts_fired >= _DART_MAX_PER_MATCH or state.openings_used >= opportunities >= len(_DART_OPPORTUNITY_TIMES):
            phase = "spent"
            remaining = 0.0
        elif state.openings_used >= opportunities:
            phase = "locked"
            next_time = next(
                (
                    item
                    for item in _DART_OPPORTUNITY_TIMES
                    if item > now + 1e-9
                ),
                self._time_limit,
            )
            remaining = max(0.0, next_time - now)
        else:
            phase = "ready"
            remaining = 0.0

        target = "基地" if state.target_structure_id in {
            structure.id for structure in self._base_by_team.values()
        } else "前哨站" if state.target_structure_id else ""
        result = (
            state.last_result
            if state.last_result_remaining > 1e-9
            else ""
        )
        return (
            team_id,
            max(0, _DART_MAX_PER_MATCH - state.darts_fired),
            max(0, opportunities - state.openings_used),
            phase,
            max(0.0, remaining),
            target,
            result,
        )

    def _advance_dart_effect_timers(self, dt: float, now: float) -> None:
        if dt <= 0:
            return
        for state in self._dart_system_by_team.values():
            state.last_result_remaining = max(0.0, state.last_result_remaining - dt)
            state.pending_projectiles = [
                projectile
                for projectile in state.pending_projectiles
                if projectile.expires_at > now + 1e-9
            ]
        for effects in self._dart_effects_by_team.values():
            effects.screen_obscured_remaining = max(
                0.0,
                effects.screen_obscured_remaining - dt,
            )
            effects.terrain_energy_suppressed_remaining = max(
                0.0,
                effects.terrain_energy_suppressed_remaining - dt,
            )
        for zone_id, until in tuple(self._field_buff_disabled_until_by_zone.items()):
            if until <= now + 1e-9:
                self._field_buff_disabled_until_by_zone[zone_id] = 0.0

    def on_attack_committed(self, robot: Robot) -> None:
        """Commit one legal shot using Fortress reserve first when available."""
        lifecycle = self._robot_lifecycle_by_robot.get(robot.id)
        allowance = self._projectile_allowance_by_robot.get(robot.id)
        shooting_heat = self._shooting_heat_by_robot.get(robot.id)
        usable_fortress_reserved = (
            0 if robot.type == "drone" else self._usable_fortress_reserved(robot)
        )
        lifecycle_ready = (
            self.drone_air_support_active(robot.id)
            and not self._drone_on_helipad(robot)
            if robot.type == "drone"
            else lifecycle is not None and not lifecycle.weak
        )
        if (
            not lifecycle_ready
            or allowance is None
            or (
                allowance.allowed <= 0
                and usable_fortress_reserved <= 0
            )
            or shooting_heat is None
            or shooting_heat.temporarily_locked
            or shooting_heat.permanently_locked
        ):
            return

        if usable_fortress_reserved > 0:
            reserve_state = self._fortress_reserved_by_robot[robot.id]
            reserve_state.reserved -= 1
        else:
            allowance.allowed -= 1

        if lifecycle is not None:
            lifecycle.disengaged_elapsed = 0.0
            lifecycle.combat_activity_this_frame = True

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
        lifecycle_state = self._robot_lifecycle_by_robot.get(robot.id)
        allowance_state = self._projectile_allowance_by_robot.get(robot.id)
        economy_state = self._economy_by_team.get(robot.team)
        purchase_state = self._projectile_purchase_by_team.get(robot.team)
        if (
            match.finished
            or robot.type == "drone"
            or not robot.alive
            or self._robots_by_id.get(robot.id) is not robot
            or lifecycle_state is None
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
            if lifecycle_state.disengaged_elapsed + 1e-9 < self._disengaged_after:
                return False
            cost = rule.remote_coins
            amount = rule.remote_allowance
        else:
            zones = self._projectile_exchange_zones_by_team.get(robot.team, ())
            if lifecycle_state.weak or not any(
                zone.contains(robot.position)
                and not self._field_buff_zone_disabled(zone.id)
                for zone in zones
            ):
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

    def remote_healing_cost(self, match: "Match") -> int:
        elapsed = min(self._time_limit, max(0.0, match.elapsed_time))
        elapsed_component = math.ceil(
            elapsed
            * self._remote_healing_elapsed_coins_multiplier
            / self._remote_healing_elapsed_seconds
        )
        return self._remote_healing_base_coins + elapsed_component

    def purchase_remote_healing(self, match: "Match", robot: Robot) -> bool:
        lifecycle = self._robot_lifecycle_by_robot.get(robot.id)
        economy = self._economy_by_team.get(robot.team)
        if (
            match.finished
            or not robot.alive
            or self._robots_by_id.get(robot.id) is not robot
            or robot.type not in self._remote_healing_eligible_types
            or lifecycle is None
            or economy is None
            or lifecycle.disengaged_elapsed + 1e-9 < self._disengaged_after
            or lifecycle.pending_remote_healing_effective_at is not None
        ):
            return False

        cost = self.remote_healing_cost(match)
        if economy.coins < cost:
            return False

        economy.coins -= cost
        lifecycle.pending_remote_healing_effective_at = (
            match.elapsed_time + self._remote_healing_effective_delay
        )
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
            or self._is_weak(engineer)
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
            or self._is_weak(engineer)
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
            self._apply_tech_core_first_rewards(engineer.team, difficulty)
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
            or self._is_weak(engineer)
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
            or self._is_weak(engineer)
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

    def _apply_tech_core_first_rewards(
        self,
        team_id: str,
        difficulty: int,
    ) -> None:
        rule = self._tech_core_difficulties[difficulty]
        if rule.first_level_cap is not None:
            self._level_cap_by_team[team_id] = max(
                self._level_cap_by_team[team_id],
                rule.first_level_cap,
            )

        structure_state = self._team_states[team_id]
        if rule.first_defense_bonus is not None:
            structure_state.tech_core_defense = max(
                structure_state.tech_core_defense,
                rule.first_defense_bonus,
            )

        if rule.first_base_hp_bonus is not None:
            base = self._base_by_team[team_id]
            bonus = rule.first_base_hp_bonus
            missing_hp = max(0, base.max_hp - base.hp)
            hp_gain = min(bonus, missing_hp)
            base.hp += hp_gain
            structure_state.base_virtual_shield += bonus - hp_gain
            self._sync_initialized_fortress_reserves(team_id)

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
        self._apply_tech_core_first_rewards(team_id, 4)
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

    def _engineer_field_invincible(self, robot: Robot) -> bool:
        if (
            robot.type != "engineer"
            or not robot.alive
            or self._is_weak(robot)
        ):
            return False

        own_supply = self._supply_buff_zone_by_team.get(robot.team)
        if (
            own_supply is not None
            and self._field_occupy_remaining.get(
                (robot.id, own_supply.id), 0.0
            )
            > 0
        ):
            return True

        own_assembly = self._assembly_zone_by_team.get(robot.team)
        return (
            own_assembly is not None
            and self._field_occupy_remaining.get(
                (robot.id, own_assembly.id), 0.0
            )
            > 0
            and self._assembly_invincibility_elapsed_by_engineer.get(
                robot.id, 0.0            )
            < self._assembly_invincibility_limit - 1e-9
        )

    def can_receive_damage(self, target: DamageableTarget) -> bool:
        if not target.alive:
            return False
        if isinstance(target, Robot):
            if target.type == "drone":
                return False
            lifecycle = self._robot_lifecycle_by_robot.get(target.id)
            if lifecycle is not None and lifecycle.invincible_remaining > 0:
                return False
            return not self._engineer_field_invincible(target)
        if isinstance(target, Structure) and target.type == "base":
            outpost = self._outpost_by_team.get(target.team)
            return outpost is None or not outpost.alive
        return True

    def grant_attack_buff(
        self,
        team_id: str,
        multiplier: float,
        duration: float,
        *,
        mechanism: str | None = None,
    ) -> bool:
        """Apply an already-resolved team Attack Buff fact.

        Source acquisition (for example Energy Mechanism activation) remains
        outside this rule-level consumer.
        """
        if (
            team_id not in self._attack_buffs_by_team
            or not math.isfinite(multiplier)
            or multiplier <= 1.0
            or not math.isfinite(duration)
            or duration <= 0
        ):
            return False
        self._attack_buffs_by_team[team_id].append(
            _TimedAttackBuff(
                multiplier=float(multiplier),
                remaining=float(duration),
                mechanism=mechanism,
            )
        )
        return True

    def _effective_attack_multiplier(self, source_team_id: str | None) -> float:
        if source_team_id is None:
            return 1.0
        return max(
            (
                buff.multiplier
                for buff in self._attack_buffs_by_team.get(source_team_id, ())
                if buff.remaining > 0
                and not (
                    buff.mechanism == "large-energy"
                    and self._dart_effects_by_team.get(source_team_id)
                    is not None
                    and self._dart_effects_by_team[source_team_id]
                    .terrain_energy_suppressed_remaining
                    > 0
                )
            ),
            default=1.0,
        )

    def _large_energy_mechanism_effects(
        self,
        average_ring_score: float,
    ) -> tuple[float, float, float] | None:
        if (
            not math.isfinite(average_ring_score)
            or average_ring_score < 1.0
            or average_ring_score > 10.0
        ):
            return None
        if average_ring_score <= 3.0:
            return (1.5, 0.25, 1.0)
        if average_ring_score <= 7.0:
            return (1.5, 0.25, 2.0)
        if average_ring_score <= 8.0:
            return (2.0, 0.25, 2.0)
        if average_ring_score <= 9.0:
            return (2.0, 0.25, 3.0)
        if average_ring_score <= 10.0:
            return (3.0, 0.50, 5.0)
        return None

    def _large_energy_mechanism_duration(
        self,
        lit_arm_count: int,
    ) -> float | None:
        return {
            5: 30.0,
            6: 35.0,
            7: 40.0,
            8: 45.0,
            9: 50.0,
            10: 60.0,
        }.get(lit_arm_count)

    def activate_large_energy_mechanism_buff(
        self,
        team_id: str,
        average_ring_score: float,
        lit_arm_count: int,
    ) -> bool:
        """Apply one confirmed activation result and its V1.4.0 Experience.

        Rotation, hit detection, ring recognition, activation opportunities, and
        the 20-second activation procedure remain outside this rule-level API.
        """
        buffs = self._energy_mechanism_buffs_by_team.get(team_id)
        effects = self._large_energy_mechanism_effects(average_ring_score)
        duration = (
            None
            if isinstance(lit_arm_count, bool)
            else self._large_energy_mechanism_duration(lit_arm_count)
        )
        if (
            buffs is None
            or effects is None
            or duration is None
            or any(
                buff.mechanism == "large" and buff.remaining > 0
                for buff in buffs
            )
        ):
            return False

        attack_multiplier, defense, cooling_multiplier = effects
        if not self.grant_attack_buff(
            team_id,
            attack_multiplier,
            duration,
            mechanism="large-energy",
        ):
            return False
        buffs.append(
            _TimedEnergyMechanismBuff(
                mechanism="large",
                defense=defense,
                cooling_multiplier=cooling_multiplier,
                remaining=duration,
            )
        )
        self._grant_large_energy_mechanism_experience(team_id)
        return True

    def activate_small_energy_mechanism_buff(
        self,
        match: "Match",
        initiator: Robot,
        activation_started_at: float,
    ) -> bool:
        """Apply one referee-confirmed Small Energy Mechanism activation.

        The caller supplies the activation start time from the upstream
        mechanism event. This rule-level result boundary checks the V1.4.0
        phase, accumulated opportunity, permitted command source, and 20-second
        completion window; rotating hardware and hit recognition stay outside
        the Rules Lab.
        """
        team_id = initiator.team
        buffs = self._energy_mechanism_buffs_by_team.get(team_id)
        activation_times = self._small_energy_mechanism_activation_times_by_team.get(
            team_id
        )
        elapsed = match.elapsed_time
        if (
            match.finished
            or buffs is None
            or activation_times is None
            or self._robots_by_id.get(initiator.id) is not initiator
            or initiator.type not in {"infantry", "sentry"}
            or not math.isfinite(activation_started_at)
            or activation_started_at < 0
            or activation_started_at >= _SMALL_ENERGY_PHASE_END
            or elapsed + 1e-9 < activation_started_at
            or elapsed >= _SMALL_ENERGY_PHASE_END
            or elapsed - activation_started_at
            >= _SMALL_ENERGY_ACTIVATION_WINDOW - 1e-9
            or any(
                buff.mechanism == "small" and buff.remaining > 0
                for buff in buffs
            )
            or any(
                abs(previous - activation_started_at) <= 1e-9
                for previous in activation_times
            )
        ):
            return False

        available_opportunities = 1 + int(
            activation_started_at + 1e-9 >= _SMALL_ENERGY_OPPORTUNITY_INTERVAL
        )
        if len(activation_times) >= available_opportunities:
            return False

        buffs.append(
            _TimedEnergyMechanismBuff(
                mechanism="small",
                defense=0.25,
                cooling_multiplier=1.0,
                remaining=_SMALL_ENERGY_BUFF_DURATION,
                experience_bonus_remaining=_SMALL_ENERGY_EXPERIENCE_BONUS_CAP,
            )
        )
        activation_times.append(float(activation_started_at))
        return True

    def _grant_large_energy_mechanism_experience(self, team_id: str) -> None:
        """Split the activation's 750 XP pool across living eligible teammates."""
        recipients = [
            robot_id
            for robot_id in sorted(self._progression_by_robot)
            if (
                self._robots_by_id[robot_id].team == team_id
                and self._robots_by_id[robot_id].alive
            )
        ]
        if not recipients:
            return

        experience_each = 750.0 / len(recipients)
        for robot_id in recipients:
            self._grant_experience(robot_id, experience_each)

    def _current_large_energy_mechanism_defense(self, team_id: str) -> float:
        if self._energy_and_terrain_buffs_suppressed(team_id):
            return 0.0
        return max(
            (
                buff.defense
                for buff in self._energy_mechanism_buffs_by_team.get(
                    team_id, ()
                )
                if buff.mechanism == "large" and buff.remaining > 0
            ),
            default=0.0,
        )

    def _current_small_energy_mechanism_defense(self, team_id: str) -> float:
        if self._energy_and_terrain_buffs_suppressed(team_id):
            return 0.0
        return max(
            (
                buff.defense
                for buff in self._energy_mechanism_buffs_by_team.get(
                    team_id, ()
                )
                if buff.mechanism == "small" and buff.remaining > 0
            ),
            default=0.0,
        )

    def _current_energy_mechanism_defense(self, team_id: str) -> float:
        return max(
            self._current_large_energy_mechanism_defense(team_id),
            self._current_small_energy_mechanism_defense(team_id),
        )

    def _current_large_energy_mechanism_cooling_multiplier(
        self,
        team_id: str,
    ) -> float:
        if self._energy_and_terrain_buffs_suppressed(team_id):
            return 1.0
        return max(
            (
                buff.cooling_multiplier
                for buff in self._energy_mechanism_buffs_by_team.get(
                    team_id, ()
                )
                if buff.mechanism == "large" and buff.remaining > 0
            ),
            default=1.0,
        )

    def _energy_and_terrain_buffs_suppressed(self, team_id: str) -> bool:
        effects = self._dart_effects_by_team.get(team_id)
        return (
            effects is not None
            and effects.terrain_energy_suppressed_remaining > 1e-9
        )

    def set_radar_vulnerability(
        self,
        source_team_id: str,
        target: Robot,
        vulnerability: float,
    ) -> bool:
        """Set the official P-derived Radar Vulnerability effect for one target.

        Radar detection, marking progress P, interference-wave gating, and
        target acquisition are intentionally outside this rule-level consumer.
        """
        if (
            self._robots_by_id.get(target.id) is not target
            or target.type not in _RADAR_VULNERABILITY_ROBOT_TYPES
            or source_team_id not in self.attack_damage_by_team
            or source_team_id == target.team
            or vulnerability not in {0.0, 0.15, 0.20}
        ):
            return False

        if vulnerability == 0.0:
            self._radar_vulnerability_by_robot.pop(target.id, None)
            return True

        self._radar_vulnerability_by_robot[target.id] = _RadarVulnerabilityState(
            source_team_id=source_team_id,
            base_vulnerability=vulnerability,
        )
        return True

    def start_radar_double_vulnerability_effect(
        self,
        source_team_id: str,
    ) -> bool:
        """Start an already-authorized 30 s Radar double-vulnerability effect.

        Opportunity accumulation and referee-command queueing remain outside
        this effect-only API.
        """
        state = self._radar_double_vulnerability_by_team.get(source_team_id)
        if (
            state is None
            or state.remaining > 0
            or state.activations >= 2
        ):
            return False
        state.remaining = 30.0
        state.activations += 1
        return True

    def _current_radar_vulnerability(self, target: Robot) -> float:
        state = self._radar_vulnerability_by_robot.get(target.id)
        if state is None:
            return 0.0
        double_state = self._radar_double_vulnerability_by_team.get(
            state.source_team_id
        )
        multiplier = (
            2.0
            if double_state is not None and double_state.remaining > 0
            else 1.0
        )
        return state.base_vulnerability * multiplier

    def resolve_damage(
        self,
        target: DamageableTarget,
        amount: int,
        source_team_id: str | None,
        *,
        bypass_attack_defense: bool = False,
    ) -> int:
        """Apply Attack, max Defense/Vulnerability, then Base Virtual Shield."""
        if (
            amount <= 0
            or source_team_id not in self.attack_damage_by_team
            or source_team_id == target.team
        ):
            return amount

        state = self._team_states.get(target.team)
        if state is None:
            return amount

        if bypass_attack_defense:
            resolved = max(0, amount)
        else:
            attack = self._effective_attack_multiplier(source_team_id)
            defense = self._effective_defense(target)
            vulnerability = self._effective_vulnerability(target)
            multiplier = max(0.0, attack * (1.0 - defense + vulnerability))
            resolved = int(math.floor(amount * multiplier + 0.5))
            resolved = max(0, resolved)

        if (
            resolved > 0
            and isinstance(target, Structure)
            and target.type == "base"
            and state.base_virtual_shield > 0
        ):
            absorbed = min(state.base_virtual_shield, resolved)
            state.base_virtual_shield -= absorbed
            resolved -= absorbed

        return resolved

    def _effective_vulnerability(
        self,
        target: DamageableTarget,
    ) -> float:
        if not isinstance(target, Robot) or not target.alive:
            return 0.0

        vulnerabilities = [
            self._enemy_fortress_vulnerability
            for (robot_id, fortress_team_id), occupation
            in self._enemy_fortress_occupation.items()
            if robot_id == target.id
            and occupation.occupy_remaining > 0
            and not self._team_states[fortress_team_id].base_armor_deployed
        ]
        radar = self._current_radar_vulnerability(target)
        if radar > 0:
            vulnerabilities.append(radar)
        return max(vulnerabilities, default=0.0)

    def _effective_defense(self, target: DamageableTarget) -> float:
        if isinstance(target, Robot) and target.type == "drone":
            return self._current_energy_mechanism_defense(target.team)
        state = self._team_states.get(target.team)
        if state is None:
            return 0.0
        energy_defense = self._current_energy_mechanism_defense(target.team)
        if not isinstance(target, Robot):
            return max(state.tech_core_defense, energy_defense)
        return max(
            state.tech_core_defense,
            energy_defense,
            self._current_field_defense(target),
            self._current_terrain_defense(target),
            self._current_fortress_defense(target),
        )

    def _current_field_defense(self, robot: Robot) -> float:
        if not robot.alive:
            return 0.0

        best = 0.0
        own_base = self._field_base_zone_by_team.get(robot.team)
        if (
            own_base is not None
            and not self._field_buff_zone_disabled(own_base.id)
            and self._field_occupy_remaining.get((robot.id, own_base.id), 0.0) > 0
        ):
            best = max(best, self._field_defense_by_type["base"])

        own_trapezoid = self._field_trapezoid_zone_by_team.get(robot.team)
        if (
            own_trapezoid is not None
            and self._field_occupy_remaining.get(
                (robot.id, own_trapezoid.id), 0.0
            ) > 0
        ):
            best = max(best, self._field_defense_by_type["trapezoid"])

        for zone in self._field_central_zones:
            point_state = self._central_defense_state_by_zone[zone.id]
            if (
                point_state.owner_team_id == robot.team
                and self._field_occupy_remaining.get((robot.id, zone.id), 0.0) > 0
            ):
                best = max(best, self._field_defense_by_type["central"])

        for point_team, zone in self._field_outpost_zone_by_team.items():
            if (
                not self._field_buff_zone_disabled(zone.id)
                and
                self._field_occupy_remaining.get((robot.id, zone.id), 0.0) > 0
                and self._outpost_buff_eligible(robot, point_team)
            ):
                best = max(best, self._field_defense_by_type["outpost"])

        return best

    def _field_buff_zone_disabled(self, zone_id: str) -> bool:
        return (
            self._field_buff_disabled_until_by_zone.get(zone_id, 0.0)
            > self._current_time + 1e-9
        )

    def _is_fortress_occupant(self, robot: Robot) -> bool:
        state = self._fortress_state_by_team.get(robot.team)
        return (
            robot.alive
            and not self._is_weak(robot)
            and robot.type in self._fortress_eligible_types
            and state is not None
            and state.owner_robot_id == robot.id
            and self._team_states[robot.team].outpost_ever_destroyed
        )

    def _fortress_reserve_limit(self, robot: Robot) -> int:
        base = self._base_by_team[robot.team]
        delta = max(0, base.max_hp - base.hp)
        return min(
            self._fortress_reserve_cap,
            self._fortress_reserve_base
            + self._fortress_reserve_per_step
            * math.floor(delta / self._fortress_reserve_hp_step),
        )

    def _sync_fortress_reserved(
        self,
        robot: Robot,
        *,
        allow_initialize: bool,
    ) -> _FortressReservedProjectileState | None:
        state = self._fortress_reserved_by_robot.get(robot.id)
        if state is None:
            return None

        limit = self._fortress_reserve_limit(robot)
        if not state.initialized:
            if not allow_initialize:
                return state
            state.reserved = limit
            state.last_limit = limit
            state.initialized = True
            return state

        if limit > state.last_limit:
            state.reserved += limit - state.last_limit
        elif limit < state.last_limit:
            state.reserved = min(state.reserved, limit)
        state.last_limit = limit
        return state

    def _sync_initialized_fortress_reserves(
        self,
        team_id: str | None = None,
    ) -> None:
        for robot_id, state in self._fortress_reserved_by_robot.items():
            if not state.initialized:
                continue
            robot = self._robots_by_id[robot_id]
            if team_id is not None and robot.team != team_id:
                continue
            self._sync_fortress_reserved(
                robot,
                allow_initialize=False,
            )

    def _usable_fortress_reserved(self, robot: Robot) -> int:
        if not self._is_fortress_occupant(robot):
            return 0
        state = self._sync_fortress_reserved(
            robot,
            allow_initialize=True,
        )
        if state is None:
            return 0
        return state.reserved

    def _current_fortress_defense(self, robot: Robot) -> float:
        return self._fortress_defense if self._is_fortress_occupant(robot) else 0.0

    def _fortress_cooling_bonus(self, robot: Robot) -> int:
        if not self._is_fortress_occupant(robot):
            return 0
        base = self._base_by_team[robot.team]
        delta = max(0, base.max_hp - base.hp)
        return min(
            self._fortress_cooling_cap,
            math.floor(delta / self._fortress_cooling_hp_step),
        )

    def _advance_fortress_occupancy(self, dt: float) -> None:
        for team_id, zone in self._fortress_zone_by_team.items():
            state = self._fortress_state_by_team[team_id]
            if not self._team_states[team_id].outpost_ever_destroyed:
                state.owner_robot_id = None
                state.release_remaining = 0.0
                continue

            owner = (
                self._robots_by_id.get(state.owner_robot_id)
                if state.owner_robot_id is not None
                else None
            )
            if (
                owner is not None
                and owner.alive
                and not self._is_weak(owner)
                and owner.team == team_id
                and owner.type in self._fortress_eligible_types
                and zone.contains(owner.position)
            ):
                state.release_remaining = self._field_occupy_release_delay
                self._sync_fortress_reserved(
                    owner,
                    allow_initialize=True,
                )
            elif state.owner_robot_id is not None:
                state.release_remaining = max(
                    0.0,
                    state.release_remaining - dt,
                )
                if state.release_remaining <= 1e-9:
                    state.owner_robot_id = None
                    state.release_remaining = 0.0

            if state.owner_robot_id is not None:
                continue

            candidates = sorted(
                (
                    robot
                    for robot in self._robots_by_id.values()
                    if robot.alive
                    and not self._is_weak(robot)
                    and robot.team == team_id
                    and robot.type in self._fortress_eligible_types
                    and zone.contains(robot.position)
                ),
                key=lambda robot: robot.id,
            )
            if candidates:
                state.owner_robot_id = candidates[0].id
                state.release_remaining = self._field_occupy_release_delay
                self._sync_fortress_reserved(
                    candidates[0],
                    allow_initialize=True,
                )

    def _enemy_fortress_eligible(
        self,
        robot: Robot,
        fortress_team_id: str,
        at_time: float,
    ) -> bool:
        return (
            robot.alive
            and not self._is_weak(robot)
            and robot.team != fortress_team_id
            and robot.type in self._enemy_fortress_eligible_types
            and at_time + 1e-9 >= self._enemy_fortress_available_after
            and self._team_states[
                fortress_team_id
            ].outpost_ever_destroyed
        )

    def _refresh_enemy_fortress_occupancy(
        self,
        match: "Match",
        dt: float,
    ) -> None:
        frame_end = min(
            match.elapsed_time + max(0.0, dt),
            self._time_limit,
        )
        for (robot_id, fortress_team_id), state in (
            self._enemy_fortress_occupation.items()
        ):
            robot = self._robots_by_id[robot_id]
            zone = self._fortress_zone_by_team[fortress_team_id]
            if (
                self._enemy_fortress_eligible(
                    robot,
                    fortress_team_id,
                    frame_end,
                )
                and zone.contains(robot.position)
            ):
                state.occupy_remaining = self._field_occupy_release_delay
                state.retention_remaining = 0.0

    def _advance_enemy_fortress_occupation(
        self,
        match: "Match",
        dt: float,
    ) -> None:
        frame_dt = max(0.0, dt)
        frame_end = min(match.elapsed_time, self._time_limit)
        frame_start = max(0.0, frame_end - frame_dt)
        armor_at_frame_start = {
            team_id: state.base_armor_deployed
            for team_id, state in self._team_states.items()
        }
        teams_to_deploy: set[str] = set()

        for key, state in self._enemy_fortress_occupation.items():
            robot_id, fortress_team_id = key
            robot = self._robots_by_id[robot_id]
            zone = self._fortress_zone_by_team[fortress_team_id]

            if key in self._enemy_fortress_death_retention_started:
                continue

            physically_occupying = (
                self._enemy_fortress_eligible(
                    robot,
                    fortress_team_id,
                    frame_end,
                )
                and zone.contains(robot.position)
            )
            armor_already_deployed = armor_at_frame_start[
                fortress_team_id
            ]

            if physically_occupying:
                state.occupy_remaining = self._field_occupy_release_delay
                state.retention_remaining = 0.0

                active_dt = frame_dt
                if frame_start < self._enemy_fortress_available_after:
                    active_dt = max(
                        0.0,
                        frame_end - self._enemy_fortress_available_after,
                    )
                if fortress_team_id in self._outposts_destroyed_this_frame:
                    active_dt = 0.0

                if not armor_already_deployed and active_dt > 0:
                    state.occupation_elapsed += active_dt
                    if (
                        state.occupation_elapsed + 1e-9
                        >= self._enemy_fortress_armor_after
                    ):
                        teams_to_deploy.add(fortress_team_id)
                continue

            if state.occupy_remaining > 0:
                active_dt = min(frame_dt, state.occupy_remaining)
                if not armor_already_deployed and active_dt > 0:
                    state.occupation_elapsed += active_dt
                    if (
                        state.occupation_elapsed + 1e-9
                        >= self._enemy_fortress_armor_after
                    ):
                        teams_to_deploy.add(fortress_team_id)

                old_occupy = state.occupy_remaining
                state.occupy_remaining = max(
                    0.0,
                    old_occupy - frame_dt,
                )
                if state.occupy_remaining <= 1e-9:
                    state.occupy_remaining = 0.0
                    overflow = max(0.0, frame_dt - old_occupy)
                    state.retention_remaining = max(
                        0.0,
                        self._enemy_fortress_retention - overflow,
                    )
                    if state.retention_remaining <= 1e-9:
                        state.retention_remaining = 0.0
                        state.occupation_elapsed = 0.0
                continue

            if state.retention_remaining > 0:
                state.retention_remaining = max(
                    0.0,
                    state.retention_remaining - frame_dt,
                )
                if state.retention_remaining <= 1e-9:
                    state.retention_remaining = 0.0
                    state.occupation_elapsed = 0.0

        for team_id in teams_to_deploy:
            self._team_states[team_id].base_armor_deployed = True

        self._enemy_fortress_death_retention_started.clear()
        self._outposts_destroyed_this_frame.clear()

    def _enemy_fortress_status_label(self, robot: Robot) -> str:
        labels: list[str] = []
        for (robot_id, fortress_team_id), state in (
            self._enemy_fortress_occupation.items()
        ):
            if robot_id != robot.id:
                continue
            armor_deployed = self._team_states[
                fortress_team_id
            ].base_armor_deployed
            if state.occupy_remaining > 0:
                if armor_deployed:
                    labels.append(
                        f"EFORT T:{state.occupation_elapsed:.1f}/"
                        f"{self._enemy_fortress_armor_after:g}"
                    )
                else:
                    labels.append(
                        f"EFORT VULN100 T:{state.occupation_elapsed:.1f}/"
                        f"{self._enemy_fortress_armor_after:g}"
                    )
            elif state.retention_remaining > 0:
                labels.append(
                    f"EFORT HOLD {state.retention_remaining:.1f}s"
                )
        return " ".join(labels)

    def _current_terrain_defense(self, robot: Robot) -> float:
        if not robot.alive or self._energy_and_terrain_buffs_suppressed(robot.team):
            return 0.0
        state = self._terrain_crossing_by_robot.get(robot.id)
        if state is None:
            return 0.0
        best = 0.0
        if state.standard_defense_remaining > 0:
            best = max(best, state.standard_defense)
        if state.tunnel_defense_remaining > 0:
            best = max(best, self._terrain_rules["tunnel"].defense)
        return best

    def _terrain_defense_display(
        self,
        robot: Robot,
    ) -> tuple[float, float]:
        state = self._terrain_crossing_by_robot.get(robot.id)
        if (
            state is None
            or not robot.alive
            or self._energy_and_terrain_buffs_suppressed(robot.team)
        ):
            return 0.0, 0.0
        options: list[tuple[float, float]] = []
        if state.standard_defense_remaining > 0:
            options.append(
                (state.standard_defense, state.standard_defense_remaining)
            )
        if state.tunnel_defense_remaining > 0:
            options.append(
                (
                    self._terrain_rules["tunnel"].defense,
                    state.tunnel_defense_remaining,
                )
            )
        if not options:
            return 0.0, 0.0
        max_defense = max(value for value, _remaining in options)
        max_remaining = max(
            remaining
            for value, remaining in options
            if abs(value - max_defense) <= 1e-9
        )
        return max_defense, max_remaining

    def _robot_status_label(self, robot: Robot) -> str:
        parts: list[str] = []
        effective_defense = self._effective_defense(robot)
        if effective_defense > 0:
            parts.append(f"DEF {int(effective_defense * 100)}%")

        terrain_defense, terrain_remaining = self._terrain_defense_display(robot)
        if terrain_defense > 0 and terrain_remaining > 0:
            parts.append(
                f"TDEF {int(terrain_defense * 100)}% {terrain_remaining:.1f}s"
            )

        terrain_state = self._terrain_crossing_by_robot.get(robot.id)
        if (
            terrain_state is not None
            and terrain_state.tunnel_cooling_remaining > 0
        ):
            multiplier = self._terrain_rules["tunnel"].cooling_multiplier
            parts.append(
                f"TCool ×{multiplier:g} "
                f"{terrain_state.tunnel_cooling_remaining:.1f}s"
            )

        if self._is_fortress_occupant(robot):
            parts.append(
                f"FORT DEF50 FC:+{self._fortress_cooling_bonus(robot)}"
            )

        enemy_fortress_status = self._enemy_fortress_status_label(robot)
        if enemy_fortress_status:
            parts.append(enemy_fortress_status)
        return " ".join(parts)

    def _advance_terrain_crossing_timers(self, dt: float) -> None:
        if dt <= 0:
            return
        for state in self._terrain_crossing_by_robot.values():
            state.standard_defense_remaining = max(
                0.0,
                state.standard_defense_remaining - dt,
            )
            if state.standard_defense_remaining <= 1e-9:
                state.standard_defense_remaining = 0.0
                state.standard_defense = 0.0

            state.tunnel_defense_remaining = max(
                0.0,
                state.tunnel_defense_remaining - dt,
            )
            if state.tunnel_defense_remaining <= 1e-9:
                state.tunnel_defense_remaining = 0.0

            state.tunnel_cooling_remaining = max(
                0.0,
                state.tunnel_cooling_remaining - dt,
            )
            if state.tunnel_cooling_remaining <= 1e-9:
                state.tunnel_cooling_remaining = 0.0

            state.road_reacquire_remaining = max(
                0.0,
                state.road_reacquire_remaining - dt,
            )
            if state.road_reacquire_remaining <= 1e-9:
                state.road_reacquire_remaining = 0.0

    @staticmethod
    def _reset_terrain_sequence(state: _TerrainCrossingState) -> None:
        state.sequence = _TerrainSequenceState()

    def _process_terrain_crossing_rfid(
        self,
        match: "Match",
        event_time: float,
    ) -> None:
        del match
        for robot in self._robots_by_id.values():
            state = self._terrain_crossing_by_robot.get(robot.id)
            if state is None:
                continue
            if not robot.alive or self._is_weak(robot):
                state.occupied_rfid_zone_ids.clear()
                self._reset_terrain_sequence(state)
                continue

            if (
                state.sequence.terrain_type is not None
                and event_time > state.sequence.expires_at + 1e-9
            ):
                self._reset_terrain_sequence(state)

            current_zone_ids = {
                zone_id
                for zone_id, zone in self._terrain_interrupt_zones_by_id.items()
                if zone.contains(robot.position)
            }
            entered_zone_ids = sorted(
                current_zone_ids - state.occupied_rfid_zone_ids
            )

            for zone_id in entered_zone_ids:
                self._process_terrain_rfid_entry(
                    robot,
                    state,
                    zone_id,
                    event_time,
                )

            state.occupied_rfid_zone_ids = current_zone_ids

    def _process_terrain_rfid_entry(
        self,
        robot: Robot,        state: _TerrainCrossingState,
        zone_id: str,
        event_time: float,
    ) -> None:
        sequence = state.sequence
        if sequence.terrain_type is not None:
            if (
                event_time <= sequence.expires_at + 1e-9
                and sequence.next_index < len(sequence.expected_zone_ids)
                and zone_id == sequence.expected_zone_ids[sequence.next_index]
            ):
                sequence.next_index += 1
                if sequence.next_index >= len(sequence.expected_zone_ids):
                    terrain_type = sequence.terrain_type
                    self._reset_terrain_sequence(state)
                    self._grant_terrain_crossing_buff(robot, terrain_type)
                return

            self._reset_terrain_sequence(state)
            return

        lookup = self._terrain_zone_lookup.get(zone_id)
        if lookup is None:
            return
        side, terrain_type, index = lookup
        zones = self._terrain_zones_by_side_and_type[side][terrain_type]
        if terrain_type == "tunnel":
            if index == 0:
                expected = tuple(zone.id for zone in zones)
            elif index == len(zones) - 1:
                expected = tuple(zone.id for zone in reversed(zones))
            else:
                return
        else:
            if index != 0:
                return
            expected = tuple(zone.id for zone in zones)

        state.sequence = _TerrainSequenceState(
            terrain_type=terrain_type,
            expected_zone_ids=expected,
            next_index=1,
            expires_at=event_time
            + self._terrain_rules[terrain_type].sequence_window,
        )

    def _grant_terrain_crossing_buff(
        self,
        robot: Robot,
        terrain_type: str,
    ) -> bool:
        state = self._terrain_crossing_by_robot.get(robot.id)
        if not robot.alive or state is None:
            return False
        rule = self._terrain_rules[terrain_type]

        if terrain_type == "road" and state.road_reacquire_remaining > 0:
            return False

        if terrain_type in {"launch_ramp", "elevated_ground", "road"}:
            if state.standard_defense_remaining > 0:
                state.standard_defense = 0.50
                state.standard_defense_remaining = max(
                    state.standard_defense_remaining,
                    rule.defense_duration,
                )
            else:
                state.standard_defense = rule.defense
                state.standard_defense_remaining = rule.defense_duration
            if terrain_type == "road":
                state.road_reacquire_remaining = rule.reacquire_cooldown
        elif terrain_type == "tunnel":
            state.tunnel_defense_remaining = rule.defense_duration
            state.tunnel_cooling_remaining = rule.cooling_duration
        else:
            raise KeyError(terrain_type)

        if terrain_type not in state.first_acquired_types:
            state.first_acquired_types.add(terrain_type)
            self._grant_experience(robot.id, self._terrain_first_experience)
        return True

    def _outpost_buff_eligible(self, robot: Robot, point_team: str) -> bool:
        own_outpost = self._outpost_by_team.get(robot.team)
        point_outpost = self._outpost_by_team.get(point_team)
        if own_outpost is None or point_outpost is None or not own_outpost.alive:
            return False
        if point_team == robot.team:
            return True
        return (
            self._field_buff_elapsed < 300.0
            and not point_outpost.alive
        )

    def _advance_field_occupy_remaining(
        self,
        robot: Robot,
        zone: Zone,
        eligible: bool,
        dt: float,
    ) -> float:
        key = (robot.id, zone.id)
        if eligible and zone.contains(robot.position):
            self._field_occupy_remaining[key] = self._field_occupy_release_delay
            return max(0.0, dt)
        if not eligible:
            self._field_occupy_remaining[key] = 0.0
            return 0.0

        previous_remaining = self._field_occupy_remaining.get(key, 0.0)
        active_dt = min(max(0.0, dt), previous_remaining)
        remaining = max(0.0, previous_remaining - max(0.0, dt))
        self._field_occupy_remaining[key] = (
            0.0 if remaining <= 1e-9 else remaining
        )
        return active_dt

    def _advance_field_defense_occupancy(
        self,
        match: "Match",
        dt: float,
    ) -> None:
        self._field_buff_elapsed = min(
            match.elapsed_time + dt,
            self._time_limit,
        )

        for zone in self._field_central_zones:
            point_state = self._central_defense_state_by_zone[zone.id]
            physical_teams = {
                robot.team
                for robot in self._robots_by_id.values()
                if robot.alive
                and not self._is_weak(robot)
                and robot.type in {"hero", "infantry", "sentry"}
                and zone.contains(robot.position)
            }

            if point_state.owner_team_id is not None:
                if point_state.owner_team_id in physical_teams:
                    point_state.release_remaining = self._field_occupy_release_delay
                else:
                    point_state.release_remaining = max(
                        0.0,
                        point_state.release_remaining - dt,
                    )
                    if point_state.release_remaining <= 1e-9:
                        point_state.owner_team_id = None
                        point_state.release_remaining = 0.0

            if point_state.owner_team_id is None and len(physical_teams) == 1:
                point_state.owner_team_id = next(iter(physical_teams))
                point_state.release_remaining = self._field_occupy_release_delay

        for robot in self._robots_by_id.values():
            if robot.type == "drone" or not robot.alive or self._is_weak(robot):
                for key in [
                    key
                    for key in self._field_occupy_remaining
                    if key[0] == robot.id
                ]:
                    self._field_occupy_remaining[key] = 0.0
                continue

            candidate_zones: list[tuple[Zone, bool]] = []
            own_base = self._field_base_zone_by_team[robot.team]
            own_trapezoid = self._field_trapezoid_zone_by_team[robot.team]
            own_supply = self._supply_buff_zone_by_team[robot.team]
            own_assembly = self._assembly_zone_by_team[robot.team]
            candidate_zones.extend(
                (
                    (own_base, True),
                    (own_trapezoid, True),
                    (own_supply, True),
                    (own_assembly, robot.type == "engineer"),
                )
            )
            candidate_zones.extend(
                (
                    zone,
                    robot.type in {"hero", "infantry", "sentry"},
                )
                for zone in self._field_central_zones
            )
            candidate_zones.extend(
                (
                    zone,
                    self._outpost_buff_eligible(robot, point_team),
                )
                for point_team, zone in self._field_outpost_zone_by_team.items()
            )

            assembly_active_dt = 0.0
            for zone, eligible in candidate_zones:
                active_dt = self._advance_field_occupy_remaining(
                    robot,
                    zone,
                    eligible,
                    dt,
                )
                if zone is own_assembly:
                    assembly_active_dt = active_dt

            if robot.type == "engineer" and assembly_active_dt > 0:
                elapsed = self._assembly_invincibility_elapsed_by_engineer[
                    robot.id
                ]
                self._assembly_invincibility_elapsed_by_engineer[robot.id] = min(
                    self._assembly_invincibility_limit,
                    elapsed + assembly_active_dt,
                )

    def prepare_movement(self, match: "Match", dt: float) -> None:
        """Settle synthetic RMUC chassis power at 10 Hz before movement."""
        for robot_id, state in self._chassis_power_by_robot.items():
            state.blocked_this_frame = state.power_off_remaining > 0
            robot = self._robots_by_id[robot_id]
            self._current_synthetic_power_by_robot[robot_id] = (
                self._synthetic_chassis_power(robot, state)
            )

        if dt <= 0:
            return

        self._chassis_power_accumulator += dt
        ticks = math.floor(
            self._chassis_power_accumulator * self._chassis_power_detection_hz
            + 1e-9
        )
        if ticks <= 0:
            return

        tick_duration = 1.0 / self._chassis_power_detection_hz
        self._chassis_power_accumulator = max(
            0.0,
            self._chassis_power_accumulator - ticks * tick_duration,
        )

        for _ in range(ticks):
            for robot_id, state in self._chassis_power_by_robot.items():
                robot = self._robots_by_id[robot_id]
                power_limit = self._effective_chassis_power_limit(robot_id)
                was_powered_off = state.power_off_remaining > 0

                if was_powered_off:
                    state.blocked_this_frame = True
                    power = self._chassis_stationary_power_demand
                else:
                    power = self._synthetic_chassis_power(robot, state)

                state.buffer_energy -= (power - power_limit) * tick_duration
                state.buffer_energy = min(
                    self._effective_buffer_energy_max(robot_id),
                    state.buffer_energy,
                )

                if state.buffer_energy <= 0:
                    state.buffer_energy = 0.0
                    if not was_powered_off and power > power_limit:
                        state.power_off_remaining = self._chassis_power_off_duration
                        state.blocked_this_frame = True

                if was_powered_off:
                    state.power_off_remaining = max(
                        0.0,
                        state.power_off_remaining - tick_duration,
                    )
                    if state.power_off_remaining <= 1e-9:
                        state.power_off_remaining = 0.0

        for robot_id, state in self._chassis_power_by_robot.items():
            robot = self._robots_by_id[robot_id]
            self._current_synthetic_power_by_robot[robot_id] = (
                self._synthetic_chassis_power(robot, state)
            )

    def prepare_combat(self, match: "Match", dt: float) -> None:
        """Refresh timed combat buffs around the existing 10 Hz Heat loop."""
        frame_dt = max(0.0, dt)
        self._advance_dart_effect_timers(
            frame_dt,
            min(match.elapsed_time + frame_dt, self._time_limit),
        )
        self._advance_attack_buffs(frame_dt)
        self._advance_energy_mechanism_buffs(frame_dt)
        self._advance_radar_double_vulnerability(frame_dt)
        self._advance_radar_anti_drone(frame_dt)
        self._advance_field_defense_occupancy(match, frame_dt)
        self._advance_fortress_occupancy(frame_dt)
        self._refresh_enemy_fortress_occupancy(match, frame_dt)
        self._advance_terrain_crossing_timers(frame_dt)

        if dt > 0:
            self._heat_cooling_accumulator += dt
            ticks = math.floor(
                self._heat_cooling_accumulator * self._shooting_heat_detection_hz
                + 1e-9
            )
            if ticks > 0:
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

        self._process_terrain_crossing_rfid(
            match,
            min(match.elapsed_time + frame_dt, self._time_limit),
        )

    def _advance_attack_buffs(self, dt: float) -> None:
        if dt <= 0:
            return
        for team_id, buffs in self._attack_buffs_by_team.items():
            active: list[_TimedAttackBuff] = []
            for buff in buffs:
                buff.remaining = max(0.0, buff.remaining - dt)
                if buff.remaining > 1e-9:
                    active.append(buff)
            self._attack_buffs_by_team[team_id] = active

    def _advance_energy_mechanism_buffs(self, dt: float) -> None:
        if dt <= 0:
            return
        for team_id, buffs in self._energy_mechanism_buffs_by_team.items():
            active: list[_TimedEnergyMechanismBuff] = []
            for buff in buffs:
                buff.remaining = max(0.0, buff.remaining - dt)
                if buff.remaining > 1e-9:
                    active.append(buff)
            self._energy_mechanism_buffs_by_team[team_id] = active

    def _advance_radar_double_vulnerability(self, dt: float) -> None:
        if dt <= 0:
            return
        for state in self._radar_double_vulnerability_by_team.values():
            if state.remaining <= 0:
                continue
            state.remaining = max(0.0, state.remaining - dt)
            if state.remaining <= 1e-9:
                state.remaining = 0.0

    def _advance_radar_anti_drone(self, dt: float) -> None:
        if dt <= 0:
            return

        for robot_id, state in self._radar_anti_drone_by_robot.items():
            if state.lock_remaining > 0:
                state.lock_remaining = max(0.0, state.lock_remaining - dt)
                if state.lock_remaining <= 1e-9:
                    state.lock_remaining = 0.0

            if state.activations >= self._radar_anti_drone_max_locks:
                state.progress = 0.0
                state.continuous_elapsed = 0.0
                state.consecutive_ticks = 0
                state.illuminated_by_team_id = None
                continue

            drone = self._robots_by_id[robot_id]
            illuminated = (
                state.illuminated_by_team_id is not None
                and state.illuminated_by_team_id != drone.team
                and self.drone_air_support_active(robot_id)
            )
            if not illuminated:
                state.illuminated_by_team_id = None
                state.continuous_elapsed = 0.0
                state.consecutive_ticks = 0
                state.progress = max(
                    0.0,
                    state.progress - self._radar_anti_drone_decay_per_second * dt,
                )
                continue

            state.continuous_elapsed += dt
            ticks = math.floor(
                state.continuous_elapsed / self._radar_anti_drone_detection_period
                + 1e-9
            )
            if ticks <= 0:
                continue
            state.continuous_elapsed = max(
                0.0,
                state.continuous_elapsed
                - ticks * self._radar_anti_drone_detection_period,
            )

            for _ in range(ticks):
                state.consecutive_ticks += 1
                state.progress = min(
                    self._radar_anti_drone_progress_max,
                    state.progress + state.consecutive_ticks,
                )
                if state.progress + 1e-9 < self._radar_anti_drone_threshold(state):
                    continue
                state.progress = 0.0
                state.activations += 1
                state.lock_remaining = self._radar_anti_drone_lock_duration
                if state.activations >= self._radar_anti_drone_max_locks:
                    state.continuous_elapsed = 0.0
                    state.consecutive_ticks = 0
                    state.illuminated_by_team_id = None
                    break

    def reset(self, match: "Match") -> None:
        expected_roster = {
            "hero": 1,
            "engineer": 1,
            "infantry": 2,
            "sentry": 1,
            "drone": 1,
        }
        for team in match.config.scenario.teams.values():
            actual_roster = {
                robot_type: sum(robot.type == robot_type for robot in team.robots)
                for robot_type in _RMUC_ROBOT_TYPES
            }
            if actual_roster != expected_roster:
                raise ConfigError(
                    f"{self._document.path}: 队伍 `{team.team_id}` 必须恰好包含 "
                    "1 hero、1 engineer、2 infantry、1 sentry、1 drone"
                )

        player_team = match.config.scenario.player_team
        player_definitions = next(
            team.robots
            for team in match.config.scenario.teams.values()
            if team.team_id == player_team
        )
        expected_player_controlled = {
            robot.id
            for robot in player_definitions
            if robot.type not in {"sentry", "drone"}
        }
        if match.config.scenario.player_controlled != expected_player_controlled:
            raise ConfigError(
                f"{self._document.path}: player_controlled 必须包含 player_team 的 "
                "hero、engineer、两台 infantry；sentry、drone 由 AI 控制"
            )

        team_by_side = {
            side: match.config.scenario.teams[side].team_id for side in ("red", "blue")
        }
        self.attack_damage_by_team = {
            team_id: 0 for team_id in team_by_side.values()
        }
        self._attack_buffs_by_team = {
            team_id: [] for team_id in team_by_side.values()
        }
        self._dart_system_by_team = {
            team_id: _DartSystemState() for team_id in team_by_side.values()
        }
        self._dart_effects_by_team = {
            team_id: _DartEffectsState() for team_id in team_by_side.values()
        }
        self._dart_detector_closed_until = {}
        self._field_buff_disabled_until_by_zone = {}
        self._current_time = match.elapsed_time
        self._energy_mechanism_buffs_by_team = {
            team_id: [] for team_id in team_by_side.values()
        }
        self._small_energy_mechanism_activation_times_by_team = {
            team_id: [] for team_id in team_by_side.values()
        }
        self._radar_vulnerability_by_robot = {}
        self._radar_double_vulnerability_by_team = {
            team_id: _RadarDoubleVulnerabilityState()
            for team_id in team_by_side.values()
        }
        self._radar_anti_drone_by_robot = {
            robot.id: _RadarAntiDroneState()
            for robot in match.robots
            if robot.type == "drone"
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
        self._assembly_invincibility_elapsed_by_engineer = {
            robot_id: 0.0 for robot_id in self._engineer_resources_by_id
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
        self._robot_lifecycle_by_robot = {
            robot.id: _RobotLifecycleState(
                disengaged_elapsed=self._disengaged_after
            )
            for robot in match.robots
            if robot.type != "drone"
        }
        self._drone_helipad_by_robot = {
            robot.id: robot.position
            for robot in match.robots
            if robot.type == "drone"
        }
        self._drone_air_support_by_robot = {
            robot.id: _DroneAirSupportState(
                available_seconds=self._drone_initial_free_air_support,
                next_grant_at=self._drone_periodic_grant_interval,
            )
            for robot in match.robots
            if robot.type == "drone"
        }
        for robot in match.robots:
            if robot.type == "drone":
                robot.alive = False
                robot.path.clear()
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
        self._chassis_power_by_robot = {
            robot.id: _ChassisPowerState(
                buffer_energy=self._effective_buffer_energy_max(robot.id)
            )
            for robot in match.robots
            if robot.type != "drone"
        }
        self._chassis_power_accumulator = 0.0
        self._current_synthetic_power_by_robot = {
            robot.id: self._chassis_stationary_power_demand
            for robot in match.robots
            if robot.type != "drone"
        }
        self._next_sentry_supply_grant = self._sentry_supply_interval
        self._progression_by_robot = {
            robot.id: _RobotProgressionState()
            for robot in match.robots
            if robot.type in _EXPERIENCE_ROBOT_TYPES
        }
        for robot_id in self._progression_by_robot:
            robot = self._robots_by_id[robot_id]
            if robot.type in _HP_PERFORMANCE_ROBOT_TYPES:
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
            | {
                zone_id
                for side_zones in self._field_zone_ids.values()
                for zone_id in side_zones.values()
            }
            | {
                zone_id
                for side_zones in self._terrain_zone_ids.values()
                for zone_ids in side_zones.values()
                for zone_id in zone_ids
            }
            | set(self._fortress_zone_ids.values())
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
        self._field_base_zone_by_team = {
            team_by_side[side]: zones_by_id[
                self._projectile_zone_ids[side]["base"]
            ]
            for side in ("red", "blue")
        }
        self._field_outpost_zone_by_team = {
            team_by_side[side]: zones_by_id[
                self._projectile_zone_ids[side]["outpost"]
            ]
            for side in ("red", "blue")
        }
        self._field_buff_disabled_until_by_zone = {
            zone.id: 0.0
            for zone in (
                *self._field_base_zone_by_team.values(),
                *self._field_outpost_zone_by_team.values(),
            )
        }
        self._field_trapezoid_zone_by_team = {
            team_by_side[side]: zones_by_id[
                self._field_zone_ids[side]["trapezoid"]
            ]
            for side in ("red", "blue")
        }
        self._field_central_zones = tuple(
            zones_by_id[self._field_zone_ids[side]["central"]]
            for side in ("red", "blue")
        )
        self._central_defense_state_by_zone = {
            zone.id: _CentralDefenseBuffState()
            for zone in self._field_central_zones
        }
        self._field_occupy_remaining = {}
        self._field_buff_elapsed = match.elapsed_time
        self._fortress_zone_by_team = {
            team_by_side[side]: zones_by_id[self._fortress_zone_ids[side]]
            for side in ("red", "blue")
        }
        self._fortress_state_by_team = {
            team_id: _FortressBuffState()
            for team_id in team_by_side.values()
        }
        self._fortress_reserved_by_robot = {
            robot.id: _FortressReservedProjectileState()
            for robot in match.robots
            if robot.type in self._fortress_eligible_types
            and self._projectile_by_type.get(robot.type)
            == self._fortress_reserve_projectile
        }
        team_ids = tuple(team_by_side.values())
        self._enemy_fortress_occupation = {
            (robot.id, fortress_team_id): _EnemyFortressOccupationState()
            for robot in match.robots
            if robot.type in self._enemy_fortress_eligible_types
            for fortress_team_id in team_ids
            if fortress_team_id != robot.team
        }
        self._enemy_fortress_death_retention_started = set()
        self._outposts_destroyed_this_frame = set()

        self._terrain_zones_by_side_and_type = {
            side: {
                terrain_type: tuple(
                    zones_by_id[zone_id]
                    for zone_id in self._terrain_zone_ids[side][terrain_type]
                )
                for terrain_type in (
                    "road",
                    "elevated_ground",
                    "launch_ramp",
                    "tunnel",
                )
            }
            for side in ("red", "blue")
        }
        self._terrain_zone_lookup = {
            zone.id: (side, terrain_type, index)
            for side, terrain_by_type in self._terrain_zones_by_side_and_type.items()
            for terrain_type, zones in terrain_by_type.items()
            for index, zone in enumerate(zones)
        }
        interrupt_zones = {
            zone.id: zone
            for terrain_by_type in self._terrain_zones_by_side_and_type.values()
            for zones in terrain_by_type.values()
            for zone in zones
        }
        for zone in self._field_base_zone_by_team.values():
            interrupt_zones[zone.id] = zone
        for zone in self._field_outpost_zone_by_team.values():
            interrupt_zones[zone.id] = zone
        for zone in self._field_trapezoid_zone_by_team.values():
            interrupt_zones[zone.id] = zone
        for zone in self._field_central_zones:
            interrupt_zones[zone.id] = zone
        for zone in self._supply_buff_zone_by_team.values():
            interrupt_zones[zone.id] = zone
        for zone in self._assembly_zone_by_team.values():
            interrupt_zones[zone.id] = zone
        for zone in self._fortress_zone_by_team.values():
            interrupt_zones[zone.id] = zone
        self._terrain_interrupt_zones_by_id = interrupt_zones
        self._terrain_crossing_by_robot = {
            robot.id: _TerrainCrossingState()
            for robot in match.robots
            if robot.type != "drone"
        }

    def _consume_drone_air_support_time(
        self,
        drone: Robot,
        state: _DroneAirSupportState,
        duration: float,
    ) -> None:
        remaining = max(0.0, duration)
        while state.active and remaining > 1e-9:
            if (
                state.available_seconds <= 1e-9
                and not self._purchase_drone_air_support_second(drone, state)
            ):
                state.available_seconds = 0.0
                self.pause_drone_air_support(drone)
                return
            consumed = min(remaining, state.available_seconds)
            state.available_seconds -= consumed
            remaining -= consumed
            if state.available_seconds <= 1e-9:
                state.available_seconds = 0.0

    def _advance_drone_air_support(
        self,
        match: "Match",
        dt: float,
    ) -> None:
        settlement_end = min(match.elapsed_time, self._time_limit)
        settlement_start = max(0.0, settlement_end - max(0.0, dt))
        for robot_id, state in self._drone_air_support_by_robot.items():
            drone = self._robots_by_id[robot_id]
            cursor = settlement_start
            while cursor < settlement_end - 1e-9:
                segment_end = min(settlement_end, state.next_grant_at)
                if state.active and segment_end > cursor:
                    self._consume_drone_air_support_time(
                        drone,
                        state,
                        segment_end - cursor,
                    )
                cursor = segment_end
                if (
                    state.next_grant_at <= cursor + 1e-9
                    and state.next_grant_at < self._time_limit - 1e-9
                ):
                    state.available_seconds += self._drone_periodic_grant
                    state.next_grant_at += self._drone_periodic_grant_interval

            while (
                state.next_grant_at <= settlement_end + 1e-9
                and state.next_grant_at < self._time_limit - 1e-9
            ):
                state.available_seconds += self._drone_periodic_grant
                state.next_grant_at += self._drone_periodic_grant_interval

            if (
                state.active
                and state.available_seconds <= 1e-9
                and settlement_end < self._time_limit - 1e-9
                and not self._purchase_drone_air_support_second(drone, state)
            ):
                self.pause_drone_air_support(drone)

    def update(self, match: "Match", dt: float) -> None:
        self._current_time = match.elapsed_time
        newly_destroyed = self._consume_events(match)
        frame_start = match.elapsed_time - dt
        active_dt = max(
            0.0, min(dt, self._time_limit - frame_start)
        )
        self._advance_drone_air_support(match, active_dt)
        newly_respawned = self._advance_robot_lifecycles(
            match, active_dt, newly_destroyed
        )
        self._advance_supply_healing(
            match, active_dt, frame_start, newly_respawned
        )
        self._advance_remote_healing(match)
        self._advance_out_of_combat(active_dt, newly_respawned)

        self._advance_enemy_fortress_occupation(match, dt)
        self._sync_initialized_fortress_reserves()
        self._advance_projectile_allowance(match, dt)
        self._advance_tech_core_attempts(match, dt)
        self._advance_d4(match, dt)
        self._advance_economy(match)

        active_rebuild_dt = max(
            0.0, min(dt, self._rebuild_cutoff - frame_start)
        )
        if active_rebuild_dt > 0:
            self._advance_rebuild(match, active_rebuild_dt)

        if match.elapsed_time >= self._rebuild_cutoff - 1e-9:
            for state in self._team_states.values():
                state.rebuild_progress_by_robot.clear()

    def _respawn_progress_required(
        self,
        event_time: float,
        immediate_respawn_count: int,
    ) -> int:
        elapsed = min(self._time_limit, max(0.0, event_time))
        raw_required = (
            self._respawn_base_progress_required
            + elapsed / self._respawn_elapsed_seconds_per_progress
            + immediate_respawn_count * self._respawn_immediate_progress_penalty
        )
        return int(math.floor(raw_required + 0.5))

    def _settle_respawn(
        self,
        robot: Robot,
        state: _RobotLifecycleState,
        *,
        hp_fraction: float,
        invincibility_duration: float,
        weak: bool,
        minimum_invincibility: float,
        immediate_power_boost_duration: float = 0.0,
    ) -> None:
        robot.alive = True
        robot.hp = min(
            robot.max_hp,
            max(
                1,
                int(math.floor(robot.max_hp * hp_fraction + 0.5)),
            ),
        )
        robot.path.clear()
        state.respawn_progress = 0.0
        state.respawn_required = None
        state.weak = weak
        state.invincible_remaining = invincibility_duration
        state.minimum_invincible_remaining = minimum_invincibility
        state.immediate_power_boost_remaining = immediate_power_boost_duration
        state.disengaged_elapsed = 0.0
        state.combat_activity_this_frame = False
        state.healing_rounding_residual = 0.0

    def immediate_respawn_cost(self, match: "Match", robot: Robot) -> int:
        if self._robots_by_id.get(robot.id) is not robot:
            raise KeyError(robot.id)
        elapsed = min(self._time_limit, max(0.0, match.elapsed_time))
        elapsed_steps = math.ceil(
            elapsed / self._immediate_respawn_elapsed_interval
        )
        return (
            elapsed_steps * self._immediate_respawn_elapsed_step_coins
            + self._robot_level(robot.id) * self._immediate_respawn_level_coins
        )

    def purchase_immediate_respawn(self, match: "Match", robot: Robot) -> bool:
        state = self._robot_lifecycle_by_robot.get(robot.id)
        economy = self._economy_by_team.get(robot.team)
        if (            match.finished
            or robot.alive
            or self._robots_by_id.get(robot.id) is not robot
            or state is None
            or economy is None
            or state.respawn_required is None
        ):
            return False

        cost = self.immediate_respawn_cost(match, robot)
        if economy.coins < cost:
            return False

        economy.coins -= cost
        state.immediate_respawn_count += 1
        self._settle_respawn(
            robot,
            state,
            hp_fraction=self._immediate_respawn_hp_fraction,
            invincibility_duration=self._immediate_respawn_invincibility_duration,
            weak=False,
            minimum_invincibility=0.0,
            immediate_power_boost_duration=self._immediate_respawn_power_duration,
        )
        return True

    def _weak_release_zone_detected(self, robot: Robot) -> bool:
        own_supply = self._supply_buff_zone_by_team.get(robot.team)
        own_base = self._field_base_zone_by_team.get(robot.team)
        if (
            own_supply is not None
            and own_supply.contains(robot.position)
        ) or (
            own_base is not None
            and own_base.contains(robot.position)
        ):
            return True

        return any(
            self._outpost_buff_eligible(robot, point_team)
            and zone.contains(robot.position)
            for point_team, zone in self._field_outpost_zone_by_team.items()
        )

    def _release_weak_if_detected(
        self,
        robot: Robot,
        state: _RobotLifecycleState,
    ) -> None:
        if not state.weak or not self._weak_release_zone_detected(robot):
            return
        state.weak = False
        state.invincible_remaining = min(
            state.invincible_remaining,
            state.minimum_invincible_remaining,
        )

    def _advance_robot_lifecycles(
        self,
        match: "Match",
        dt: float,
        newly_destroyed: set[str],
    ) -> set[str]:
        newly_respawned: set[str] = set()
        for robot in match.robots:
            state = self._robot_lifecycle_by_robot.get(robot.id)
            if state is None:
                continue
            if not robot.alive:
                state.disengaged_elapsed = 0.0
                state.healing_rounding_residual = 0.0
                if robot.id in newly_destroyed or state.respawn_required is None:
                    continue

                supply_zone = self._supply_buff_zone_by_team[robot.team]
                base = self._base_by_team[robot.team]
                accelerated = (
                    supply_zone.contains(robot.position)
                    or base.hp < self._respawn_accelerated_base_hp_below
                )
                rate = (
                    self._respawn_accelerated_progress_per_second
                    if accelerated
                    else self._respawn_progress_per_second
                )
                state.respawn_progress += dt * rate
                if state.respawn_progress + 1e-9 < state.respawn_required:
                    continue

                self._settle_respawn(
                    robot,
                    state,
                    hp_fraction=self._respawn_hp_fraction,
                    invincibility_duration=self._respawn_invincibility_duration,
                    weak=True,
                    minimum_invincibility=self._weak_release_min_invincibility,
                )
                self._release_weak_if_detected(robot, state)
                newly_respawned.add(robot.id)
                continue

            state.invincible_remaining = max(
                0.0, state.invincible_remaining - dt
            )
            if state.invincible_remaining <= 1e-9:
                state.invincible_remaining = 0.0
            state.minimum_invincible_remaining = max(
                0.0, state.minimum_invincible_remaining - dt
            )
            if state.minimum_invincible_remaining <= 1e-9:
                state.minimum_invincible_remaining = 0.0
            state.immediate_power_boost_remaining = max(
                0.0, state.immediate_power_boost_remaining - dt
            )
            if state.immediate_power_boost_remaining <= 1e-9:
                state.immediate_power_boost_remaining = 0.0
            self._release_weak_if_detected(robot, state)

        return newly_respawned

    def _advance_supply_healing(
        self,
        match: "Match",
        dt: float,
        frame_start: float,
        newly_respawned: set[str],
    ) -> None:
        if dt <= 0:
            return

        for robot in match.robots:
            state = self._robot_lifecycle_by_robot.get(robot.id)
            if state is None:
                continue
            supply_zone = self._supply_buff_zone_by_team[robot.team]
            if (
                robot.id in newly_respawned
                or not robot.alive
                or state.weak
                or not supply_zone.contains(robot.position)
                or robot.hp >= robot.max_hp
            ):
                state.healing_rounding_residual = 0.0
                continue

            enhanced_dt = 0.0
            if not state.combat_activity_this_frame:
                enhanced_start_offset = max(
                    0.0,
                    self._resupply_enhanced_after - frame_start,
                    self._disengaged_after - state.disengaged_elapsed,
                )
                enhanced_dt = max(
                    0.0,
                    dt - min(dt, enhanced_start_offset),
                )

            healing_fraction = (
                dt * self._resupply_heal_fraction_per_second
                + enhanced_dt
                * (
                    self._resupply_enhanced_heal_fraction_per_second
                    - self._resupply_heal_fraction_per_second
                )
            )
            state.healing_rounding_residual += robot.max_hp * healing_fraction
            healing_points = max(
                0,
                math.floor(state.healing_rounding_residual + 0.5 + 1e-9),
            )
            if healing_points <= 0:
                continue

            robot.hp = min(robot.max_hp, robot.hp + healing_points)
            if robot.hp >= robot.max_hp:
                state.healing_rounding_residual = 0.0
            else:
                state.healing_rounding_residual -= healing_points

    def _advance_remote_healing(self, match: "Match") -> None:
        settlement_end = min(match.elapsed_time, self._time_limit)
        for robot_id, state in self._robot_lifecycle_by_robot.items():
            effective_at = state.pending_remote_healing_effective_at
            if effective_at is None or effective_at > settlement_end + 1e-9:
                continue

            robot = self._robots_by_id[robot_id]
            if robot.alive and effective_at < self._time_limit - 1e-9:
                healing_points = int(
                    math.floor(
                        robot.max_hp * self._remote_healing_hp_fraction
                        + 0.5
                    )
                )
                robot.hp = min(robot.max_hp, robot.hp + healing_points)
            state.pending_remote_healing_effective_at = None

    def _advance_out_of_combat(
        self,
        dt: float,
        newly_respawned: set[str],
    ) -> None:
        for robot_id, state in self._robot_lifecycle_by_robot.items():
            robot = self._robots_by_id[robot_id]
            if robot_id in newly_respawned or state.combat_activity_this_frame:
                state.disengaged_elapsed = 0.0
            elif robot.alive:
                state.disengaged_elapsed += max(0.0, dt)
            else:
                state.disengaged_elapsed = 0.0
            state.combat_activity_this_frame = False

    def _advance_projectile_allowance(
        self,
        match: "Match",
        dt: float,
    ) -> None:
        settlement_end = min(match.elapsed_time, self._time_limit)

        for robot_id, state in self._projectile_allowance_by_robot.items():
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
                or self._is_weak(sentry)
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

    def _effective_buffer_energy_max(self, robot_id: str) -> float:
        if robot_id not in self._robots_by_id:
            raise KeyError(robot_id)
        return self._chassis_buffer_energy_max

    def _effective_chassis_power_limit(self, robot_id: str) -> float:
        robot_type = self._robot_types_by_id[robot_id]
        if robot_type in _EXPERIENCE_ROBOT_TYPES:
            base_limit = float(
                self._effective_performance(robot_id).chassis_power_limit
            )
        else:
            base_limit = float(self._chassis_power_limit_by_type[robot_type])

        lifecycle = self._robot_lifecycle_by_robot.get(robot_id)
        if (
            lifecycle is not None
            and lifecycle.immediate_power_boost_remaining > 0
        ):
            return min(
                float(self._immediate_respawn_power_cap),
                base_limit * self._immediate_respawn_power_multiplier,
            )
        return base_limit

    def _synthetic_chassis_power(
        self,
        robot: Robot,
        state: _ChassisPowerState,
    ) -> float:
        if not robot.alive or state.power_off_remaining > 0:
            return self._chassis_stationary_power_demand
        if robot.path:
            return (
                self._effective_chassis_power_limit(robot.id)
                + self._chassis_moving_over_limit
            )
        return self._chassis_stationary_power_demand

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
            base_cooling_per_second = float(performance.cooling_per_second)
        elif robot_type == "sentry":
            heat_limit = self._sentry_heat_limit
            base_cooling_per_second = self._sentry_cooling_per_second
        else:
            raise KeyError(robot_id)

        cooling_candidates = [base_cooling_per_second]
        robot = self._robots_by_id[robot_id]
        fortress_bonus = self._fortress_cooling_bonus(robot)
        if fortress_bonus > 0:
            cooling_candidates.append(base_cooling_per_second + fortress_bonus)

        terrain_state = self._terrain_crossing_by_robot.get(robot_id)
        if (
            terrain_state is not None
            and not self._energy_and_terrain_buffs_suppressed(robot.team)
            and terrain_state.tunnel_cooling_remaining > 0
        ):
            cooling_candidates.append(
                base_cooling_per_second
                * self._terrain_rules["tunnel"].cooling_multiplier
            )

        energy_multiplier = self._current_large_energy_mechanism_cooling_multiplier(
            robot.team
        )
        if energy_multiplier > 1.0:
            cooling_candidates.append(base_cooling_per_second * energy_multiplier)

        cooling_per_second = max(cooling_candidates)

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
        if robot_type == "drone":
            row = self._drone_performance[level]
            # HP/chassis power are not applicable to Drone in V1.4.0.
            # The values stay internal sentinels and are never exposed as rules.
            return _EffectivePerformance(
                max_hp=1,
                chassis_power_limit=0,
                heat_limit=row["heat_limit"],
                cooling_per_second=row["cooling_per_second"],
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
        experience_before = state.experience
        base_awarded = min(
            cap_experience - experience_before,
            float(amount),
        )
        experience_after_base = experience_before + base_awarded
        small_energy_buff = None
        if robot.type in _EXPERIENCE_ROBOT_TYPES:
            small_energy_buff = next(
                (
                    buff
                    for buff in self._energy_mechanism_buffs_by_team.get(
                        robot.team, ()
                    )
                    if (
                        buff.mechanism == "small"
                        and buff.remaining > 0
                        and buff.experience_bonus_remaining > 1e-9
                    )
                ),
                None,
            )
        bonus_awarded = 0.0
        if (
            small_energy_buff is not None
            and not self._energy_and_terrain_buffs_suppressed(robot.team)
        ):
            bonus_awarded = min(
                base_awarded,
                small_energy_buff.experience_bonus_remaining,
                cap_experience - experience_after_base,
            )
            small_energy_buff.experience_bonus_remaining = max(
                0.0,
                small_energy_buff.experience_bonus_remaining - bonus_awarded,
            )
        state.experience = experience_after_base + bonus_awarded
        state.level = max(
            level
            for level, threshold in self._level_thresholds.items()
            if level <= level_cap and threshold <= state.experience + 1e-9
        )
        if state.level == old_level:
            return

        performance = self._effective_performance(robot_id)
        if robot.type in _HP_PERFORMANCE_ROBOT_TYPES:
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
            not event.award_experience
            or event.attacker_id not in self._progression_by_robot
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

    def _consume_events(self, match: "Match") -> set[str]:
        newly_destroyed: set[str] = set()
        self._enemy_fortress_death_retention_started.clear()
        self._outposts_destroyed_this_frame.clear()
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
                is_enemy_damage
                and event.award_experience
                and event.attacker_id in self._progression_by_robot
            )
            if event.type == MatchEventType.ROBOT_DAMAGED:
                lifecycle = self._robot_lifecycle_by_robot.get(event.robot_id)
                if lifecycle is not None:
                    lifecycle.disengaged_elapsed = 0.0
                    lifecycle.combat_activity_this_frame = True
                if known_experience_source:
                    self._grant_experience(
                        event.attacker_id,
                        event.damage * self._robot_damage_experience_per_hp,
                    )
                continue

            if event.type == MatchEventType.ROBOT_DESTROYED:
                self._grant_kill_experience(event)
                lifecycle = self._robot_lifecycle_by_robot.get(event.robot_id)
                if lifecycle is not None:
                    lifecycle.disengaged_elapsed = 0.0
                    lifecycle.combat_activity_this_frame = False
                    lifecycle.respawn_progress = 0.0
                    lifecycle.respawn_required = self._respawn_progress_required(
                        event.time,
                        lifecycle.immediate_respawn_count,
                    )
                    lifecycle.weak = False
                    lifecycle.invincible_remaining = 0.0
                    lifecycle.minimum_invincible_remaining = 0.0
                    lifecycle.immediate_power_boost_remaining = 0.0
                    lifecycle.pending_remote_healing_effective_at = None
                    lifecycle.healing_rounding_residual = 0.0
                    newly_destroyed.add(event.robot_id)
                for key, occupation in self._enemy_fortress_occupation.items():
                    if key[0] != event.robot_id:
                        continue
                    if (
                        occupation.occupy_remaining > 0
                        or occupation.occupation_elapsed > 0
                        or occupation.retention_remaining > 0
                    ):
                        occupation.occupy_remaining = 0.0
                        occupation.retention_remaining = (
                            self._enemy_fortress_retention
                        )
                        self._enemy_fortress_death_retention_started.add(
                            key
                        )
                fortress_state = self._fortress_state_by_team.get(event.team_id)
                if (
                    fortress_state is not None
                    and fortress_state.owner_robot_id == event.robot_id
                ):
                    fortress_state.owner_robot_id = None
                    fortress_state.release_remaining = 0.0
                terrain = self._terrain_crossing_by_robot.get(event.robot_id)
                if terrain is not None:
                    terrain.standard_defense = 0.0
                    terrain.standard_defense_remaining = 0.0
                    terrain.tunnel_defense_remaining = 0.0
                    terrain.tunnel_cooling_remaining = 0.0
                    terrain.occupied_rfid_zone_ids.clear()
                    self._reset_terrain_sequence(terrain)
                shooting_heat = self._shooting_heat_by_robot.get(event.robot_id)
                if shooting_heat is not None:
                    shooting_heat.heat = 0.0
                    shooting_heat.temporarily_locked = False
                chassis = self._chassis_power_by_robot.get(event.robot_id)
                if chassis is not None:
                    chassis.buffer_energy = self._effective_buffer_energy_max(
                        event.robot_id
                    )
                    chassis.power_off_remaining = 0.0
                    chassis.blocked_this_frame = False
                    self._current_synthetic_power_by_robot[event.robot_id] = (
                        self._chassis_stationary_power_demand
                    )
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
                self._outposts_destroyed_this_frame.add(structure.team)

        return newly_destroyed

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
            if (
                not self._is_weak(engineer)
                and assembly_zone.contains(engineer.position)
            ):
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
        if (
            not self._is_weak(engineer)
            and assembly_zone.contains(engineer.position)
        ):
            attempt.outside_zone_elapsed = 0.0
        else:
            outside_before = attempt.outside_zone_elapsed
            attempt.outside_zone_elapsed += max(0.0, dt)
            if (                attempt.outside_zone_elapsed + 1e-9
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
                and not self._is_weak(robot)
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
                robot.hp
                for robot in match.robots
                if robot.team == team_id and robot.type != "drone"
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
