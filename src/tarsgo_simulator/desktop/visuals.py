"""Small desktop-only visual feedback state for the Pygame front end."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import secrets
from typing import TYPE_CHECKING

from tarsgo_simulator.core.events import MatchEvent, MatchEventType
from tarsgo_simulator.desktop.polish import parse_virtual_shield

if TYPE_CHECKING:
    from tarsgo_simulator.core.match import Match


@dataclass(frozen=True)
class RobotVisualProfile:
    body_width: int
    body_height: int
    turret_radius: int
    barrel_length: int
    barrel_width: int
    tool_arm_length: int = 0


@dataclass(frozen=True)
class ProjectileVisualProfile:
    caliber: str
    lifetime: float
    tracer_width: int
    head_radius: int
    flash_duration: float
    impact_duration: float


ROBOT_VISUAL_PROFILES = {
    "hero": RobotVisualProfile(46, 28, 10, 31, 8),
    "engineer": RobotVisualProfile(38, 28, 0, 0, 0, tool_arm_length=27),
    "infantry": RobotVisualProfile(28, 20, 6, 19, 2),
    "sentry": RobotVisualProfile(52, 30, 11, 25, 4),
    "drone": RobotVisualProfile(40, 28, 0, 0, 0),
}

PROJECTILE_VISUAL_PROFILES = {
    "17mm": ProjectileVisualProfile("17mm", 0.11, 2, 2, 0.055, 0.12),
    "42mm": ProjectileVisualProfile("42mm", 0.19, 5, 4, 0.090, 0.22),
}

DESTROY_VISUAL_DURATION = 0.46
RESPAWN_VISUAL_DURATION = 0.68
SHIELD_IMPACT_DURATION = 0.20
MAX_SCREEN_SHAKE_AMPLITUDE = 2.25
MAX_SCREEN_SHAKE_DURATION = 0.14
SCREEN_SHAKE_COOLDOWN = 0.08
OUTPOST_ROTATION_SPEED = 0.8 * math.pi
OUTPOST_ROTATION_RAMP_SECONDS = 5.0
OUTPOST_ROTATION_STOP_SECONDS = 180.0
OUTPOST_ROTATION_RETURN_SECONDS = 10.0


def robot_visual_profile(robot_type: str) -> RobotVisualProfile:
    return ROBOT_VISUAL_PROFILES.get(
        robot_type,
        RobotVisualProfile(28, 22, 7, 22, 3),
    )


def projectile_visual_profile(caliber: str) -> ProjectileVisualProfile:
    return PROJECTILE_VISUAL_PROFILES.get(
        caliber,
        PROJECTILE_VISUAL_PROFILES["17mm"],
    )


def low_hp_warning_strength(hp_ratio: float, animation_time: float) -> float:
    if hp_ratio <= 0 or hp_ratio > 0.25:
        return 0.0
    pulse = 0.5 + 0.5 * math.sin(animation_time * 5.0)
    return 0.30 + 0.55 * pulse


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (math.tau) - math.pi


def approach_angle(current: float, target: float, dt: float, response: float) -> float:
    """Smooth one visual angle toward another without touching gameplay state."""
    if dt <= 0:
        return _wrap_angle(current)
    difference = _wrap_angle(target - current)
    factor = 1.0 - math.exp(-max(0.0, response) * dt)
    return _wrap_angle(current + difference * factor)


@dataclass
class VisualRobotState:
    position: tuple[float, float]
    hp: int
    cooldown: float
    alive: bool = True
    body_angle: float = 0.0
    turret_angle: float = 0.0
    target_position: tuple[float, float] | None = None
    target_hold_remaining: float = 0.0
    muzzle_remaining: float = 0.0
    muzzle_caliber: str = "17mm"
    impact_remaining: float = 0.0
    impact_caliber: str = "17mm"
    destroy_remaining: float = 0.0
    respawn_remaining: float = 0.0
    ghost_from_hp: float = 0.0
    ghost_remaining: float = 0.0
    ghost_duration: float = 0.38

    def advance_motion(
        self,
        new_position: tuple[float, float],
        dt: float,
    ) -> None:
        dx = new_position[0] - self.position[0]
        dy = new_position[1] - self.position[1]
        if math.hypot(dx, dy) > 1e-6:
            desired = math.atan2(dy, dx)
            self.body_angle = approach_angle(
                self.body_angle,
                desired,
                dt,
                response=9.0,
            )
        self.position = new_position

    def advance_turret(self, dt: float) -> None:
        if self.target_hold_remaining > 0 and self.target_position is not None:
            dx = self.target_position[0] - self.position[0]
            dy = self.target_position[1] - self.position[1]
            desired = (
                math.atan2(dy, dx)
                if math.hypot(dx, dy) > 1e-6
                else self.body_angle
            )
        else:
            desired = self.body_angle
        self.turret_angle = approach_angle(
            self.turret_angle,
            desired,
            dt,
            response=14.0,
        )

    def register_damage(self, previous_hp: int, current_hp: int) -> None:
        if current_hp >= previous_hp:
            self.hp = current_hp
            return
        current_ghost = self.ghost_hp(current_hp)
        self.ghost_from_hp = max(float(previous_hp), current_ghost)
        self.ghost_remaining = self.ghost_duration
        self.hp = current_hp

    def register_lifecycle(self, alive: bool) -> None:
        if self.alive and not alive:
            self.destroy_remaining = DESTROY_VISUAL_DURATION
            self.respawn_remaining = 0.0
        elif not self.alive and alive:
            self.respawn_remaining = RESPAWN_VISUAL_DURATION
            self.destroy_remaining = 0.0
        self.alive = alive

    @property
    def destroy_progress(self) -> float:
        if self.destroy_remaining <= 0:
            return 1.0
        return 1.0 - min(1.0, self.destroy_remaining / DESTROY_VISUAL_DURATION)

    @property
    def respawn_progress(self) -> float:
        if self.respawn_remaining <= 0:
            return 1.0
        return 1.0 - min(1.0, self.respawn_remaining / RESPAWN_VISUAL_DURATION)

    def ghost_hp(self, current_hp: int) -> float:
        if self.ghost_remaining <= 0 or self.ghost_from_hp <= current_hp:
            return float(current_hp)
        ratio = min(1.0, self.ghost_remaining / self.ghost_duration)
        return current_hp + (self.ghost_from_hp - current_hp) * ratio

    def advance_timers(self, dt: float) -> None:
        self.target_hold_remaining = max(0.0, self.target_hold_remaining - dt)
        self.muzzle_remaining = max(0.0, self.muzzle_remaining - dt)
        self.impact_remaining = max(0.0, self.impact_remaining - dt)
        self.destroy_remaining = max(0.0, self.destroy_remaining - dt)
        self.respawn_remaining = max(0.0, self.respawn_remaining - dt)
        self.ghost_remaining = max(0.0, self.ghost_remaining - dt)


@dataclass
class VisualStructureState:
    hp: int
    shield: int = 0
    impact_remaining: float = 0.0
    impact_caliber: str = "17mm"
    shield_impact_remaining: float = 0.0

    def advance_timers(self, dt: float) -> None:
        self.impact_remaining = max(0.0, self.impact_remaining - max(0.0, dt))
        self.shield_impact_remaining = max(
            0.0,
            self.shield_impact_remaining - max(0.0, dt),
        )


@dataclass
class OutpostRotorVisualState:
    """Presentation-only pose for the Outpost's rotating middle armor."""

    direction: int
    angle: float = 0.0
    stop_time: float | None = None
    destroyed_at_stop: bool = False

    def advance(
        self,
        elapsed_time: float,
        *,
        alive: bool,
        opponent_base_hp: int,
    ) -> None:
        now = max(0.0, elapsed_time)
        if self.stop_time is None:
            if not alive:
                self.stop_time = now
                self.destroyed_at_stop = True
            elif opponent_base_hp <= 2000:
                self.stop_time = now
            elif now >= OUTPOST_ROTATION_STOP_SECONDS:
                self.stop_time = OUTPOST_ROTATION_STOP_SECONDS

        if self.stop_time is None:
            self.angle = _wrap_angle(self.direction * _outpost_active_angle(now))
            return

        stopped_angle = _wrap_angle(
            self.direction * _outpost_active_angle(self.stop_time)
        )
        if self.destroyed_at_stop:
            self.angle = stopped_angle
            return

        return_progress = min(
            1.0,
            max(0.0, (now - self.stop_time) / OUTPOST_ROTATION_RETURN_SECONDS),
        )
        # Smoothly ease the armor back to its official starting pose over 10 s.
        smooth_return = return_progress * return_progress * (
            3.0 - 2.0 * return_progress
        )
        self.angle = stopped_angle * (1.0 - smooth_return)


def _outpost_active_angle(elapsed_time: float) -> float:
    elapsed = max(0.0, elapsed_time)
    acceleration = OUTPOST_ROTATION_SPEED / OUTPOST_ROTATION_RAMP_SECONDS
    if elapsed <= OUTPOST_ROTATION_RAMP_SECONDS:
        return 0.5 * acceleration * elapsed * elapsed
    ramp_angle = 0.5 * OUTPOST_ROTATION_SPEED * OUTPOST_ROTATION_RAMP_SECONDS
    return ramp_angle + OUTPOST_ROTATION_SPEED * (
        elapsed - OUTPOST_ROTATION_RAMP_SECONDS
    )


@dataclass
class VisualProjectile:
    start: tuple[float, float]
    end: tuple[float, float]
    caliber: str
    attacker_team_id: str
    target_id: str | None
    damaging: bool
    shielded: bool = False
    age: float = 0.0

    @property
    def profile(self) -> ProjectileVisualProfile:
        return projectile_visual_profile(self.caliber)

    @property
    def progress(self) -> float:
        return min(1.0, self.age / self.profile.lifetime)

    @property
    def expired(self) -> bool:
        return self.age >= self.profile.lifetime

    @property
    def position(self) -> tuple[float, float]:
        p = self.progress
        return (
            self.start[0] + (self.end[0] - self.start[0]) * p,
            self.start[1] + (self.end[1] - self.start[1]) * p,
        )

    def advance(self, dt: float) -> None:
        self.age += max(0.0, dt)


@dataclass
class ImpactEffect:
    position: tuple[float, float]
    caliber: str
    remaining: float
    duration: float
    shielded: bool = False
    target_kind: str = "robot"

    @property
    def progress(self) -> float:
        if self.duration <= 0:
            return 1.0
        return 1.0 - min(1.0, self.remaining / self.duration)

    def advance(self, dt: float) -> None:
        self.remaining = max(0.0, self.remaining - max(0.0, dt))


@dataclass
class MoveMarker:
    position: tuple[float, float]
    remaining: float = 0.75
    duration: float = 0.75

    @property
    def progress(self) -> float:
        return 1.0 - min(1.0, self.remaining / self.duration)

    def advance(self, dt: float) -> None:
        self.remaining = max(0.0, self.remaining - max(0.0, dt))


@dataclass
class CombatVisualState:
    robots: dict[str, VisualRobotState] = field(default_factory=dict)
    structures: dict[str, VisualStructureState] = field(default_factory=dict)
    outpost_rotors: dict[str, OutpostRotorVisualState] = field(default_factory=dict)
    projectiles: list[VisualProjectile] = field(default_factory=list)
    impacts: list[ImpactEffect] = field(default_factory=list)
    move_markers: list[MoveMarker] = field(default_factory=list)
    shake_remaining: float = 0.0
    shake_duration: float = 0.0
    shake_amplitude: float = 0.0
    shake_cooldown_remaining: float = 0.0
    _before_cooldowns: dict[str, float] = field(default_factory=dict)
    _before_structure_shields: dict[str, int] = field(default_factory=dict)

    def reset(self, match: "Match") -> None:
        structure_statuses = self._structure_statuses(match)
        outposts = [structure for structure in match.structures if structure.type == "outpost"]
        rotation_direction = secrets.choice((-1, 1))
        self.robots = {
            robot.id: VisualRobotState(
                position=robot.position,
                hp=robot.hp,
                cooldown=robot.attack_cooldown,
                alive=robot.alive,
            )
            for robot in match.robots
        }
        self.structures = {
            structure.id: VisualStructureState(
                hp=structure.hp,
                shield=parse_virtual_shield(structure_statuses.get(structure.id, "")),
            )
            for structure in match.structures
        }
        self.outpost_rotors = {
            outpost.id: OutpostRotorVisualState(direction=rotation_direction)
            for outpost in outposts
        }
        self.projectiles.clear()
        self.impacts.clear()
        self.move_markers.clear()
        self.shake_remaining = 0.0
        self.shake_duration = 0.0
        self.shake_amplitude = 0.0
        self.shake_cooldown_remaining = 0.0
        self._before_cooldowns.clear()
        self._before_structure_shields.clear()

    def begin_frame(self, match: "Match") -> None:
        self._before_cooldowns = {
            robot.id: robot.attack_cooldown for robot in match.robots
        }
        structure_statuses = self._structure_statuses(match)
        self._before_structure_shields = {}
        for robot in match.robots:
            self.robots.setdefault(
                robot.id,
                VisualRobotState(
                    position=robot.position,
                    hp=robot.hp,
                    cooldown=robot.attack_cooldown,
                    alive=robot.alive,
                ),
            )
        for structure in match.structures:
            state = self.structures.setdefault(
                structure.id,
                VisualStructureState(
                    hp=structure.hp,
                    shield=parse_virtual_shield(
                        structure_statuses.get(structure.id, "")
                    ),
                ),
            )
            self._before_structure_shields[structure.id] = state.shield

    def add_move_marker(self, position: tuple[float, float]) -> None:
        self.move_markers.append(MoveMarker(position=position))

    def trigger_screen_shake(self, amplitude: float, duration: float) -> None:
        if self.shake_cooldown_remaining > 0:
            return
        amplitude = min(MAX_SCREEN_SHAKE_AMPLITUDE, max(0.0, amplitude))
        duration = min(MAX_SCREEN_SHAKE_DURATION, max(0.0, duration))
        if amplitude <= 0 or duration <= 0:
            return
        self.shake_amplitude = max(self.shake_amplitude, amplitude)
        self.shake_duration = max(self.shake_duration, duration)
        self.shake_remaining = max(self.shake_remaining, duration)
        self.shake_cooldown_remaining = SCREEN_SHAKE_COOLDOWN

    def screen_shake_offset(self) -> tuple[int, int]:
        if self.shake_remaining <= 0 or self.shake_duration <= 0:
            return (0, 0)
        envelope = min(1.0, self.shake_remaining / self.shake_duration)
        elapsed = self.shake_duration - self.shake_remaining
        magnitude = self.shake_amplitude * envelope
        return (
            round(math.sin(elapsed * 92.0) * magnitude),
            round(math.cos(elapsed * 73.0) * magnitude * 0.72),
        )

    def after_match_update(self, match: "Match", dt: float) -> None:
        dt = max(0.0, dt)
        self._advance_outpost_rotors(match)
        self.shake_remaining = max(0.0, self.shake_remaining - dt)
        self.shake_cooldown_remaining = max(
            0.0,
            self.shake_cooldown_remaining - dt,
        )
        if self.shake_remaining <= 0:
            self.shake_duration = 0.0
            self.shake_amplitude = 0.0

        robot_by_id = {robot.id: robot for robot in match.robots}
        structure_by_id = {
            structure.id: structure for structure in match.structures
        }
        structure_statuses = self._structure_statuses(match)
        current_shields = {
            structure.id: parse_virtual_shield(
                structure_statuses.get(structure.id, "")
            )
            for structure in match.structures
        }
        shield_drops = {
            structure_id
            for structure_id, previous in self._before_structure_shields.items()
            if current_shields.get(structure_id, 0) < previous
        }
        damage_events = {
            event.attacker_id: event
            for event in match.current_events
            if event.attacker_id is not None
            and event.type
            in {
                MatchEventType.ROBOT_DAMAGED,
                MatchEventType.STRUCTURE_DAMAGED,
            }
        }

        for robot in match.robots:
            state = self.robots.setdefault(
                robot.id,
                VisualRobotState(
                    position=robot.position,
                    hp=robot.hp,
                    cooldown=robot.attack_cooldown,
                    alive=robot.alive,
                ),
            )
            previous_hp = state.hp
            state.advance_motion(robot.position, dt)
            if robot.aerial:
                state.hp = robot.hp
                state.alive = robot.alive
                state.destroy_remaining = 0.0
                state.respawn_remaining = 0.0
            else:
                state.register_damage(previous_hp, robot.hp)
                state.register_lifecycle(robot.alive)

        for structure in match.structures:
            state = self.structures.setdefault(
                structure.id,
                VisualStructureState(
                    hp=structure.hp,
                    shield=current_shields.get(structure.id, 0),
                ),
            )
            state.hp = structure.hp
            state.shield = current_shields.get(structure.id, 0)

        for robot in match.robots:
            previous = self._before_cooldowns.get(robot.id, robot.attack_cooldown)
            expected_without_shot = max(0.0, previous - dt)
            committed = robot.attack_cooldown > expected_without_shot + 1e-6
            if not committed:
                continue

            event = damage_events.get(robot.id)
            target_id, target_position = self._target_from_event(match, event)
            damaging = event is not None
            if target_position is None:
                target_id, target_position = self._infer_visual_target(match, robot.id)
            if target_position is None:
                continue

            caliber = self._caliber_for_robot(match, robot.id)
            profile = projectile_visual_profile(caliber)
            state = self.robots[robot.id]
            state.target_position = target_position
            state.target_hold_remaining = max(0.30, profile.lifetime + 0.12)
            state.muzzle_remaining = profile.flash_duration
            state.muzzle_caliber = caliber
            self.projectiles.append(
                VisualProjectile(
                    start=robot.position,
                    end=target_position,
                    caliber=caliber,
                    attacker_team_id=robot.team,
                    target_id=target_id,
                    damaging=damaging,
                    shielded=target_id in shield_drops,
                )
            )

        for state in self.robots.values():
            state.advance_turret(dt)
            state.advance_timers(dt)
        for state in self.structures.values():
            state.advance_timers(dt)

        active_projectiles: list[VisualProjectile] = []
        for projectile in self.projectiles:
            projectile.advance(dt)
            if not projectile.expired:
                active_projectiles.append(projectile)
                continue
            if projectile.target_id is None:
                continue

            profile = projectile.profile
            target_kind = (
                "structure"
                if projectile.target_id in structure_by_id
                else "robot"
            )
            self.impacts.append(
                ImpactEffect(
                    position=projectile.end,
                    caliber=projectile.caliber,
                    remaining=(
                        SHIELD_IMPACT_DURATION
                        if projectile.shielded
                        else profile.impact_duration
                    ),
                    duration=(
                        SHIELD_IMPACT_DURATION
                        if projectile.shielded
                        else profile.impact_duration
                    ),
                    shielded=projectile.shielded,
                    target_kind=target_kind,
                )
            )

            if projectile.target_id in self.robots:
                target_state = self.robots[projectile.target_id]
                target_state.impact_remaining = max(
                    target_state.impact_remaining,
                    profile.impact_duration,
                )
                target_state.impact_caliber = projectile.caliber
            elif projectile.target_id in self.structures:
                target_state = self.structures[projectile.target_id]
                if projectile.shielded:
                    target_state.shield_impact_remaining = max(
                        target_state.shield_impact_remaining,
                        SHIELD_IMPACT_DURATION,
                    )
                else:
                    target_state.impact_remaining = max(
                        target_state.impact_remaining,
                        profile.impact_duration,
                    )
                    target_state.impact_caliber = projectile.caliber

            if projectile.caliber == "42mm" or target_kind == "structure":
                amplitude = 1.55 if projectile.caliber == "42mm" else 0.65
                if target_kind == "structure":
                    amplitude += 0.35
                self.trigger_screen_shake(amplitude, 0.11)

        self.projectiles = active_projectiles

        for impact in self.impacts:
            impact.advance(dt)
        self.impacts = [impact for impact in self.impacts if impact.remaining > 0]

        for marker in self.move_markers:
            marker.advance(dt)
        self.move_markers = [
            marker for marker in self.move_markers if marker.remaining > 0
        ]

        for robot_id, robot in robot_by_id.items():
            self.robots[robot_id].cooldown = robot.attack_cooldown

    def _advance_outpost_rotors(self, match: "Match") -> None:
        bases_by_team = {
            structure.team: structure
            for structure in match.structures
            if structure.type == "base"
        }
        for outpost in match.structures:
            if outpost.type != "outpost":
                continue
            rotor = self.outpost_rotors.setdefault(
                outpost.id,
                OutpostRotorVisualState(direction=1),
            )
            opponent_base = next(
                (
                    base
                    for team_id, base in bases_by_team.items()
                    if team_id != outpost.team
                ),
                None,
            )
            rotor.advance(
                match.elapsed_time,
                alive=outpost.alive,
                opponent_base_hp=(
                    opponent_base.hp if opponent_base is not None else 5000
                ),
            )

    @staticmethod
    def _structure_statuses(match: "Match") -> dict[str, str]:
        display_state = match.ruleset.display_state
        if display_state is None:
            return {}
        return {
            structure_id: status
            for structure_id, _hp, _max_hp, status
            in getattr(display_state, "structure_statuses", ())
        }

    @staticmethod
    def _target_from_event(
        match: "Match",
        event: MatchEvent | None,
    ) -> tuple[str | None, tuple[float, float] | None]:
        if event is None:
            return None, None
        if event.robot_id is not None:
            target = next(
                (robot for robot in match.robots if robot.id == event.robot_id),
                None,
            )
            return (
                (target.id, target.position)
                if target is not None
                else (event.robot_id, None)
            )
        if event.structure_id is not None:
            target = next(
                (
                    structure
                    for structure in match.structures
                    if structure.id == event.structure_id
                ),
                None,
            )
            return (
                (target.id, target.position)
                if target is not None
                else (event.structure_id, None)
            )
        return None, None

    @staticmethod
    def _infer_visual_target(
        match: "Match",
        attacker_id: str,
    ) -> tuple[str | None, tuple[float, float] | None]:
        attacker = next(
            (robot for robot in match.robots if robot.id == attacker_id),
            None,
        )
        if attacker is None:
            return None, None

        candidates = []
        for target in [*match.robots, *match.structures]:
            if target.team == attacker.team:
                continue
            if math.dist(attacker.position, target.position) > attacker.attack_range:
                continue
            if not match.map.has_line_of_sight(
                attacker.position,
                target.position,
                (
                    target.id
                    if any(item is target for item in match.structures)
                    else None
                ),
            ):
                continue
            if target.alive and not match.ruleset.can_target(target):
                continue
            candidates.append(target)
        if not candidates:
            return None, None
        target = min(
            candidates,
            key=lambda item: (math.dist(attacker.position, item.position), item.id),
        )
        return target.id, target.position

    @staticmethod
    def _caliber_for_robot(match: "Match", robot_id: str) -> str:
        display_state = match.ruleset.display_state
        if display_state is not None:
            for item_robot_id, projectile, _count in display_state.robot_projectiles:
                if item_robot_id == robot_id:
                    return projectile
        robot = next(
            (item for item in match.robots if item.id == robot_id),
            None,
        )
        return "42mm" if robot is not None and robot.type == "hero" else "17mm"
