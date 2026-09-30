"""Small desktop-only visual feedback state for the Pygame front end."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING

from tarsgo_simulator.core.events import MatchEvent, MatchEventType

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
    "hero": RobotVisualProfile(38, 26, 10, 30, 6),
    "engineer": RobotVisualProfile(30, 30, 0, 0, 0, tool_arm_length=20),
    "infantry": RobotVisualProfile(27, 20, 7, 23, 3),
    "sentry": RobotVisualProfile(42, 24, 9, 26, 4),
}

PROJECTILE_VISUAL_PROFILES = {
    "17mm": ProjectileVisualProfile("17mm", 0.10, 2, 2, 0.055, 0.12),
    "42mm": ProjectileVisualProfile("42mm", 0.18, 5, 4, 0.090, 0.20),
}


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
    body_angle: float = 0.0
    turret_angle: float = 0.0
    target_position: tuple[float, float] | None = None
    target_hold_remaining: float = 0.0
    muzzle_remaining: float = 0.0
    muzzle_caliber: str = "17mm"
    impact_remaining: float = 0.0
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

    def ghost_hp(self, current_hp: int) -> float:
        if self.ghost_remaining <= 0 or self.ghost_from_hp <= current_hp:
            return float(current_hp)
        ratio = min(1.0, self.ghost_remaining / self.ghost_duration)
        return current_hp + (self.ghost_from_hp - current_hp) * ratio

    def advance_timers(self, dt: float) -> None:
        self.target_hold_remaining = max(0.0, self.target_hold_remaining - dt)
        self.muzzle_remaining = max(0.0, self.muzzle_remaining - dt)
        self.impact_remaining = max(0.0, self.impact_remaining - dt)
        self.ghost_remaining = max(0.0, self.ghost_remaining - dt)


@dataclass
class VisualProjectile:
    start: tuple[float, float]
    end: tuple[float, float]
    caliber: str
    attacker_team_id: str
    target_id: str | None
    damaging: bool
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
    projectiles: list[VisualProjectile] = field(default_factory=list)
    impacts: list[ImpactEffect] = field(default_factory=list)
    move_markers: list[MoveMarker] = field(default_factory=list)
    _before_cooldowns: dict[str, float] = field(default_factory=dict)

    def reset(self, match: "Match") -> None:
        self.robots = {
            robot.id: VisualRobotState(
                position=robot.position,
                hp=robot.hp,
                cooldown=robot.attack_cooldown,
            )
            for robot in match.robots
        }
        self.projectiles.clear()
        self.impacts.clear()
        self.move_markers.clear()
        self._before_cooldowns.clear()

    def begin_frame(self, match: "Match") -> None:
        self._before_cooldowns = {
            robot.id: robot.attack_cooldown for robot in match.robots
        }
        for robot in match.robots:
            self.robots.setdefault(
                robot.id,
                VisualRobotState(
                    position=robot.position,
                    hp=robot.hp,
                    cooldown=robot.attack_cooldown,
                ),
            )

    def add_move_marker(self, position: tuple[float, float]) -> None:
        self.move_markers.append(MoveMarker(position=position))

    def after_match_update(self, match: "Match", dt: float) -> None:
        robot_by_id = {robot.id: robot for robot in match.robots}
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
                ),
            )
            previous_hp = state.hp
            state.advance_motion(robot.position, dt)
            state.register_damage(previous_hp, robot.hp)

        for robot in match.robots:
            previous = self._before_cooldowns.get(robot.id, robot.attack_cooldown)
            expected_without_shot = max(0.0, previous - max(0.0, dt))
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
                )
            )

        for state in self.robots.values():
            state.advance_turret(dt)
            state.advance_timers(dt)

        active_projectiles: list[VisualProjectile] = []
        for projectile in self.projectiles:
            projectile.advance(dt)
            if not projectile.expired:
                active_projectiles.append(projectile)
                continue
            if projectile.damaging:
                profile = projectile.profile
                self.impacts.append(
                    ImpactEffect(
                        position=projectile.end,
                        caliber=projectile.caliber,
                        remaining=profile.impact_duration,
                        duration=profile.impact_duration,
                    )
                )
                if projectile.target_id in self.robots:
                    self.robots[projectile.target_id].impact_remaining = max(
                        self.robots[projectile.target_id].impact_remaining,
                        profile.impact_duration,
                    )
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
            if not match.map.has_line_of_sight(attacker.position, target.position):
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
