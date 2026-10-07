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
    "dart": ProjectileVisualProfile("dart", 0.72, 3, 3, 0.10, 0.46),
}

DESTROY_VISUAL_DURATION = 0.46
RESPAWN_VISUAL_DURATION = 0.68
SHIELD_IMPACT_DURATION = 0.20
MAX_SCREEN_SHAKE_AMPLITUDE = 2.25
MAX_SCREEN_SHAKE_DURATION = 0.14
SCREEN_SHAKE_COOLDOWN = 0.08
MAX_ACTIVE_DART_VISUALS = 8
MAX_ACTIVE_IMPACTS = 24
MAX_VISIBLE_IMPACT_PARTICLES = 384
_DART_GATE_OPENING_SECONDS = 7.0
_DART_FLIGHT_SPEED_MM_PER_SECOND = 34_000.0
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


def _interpolate_angle(previous: float, current: float, alpha: float) -> float:
    weight = min(1.0, max(0.0, alpha))
    difference = _wrap_angle(current - previous)
    return _wrap_angle(previous + difference * weight)


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
    previous_position: tuple[float, float] | None = None
    alive: bool = True
    body_angle: float = 0.0
    previous_body_angle: float = 0.0
    turret_angle: float = 0.0
    previous_turret_angle: float = 0.0
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
        *,
        chassis_angle: float | None = None,
    ) -> None:
        self.previous_position = self.position
        self.previous_body_angle = self.body_angle
        dx = new_position[0] - self.position[0]
        dy = new_position[1] - self.position[1]
        if chassis_angle is not None:
            self.body_angle = _wrap_angle(chassis_angle)
        elif math.hypot(dx, dy) > 1e-6:
            desired = math.atan2(dy, dx)
            self.body_angle = approach_angle(
                self.body_angle,
                desired,
                dt,
                response=9.0,
            )
        self.position = new_position

    def interpolated_position(self, alpha: float) -> tuple[float, float]:
        """Interpolate presentation between adjacent fixed simulation states."""
        previous = self.previous_position or self.position
        weight = min(1.0, max(0.0, alpha))
        return (
            previous[0] + (self.position[0] - previous[0]) * weight,
            previous[1] + (self.position[1] - previous[1]) * weight,
        )

    def interpolated_body_angle(self, alpha: float) -> float:
        return _interpolate_angle(
            self.previous_body_angle,
            self.body_angle,
            alpha,
        )

    def interpolated_turret_angle(self, alpha: float) -> float:
        return _interpolate_angle(
            self.previous_turret_angle,
            self.turret_angle,
            alpha,
        )

    def advance_turret(self, dt: float) -> None:
        self.previous_turret_angle = self.turret_angle
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
        opponent_base_armor_deployed: bool,
    ) -> None:
        now = max(0.0, elapsed_time)
        if self.stop_time is None:
            if not alive:
                self.stop_time = now
                self.destroyed_at_stop = True
            elif opponent_base_armor_deployed:
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


@dataclass(frozen=True)
class PhysicalProjectileVisual:
    """A presentation snapshot copied from a real simulation projectile."""

    projectile_id: int
    previous_position: tuple[float, float]
    position: tuple[float, float]
    caliber: str
    attacker_team_id: str


@dataclass
class DartVisual:
    """Presentation of a referee-recorded Dart launch; never resolves a hit."""

    team_id: str
    target_id: str | None
    start: tuple[float, float]
    end: tuple[float, float]
    duration: float
    age: float = 0.0
    missed: bool = False
    resolved: bool = False

    @property
    def progress(self) -> float:
        return min(1.0, self.age / max(1e-6, self.duration))

    @property
    def position(self) -> tuple[float, float]:
        progress = self.progress
        return (
            self.start[0] + (self.end[0] - self.start[0]) * progress,
            self.start[1] + (self.end[1] - self.start[1]) * progress,
        )

    @property
    def expired(self) -> bool:
        return self.age >= self.duration or self.missed and self.age >= 0.10

    def advance(self, dt: float) -> None:
        self.age += max(0.0, dt)


@dataclass
class DartLauncherVisualState:
    """Small presentation mirror of the existing referee Dart status."""

    ammo: int = 4
    phase: str = "locked"
    phase_remaining: float = 0.0
    target: str = ""
    gate_open: float = 0.0
    launch_pulse_remaining: float = 0.0
    launch_progress: float = 0.0

    def sync(
        self,
        ammo: int,
        phase: str,
        remaining: float,
        target: str,
        dt: float,
    ) -> None:
        self.ammo = max(0, int(ammo))
        self.phase = phase
        self.phase_remaining = max(0.0, remaining)
        self.target = target
        if phase == "opening":
            self.gate_open = min(
                1.0,
                max(0.0, 1.0 - self.phase_remaining / _DART_GATE_OPENING_SECONDS),
            )
        elif phase == "firing":
            self.gate_open = 1.0
        else:
            self.gate_open = 0.0
        self.launch_pulse_remaining = max(
            0.0,
            self.launch_pulse_remaining - max(0.0, dt),
        )
        if self.launch_pulse_remaining > 0.0:
            self.launch_progress = min(
                1.0,
                self.launch_progress + max(0.0, dt) / 0.24,
            )
        if self.launch_pulse_remaining <= 0.0:
            self.launch_progress = 0.0

    def launch(self) -> None:
        self.launch_pulse_remaining = 0.24
        self.launch_progress = 0.0


@dataclass(frozen=True)
class ImpactParticle:
    angle: float
    direction_x: float
    direction_y: float
    speed: float
    lifetime: float
    length: float
    kind: str


@dataclass
class ImpactEffect:
    position: tuple[float, float]
    caliber: str
    remaining: float
    duration: float
    shielded: bool = False
    target_kind: str = "robot"
    attacker_team_id: str = ""
    direction: tuple[float, float] = (1.0, 0.0)
    event_sequence: int = 0
    surface: str = "armor"
    outcome: str = "damage"
    particles: tuple[ImpactParticle, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        caliber = self.caliber if self.caliber in {"17mm", "42mm", "dart"} else "17mm"
        count, min_speed, max_speed, min_life, max_life, spread = {
            "17mm": (8, 220.0, 620.0, 0.07, 0.15, 2.2),
            "42mm": (18, 360.0, 980.0, 0.10, 0.28, 2.55),
            "dart": (26, 760.0, 2050.0, 0.15, 0.48, 1.95),
        }[caliber]
        if self.outcome in {"immune", "absorbed"}:
            count = max(4, count // 3)
            min_speed *= 0.45
            max_speed *= 0.62
            min_life *= 0.7
            max_life *= 0.72
            spread *= 0.78
        elif self.surface in {"wheel", "obstacle"} or self.outcome == "obstacle":
            count = max(4, count // 2)
            min_speed *= 0.58
            max_speed *= 0.70
            min_life *= 0.65
            max_life *= 0.72
        elif self.outcome == "non_armor" or self.surface == "chassis":
            count = max(4, count // 2)
            min_speed *= 0.68
            max_speed *= 0.72
            min_life *= 0.75
            max_life *= 0.78
        elif self.surface in {"structure", "dart-target"}:
            count = min(count + 4, 30)
        length_scale = {"17mm": 0.48, "42mm": 0.72, "dart": 1.35}[caliber]
        direction_angle = math.atan2(self.direction[1], self.direction[0])
        seed = (
            sum((index + 1) * ord(char) for index, char in enumerate(self.attacker_team_id))
            + round(self.position[0] / 100.0) * 37
            + round(self.position[1] / 100.0) * 101
            + self.event_sequence * 7919
        )
        particles: list[ImpactParticle] = []
        for index in range(count):
            # A golden-ratio sequence gives a stable, evenly scattered pattern
            # without allocating RNG state or changing from frame to frame.
            unit = ((index * 0.6180339887498949) + seed * 0.013) % 1.0
            speed_unit = (index * 0.4142135623730951 + seed * 0.021) % 1.0
            life_unit = (index * 0.7320508075688772 + seed * 0.017) % 1.0
            angle = direction_angle + (unit - 0.5) * spread
            if self.outcome in {"immune", "absorbed"} and index % 3 == 0:
                kind = "absorbed"
            elif index % 7 == 5 and self.surface in {"structure", "dart-target"}:
                kind = "smoke"
            elif self.surface in {"wheel", "obstacle"} and index % 2 == 0:
                kind = "debris"
            elif index % 7 in (3, 4):
                kind = "dust"
            elif index % 7 == 6:
                kind = "team"
            elif index % 3 == 0:
                kind = "metal"
            else:
                kind = "spark"
            particles.append(
                ImpactParticle(
                    angle=angle,
                    direction_x=math.cos(angle),
                    direction_y=math.sin(angle),
                    speed=min_speed + (max_speed - min_speed) * speed_unit,
                    lifetime=min_life + (max_life - min_life) * life_unit,
                    length=(45.0 + 340.0 * unit) * length_scale,
                    kind=kind,
                )
            )
        object.__setattr__(self, "particles", tuple(particles))

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
    physical_projectiles: dict[int, PhysicalProjectileVisual] = field(default_factory=dict)
    dart_launchers: dict[str, DartLauncherVisualState] = field(default_factory=dict)
    dart_projectiles: list[DartVisual] = field(default_factory=list)
    impacts: list[ImpactEffect] = field(default_factory=list)
    move_markers: list[MoveMarker] = field(default_factory=list)
    shake_remaining: float = 0.0
    shake_duration: float = 0.0
    shake_amplitude: float = 0.0
    shake_cooldown_remaining: float = 0.0
    _before_cooldowns: dict[str, float] = field(default_factory=dict)
    _before_structure_shields: dict[str, int] = field(default_factory=dict)
    _before_dart_statuses: dict[
        str, tuple[int, str, float, str, str]
    ] = field(default_factory=dict)
    _before_dart_outcome_sequences: dict[str, int] = field(default_factory=dict)

    def reset(self, match: "Match") -> None:
        structure_statuses = self._structure_statuses(match)
        dart_statuses = self._dart_statuses(match)
        outposts = [structure for structure in match.structures if structure.type == "outpost"]
        rotation_direction = secrets.choice((-1, 1))
        self.robots = {
            robot.id: VisualRobotState(
                position=robot.position,
                hp=robot.hp,
                cooldown=robot.attack_cooldown,
                alive=robot.alive,
                body_angle=robot.chassis_angle,
                previous_body_angle=robot.chassis_angle,
                turret_angle=robot.turret_angle,
                previous_turret_angle=robot.turret_angle,
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
        self.physical_projectiles.clear()
        self.dart_projectiles.clear()
        self.dart_launchers = {
            team_id: DartLauncherVisualState(
                ammo=status[0],
                phase=status[1],
                phase_remaining=status[2],
                target=status[3],
            )
            for team_id, status in dart_statuses.items()
        }
        self.impacts.clear()
        self.move_markers.clear()
        self.shake_remaining = 0.0
        self.shake_duration = 0.0
        self.shake_amplitude = 0.0
        self.shake_cooldown_remaining = 0.0
        self._before_cooldowns.clear()
        self._before_structure_shields.clear()
        self._before_dart_statuses = dart_statuses
        self._before_dart_outcome_sequences = self._dart_outcome_sequences(match)

    def begin_frame(self, match: "Match") -> None:
        self._before_cooldowns = {
            robot.id: robot.attack_cooldown for robot in match.robots
        }
        structure_statuses = self._structure_statuses(match)
        self._before_dart_statuses = self._dart_statuses(match)
        self._before_dart_outcome_sequences = self._dart_outcome_sequences(match)
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
        dart_statuses = self._dart_statuses(match)
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
            physical_aim = getattr(match, "uses_physical_projectiles", False)
            state.advance_motion(
                robot.position,
                dt,
                chassis_angle=robot.chassis_angle if physical_aim else None,
            )
            if physical_aim:
                state.previous_turret_angle = state.turret_angle
                state.turret_angle = _wrap_angle(robot.turret_angle)
                if robot.aim_point is not None:
                    state.target_position = robot.aim_point
                    state.target_hold_remaining = max(
                        state.target_hold_remaining,
                        0.30,
                    )
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
            if (
                getattr(match, "uses_physical_projectiles", False)
                and robot.aim_point is not None
            ):
                target_id, target_position = robot.aim_target_id, robot.aim_point
            if target_position is None:
                continue

            caliber = self._caliber_for_robot(match, robot.id)
            profile = projectile_visual_profile(caliber)
            state = self.robots[robot.id]
            state.target_position = target_position
            state.target_hold_remaining = max(0.30, profile.lifetime + 0.12)
            state.muzzle_remaining = profile.flash_duration
            state.muzzle_caliber = caliber
            if not getattr(match, "uses_physical_projectiles", False):
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

        self.physical_projectiles = {
            projectile.id: PhysicalProjectileVisual(
                projectile_id=projectile.id,
                previous_position=projectile.previous_position,
                position=projectile.position,
                caliber=projectile.caliber,
                attacker_team_id=projectile.shooter_team_id,
            )
            for projectile in getattr(match, "projectiles", ())
        }

        self._advance_dart_visuals(match, dart_statuses, dt)

        for state in self.robots.values():
            if not getattr(match, "uses_physical_projectiles", False):
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
                    attacker_team_id=projectile.attacker_team_id,
                    direction=(
                        projectile.end[0] - projectile.start[0],
                        projectile.end[1] - projectile.start[1],
                    ),
                    event_sequence=round(match.elapsed_time * 60),
                )
            )
            self._cap_impacts()

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

        if getattr(match, "uses_physical_projectiles", False):
            for contact in match.projectile_impacts:
                profile = projectile_visual_profile(contact.caliber)
                impact = ImpactEffect(
                    position=contact.position,
                    caliber=contact.caliber,
                    remaining=profile.impact_duration,
                    duration=profile.impact_duration,
                    target_kind=contact.target_kind,
                    attacker_team_id=contact.shooter_team_id,
                    direction=contact.direction,
                    event_sequence=contact.projectile_id,
                    surface=contact.surface,
                    outcome=contact.outcome,
                )
                self.impacts.append(impact)
                self._cap_impacts()
                if contact.target_id in self.robots and contact.outcome == "damage":
                    robot_state = self.robots[contact.target_id]
                    robot_state.impact_remaining = max(
                        robot_state.impact_remaining,
                        profile.impact_duration,
                    )
                    robot_state.impact_caliber = contact.caliber
                elif contact.target_id in self.structures and contact.outcome == "damage":
                    structure_state = self.structures[contact.target_id]
                    structure_state.impact_remaining = max(
                        structure_state.impact_remaining,
                        profile.impact_duration,
                    )
                    structure_state.impact_caliber = contact.caliber
                if contact.outcome == "damage" and (
                    contact.caliber == "42mm" or contact.target_kind == "structure"
                ):
                    amplitude = 1.55 if contact.caliber == "42mm" else 0.65
                    if contact.target_kind == "structure":
                        amplitude += 0.35
                    self.trigger_screen_shake(amplitude, 0.11)

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

    def _advance_dart_visuals(
        self,
        match: "Match",
        statuses: dict[str, tuple[int, str, float, str, str]],
        dt: float,
    ) -> None:
        bases = [structure for structure in match.structures if structure.type == "base"]
        structures_by_id = {structure.id: structure for structure in match.structures}
        outcome_events = self._dart_outcome_events(match)
        for team_id in sorted(statuses):
            ammo, phase, remaining, target_label, _result = statuses[team_id]
            launcher = self.dart_launchers.setdefault(
                team_id,
                DartLauncherVisualState(),
            )
            previous = self._before_dart_statuses.get(team_id)
            launcher.sync(ammo, phase, remaining, target_label, dt)
            if previous is not None and ammo < previous[0]:
                launcher.launch()
                target_kind = "base" if target_label == "基地" else "outpost"
                own_base = next((base for base in bases if base.team == team_id), None)
                enemy_target = next(
                    (
                        structure
                        for structure in match.structures
                        if structure.team != team_id
                        and structure.type == target_kind
                    ),
                    None,
                )
                if own_base is not None and enemy_target is not None:
                    opponent_base = next(
                        (base for base in bases if base.team != team_id),
                        None,
                    )
                    direction = (
                        1.0
                        if opponent_base is None
                        or opponent_base.position[0] >= own_base.position[0]
                        else -1.0
                    )
                    start = (
                        match.map.width * 0.025
                        if direction > 0
                        else match.map.width * 0.975,
                        match.map.height * (0.22 if direction > 0 else 0.78),
                    )
                    distance = math.hypot(
                        enemy_target.position[0] - start[0],
                        enemy_target.position[1] - start[1],
                    )
                    self.dart_projectiles.append(
                        DartVisual(
                            team_id=team_id,
                            target_id=enemy_target.id,
                            start=start,
                            end=enemy_target.position,
                            duration=max(
                                0.34,
                                min(1.15, distance / _DART_FLIGHT_SPEED_MM_PER_SECOND),
                            ),
                        )
                    )
                    if len(self.dart_projectiles) > MAX_ACTIVE_DART_VISUALS:
                        del self.dart_projectiles[
                            : len(self.dart_projectiles) - MAX_ACTIVE_DART_VISUALS
                        ]

            previous_sequence = self._before_dart_outcome_sequences.get(team_id, 0)
            for sequence, target_id, outcome in outcome_events.get(team_id, ()):
                if sequence <= previous_sequence:
                    continue
                dart = next(
                    (
                        item
                        for item in self.dart_projectiles
                        if item.team_id == team_id and not item.resolved
                    ),
                    None,
                )
                if dart is not None:
                    dart.resolved = True
                if outcome == "hit":
                    target = structures_by_id.get(target_id)
                    if target is None:
                        continue
                    own_base = next(
                        (base for base in bases if base.team == team_id),
                        None,
                    )
                    direction = (
                        (
                            target.position[0] - own_base.position[0],
                            target.position[1] - own_base.position[1],
                        )
                        if own_base is not None
                        else (1.0, 0.0)
                    )
                    duration = projectile_visual_profile("dart").impact_duration
                    self.impacts.append(
                        ImpactEffect(
                            position=target.position,
                            caliber="dart",
                            remaining=duration,
                            duration=duration,
                            target_kind="structure",
                            attacker_team_id=team_id,
                            direction=direction,
                            event_sequence=sequence,
                            surface="dart-target",
                        )
                    )
                    self._cap_impacts()
                    target_state = self.structures.get(target.id)
                    if target_state is not None:
                        target_state.impact_remaining = max(
                            target_state.impact_remaining,
                            duration,
                        )
                        target_state.impact_caliber = "dart"
                elif outcome == "miss" and dart is not None:
                    dart.missed = True

        active_darts: list[DartVisual] = []
        for dart in self.dart_projectiles:
            dart.advance(dt)
            if not dart.expired:
                active_darts.append(dart)
        self.dart_projectiles = active_darts
        self._before_dart_statuses = statuses
        self._before_dart_outcome_sequences = self._dart_outcome_sequences(match)

    def _cap_impacts(self) -> None:
        if len(self.impacts) > MAX_ACTIVE_IMPACTS:
            del self.impacts[: len(self.impacts) - MAX_ACTIVE_IMPACTS]

    @staticmethod
    def _dart_statuses(
        match: "Match",
    ) -> dict[str, tuple[int, str, float, str, str]]:
        display_state = getattr(match.ruleset, "display_state", None)
        statuses = getattr(display_state, "dart_system_statuses", ())
        return {
            team_id: (
                ammo,
                phase,
                remaining,
                target,
                result,
            )
            for team_id, ammo, _openings, phase, remaining, target, result in statuses
        }

    @staticmethod
    def _dart_outcome_events(
        match: "Match",
    ) -> dict[str, tuple[tuple[int, str, str], ...]]:
        display_state = getattr(match.ruleset, "display_state", None)
        events = getattr(display_state, "dart_outcome_events", ())
        by_team: dict[str, list[tuple[int, str, str]]] = {}
        for team_id, sequence, target_id, outcome in events:
            by_team.setdefault(team_id, []).append(
                (sequence, target_id, outcome)
            )
        return {
            team_id: tuple(sorted(team_events))
            for team_id, team_events in by_team.items()
        }

    @classmethod
    def _dart_outcome_sequences(cls, match: "Match") -> dict[str, int]:
        return {
            team_id: max(
                (sequence for sequence, _target_id, _outcome in events),
                default=0,
            )
            for team_id, events in cls._dart_outcome_events(match).items()
        }

    def _advance_outpost_rotors(self, match: "Match") -> None:
        bases_by_team = {
            structure.team: structure
            for structure in match.structures
            if structure.type == "base"
        }
        team_states = getattr(match.ruleset, "_team_states", {})
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
            opponent_base_state = (
                team_states.get(opponent_base.team)
                if opponent_base is not None
                else None
            )
            rotor.advance(
                match.elapsed_time,
                alive=outpost.alive,
                opponent_base_armor_deployed=bool(
                    getattr(opponent_base_state, "base_armor_deployed", False)
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
