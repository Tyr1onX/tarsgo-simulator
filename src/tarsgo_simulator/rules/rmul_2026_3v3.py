"""Partial RMUL 2026 rules for VP, lifecycle, economy, heat, and chassis buffer."""

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, Any, Mapping

from tarsgo_simulator.core.config import ConfigError, RuleDocument
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.map import Zone
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.rules.protocol import (
    MatchResult,
    RobotParameters,
    RuleSetDisplayState,
)


_RMUL_ROBOT_TYPES = ("hero", "infantry", "sentry")


@dataclass
class _RobotLifecycle:
    death_count: int = 0
    respawn_progress: float = 0.0
    respawn_required: float | None = None
    weak: bool = False
    invincible_remaining: float = 0.0
    healing_hp_fraction: float = 0.0


@dataclass
class _RobotPenaltyState:
    forbidden_elapsed: float = 0.0
    next_yellow_at: float = 0.0
    yellow_cards: int = 0
    last_yellow_time: float | None = None
    last_yellow_fraction: float = 0.0
    disqualified: bool = False


@dataclass(frozen=True)
class _AllowedProjectileRule:
    projectile: str
    initial: int
    exchangeable: bool
    exchange_cost: int | None = None
    exchange_amount: int | None = None


@dataclass(frozen=True)
class _ShootingHeatRule:
    heat_limit: float
    cooling_per_second: float
    projectile_heat: float
    permanent_lock_extra: float


@dataclass
class _RobotShootingState:
    heat: float = 0.0
    heat_locked: bool = False
    permanently_locked: bool = False


@dataclass(frozen=True)
class _ChassisPowerRule:
    power_limit: float
    moving_power_demand: float


@dataclass
class _RobotChassisState:
    buffer_energy: float
    power_off_remaining: float = 0.0
    blocked_this_frame: bool = False


class RMUL2026Rules:
    def __init__(self, document: RuleDocument) -> None:
        if document.metadata.status != "official-partial":
            raise ConfigError(
                f"{document.path}: rmul-2026-3v3 requires `status: official-partial`"
            )
        if document.metadata.official_version != "1.2.0":
            raise ConfigError(
                f"{document.path}: this implementation is verified against manual V1.2.0"
            )

        self._document = document
        self._time_limit = _number(document.data, "match_duration", document)
        economy = _mapping(document.data, "economy", document)
        self._timed_coin_grants = _parse_timed_coin_grants(
            economy, document, self._time_limit
        )
        self._vp_gap_coin_grants = _parse_vp_gap_coin_grants(economy, document)
        self._allowed_projectile_rules = _parse_allowed_projectiles(document)
        (
            self._heat_cooling_hz,
            self._shooting_heat_rules,
            self._lab_infantry_launcher_profile,
        ) = _parse_shooting_heat(document, self._allowed_projectile_rules)
        (
            self._chassis_power_detection_hz,
            self._buffer_energy_max,
            self._power_off_duration,
            self._chassis_power_rules,
            self._lab_infantry_chassis_profile,
            self._stationary_power_demand,
        ) = _parse_chassis_power(document)
        victory_points = _mapping(document.data, "victory_points", document)
        self._initial_victory_points = _integer(
            victory_points, "initial", document, "victory_points.initial"
        )
        self._control_drain_per_second = _integer(
            victory_points,
            "control_drain_per_second",
            document,
            "victory_points.control_drain_per_second",
        )
        self._robot_destroyed_penalty = _integer(
            victory_points,
            "robot_destroyed_penalty",
            document,
            "victory_points.robot_destroyed_penalty",
        )
        control_zone = _mapping(document.data, "control_zone", document)
        self._control_zone_id = _string(control_zone, "id", document, "control_zone.id")
        self._control_loss_delay = _number(
            control_zone, "loss_delay", document, "control_zone.loss_delay"
        )

        respawn = _mapping(document.data, "respawn", document)
        self._initial_respawn_progress = _number(
            respawn,
            "initial_progress_required",
            document,
            "respawn.initial_progress_required",
        )
        self._additional_respawn_progress_per_death = _number(
            respawn,
            "additional_progress_per_death",
            document,
            "respawn.additional_progress_per_death",
        )
        self._respawn_progress_per_second = _number(
            respawn,
            "progress_per_second",
            document,
            "respawn.progress_per_second",
        )
        self._respawn_hp_fraction = _fraction(
            respawn, "hp_fraction", document, "respawn.hp_fraction"
        )
        self._invincibility_duration = _number(
            respawn,
            "invincibility_duration",
            document,
            "respawn.invincibility_duration",
        )
        supply = _mapping(document.data, "supply", document)
        self._supply_heal_fraction_per_second = _fraction(
            supply,
            "heal_fraction_per_second",
            document,
            "supply.heal_fraction_per_second",
        )
        supply_zones = _mapping(document.data, "supply_zones", document)
        self._supply_zone_ids = {
            side: _string(supply_zones, side, document, f"supply_zones.{side}")
            for side in ("red", "blue")
        }
        if len(set(self._supply_zone_ids.values())) != 2:
            raise ConfigError(f"{document.path}: red / blue 补给区必须使用不同的 zone id")

        penalties = _mapping(document.data, "penalties", document)
        forbidden_zone = _mapping(
            penalties, "supply_forbidden_zone", document
        )
        self._first_yellow_after = _number(
            forbidden_zone,
            "first_yellow_after",
            document,
            "penalties.supply_forbidden_zone.first_yellow_after",
        )
        self._repeat_yellow_interval = _number(
            forbidden_zone,
            "repeat_yellow_interval",
            document,
            "penalties.supply_forbidden_zone.repeat_yellow_interval",
        )
        yellow_card = _mapping(penalties, "yellow_card", document)
        self._offender_hp_fraction = _fraction(
            yellow_card,
            "offender_hp_fraction",
            document,
            "penalties.yellow_card.offender_hp_fraction",
        )
        self._teammate_hp_fraction = _fraction(
            yellow_card,
            "teammate_hp_fraction",
            document,
            "penalties.yellow_card.teammate_hp_fraction",
        )
        self._yellow_repeat_window = _number(
            yellow_card,
            "repeat_window",
            document,
            "penalties.yellow_card.repeat_window",
        )
        self._yellow_repeat_multiplier = _integer(
            yellow_card,
            "repeat_multiplier",
            document,
            "penalties.yellow_card.repeat_multiplier",
        )
        self._red_after_yellows = _integer(
            yellow_card,
            "red_after_count",
            document,
            "penalties.yellow_card.red_after_count",
        )

        lab_parameters = _mapping(
            document.data, "lab_robot_parameters", document
        )
        common = _mapping(lab_parameters, "common", document)
        common_values = {
            "move_speed": _number(
                common, "move_speed", document, "lab_robot_parameters.common.move_speed"
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
            "damage": _integer(
                common, "damage", document, "lab_robot_parameters.common.damage"
            ),
        }
        expected_parameter_keys = {"common", *_RMUL_ROBOT_TYPES}
        if set(lab_parameters) != expected_parameter_keys:
            raise ConfigError(
                f"{document.path}: `lab_robot_parameters` 必须只包含 common、hero、infantry、sentry"
            )
        self._lab_parameters: dict[str, RobotParameters] = {}
        for robot_type in _RMUL_ROBOT_TYPES:
            type_data = _mapping(lab_parameters, robot_type, document)
            self._lab_parameters[robot_type] = RobotParameters(
                max_hp=_integer(
                    type_data,
                    "max_hp",
                    document,
                    f"lab_robot_parameters.{robot_type}.max_hp",
                ),
                **common_values,
            )
        self._lab_infantry_profile = _string(
            document.data, "lab_infantry_profile", document, "lab_infantry_profile"
        )

        self.victory_points: dict[str, int] = {}
        self.control_owner: str | None = None
        self._control_loss_elapsed = 0.0
        self._control_tick_accumulator = 0.0
        self._previous_zone_teams: set[str] = set()
        self._robot_lifecycles: dict[str, _RobotLifecycle] = {}
        self._supply_zones: dict[str, Zone] = {}
        self._forbidden_zones: dict[str, Zone] = {}
        self._opposing_team: dict[str, str] = {}
        self._robot_penalties: dict[str, _RobotPenaltyState] = {}
        self.coins_by_team: dict[str, int] = {}
        self.allowed_projectiles_by_robot: dict[str, int] = {}
        self._robot_shooting_states: dict[str, _RobotShootingState] = {}
        self._heat_cooling_accumulator = 0.0
        self._robot_chassis_states: dict[str, _RobotChassisState] = {}
        self._chassis_power_accumulator = 0.0
        self._current_synthetic_power_by_robot: dict[str, float] = {}
        self._granted_timed_coin_events: set[int] = set()
        self._granted_vp_gap_thresholds: set[int] = set()

    @property
    def time_limit(self) -> float:
        return self._time_limit

    @property
    def display_state(self) -> RuleSetDisplayState:
        robot_statuses = []
        for robot_id, lifecycle in sorted(self._robot_lifecycles.items()):
            penalty = self._robot_penalties[robot_id]
            parts = []
            if penalty.disqualified:
                parts.append("RED")
            elif penalty.yellow_cards:
                parts.append(f"Y{penalty.yellow_cards}")
            if not penalty.disqualified and penalty.forbidden_elapsed > 0:
                parts.append(f"FORB {penalty.forbidden_elapsed:.1f}s")
            if lifecycle.respawn_required is not None:
                parts.append(
                    f"RESP {lifecycle.respawn_progress:.1f}/"
                    f"{lifecycle.respawn_required:g}"
                )
            elif lifecycle.weak and lifecycle.invincible_remaining > 0:
                parts.append(f"WEAK INV {math.ceil(lifecycle.invincible_remaining)}s")
            elif lifecycle.weak:
                parts.append("WEAK")
            elif lifecycle.invincible_remaining > 0:
                parts.append(f"INV {math.ceil(lifecycle.invincible_remaining)}s")
            if not parts:
                continue
            robot_statuses.append((robot_id, " ".join(parts)))
        return RuleSetDisplayState(
            victory_points=tuple(sorted(self.victory_points.items())),
            control_owner=self.control_owner,
            robot_statuses=tuple(robot_statuses),
            attack_damage=tuple(sorted(self.attack_damage_by_team.items())),
            coins=tuple(sorted(self.coins_by_team.items())),
            robot_projectiles=tuple(
                (
                    robot_id,
                    self._allowed_projectile_rules[robot_type].projectile,
                    self.allowed_projectiles_by_robot[robot_id],
                )
                for robot_id, robot_type in sorted(self._robot_types_by_id.items())
            ),
            robot_shooting_heat=tuple(
                (
                    robot_id,
                    self._robot_shooting_states[robot_id].heat,
                    self._shooting_heat_rules[robot_type].heat_limit,
                    self._robot_shooting_states[robot_id].heat_locked,
                    self._robot_shooting_states[robot_id].permanently_locked,
                )
                for robot_id, robot_type in sorted(self._robot_types_by_id.items())
            ),
            robot_chassis_power=tuple(
                (
                    robot_id,
                    self._robot_chassis_states[robot_id].buffer_energy,
                    self._buffer_energy_max,
                    self._current_synthetic_power_by_robot.get(robot_id, 0.0),
                    self._chassis_power_rules[robot_type].power_limit,
                    self._robot_chassis_states[robot_id].power_off_remaining,
                )
                for robot_id, robot_type in sorted(self._robot_types_by_id.items())
            ),
        )

    def robot_parameters(self, robot_type: str) -> RobotParameters:
        """Return the explicit rules-lab parameters for a supported robot type."""
        try:
            return self._lab_parameters[robot_type]
        except KeyError as exc:
            raise ConfigError(
                f"{self._document.path}: rmul-2026-3v3 不支持机器人类型 `{robot_type}`"
            ) from exc

    def can_move(self, robot: Robot) -> bool:
        state = self._robot_chassis_states.get(robot.id)
        return robot.alive and (
            state is None
            or not state.blocked_this_frame
            and state.power_off_remaining <= 0
        )

    def can_attack(self, robot: Robot) -> bool:
        lifecycle = self._robot_lifecycles.get(robot.id)
        penalty = self._robot_penalties.get(robot.id)
        shooting = self._robot_shooting_states.get(robot.id)
        return (
            robot.alive
            and self.allowed_projectiles_by_robot.get(robot.id, 0) > 0
            and (lifecycle is None or not lifecycle.weak)
            and (penalty is None or not penalty.disqualified)
            and (
                shooting is None
                or not shooting.heat_locked
                and not shooting.permanently_locked
            )
        )

    def on_attack_committed(self, robot: Robot) -> None:
        shooting = self._robot_shooting_states.get(robot.id)
        projectile_rule = self._allowed_projectile_rules.get(robot.type)
        if (
            robot.id not in self.allowed_projectiles_by_robot
            or shooting is None
            or projectile_rule is None
        ):
            return

        self.allowed_projectiles_by_robot[robot.id] = max(
            0, self.allowed_projectiles_by_robot[robot.id] - 1
        )
        heat_rule = self._shooting_heat_rules[robot.type]
        shooting.heat += heat_rule.projectile_heat
        permanent_threshold = heat_rule.heat_limit + heat_rule.permanent_lock_extra
        if shooting.heat >= permanent_threshold:
            shooting.permanently_locked = True
            shooting.heat_locked = False
        elif shooting.heat > heat_rule.heat_limit:
            shooting.heat_locked = True

    def exchange_projectiles(self, match: "Match", robot: Robot) -> bool:
        rule = self._allowed_projectile_rules.get(robot.type)
        penalty = self._robot_penalties.get(robot.id)
        supply_zone = self._supply_zones.get(robot.team)
        if (
            match.finished
            or rule is None
            or not rule.exchangeable
            or rule.exchange_cost is None
            or rule.exchange_amount is None
            or not robot.alive
            or penalty is None
            or penalty.disqualified
            or supply_zone is None
            or not supply_zone.contains(robot.position)
            or self.coins_by_team.get(robot.team, 0) < rule.exchange_cost
            or robot.id not in self.allowed_projectiles_by_robot
        ):
            return False

        self.coins_by_team[robot.team] -= rule.exchange_cost
        self.allowed_projectiles_by_robot[robot.id] += rule.exchange_amount
        return True

    def can_receive_damage(self, robot: Robot) -> bool:
        lifecycle = self._robot_lifecycles.get(robot.id)
        return robot.alive and (
            lifecycle is None or lifecycle.invincible_remaining <= 0
        )

    def prepare_movement(self, match: "Match", dt: float) -> None:
        """Advance quantized chassis buffer state before movement."""
        for robot in match.robots:
            state = self._robot_chassis_states[robot.id]
            state.blocked_this_frame = state.power_off_remaining > 0
            self._current_synthetic_power_by_robot[robot.id] = (
                self._synthetic_power_demand(robot, state)
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
            for robot in match.robots:
                state = self._robot_chassis_states[robot.id]
                rule = self._chassis_power_rules[robot.type]
                was_powered_off = state.power_off_remaining > 0
                if was_powered_off:
                    state.blocked_this_frame = True
                    power = self._stationary_power_demand
                else:
                    power = self._synthetic_power_demand(robot, state)

                state.buffer_energy -= (power - rule.power_limit) * tick_duration
                state.buffer_energy = min(
                    self._buffer_energy_max, state.buffer_energy
                )
                if state.buffer_energy <= 0:
                    state.buffer_energy = 0.0
                    if not was_powered_off and power > rule.power_limit:
                        state.power_off_remaining = self._power_off_duration
                        state.blocked_this_frame = True

                if was_powered_off:
                    state.power_off_remaining = max(
                        0.0, state.power_off_remaining - tick_duration
                    )

        for robot in match.robots:
            state = self._robot_chassis_states[robot.id]
            self._current_synthetic_power_by_robot[robot.id] = (
                self._synthetic_power_demand(robot, state)
            )

    def _synthetic_power_demand(
        self, robot: Robot, state: _RobotChassisState
    ) -> float:
        if not robot.alive or state.power_off_remaining > 0:
            return self._stationary_power_demand
        if robot.path:
            return self._chassis_power_rules[robot.type].moving_power_demand
        return self._stationary_power_demand

    def prepare_combat(self, match: "Match", dt: float) -> None:
        """Advance only quantized shooting-heat cooling before new attacks."""
        if dt <= 0:
            return

        self._heat_cooling_accumulator += dt
        ticks = math.floor(
            self._heat_cooling_accumulator * self._heat_cooling_hz + 1e-9
        )
        if ticks <= 0:
            return

        self._heat_cooling_accumulator = max(
            0.0,
            self._heat_cooling_accumulator - ticks / self._heat_cooling_hz,
        )
        for robot in match.robots:
            state = self._robot_shooting_states[robot.id]
            heat_rule = self._shooting_heat_rules[robot.type]
            state.heat = max(
                0.0,
                state.heat
                - ticks * heat_rule.cooling_per_second / self._heat_cooling_hz,
            )
            if state.heat <= 1e-9:
                state.heat = 0.0
                if not state.permanently_locked:
                    state.heat_locked = False

    def reset(self, match: "Match") -> None:
        expected_roster = {robot_type: 1 for robot_type in _RMUL_ROBOT_TYPES}
        for team in match.config.scenario.teams.values():
            actual_roster = {
                robot_type: sum(robot.type == robot_type for robot in team.robots)
                for robot_type in _RMUL_ROBOT_TYPES
            }
            if actual_roster != expected_roster:
                raise ConfigError(
                    f"{self._document.path}: 队伍 `{team.team_id}` 必须恰好包含 "
                    "1 hero、1 infantry、1 sentry"
                )

        player_team = match.config.scenario.player_team
        player_robot_definitions = next(
            team.robots
            for team in match.config.scenario.teams.values()
            if team.team_id == player_team
        )
        expected_player_controlled = {
            robot.id
            for robot in player_robot_definitions
            if robot.type in {"hero", "infantry"}
        }
        if match.config.scenario.player_controlled != expected_player_controlled:
            raise ConfigError(
                f"{self._document.path}: player_controlled 必须只包含 player_team 的 hero 和 infantry；"
                "sentry 必须由 AI 控制"
            )

        zones = [zone for zone in match.map.zones if zone.id == self._control_zone_id]
        if len(zones) != 1:
            raise ConfigError(
                f"{self._document.path}: scenario must define exactly one map zone "
                f"with id `{self._control_zone_id}`"
            )
        self._control_zone = zones[0]
        zones_by_id = {zone.id: zone for zone in match.map.zones}
        missing_supply_zones = sorted(
            set(self._supply_zone_ids.values()) - set(zones_by_id)
        )
        if missing_supply_zones:
            missing = ", ".join(missing_supply_zones)
            raise ConfigError(
                f"{self._document.path}: scenario 缺少补给区 map zones：{missing}"
            )
        self._supply_zones = {
            match.config.scenario.teams[side].team_id: zones_by_id[zone_id]
            for side, zone_id in self._supply_zone_ids.items()
        }
        team_by_side = {
            side: match.config.scenario.teams[side].team_id for side in ("red", "blue")
        }
        self._opposing_team = {
            team_by_side["red"]: team_by_side["blue"],
            team_by_side["blue"]: team_by_side["red"],
        }
        self._forbidden_zones = {
            team_by_side["red"]: zones_by_id[self._supply_zone_ids["blue"]],
            team_by_side["blue"]: zones_by_id[self._supply_zone_ids["red"]],
        }
        self._robot_lifecycles = {
            robot.id: _RobotLifecycle() for robot in match.robots
        }
        self._robot_penalties = {
            robot.id: _RobotPenaltyState(
                next_yellow_at=self._first_yellow_after
            )
            for robot in match.robots
        }
        self._robot_types_by_id = {robot.id: robot.type for robot in match.robots}
        self.allowed_projectiles_by_robot = {
            robot.id: self._allowed_projectile_rules[robot.type].initial
            for robot in match.robots
        }
        self._robot_shooting_states = {
            robot.id: _RobotShootingState() for robot in match.robots
        }
        self._heat_cooling_accumulator = 0.0
        self._robot_chassis_states = {
            robot.id: _RobotChassisState(buffer_energy=self._buffer_energy_max)
            for robot in match.robots
        }
        self._chassis_power_accumulator = 0.0
        self._current_synthetic_power_by_robot = {
            robot.id: self._stationary_power_demand for robot in match.robots
        }
        self.victory_points = {
            team.team_id: self._initial_victory_points
            for team in match.config.scenario.teams.values()
        }
        self.coins_by_team = dict.fromkeys(self.victory_points, 0)
        self._granted_timed_coin_events = set()
        self._granted_vp_gap_thresholds = set()
        self.attack_damage_by_team = dict.fromkeys(self.victory_points, 0)
        self.control_owner = None
        self._control_loss_elapsed = 0.0
        self._control_tick_accumulator = 0.0
        self._previous_zone_teams = set()

    def update(self, match: "Match", dt: float) -> None:
        team_ids = tuple(self.victory_points)
        previous_vp_gap = abs(
            self.victory_points[team_ids[0]] - self.victory_points[team_ids[1]]
        )
        # Consume each damage/death fact once, including facts emitted by a
        # penalty later in this same update.
        event_cursor = 0
        newly_destroyed, event_cursor = self._consume_events(
            match, event_cursor
        )

        frame_start = match.elapsed_time - dt
        active_dt = max(0.0, min(dt, self._time_limit - frame_start))
        self._advance_forbidden_zone_penalties(match, dt, active_dt)
        more_destroyed, event_cursor = self._consume_events(match, event_cursor)
        newly_destroyed.update(more_destroyed)

        alive_before_lifecycle = {robot.id: robot.alive for robot in match.robots}
        self._advance_robot_lifecycles(match, active_dt, newly_destroyed)
        newly_respawned = {
            robot.id
            for robot in match.robots
            if robot.alive and not alive_before_lifecycle[robot.id]
        }
        self._advance_supply_healing(match, active_dt, newly_respawned)
        present_teams = {
            robot.team
            for robot in match.robots
            if robot.alive
            and not self._robot_lifecycles[robot.id].weak
            and self._control_zone.contains(robot.position)
        }
        entering_teams = present_teams - self._previous_zone_teams
        self._advance_control(present_teams, entering_teams, active_dt)
        self._previous_zone_teams = present_teams
        self._grant_timed_coins(match, dt)
        self._grant_vp_gap_coins(previous_vp_gap)

    def _grant_timed_coins(self, match: "Match", dt: float) -> None:
        frame_start = match.elapsed_time - dt
        remaining_before = min(
            self._time_limit, max(0.0, self._time_limit - frame_start)
        )
        remaining_after = min(
            self._time_limit, max(0.0, self._time_limit - match.elapsed_time)
        )
        for remaining_time, amount in self._timed_coin_grants:
            if (
                remaining_time not in self._granted_timed_coin_events
                and remaining_before > remaining_time
                and remaining_after <= remaining_time
            ):
                for team_id in self.coins_by_team:
                    self.coins_by_team[team_id] += amount
                self._granted_timed_coin_events.add(remaining_time)

    def _grant_vp_gap_coins(self, previous_gap: int) -> None:
        team_ids = tuple(self.victory_points)
        current_gap = abs(
            self.victory_points[team_ids[0]] - self.victory_points[team_ids[1]]
        )
        if current_gap < previous_gap:
            return
        if self.victory_points[team_ids[0]] < self.victory_points[team_ids[1]]:
            losing_team = team_ids[0]
        elif self.victory_points[team_ids[1]] < self.victory_points[team_ids[0]]:
            losing_team = team_ids[1]
        else:
            return
        for threshold, amount in self._vp_gap_coin_grants:
            if (
                threshold not in self._granted_vp_gap_thresholds
                and previous_gap < threshold <= current_gap
            ):
                self.coins_by_team[losing_team] += amount
                self._granted_vp_gap_thresholds.add(threshold)

    def _consume_events(
        self, match: "Match", start: int
    ) -> tuple[set[str], int]:
        newly_destroyed: set[str] = set()
        events = match.current_events
        for event in events[start:]:
            if event.type == MatchEventType.ROBOT_DAMAGED:
                if (
                    event.attacker_team_id in self.attack_damage_by_team
                    and event.damage > 0
                ):
                    self.attack_damage_by_team[event.attacker_team_id] += event.damage
                continue
            if event.type != MatchEventType.ROBOT_DESTROYED:
                continue
            shooting = self._robot_shooting_states.get(event.robot_id)
            if shooting is not None:
                shooting.heat = 0.0
                shooting.heat_locked = False
            chassis = self._robot_chassis_states.get(event.robot_id)
            if chassis is not None:
                chassis.buffer_energy = self._buffer_energy_max
                chassis.power_off_remaining = 0.0
                chassis.blocked_this_frame = False
                self._current_synthetic_power_by_robot[event.robot_id] = (
                    self._stationary_power_demand
                )
            lifecycle = self._robot_lifecycles.get(event.robot_id)
            if lifecycle is not None:
                penalty = self._robot_penalties[event.robot_id]
                penalty.forbidden_elapsed = 0.0
                penalty.next_yellow_at = self._first_yellow_after
                if not penalty.disqualified:
                    lifecycle.death_count += 1
                    lifecycle.respawn_progress = 0.0
                    lifecycle.respawn_required = self._initial_respawn_progress + (
                        lifecycle.death_count - 1
                    ) * self._additional_respawn_progress_per_death
                lifecycle.weak = False
                lifecycle.invincible_remaining = 0.0
                newly_destroyed.add(event.robot_id)
            if event.team_id in self.victory_points:
                self.victory_points[event.team_id] = max(
                    0,
                    self.victory_points[event.team_id] - self._robot_destroyed_penalty,
                )
        return newly_destroyed, len(events)

    def _advance_forbidden_zone_penalties(
        self, match: "Match", dt: float, active_dt: float
    ) -> None:
        active_end_time = match.elapsed_time - max(0.0, dt - active_dt)
        for robot in match.robots:
            penalty = self._robot_penalties[robot.id]
            zone = self._forbidden_zones[robot.team]
            if (
                not robot.alive
                or penalty.disqualified
                or not zone.contains(robot.position)
            ):
                penalty.forbidden_elapsed = 0.0
                penalty.next_yellow_at = self._first_yellow_after
                continue

            penalty.forbidden_elapsed += active_dt
            while (
                robot.alive
                and not penalty.disqualified
                and penalty.forbidden_elapsed > penalty.next_yellow_at + 1e-9
            ):
                threshold = penalty.next_yellow_at
                card_time = active_end_time - max(
                    0.0, penalty.forbidden_elapsed - threshold
                )
                self._issue_yellow_card(match, robot, card_time)
                penalty.next_yellow_at += self._repeat_yellow_interval

    def _issue_yellow_card(
        self, match: "Match", offender: Robot, card_time: float
    ) -> None:
        penalty = self._robot_penalties[offender.id]
        repeated = (
            penalty.last_yellow_time is not None
            and card_time - penalty.last_yellow_time <= self._yellow_repeat_window + 1e-9
        )
        fraction = (
            penalty.last_yellow_fraction * self._yellow_repeat_multiplier
            if repeated
            else self._offender_hp_fraction
        )
        penalty.yellow_cards += 1
        penalty.last_yellow_time = card_time
        penalty.last_yellow_fraction = fraction
        opponent_team = self._opposing_team[offender.team]

        self._apply_yellow_hp_loss(
            match, offender, fraction, opponent_team
        )
        for teammate in match.robots:
            if teammate.team == offender.team and teammate is not offender and teammate.alive:
                self._apply_yellow_hp_loss(
                    match, teammate, self._teammate_hp_fraction, opponent_team
                )

        if penalty.yellow_cards >= self._red_after_yellows:
            penalty.disqualified = True
            match.apply_damage(
                offender,
                offender.hp,
                source_team_id=opponent_team,
                bypass_invincibility=True,
            )

    @staticmethod
    def _apply_yellow_hp_loss(
        match: "Match", robot: Robot, fraction: float, source_team_id: str
    ) -> None:
        if not robot.alive:
            return
        # The manual specifies whole-HP settlement with standard rounding.
        nominal_damage = int(math.floor(robot.max_hp * fraction + 0.5))
        damage = min(nominal_damage, max(0, robot.hp - 1))
        if damage:
            match.apply_damage(
                robot,
                damage,
                source_team_id=source_team_id,
                bypass_invincibility=True,
            )

    def _advance_robot_lifecycles(
        self,
        match: "Match",
        dt: float,
        newly_destroyed: set[str],
    ) -> None:
        for robot in match.robots:
            lifecycle = self._robot_lifecycles[robot.id]
            if not robot.alive:
                if self._robot_penalties[robot.id].disqualified:
                    lifecycle.respawn_progress = 0.0
                    lifecycle.respawn_required = None
                    continue
                # The robot died during this frame. Start accumulating next frame.
                if robot.id in newly_destroyed or lifecycle.respawn_required is None:
                    continue
                lifecycle.respawn_progress += dt * self._respawn_progress_per_second
                if lifecycle.respawn_progress + 1e-9 < lifecycle.respawn_required:
                    continue

                robot.alive = True
                # HP is an integer in the Engine; positive fractional values round down.
                robot.hp = max(1, int(robot.max_hp * self._respawn_hp_fraction))
                robot.path.clear()
                lifecycle.respawn_progress = 0.0
                lifecycle.respawn_required = None
                lifecycle.weak = True
                lifecycle.invincible_remaining = self._invincibility_duration
                continue

            lifecycle.invincible_remaining = max(
                0.0, lifecycle.invincible_remaining - dt
            )
            supply_zone = self._supply_zones[robot.team]
            if lifecycle.weak and supply_zone.contains(robot.position):
                lifecycle.weak = False
                lifecycle.invincible_remaining = 0.0

    def _advance_supply_healing(
        self,
        match: "Match",
        dt: float,
        newly_respawned: set[str],
    ) -> None:
        for robot in match.robots:
            lifecycle = self._robot_lifecycles[robot.id]
            supply_zone = self._supply_zones[robot.team]
            if robot.id in newly_respawned:
                lifecycle.healing_hp_fraction = 0.0
                continue
            if not robot.alive or not supply_zone.contains(robot.position):
                lifecycle.healing_hp_fraction = 0.0
                continue
            if robot.hp >= robot.max_hp:
                lifecycle.healing_hp_fraction = 0.0
                continue

            lifecycle.healing_hp_fraction += (
                dt * robot.max_hp * self._supply_heal_fraction_per_second
            )
            healing_points = math.floor(lifecycle.healing_hp_fraction + 1e-9)
            if healing_points <= 0:
                continue

            robot.hp = min(robot.max_hp, robot.hp + healing_points)
            if robot.hp >= robot.max_hp:
                lifecycle.healing_hp_fraction = 0.0
            else:
                lifecycle.healing_hp_fraction = max(
                    0.0, lifecycle.healing_hp_fraction - healing_points
                )

    def _advance_control(
        self,
        present_teams: set[str],
        entering_teams: set[str],
        dt: float,
    ) -> None:
        if self.control_owner is None:
            self._control_loss_elapsed = 0.0
            if not present_teams:
                self._control_tick_accumulator = 0.0
                return
            self.control_owner = self._choose_claimant(entering_teams or present_teams)
            self._control_tick_accumulator = 0.0
            self._apply_control_time(self.control_owner, dt)
            return

        if self.control_owner in present_teams:
            self._control_loss_elapsed = 0.0
            self._apply_control_time(self.control_owner, dt)
            return

        held_time = min(dt, max(0.0, self._control_loss_delay - self._control_loss_elapsed))
        self._control_loss_elapsed += dt
        self._apply_control_time(self.control_owner, held_time)
        if self._control_loss_elapsed + 1e-9 < self._control_loss_delay:
            return

        self.control_owner = None
        self._control_loss_elapsed = 0.0
        self._control_tick_accumulator = 0.0
        remaining_time = max(0.0, dt - held_time)
        if present_teams:
            self.control_owner = self._choose_claimant(entering_teams or present_teams)
            self._apply_control_time(self.control_owner, remaining_time)

    def _apply_control_time(self, owner: str, dt: float) -> None:
        if dt <= 0:
            return
        self._control_tick_accumulator += dt
        ticks = math.floor(self._control_tick_accumulator + 1e-9)
        if ticks <= 0:
            return
        self._control_tick_accumulator = max(0.0, self._control_tick_accumulator - ticks)
        for team_id in self.victory_points:
            if team_id != owner:
                self.victory_points[team_id] = max(
                    0,
                    self.victory_points[team_id]
                    - ticks * self._control_drain_per_second,
                )

    @staticmethod
    def _choose_claimant(candidates: set[str]) -> str:
        # Frame-sampled arrivals cannot reveal order within a frame; team id is
        # the documented, stable tie-break and does not depend on robot order.
        return min(candidates)

    def evaluate_result(self, match: "Match") -> MatchResult | None:
        teams_at_zero = [
            team_id for team_id, points in self.victory_points.items() if points <= 0
        ]
        if teams_at_zero:
            remaining = [
                team_id for team_id, points in self.victory_points.items() if points > 0
            ]
            return MatchResult(remaining[0] if len(remaining) == 1 else None)

        if match.elapsed_time < self.time_limit:
            return None

        highest = max(self.victory_points.values())
        leaders = [
            team_id for team_id, points in self.victory_points.items() if points == highest
        ]
        if len(leaders) == 1:
            return MatchResult(leaders[0])

        highest_damage = max(self.attack_damage_by_team.values())
        damage_leaders = [
            team_id
            for team_id, damage in self.attack_damage_by_team.items()
            if damage == highest_damage
        ]
        if len(damage_leaders) == 1:
            return MatchResult(damage_leaders[0])

        remaining_hp = {
            team.team_id: sum(
                robot.hp for robot in match.robots if robot.team == team.team_id
            )
            for team in match.config.scenario.teams.values()
        }
        highest_hp = max(remaining_hp.values())
        hp_leaders = [
            team_id for team_id, hp in remaining_hp.items() if hp == highest_hp
        ]
        return MatchResult(hp_leaders[0] if len(hp_leaders) == 1 else None)


def _mapping(data: Mapping[str, Any], key: str, document: RuleDocument) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{document.path}: `{key}` 必须是 YAML 字典")
    return value


def _parse_timed_coin_grants(
    economy: Mapping[str, Any], document: RuleDocument, time_limit: float
) -> tuple[tuple[int, int], ...]:
    if set(economy) != {"timed_grants", "vp_gap_grants"}:
        raise ConfigError(
            f"{document.path}: `economy` 只能包含 timed_grants、vp_gap_grants"
        )
    grants = economy.get("timed_grants")
    if not isinstance(grants, list) or not grants:
        raise ConfigError(f"{document.path}: `economy.timed_grants` 必须是非空列表")
    parsed = []
    seen_times: set[int] = set()
    for index, item in enumerate(grants):
        field = f"economy.timed_grants[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{document.path}: `{field}` 必须是 YAML 字典")
        if set(item) != {"remaining_time", "amount"}:
            raise ConfigError(f"{document.path}: `{field}` 字段不完整或包含未知字段")
        remaining_time = _positive_integer(
            item, "remaining_time", document, f"{field}.remaining_time"
        )
        amount = _positive_integer(item, "amount", document, f"{field}.amount")
        if remaining_time >= time_limit:
            raise ConfigError(
                f"{document.path}: `{field}.remaining_time` 必须小于比赛时长"
            )
        if remaining_time in seen_times:
            raise ConfigError(
                f"{document.path}: `economy.timed_grants` remaining_time 不能重复"
            )
        seen_times.add(remaining_time)
        parsed.append((remaining_time, amount))
    return tuple(sorted(parsed, reverse=True))


def _parse_vp_gap_coin_grants(
    economy: Mapping[str, Any], document: RuleDocument
) -> tuple[tuple[int, int], ...]:
    grants = economy.get("vp_gap_grants")
    if not isinstance(grants, list) or not grants:
        raise ConfigError(f"{document.path}: `economy.vp_gap_grants` 必须是非空列表")
    parsed = []
    seen_thresholds: set[int] = set()
    for index, item in enumerate(grants):
        field = f"economy.vp_gap_grants[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{document.path}: `{field}` 必须是 YAML 字典")
        if set(item) != {"threshold", "amount"}:
            raise ConfigError(f"{document.path}: `{field}` 字段不完整或包含未知字段")
        threshold = _positive_integer(
            item, "threshold", document, f"{field}.threshold"
        )
        amount = _positive_integer(item, "amount", document, f"{field}.amount")
        if threshold in seen_thresholds:
            raise ConfigError(
                f"{document.path}: `economy.vp_gap_grants` threshold 不能重复"
            )
        seen_thresholds.add(threshold)
        parsed.append((threshold, amount))
    return tuple(sorted(parsed))


def _parse_allowed_projectiles(
    document: RuleDocument,
) -> dict[str, _AllowedProjectileRule]:
    definitions = _mapping(document.data, "allowed_projectiles", document)
    if set(definitions) != set(_RMUL_ROBOT_TYPES):
        raise ConfigError(
            f"{document.path}: `allowed_projectiles` 必须只包含 hero、infantry、sentry"
        )

    parsed = {}
    for robot_type in _RMUL_ROBOT_TYPES:
        field = f"allowed_projectiles.{robot_type}"
        item = _mapping(definitions, robot_type, document)
        projectile = _string(item, "projectile", document, f"{field}.projectile")
        initial = _nonnegative_integer(item, "initial", document, f"{field}.initial")
        exchangeable = item.get("exchangeable")
        if not isinstance(exchangeable, bool):
            raise ConfigError(f"{document.path}: `{field}.exchangeable` 必须是布尔值")

        if robot_type == "sentry":
            if exchangeable:
                raise ConfigError(f"{document.path}: 哨兵允许发弹量不可兑换增加")
            expected_keys = {"projectile", "initial", "exchangeable"}
            if set(item) != expected_keys:
                raise ConfigError(
                    f"{document.path}: `{field}` 不可兑换，不应配置兑换价格或数量"
                )
            parsed[robot_type] = _AllowedProjectileRule(
                projectile=projectile,
                initial=initial,
                exchangeable=False,
            )
            continue

        if not exchangeable:
            raise ConfigError(
                f"{document.path}: `{field}.exchangeable` 必须为 true"
            )
        expected_keys = {
            "projectile",
            "initial",
            "exchangeable",
            "exchange_cost",
            "exchange_amount",
        }
        if set(item) != expected_keys:
            raise ConfigError(f"{document.path}: `{field}` 兑换参数不完整或包含未知字段")
        parsed[robot_type] = _AllowedProjectileRule(
            projectile=projectile,
            initial=initial,
            exchangeable=True,
            exchange_cost=_positive_integer(
                item, "exchange_cost", document, f"{field}.exchange_cost"
            ),
            exchange_amount=_positive_integer(
                item, "exchange_amount", document, f"{field}.exchange_amount"
            ),
        )
    return parsed


def _parse_shooting_heat(
    document: RuleDocument,
    allowed_projectiles: Mapping[str, _AllowedProjectileRule],
) -> tuple[float, dict[str, _ShootingHeatRule], str]:
    data = _mapping(document.data, "shooting_heat", document)
    expected_keys = {
        "cooling_hz",
        "projectile_heat",
        "permanent_lock_extra",
        "robot_profiles",
    }
    if set(data) != expected_keys:
        raise ConfigError(
            f"{document.path}: `shooting_heat` 字段不完整或包含未知字段"
        )

    cooling_hz = _number(
        data, "cooling_hz", document, "shooting_heat.cooling_hz"
    )
    projectile_heat = _mapping(data, "projectile_heat", document)
    permanent_lock_extra = _mapping(data, "permanent_lock_extra", document)
    projectiles = {rule.projectile for rule in allowed_projectiles.values()}
    if set(projectile_heat) != projectiles:
        raise ConfigError(
            f"{document.path}: `shooting_heat.projectile_heat` 必须匹配允许弹丸类型"
        )
    if set(permanent_lock_extra) != projectiles:
        raise ConfigError(
            f"{document.path}: `shooting_heat.permanent_lock_extra` 必须匹配允许弹丸类型"
        )

    projectile_heat_values = {
        projectile: _number(
            projectile_heat,
            projectile,
            document,
            f"shooting_heat.projectile_heat.{projectile}",
        )
        for projectile in projectiles
    }
    permanent_extra_values = {
        projectile: _number(
            permanent_lock_extra,
            projectile,
            document,
            f"shooting_heat.permanent_lock_extra.{projectile}",
        )
        for projectile in projectiles
    }

    profiles = _mapping(data, "robot_profiles", document)
    if set(profiles) != set(_RMUL_ROBOT_TYPES):
        raise ConfigError(
            f"{document.path}: `shooting_heat.robot_profiles` "
            "必须只包含 hero、infantry、sentry"
        )

    parsed: dict[str, _ShootingHeatRule] = {}
    infantry_launcher_profile = ""
    for robot_type in _RMUL_ROBOT_TYPES:
        field = f"shooting_heat.robot_profiles.{robot_type}"
        profile = _mapping(profiles, robot_type, document)
        expected_profile_keys = {"heat_limit", "cooling_per_second"}
        if robot_type == "infantry":
            expected_profile_keys.add("launcher_profile")
        if set(profile) != expected_profile_keys:
            raise ConfigError(
                f"{document.path}: `{field}` 字段不完整或包含未知字段"
            )
        if robot_type == "infantry":
            infantry_launcher_profile = _string(
                profile, "launcher_profile", document, f"{field}.launcher_profile"
            )

        projectile = allowed_projectiles[robot_type].projectile
        parsed[robot_type] = _ShootingHeatRule(
            heat_limit=_number(
                profile, "heat_limit", document, f"{field}.heat_limit"
            ),
            cooling_per_second=_number(
                profile,
                "cooling_per_second",
                document,
                f"{field}.cooling_per_second",
            ),
            projectile_heat=projectile_heat_values[projectile],
            permanent_lock_extra=permanent_extra_values[projectile],
        )

    return cooling_hz, parsed, infantry_launcher_profile


def _parse_chassis_power(
    document: RuleDocument,
) -> tuple[float, float, float, dict[str, _ChassisPowerRule], str, float]:
    data = _mapping(document.data, "chassis_power", document)
    expected_keys = {
        "detection_hz",
        "buffer_energy_max",
        "power_off_duration",
        "robot_profiles",
        "lab_power_demand",
    }
    if set(data) != expected_keys:
        raise ConfigError(
            f"{document.path}: chassis_power 字段不完整或包含未知字段"
        )

    detection_hz = _number(
        data, "detection_hz", document, "chassis_power.detection_hz"
    )
    buffer_energy_max = _number(
        data, "buffer_energy_max", document, "chassis_power.buffer_energy_max"
    )
    power_off_duration = _number(
        data, "power_off_duration", document, "chassis_power.power_off_duration"
    )

    profiles = _mapping(data, "robot_profiles", document)
    if set(profiles) != set(_RMUL_ROBOT_TYPES):
        raise ConfigError(
            f"{document.path}: chassis_power.robot_profiles 必须只包含 "
            "hero、infantry、sentry"
        )

    demand = _mapping(data, "lab_power_demand", document)
    if set(demand) != {"stationary", "moving"}:
        raise ConfigError(
            f"{document.path}: chassis_power.lab_power_demand "
            "必须只包含 stationary、moving"
        )
    stationary = _nonnegative_number(
        demand,
        "stationary",
        document,
        "chassis_power.lab_power_demand.stationary",
    )
    moving = _mapping(demand, "moving", document)
    if set(moving) != set(_RMUL_ROBOT_TYPES):
        raise ConfigError(
            f"{document.path}: chassis_power.lab_power_demand.moving "
            "必须只包含 hero、infantry、sentry"
        )

    parsed: dict[str, _ChassisPowerRule] = {}
    infantry_chassis_profile = ""
    for robot_type in _RMUL_ROBOT_TYPES:
        field = f"chassis_power.robot_profiles.{robot_type}"
        profile = _mapping(profiles, robot_type, document)
        expected_profile_keys = {"power_limit"}
        if robot_type == "infantry":
            expected_profile_keys.add("chassis_profile")
        if set(profile) != expected_profile_keys:
            raise ConfigError(
                f"{document.path}: {field} 字段不完整或包含未知字段"
            )
        if robot_type == "infantry":
            infantry_chassis_profile = _string(
                profile, "chassis_profile", document, f"{field}.chassis_profile"
            )
        parsed[robot_type] = _ChassisPowerRule(
            power_limit=_number(
                profile, "power_limit", document, f"{field}.power_limit"
            ),
            moving_power_demand=_number(
                moving,
                robot_type,
                document,
                f"chassis_power.lab_power_demand.moving.{robot_type}",
            ),
        )

    return (
        detection_hz,
        buffer_energy_max,
        power_off_duration,
        parsed,
        infantry_chassis_profile,
        stationary,
    )

def _string(
    data: Mapping[str, Any], key: str, document: RuleDocument, field: str
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{document.path}: `{field}` 必须是非空字符串")
    return value.strip()


def _number(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str | None = None,
) -> float:
    value = data.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigError(f"{document.path}: `{field or key}` 必须是大于 0 的数字")
    return float(value)


def _nonnegative_number(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> float:
    value = data.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ConfigError(f"{document.path}: {field} 必须是非负数字")
    return float(value)

def _integer(
    data: Mapping[str, Any], key: str, document: RuleDocument, field: str
) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{document.path}: `{field}` 必须是正整数")
    return value


def _positive_integer(
    data: Mapping[str, Any], key: str, document: RuleDocument, field: str
) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{document.path}: `{field}` 必须是正整数")
    return value


def _nonnegative_integer(
    data: Mapping[str, Any], key: str, document: RuleDocument, field: str
) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{document.path}: `{field}` 必须是非负整数")
    return value


def _fraction(
    data: Mapping[str, Any],
    key: str,
    document: RuleDocument,
    field: str,
) -> float:
    value = data.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 < value <= 1
    ):
        raise ConfigError(f"{document.path}: `{field}` 必须在 0 和 1 之间（含 1）")
    return float(value)


if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match
