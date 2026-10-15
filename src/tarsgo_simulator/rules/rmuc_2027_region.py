"""RMUC 2027 Rules Lab, currently implementing P2 territory control.

Physical robot performance and the gainpoint-card polygons remain isolated
Rules Lab assumptions; control timing and transitions follow RMUC 2027 V1.0.0.
"""

from collections import Counter
from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, Any

from tarsgo_simulator.core.config import ConfigError, RuleDocument
from tarsgo_simulator.rules.protocol import (
    DamageableTarget,
    DamageResolution,
    MatchResult,
    RobotParameters,
    RuleSetDisplayState,
    StructureParameters,
    TerritoryControlDisplayState,
)

if TYPE_CHECKING:
    from tarsgo_simulator.core.config import ScenarioDefinition
    from tarsgo_simulator.core.match import Match
    from tarsgo_simulator.core.robot import Robot


RMUC_2027_RULE_ID = "rmuc-2027-region-v1.0.0"
_GROUND_ROSTER = {"heavy": 1, "infantry": 2, "sentry": 1}
_SYSTEM_ROSTER = {
    "air": {"hangar": 1, "aircraft": 4},
    "dart": {"launcher": 1, "dart_bodies": 4},
    "radar": {"computing_platform": 1, "sensor": 1},
}
_TERRITORY_KINDS = {"outpost", "base"}


@dataclass(slots=True)
class _TerritoryState:
    territory_id: str
    kind: str
    initial_owner: str
    owner: str
    last_full_owner: str
    status: str = "full"
    progress_seconds: float = 0.0
    progress_team_id: str | None = None
    active_team_ids: tuple[str, ...] = ()


class RMUC2027RegionRules:
    """RMUC 2027 RuleSet with real tick-driven territory activation."""

    def __init__(self, document: RuleDocument) -> None:
        if document.metadata.id != RMUC_2027_RULE_ID:
            raise ConfigError(
                f"{document.path}: RMUC 2027 requires `{RMUC_2027_RULE_ID}`"
            )
        if document.metadata.status != "rules-lab-partial":
            raise ConfigError(
                f"{document.path}: RMUC 2027 must remain `rules-lab-partial`"
            )
        if (
            document.metadata.competition != "RMUC"
            or document.metadata.season != 2027
            or document.metadata.official_version != "V1.0.0"
        ):
            raise ConfigError(
                f"{document.path}: RMUC 2027 requires season 2027 V1.0.0 metadata"
            )

        roster = document.data.get("active_roster")
        expected_roster = {"ground": _GROUND_ROSTER, "systems": _SYSTEM_ROSTER}
        if roster != expected_roster:
            raise ConfigError(
                f"{document.path}: `active_roster` must match RMUC 2027 V1.0.0"
            )
        self._ground_roster = Counter(_GROUND_ROSTER)

        duration = document.data.get("match_duration")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration != 420
        ):
            raise ConfigError(
                f"{document.path}: RMUC 2027 V1.0.0 match duration must be 420 seconds"
            )
        self._time_limit = float(duration)

        profile = document.data.get("rules_lab_placeholder")
        if not isinstance(profile, dict):
            raise ConfigError(
                f"{document.path}: `rules_lab_placeholder` must define the synthetic robot profile"
            )
        self._parameters = RobotParameters(
            max_hp=_positive_integer(profile, "max_hp", document),
            move_speed=_positive_number(profile, "move_speed", document),
            collision_radius=_positive_number(profile, "collision_radius", document),
            attack_range=_non_negative_number(profile, "attack_range", document),
            attack_interval=_positive_number(profile, "attack_interval", document),
            damage=_non_negative_integer(profile, "damage", document),
        )

        control = document.data.get("territory_control")
        if not isinstance(control, dict):
            raise ConfigError(f"{document.path}: `territory_control` must be a mapping")
        self._capture_seconds = _positive_number(
            control, "capture_seconds", document, prefix="territory_control"
        )
        self._invalidation_delay = _non_negative_number(
            control,
            "activation_invalidation_delay_seconds",
            document,
            prefix="territory_control",
        )
        self._territory_definitions = _territory_definitions(
            control.get("territories"), document
        )

        self._territories: dict[str, _TerritoryState] = {}
        self._team_ids_by_side: dict[str, str] = {}
        self._zone_by_id = {}
        self._active_robot_zones: set[tuple[str, str]] = set()
        self._zone_inactive_at: dict[tuple[str, str], float] = {}
        self._last_update_time = 0.0

    @property
    def time_limit(self) -> float:
        return self._time_limit

    @property
    def runs_generic_robot_ai(self) -> bool:
        """P2 enables manual movement without silently adding a combat AI."""
        return False

    @property
    def replay_timebox_without_settlement(self) -> bool:
        """P2a has no winner rule yet; P2c removes this guard with settlement."""
        return True

    @property
    def display_state(self) -> RuleSetDisplayState:
        territories = tuple(
            TerritoryControlDisplayState(
                territory_id=state.territory_id,
                kind=state.kind,
                owner=state.owner,
                status=state.status,
                progress_seconds=state.progress_seconds,
                progress_team_id=state.progress_team_id,
                active_team_ids=state.active_team_ids,
            )
            for state in sorted(self._territories.values(), key=lambda item: item.territory_id)
        )
        return RuleSetDisplayState(
            victory_points=(),
            control_owner=None,
            territory_control=territories,
        )

    def validate_scenario(self, scenario: "ScenarioDefinition") -> None:
        """Reject any active ground roster outside the official 2027 lineup."""
        for team in scenario.teams.values():
            actual = Counter(robot.type for robot in team.robots)
            if actual != self._ground_roster:
                raise ConfigError(
                    f"RMUC 2027 active ground roster for `{team.team_id}` must be "
                    "heavy×1, infantry×2, sentry×1; combination systems are not ground robots"
                )

    def robot_parameters(self, robot_type: str) -> RobotParameters:
        if robot_type not in _GROUND_ROSTER:
            raise ConfigError(
                f"RMUC 2027 Rules Lab does not support mobile robot type `{robot_type}`"
            )
        return self._parameters

    def structure_parameters(self, structure_type: str) -> StructureParameters:
        raise ConfigError(
            f"RMUC 2027 P2a does not implement `{structure_type}` structures yet"
        )

    def can_move(self, robot: "Robot") -> bool:
        return robot.type in _GROUND_ROSTER and self._parameters.move_speed > 0

    def can_attack(self, robot: "Robot") -> bool:
        del robot
        return False

    def can_target(self, target: DamageableTarget) -> bool:
        del target
        return False

    def on_attack_committed(self, robot: "Robot") -> None:
        del robot

    def exchange_projectiles(self, match: "Match", robot: "Robot") -> bool:
        del match, robot
        return False

    def can_receive_damage(self, target: DamageableTarget) -> bool:
        del target
        return False

    def resolve_damage(
        self,
        target: DamageableTarget,
        amount: int,
        source_team_id: str | None,
        *,
        bypass_attack_defense: bool = False,
        attack_multiplier: float = 1.0,
    ) -> int:
        del target, amount, source_team_id, bypass_attack_defense, attack_multiplier
        return 0

    def resolve_damage_detail(
        self,
        target: DamageableTarget,
        amount: int,
        source_team_id: str | None,
        *,
        bypass_attack_defense: bool = False,
        attack_multiplier: float = 1.0,
    ) -> DamageResolution:
        return DamageResolution(
            self.resolve_damage(
                target,
                amount,
                source_team_id,
                bypass_attack_defense=bypass_attack_defense,
                attack_multiplier=attack_multiplier,
            )
        )

    def prepare_movement(self, match: "Match", dt: float) -> None:
        del match, dt

    def prepare_combat(self, match: "Match", dt: float) -> None:
        del match, dt

    def reset(self, match: "Match") -> None:
        self._team_ids_by_side = {
            side: match.config.scenario.teams[side].team_id
            for side in ("red", "blue")
        }
        self._zone_by_id = {zone.id: zone for zone in match.map.zones}
        configured_zone_ids = {
            zone_id
            for definition in self._territory_definitions.values()
            for zone_id in definition["gainpoints"]
        }
        missing_zones = configured_zone_ids - self._zone_by_id.keys()
        if missing_zones:
            raise ConfigError(
                "RMUC 2027 field is missing territory gainpoint zones: "
                + ", ".join(sorted(missing_zones))
            )

        self._territories = {}
        for territory_id, definition in self._territory_definitions.items():
            owner = self._team_ids_by_side[definition["initial_side"]]
            self._territories[territory_id] = _TerritoryState(
                territory_id=territory_id,
                kind=definition["kind"],
                initial_owner=owner,
                owner=owner,
                last_full_owner=owner,
            )
        self._active_robot_zones = {
            (robot.id, zone.id)
            for robot in match.robots
            if robot.alive
            for zone in self._zone_by_id.values()
            if zone.id in configured_zone_ids and zone.contains(robot.position)
        }
        self._zone_inactive_at.clear()
        self._last_update_time = match.elapsed_time

    def update(self, match: "Match", dt: float) -> None:
        del dt
        now = match.elapsed_time
        elapsed = max(0.0, now - self._last_update_time)
        self._last_update_time = now
        active_teams_by_zone = self._active_teams_by_zone(match, now)

        for territory_id, state in self._territories.items():
            definition = self._territory_definitions[territory_id]
            active_teams = set().union(
                *(active_teams_by_zone[zone_id] for zone_id in definition["gainpoints"])
            )
            state.active_team_ids = tuple(sorted(active_teams))
            self._advance_territory(state, active_teams, elapsed)

    def _active_teams_by_zone(
        self, match: "Match", now: float
    ) -> dict[str, set[str]]:
        active_teams_by_zone = {
            zone_id: set()
            for definition in self._territory_definitions.values()
            for zone_id in definition["gainpoints"]
        }
        live_ids = {robot.id for robot in match.robots if robot.alive}
        for key in tuple(self._zone_inactive_at):
            if key[0] not in live_ids or self._zone_inactive_at[key] < now:
                self._zone_inactive_at.pop(key, None)

        current_active: set[tuple[str, str]] = set()
        configured_zone_ids = active_teams_by_zone.keys()
        for robot in match.robots:
            for zone_id in configured_zone_ids:
                key = (robot.id, zone_id)
                zone = self._zone_by_id[zone_id]
                inside = robot.alive and zone.contains(robot.position)
                was_inside = key in self._active_robot_zones
                if inside:
                    current_active.add(key)
                    self._zone_inactive_at.pop(key, None)
                    active_teams_by_zone[zone_id].add(robot.team)
                elif not robot.alive:
                    self._zone_inactive_at.pop(key, None)
                elif was_inside:
                    inactive_at = now + self._invalidation_delay
                    self._zone_inactive_at[key] = inactive_at
                    active_teams_by_zone[zone_id].add(robot.team)
                elif self._zone_inactive_at.get(key, -math.inf) >= now:
                    active_teams_by_zone[zone_id].add(robot.team)

        self._active_robot_zones = current_active
        return active_teams_by_zone

    def _advance_territory(
        self,
        state: _TerritoryState,
        active_teams: set[str],
        elapsed: float,
    ) -> None:
        if len(active_teams) > 1:
            return

        if state.status == "full":
            attacker = next(
                (team_id for team_id in active_teams if team_id != state.owner),
                None,
            )
            if attacker is None:
                if state.progress_team_id is not None:
                    state.progress_seconds = max(0.0, state.progress_seconds - elapsed)
                    if state.progress_seconds == 0.0:
                        state.progress_team_id = None
                return

            if state.progress_team_id != attacker:
                state.progress_seconds = 0.0
                state.progress_team_id = attacker
            state.progress_seconds = min(
                self._capture_seconds,
                state.progress_seconds + elapsed,
            )
            if state.progress_seconds >= self._capture_seconds:
                state.last_full_owner = state.owner
                state.owner = attacker
                state.status = "temporary"
                state.progress_seconds = 0.0
                state.progress_team_id = None
            return

        temporary_owner_active = state.owner in active_teams
        if temporary_owner_active:
            state.progress_seconds = 0.0
            state.progress_team_id = None
            return

        state.progress_team_id = state.last_full_owner
        state.progress_seconds = min(
            self._capture_seconds,
            state.progress_seconds + elapsed,
        )
        if state.progress_seconds >= self._capture_seconds:
            state.owner = state.last_full_owner
            state.status = "full"
            state.progress_seconds = 0.0
            state.progress_team_id = None

    def evaluate_result(self, match: "Match") -> MatchResult | None:
        del match
        return None


def _territory_definitions(
    raw: Any, document: RuleDocument
) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or len(raw) != 4:
        raise ConfigError(
            f"{document.path}: `territory_control.territories` must define four territories"
        )
    result: dict[str, dict[str, Any]] = {}
    kind_sides: set[tuple[str, str]] = set()
    for territory_id, value in raw.items():
        if not isinstance(territory_id, str) or not isinstance(value, dict):
            raise ConfigError(f"{document.path}: territory definitions must be mappings")
        kind = value.get("kind")
        side = value.get("initial_side")
        gainpoints = value.get("gainpoints")
        if (
            not isinstance(kind, str)
            or kind not in _TERRITORY_KINDS
            or not isinstance(side, str)
            or side not in {"red", "blue"}
        ):
            raise ConfigError(
                f"{document.path}: `{territory_id}` needs kind and initial_side"
            )
        if (
            not isinstance(gainpoints, list)
            or len(gainpoints) != 2
            or any(not isinstance(zone_id, str) or not zone_id for zone_id in gainpoints)
            or len(set(gainpoints)) != 2
        ):
            raise ConfigError(
                f"{document.path}: `{territory_id}.gainpoints` must name two distinct zones"
            )
        if (kind, side) in kind_sides:
            raise ConfigError(
                f"{document.path}: duplicate `{kind}` territory for `{side}`"
            )
        kind_sides.add((kind, side))
        result[territory_id] = {
            "kind": kind,
            "initial_side": side,
            "gainpoints": tuple(gainpoints),
        }
    if kind_sides != {
        (kind, side) for kind in _TERRITORY_KINDS for side in ("red", "blue")
    }:
        raise ConfigError(
            f"{document.path}: each side needs one base and one outpost territory"
        )
    all_zones = [
        zone_id
        for definition in result.values()
        for zone_id in definition["gainpoints"]
    ]
    if len(all_zones) != len(set(all_zones)):
        raise ConfigError(f"{document.path}: a gainpoint zone cannot belong to two territories")
    return result


def _positive_integer(profile: dict[str, Any], key: str, document: RuleDocument) -> int:
    value = profile.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(
            f"{document.path}: `rules_lab_placeholder.{key}` must be a positive integer"
        )
    return value


def _non_negative_integer(profile: dict[str, Any], key: str, document: RuleDocument) -> int:
    value = profile.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(
            f"{document.path}: `rules_lab_placeholder.{key}` must be a non-negative integer"
        )
    return value


def _positive_number(
    profile: dict[str, Any],
    key: str,
    document: RuleDocument,
    *,
    prefix: str = "rules_lab_placeholder",
) -> float:
    value = profile.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ConfigError(f"{document.path}: `{prefix}.{key}` must be positive")
    return float(value)


def _non_negative_number(
    profile: dict[str, Any],
    key: str,
    document: RuleDocument,
    *,
    prefix: str = "rules_lab_placeholder",
) -> float:
    value = profile.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ConfigError(f"{document.path}: `{prefix}.{key}` must be non-negative")
    return float(value)
