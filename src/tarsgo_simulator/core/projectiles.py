"""Deterministic, swept-collision projectiles for RMUC Rules Lab matches."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import math

from tarsgo_simulator.core.map import (
    GameMap,
    Rectangle,
    _distance_to_segment,
    _point_in_polygon,
)
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.projectile_targets import (
    ProjectileAimTarget,
    ProjectileSpecialHitbox,
)
from tarsgo_simulator.core.structure import (
    Structure,
    StructureProjectileHitContext,
    StructureProjectileHitboxProfile,
)
from tarsgo_simulator.rules.protocol import (
    AimMotionParameters,
    DamageableTarget,
    ProjectileParameters,
    ProjectileRobotHitboxParameters,
)


_CHASSIS_SPIN_ROBOT_TYPES = {"hero", "infantry", "sentry"}


@dataclass(slots=True)
class Projectile:
    id: int
    shooter_id: str
    shooter_team_id: str
    caliber: str
    damage: int
    radius: float
    speed: float
    effective_range: float
    position: tuple[float, float]
    previous_position: tuple[float, float]
    velocity: tuple[float, float]
    traveled: float = 0.0
    height_mm: float | None = None
    vertical_velocity_mm_s: float = 0.0
    target_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectileImpact:
    projectile_id: int
    shooter_id: str
    shooter_team_id: str
    caliber: str
    position: tuple[float, float]
    direction: tuple[float, float]
    target_id: str | None
    target_kind: str
    applied_damage: int
    surface: str = "unknown"
    outcome: str = "damage"
    armor_face: str | None = None
    normal: tuple[float, float] = (0.0, 0.0)
    structure_hit: StructureProjectileHitContext | None = None


@dataclass(frozen=True, slots=True)
class _StructureContact:
    fraction: float
    normal: tuple[float, float]
    module_id: str | None = None
    center_hit: bool = False
    modeled_armor: bool = False


class ProjectileSystem:
    """Own live simulation projectiles; visuals consume snapshots separately."""

    def __init__(self) -> None:
        self.projectiles: list[Projectile] = []
        self.impacts: list[ProjectileImpact] = []
        self._next_id = 1
        self.max_active_projectiles = 0
        self.total_launched = 0
        self.total_impacts = 0
        self.robot_contacts = 0
        self.armor_hits = 0
        self.friendly_armor_contacts = 0
        self.nonarmor_contacts = 0
        self.misses = 0
        self.applied_damage = 0
        self._shooter_stats: dict[str, dict[str, int]] = {}

    def reset(self) -> None:
        self.projectiles.clear()
        self.impacts.clear()
        self._next_id = 1
        self.max_active_projectiles = 0
        self.total_launched = 0
        self.total_impacts = 0
        self.robot_contacts = 0
        self.armor_hits = 0
        self.friendly_armor_contacts = 0
        self.nonarmor_contacts = 0
        self.misses = 0
        self.applied_damage = 0
        self._shooter_stats.clear()

    def update_aim(
        self,
        dt: float,
        robots: list[Robot],
        structures: list[Structure],
        game_map: GameMap,
        *,
        can_target: Callable[[DamageableTarget], bool],
        parameters_for: Callable[[Robot], ProjectileParameters | None],
        aim_parameters_for: Callable[[Robot], AimMotionParameters],
        special_aim_targets: dict[str, ProjectileAimTarget] | None = None,
    ) -> None:
        """Track visible targets from current state and last-tick velocity only."""
        step = max(0.0, dt)
        robot_targets = [robot for robot in robots if robot.alive and not robot.aerial]
        structure_targets = [structure for structure in structures if structure.alive]
        for shooter in robots:
            parameters = parameters_for(shooter)
            if not shooter.alive or parameters is None:
                shooter.aim_target_id = None
                shooter.aim_point = None
                shooter.chassis_angular_velocity = 0.0
                continue

            maximum_range = min(shooter.attack_range, parameters.effective_range)
            special = (special_aim_targets or {}).get(shooter.id)
            special_is_visible = bool(
                special is not None
                and math.dist(shooter.position, special.position) <= maximum_range
                and game_map.has_line_of_sight(shooter.position, special.position)
            )
            target = (
                special
                if special_is_visible
                else _nearest_visible_target(
                    shooter,
                    robot_targets,
                    structure_targets,
                    game_map,
                    can_target,
                    maximum_range,
                )
            )
            if target is None:
                shooter.aim_target_id = None
                shooter.aim_point = None
                shooter.chassis_angular_velocity = 0.0
                _face_motion(shooter, step, aim_parameters_for(shooter).turret_turn_rate)
                continue

            target_velocity = target.velocity if isinstance(target, Robot) else (0.0, 0.0)
            aim_point = predictive_intercept_point(
                shooter.position,
                target.position,
                target_velocity,
                parameters.speed,
                min(shooter.attack_range, parameters.effective_range),
            )
            shooter.aim_target_id = target.id
            shooter.aim_point = aim_point

            motion = aim_parameters_for(shooter)
            if (
                not shooter.aerial
                and shooter.type in _CHASSIS_SPIN_ROBOT_TYPES
            ):
                shooter.chassis_angular_velocity = (
                    motion.chassis_spin_rate * shooter.chassis_spin_direction
                )
                shooter.chassis_angle = _wrap_angle(
                    shooter.chassis_angle
                    + shooter.chassis_angular_velocity * step
                )
            else:
                shooter.chassis_angular_velocity = 0.0
                _face_motion(shooter, step, motion.turret_turn_rate)

            desired_turret_angle = math.atan2(
                aim_point[1] - shooter.position[1],
                aim_point[0] - shooter.position[0],
            )
            shooter.turret_angle = _approach_angle(
                shooter.turret_angle,
                desired_turret_angle,
                motion.turret_turn_rate * step,
            )

    def launch_ready_shots(
        self,
        robots: list[Robot],
        structures: list[Structure],
        game_map: GameMap,
        *,
        can_attack: Callable[[Robot], bool],
        can_target: Callable[[DamageableTarget], bool],
        parameters_for: Callable[[Robot], ProjectileParameters | None],
        on_attack_committed: Callable[[Robot], None],
        special_aim_targets: dict[str, ProjectileAimTarget] | None = None,
    ) -> tuple[int, ...]:
        """Launch at most one projectile for each ready legal shooter."""
        robot_targets = [robot for robot in robots if robot.alive and not robot.aerial]
        structure_targets = [structure for structure in structures if structure.alive]
        launched: list[int] = []

        for shooter in robots:
            if not shooter.alive or shooter.attack_cooldown > 1e-9:
                continue
            parameters = parameters_for(shooter)
            if parameters is None or not can_attack(shooter):
                continue
            if (
                shooter.aim_target_id is not None
                and shooter.aim_target_id.startswith("small-energy:")
                and any(
                    projectile.shooter_id == shooter.id
                    and projectile.target_id is not None
                    and projectile.target_id.startswith("small-energy:")
                    for projectile in self.projectiles
                )
            ):
                # A new lamp is selected only after the previous real shot is
                # resolved. Otherwise a queued second shot could hit the now
                # unlit module and legally reset the team's sequence.
                continue

            candidates: list[
                tuple[float, str, Robot | Structure | ProjectileAimTarget]
            ] = []
            for target in [*robot_targets, *structure_targets]:
                if target.team == shooter.team or not can_target(target):
                    continue
                distance = math.dist(shooter.position, target.position)
                if distance > min(shooter.attack_range, parameters.effective_range):
                    continue
                target_structure_id = target.id if isinstance(target, Structure) else None
                if not game_map.has_line_of_sight(
                    shooter.position,
                    target.position,
                    target_structure_id,
                ):
                    continue
                candidates.append((distance, target.id, target))
            special = (special_aim_targets or {}).get(shooter.id)
            if (
                special is not None
                and math.dist(shooter.position, special.position)
                <= min(shooter.attack_range, parameters.effective_range)
                and game_map.has_line_of_sight(shooter.position, special.position)
            ):
                candidates.append(
                    (math.dist(shooter.position, special.position), special.id, special)
                )
            if not candidates:
                continue
            intended_target = next(
                (
                    target
                    for _distance, target_id, target in candidates
                    if target_id == shooter.aim_target_id
                ),
                min(candidates, key=lambda item: (item[0], item[1]))[2],
            )
            if (
                isinstance(intended_target, ProjectileAimTarget)
                and intended_target.alignment_tolerance_rad is not None
            ):
                desired_angle = math.atan2(
                    intended_target.position[1] - shooter.position[1],
                    intended_target.position[0] - shooter.position[0],
                )
                if abs(_wrap_angle(desired_angle - shooter.turret_angle)) > (
                    intended_target.alignment_tolerance_rad
                ):
                    continue
            if (
                isinstance(intended_target, ProjectileAimTarget)
                and intended_target.approach_position is not None
                and math.dist(shooter.position, intended_target.approach_position)
                > intended_target.approach_tolerance_mm
            ):
                # A special moving panel may be visible from its far side, but
                # other panels can physically intercept that shot first. The
                # Rules Lab AI must first reach the target's clear radial side.
                continue
            direction = (
                math.cos(shooter.turret_angle),
                math.sin(shooter.turret_angle),
            )
            muzzle_offset = (
                game_map.collision_radius
                + parameters.radius
                + 2.0 * game_map.unit_scale
            )
            position = (
                shooter.position[0] + direction[0] * muzzle_offset,
                shooter.position[1] + direction[1] * muzzle_offset,
            )
            projectile_id = self._next_id
            self._next_id += 1
            self.projectiles.append(
                Projectile(
                    id=projectile_id,
                    shooter_id=shooter.id,
                    shooter_team_id=shooter.team,
                    caliber=parameters.caliber,
                    damage=shooter.damage,
                    radius=parameters.radius,
                    speed=parameters.speed,
                    effective_range=max(0.0, parameters.effective_range - muzzle_offset),
                    position=position,
                    previous_position=position,
                    velocity=(
                        direction[0] * parameters.speed,
                        direction[1] * parameters.speed,
                    ),
                    height_mm=game_map.terrain_height_at(shooter.position),
                    vertical_velocity_mm_s=(
                        game_map.terrain_height_at(intended_target.position)
                        - game_map.terrain_height_at(shooter.position)
                    )
                    / max(math.dist(shooter.position, intended_target.position), 1.0)
                    * parameters.speed,
                    target_id=intended_target.id,
                )
            )
            shooter.attack_cooldown = parameters.firing_interval
            on_attack_committed(shooter)
            launched.append(projectile_id)
            shooter_stats = self._shooter_stats.setdefault(
                shooter.id,
                {"shots_fired": 0, "armor_hits": 0, "applied_damage": 0},
            )
            shooter_stats["shots_fired"] += 1

        self.total_launched += len(launched)
        self.max_active_projectiles = max(
            self.max_active_projectiles,
            len(self.projectiles),
        )
        return tuple(launched)

    def advance(
        self,
        dt: float,
        robots: list[Robot],
        structures: list[Structure],
        game_map: GameMap,
        *,
        apply_damage: Callable[[DamageableTarget, int, Robot], int],
        projectile_ids: Iterable[int] | None = None,
        robot_hitboxes: ProjectileRobotHitboxParameters | None = None,
        structure_hitbox_profile_for: Callable[
            [Structure], StructureProjectileHitboxProfile | None
        ]
        | None = None,
        apply_structure_damage: Callable[
            [Structure, int, Robot, StructureProjectileHitContext], int
        ]
        | None = None,
        special_hitboxes: Iterable[ProjectileSpecialHitbox] = (),
        on_special_hit: Callable[
            [Projectile, ProjectileSpecialHitbox, tuple[float, float], float, float],
            str,
        ]
        | None = None,
        simulation_start_time: float = 0.0,
    ) -> None:
        """Advance selected projectiles continuously and settle first contacts."""
        self.impacts.clear()
        selected = None if projectile_ids is None else set(projectile_ids)
        robot_by_id = {robot.id: robot for robot in robots}
        active: list[Projectile] = []
        for projectile in self.projectiles:
            if selected is not None and projectile.id not in selected:
                active.append(projectile)
                continue
            step = max(0.0, dt)
            remaining = projectile.effective_range - projectile.traveled
            if step <= 0 or remaining <= 1e-9:
                active.append(projectile) if remaining > 1e-9 else None
                continue
            distance = min(projectile.speed * step, remaining)
            start = projectile.position
            end = (
                start[0] + projectile.velocity[0] / projectile.speed * distance,
                start[1] + projectile.velocity[1] / projectile.speed * distance,
            )
            start_height = (
                game_map.terrain_height_at(start)
                if projectile.height_mm is None
                else projectile.height_mm
            )
            end_height = start_height + (
                projectile.vertical_velocity_mm_s / projectile.speed * distance
            )
            projectile.previous_position = start
            collision = _first_collision(
                start,
                end,
                projectile.radius,
                projectile.shooter_id,
                robots,
                structures,
                game_map,
                robot_hitboxes,
                structure_hitbox_profile_for,
                start_height_mm=start_height,
                end_height_mm=end_height,
                special_hitboxes=special_hitboxes,
            )
            if collision is not None:
                (
                    fraction,
                    target,
                    target_kind,
                    normal,
                    surface,
                    armor_face,
                    structure_module_id,
                    structure_center_hit,
                    structure_hit_modeled,
                ) = collision
                point = (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                )
                impact_speed = abs(
                    projectile.velocity[0] * normal[0]
                    + projectile.velocity[1] * normal[1]
                )
                structure_hit = None
                if isinstance(target, Structure):
                    surface_point = (
                        point[0] - projectile.radius * normal[0],
                        point[1] - projectile.radius * normal[1],
                    )
                    structure_hit = StructureProjectileHitContext(
                        module_id=structure_module_id,
                        impact_position=surface_point,
                        caliber=projectile.caliber,
                        effective_impact_speed=impact_speed,
                        center_hit=structure_center_hit,
                        normal=normal,
                    )
                applied = 0
                outcome = "obstacle" if target is None else "friendly_contact"
                if target_kind == "energy_mechanism":
                    special = target
                    if isinstance(special, ProjectileSpecialHitbox) and on_special_hit:
                        surface_point = (
                            point[0] - projectile.radius * normal[0],
                            point[1] - projectile.radius * normal[1],
                        )
                        outcome = on_special_hit(
                            projectile,
                            special,
                            surface_point,
                            impact_speed,
                            simulation_start_time + max(0.0, dt) * fraction,
                        )
                    else:
                        outcome = "energy_mechanism_contact"
                if target_kind == "robot":
                    self.robot_contacts += 1
                    if surface == "armor":
                        if target is not None and target.team != projectile.shooter_team_id:
                            self.armor_hits += 1
                            shooter_stats = self._shooter_stats.setdefault(
                                projectile.shooter_id,
                                {"shots_fired": 0, "armor_hits": 0, "applied_damage": 0},
                            )
                            shooter_stats["armor_hits"] += 1
                        else:
                            self.friendly_armor_contacts += 1
                    else:
                        self.nonarmor_contacts += 1
                    shooter_stats = self._shooter_stats.setdefault(
                        projectile.shooter_id,
                        {"shots_fired": 0, "armor_hits": 0, "applied_damage": 0},
                    )
                if (
                    target_kind != "energy_mechanism"
                    and target is not None
                    and target.team != projectile.shooter_team_id
                ):
                    shooter = robot_by_id.get(projectile.shooter_id)
                    required_speed = 12_000.0 if projectile.caliber == "17mm" else 10_000.0
                    if target_kind == "robot" and surface != "armor":
                        outcome = "non_armor"
                    elif (
                        structure_hit is not None
                        and structure_hit_modeled
                        and structure_hit.module_id is None
                    ):
                        outcome = "structure_body"
                    elif shooter is None or impact_speed <= required_speed + 1e-9:
                        outcome = "ineffective"
                    else:
                        hp_before = target.hp
                        if (
                            isinstance(target, Structure)
                            and structure_hit is not None
                            and structure_hit.module_id is not None
                            and apply_structure_damage is not None
                        ):
                            applied = apply_structure_damage(
                                target,
                                projectile.damage,
                                shooter,
                                structure_hit,
                            )
                        else:
                            applied = apply_damage(target, projectile.damage, shooter)
                        if applied > 0:
                            outcome = "damage"
                            self.applied_damage += applied
                            if target_kind == "robot":
                                shooter_stats["applied_damage"] += applied
                        elif target.hp == hp_before:
                            outcome = "immune"
                        else:
                            outcome = "absorbed"
                self.impacts.append(
                    ProjectileImpact(
                        projectile_id=projectile.id,
                        shooter_id=projectile.shooter_id,
                        shooter_team_id=projectile.shooter_team_id,
                        caliber=projectile.caliber,
                        position=point,
                        direction=projectile.velocity,
                        target_id=target.id if target is not None else None,
                        target_kind=target_kind,
                        applied_damage=applied,
                        surface=surface,
                        outcome=outcome,
                        armor_face=armor_face,
                        normal=normal,
                        structure_hit=structure_hit,
                    )
                )
                self.total_impacts += 1
                continue

            projectile.position = end
            projectile.height_mm = end_height
            projectile.traveled += distance
            if projectile.traveled + 1e-9 < projectile.effective_range:
                active.append(projectile)
            else:
                self.misses += 1

        self.projectiles = active


def predictive_intercept_point(
    shooter_position: tuple[float, float],
    target_position: tuple[float, float],
    target_velocity: tuple[float, float],
    projectile_speed: float,
    maximum_range: float,
) -> tuple[float, float]:
    """Solve a constant-velocity intercept without consulting a target path."""
    rx = target_position[0] - shooter_position[0]
    ry = target_position[1] - shooter_position[1]
    vx, vy = target_velocity
    speed = max(0.0, projectile_speed)
    a = vx * vx + vy * vy - speed * speed
    b = 2.0 * (rx * vx + ry * vy)
    c = rx * rx + ry * ry
    if speed <= 1e-9 or c <= 1e-18:
        return target_position

    times: list[float] = []
    if abs(a) <= 1e-12:
        if abs(b) > 1e-12:
            times.append(-c / b)
    else:
        discriminant = b * b - 4.0 * a * c
        if discriminant >= 0:
            root = math.sqrt(discriminant)
            times.extend(((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)))

    valid_times = [
        value
        for value in times
        if value > 1e-9 and value * speed <= max(0.0, maximum_range) + 1e-6
    ]
    if not valid_times:
        return target_position
    flight_time = min(valid_times)
    return (
        target_position[0] + vx * flight_time,
        target_position[1] + vy * flight_time,
    )


def _nearest_visible_target(
    shooter: Robot,
    robots: list[Robot],
    structures: list[Structure],
    game_map: GameMap,
    can_target: Callable[[DamageableTarget], bool],
    maximum_range: float,
) -> Robot | Structure | None:
    candidates: list[tuple[float, str, Robot | Structure]] = []
    for target in [*robots, *structures]:
        if target.id == shooter.id or target.team == shooter.team or not can_target(target):
            continue
        distance = math.dist(shooter.position, target.position)
        if distance > maximum_range:
            continue
        structure_id = target.id if isinstance(target, Structure) else None
        if not game_map.has_line_of_sight(
            shooter.position,
            target.position,
            structure_id,
        ):
            continue
        candidates.append((distance, target.id, target))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _face_motion(robot: Robot, dt: float, turn_rate: float) -> None:
    if math.hypot(*robot.velocity) <= 1e-9 or dt <= 0:
        return
    desired = math.atan2(robot.velocity[1], robot.velocity[0])
    delta = _wrap_angle(desired - robot.chassis_angle)
    maximum_delta = max(0.0, turn_rate * dt)
    delta = max(-maximum_delta, min(maximum_delta, delta))
    robot.chassis_angular_velocity = delta / dt
    robot.chassis_angle = _wrap_angle(robot.chassis_angle + delta)


def _approach_angle(current: float, target: float, maximum_delta: float) -> float:
    delta = _wrap_angle(target - current)
    delta = max(-max(0.0, maximum_delta), min(max(0.0, maximum_delta), delta))
    return _wrap_angle(current + delta)


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % math.tau - math.pi


def _first_collision(
    start: tuple[float, float],
    end: tuple[float, float],
    projectile_radius: float,
    shooter_id: str,
    robots: list[Robot],
    structures: list[Structure],
    game_map: GameMap,
    robot_hitboxes: ProjectileRobotHitboxParameters | None = None,
    structure_hitbox_profile_for: Callable[
        [Structure], StructureProjectileHitboxProfile | None
    ]
    | None = None,
    *,
    start_height_mm: float = 0.0,
    end_height_mm: float = 0.0,
    special_hitboxes: Iterable[ProjectileSpecialHitbox] = (),
) -> tuple[
    float,
    DamageableTarget | ProjectileSpecialHitbox | None,
    str,
    tuple[float, float],
    str,
    str | None,
    str | None,
    bool,
    bool,
] | None:
    candidates: list[
        tuple[
            float,
            int,
            str,
            DamageableTarget | ProjectileSpecialHitbox | None,
            tuple[float, float],
            str,
            str | None,
            str | None,
            bool,
            bool,
    ]
    ] = []
    terrain_contact = game_map.terrain_collision_fraction(
        start,
        end,
        start_height_mm,
        end_height_mm,
    )
    if terrain_contact is not None:
        candidates.append(
            (
                terrain_contact,
                2,
                "terrain",
                None,
                (0.0, 0.0),
                "obstacle",
                None,
                None,
                False,
                False,
            )
        )
    for robot in robots:
        if not robot.alive or robot.aerial or robot.id == shooter_id:
            continue
        # Conservative broad phase only. Movement collision never decides
        # whether a projectile contact is armor.
        if _distance_to_segment(robot.position, start, end) > (
            game_map.collision_radius + projectile_radius
        ):
            continue
        hit = _robot_contact(start, end, projectile_radius, robot, robot_hitboxes)
        if hit is not None:
            fraction, normal, surface, armor_face = hit
            candidates.append(
                (
                    fraction,
                    0,
                    robot.id,
                    robot,
                    normal,
                    surface,
                    armor_face,
                    None,
                    False,
                    False,
                )
            )

    for structure in structures:
        if not structure.alive or structure.footprint is None:
            continue
        profile = (
            structure_hitbox_profile_for(structure)
            if structure_hitbox_profile_for is not None
            else None
        )
        hit = _structure_contact(start, end, projectile_radius, structure, profile)
        if hit is not None:
            candidates.append(
                (
                    hit.fraction,
                    1,
                    structure.id,
                    structure,
                    hit.normal,
                    "structure",
                    None,
                    hit.module_id,
                    hit.center_hit,
                    hit.modeled_armor,
                )
            )

    for special in special_hitboxes:
        hit = _moving_circle_contact(
            start,
            end,
            special.center,
            special.radius + projectile_radius,
        )
        if hit is None:
            continue
        fraction, contact_center = hit
        normal = _unit_vector(
            contact_center[0] - special.center[0],
            contact_center[1] - special.center[1],
        )
        if normal == (0.0, 0.0):
            normal = _unit_vector(start[0] - end[0], start[1] - end[1])
        candidates.append(
            (
                fraction,
                2,
                f"{special.id}:{special.module_id}",
                special,
                normal,
                "energy_module",
                special.module_id,
                None,
                False,
                False,
            )
        )

    for index, obstacle in enumerate(game_map.obstacles):
        hit = _rectangle_contact(start, end, projectile_radius, obstacle)
        if hit is not None:
            fraction, normal = hit
            candidates.append(
                (
                    fraction,
                    2,
                    f"obstacle-{index:04d}",
                    None,
                    normal,
                    "obstacle",
                    None,
                    None,
                    False,
                    False,
                )
            )

    # The perimeter is solid for a radius-sized projectile.
    bounds = Rectangle(
        projectile_radius,
        projectile_radius,
        game_map.width - projectile_radius * 2,
        game_map.height - projectile_radius * 2,
    )
    boundary = _boundary_contact(start, end, bounds)
    if boundary is not None:
        fraction, normal = boundary
        candidates.append(
            (
                fraction,
                3,
                "field-boundary",
                None,
                normal,
                "obstacle",
                None,
                None,
                False,
                False,
            )
        )

    if not candidates:
        return None
    (
        fraction,
        _priority,
        _identity,
        target,
        normal,
        surface,
        armor_face,
        structure_module_id,
        structure_center_hit,
        structure_hit_modeled,
    ) = min(candidates)
    target_kind = (
        "robot"
        if isinstance(target, Robot)
        else "structure"
        if isinstance(target, Structure)
        else target.target_kind
        if isinstance(target, ProjectileSpecialHitbox)
        else "obstacle"
    )
    return (
        fraction,
        target,
        target_kind,
        normal,
        surface,
        armor_face,
        structure_module_id,
        structure_center_hit,
        structure_hit_modeled,
    )


def _robot_contact(
    start: tuple[float, float],
    end: tuple[float, float],
    projectile_radius: float,
    robot: Robot,
    hitboxes: ProjectileRobotHitboxParameters | None,
) -> tuple[float, tuple[float, float], str, str | None] | None:
    """Sweep against explicit armor plates and a separate non-armor frame."""
    if hitboxes is None:
        return None
    radius = hitboxes.chassis_radius
    panel_offset = hitboxes.armor_panel_offset
    panel_width = hitboxes.armor_panel_width
    panel_depth = hitboxes.armor_panel_depth
    wheel_offset = hitboxes.wheel_center_offset
    wheel_radius = hitboxes.wheel_radius

    cosine, sine = math.cos(robot.chassis_angle), math.sin(robot.chassis_angle)

    def local(point: tuple[float, float]) -> tuple[float, float]:
        dx, dy = point[0] - robot.position[0], point[1] - robot.position[1]
        return dx * cosine + dy * sine, -dx * sine + dy * cosine

    def world_normal(normal: tuple[float, float]) -> tuple[float, float]:
        return (
            normal[0] * cosine - normal[1] * sine,
            normal[0] * sine + normal[1] * cosine,
        )

    local_start, local_end = local(start), local(end)
    contacts: list[tuple[float, int, tuple[float, float], str, str | None]] = []
    frame_hit = _moving_circle_contact(
        local_start,
        local_end,
        (0.0, 0.0),
        radius + projectile_radius,
    )
    if frame_hit is not None:
        fraction, point = frame_hit
        contacts.append(
            (
                fraction,
                1,
                world_normal(_unit_vector(point[0], point[1])),
                "chassis",
                None,
            )
        )

    for wheel_x in (-wheel_offset, wheel_offset):
        for wheel_y in (-wheel_offset, wheel_offset):
            wheel_hit = _moving_circle_contact(
                local_start,
                local_end,
                (wheel_x, wheel_y),
                wheel_radius + projectile_radius,
            )
            if wheel_hit is not None:
                fraction, point = wheel_hit
                contacts.append(
                    (
                        fraction,
                        1,
                        world_normal(
                            _unit_vector(point[0] - wheel_x, point[1] - wheel_y)
                        ),
                        "wheel",
                        None,
                    )
                )

    half_depth, half_width = panel_depth / 2, panel_width / 2
    panels = (
        ("front", panel_offset, 0.0, half_depth, half_width),
        ("rear", -panel_offset, 0.0, half_depth, half_width),
        ("right", 0.0, panel_offset, half_width, half_depth),
        ("left", 0.0, -panel_offset, half_width, half_depth),
    )
    for face, center_x, center_y, half_x, half_y in panels:
        rectangle = Rectangle(
            center_x - half_x,
            center_y - half_y,
            half_x * 2,
            half_y * 2,
        )
        hit = _rectangle_contact(local_start, local_end, projectile_radius, rectangle)
        if hit is not None:
            fraction, normal = hit
            contacts.append((fraction, 0, world_normal(normal), "armor", face))

    if not contacts:
        return None
    fraction, _priority, normal, surface, face = min(
        contacts,
        key=lambda item: (item[0], item[1], item[4] or ""),
    )
    return fraction, normal, surface, face


def _structure_contact(
    start: tuple[float, float],
    end: tuple[float, float],
    radius: float,
    structure: Structure,
    profile: StructureProjectileHitboxProfile | None = None,
) -> _StructureContact | None:
    width, height = structure.footprint or (0.0, 0.0)
    module_contacts: list[tuple[float, int, str, tuple[float, float], bool]] = []
    if profile is not None and structure.type == "outpost" and profile.armor_panels:
        # The rulebook does not give the middle armor's full 2D footprint or
        # height. Its shared projected panel polygons are an explicit 2.5D
        # approximation and are allowed to sit above the circular body.
        for panel_index, panel in enumerate(profile.armor_panels):
            vertices = tuple(
                (
                    structure.position[0] + x,
                    structure.position[1] + y,
                )
                for x, y in panel.vertices
            )
            panel_hit = _polygon_contact(start, end, vertices, radius)
            if panel_hit is None:
                continue
            fraction, normal = panel_hit
            path_position = (
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
            impact_position = (
                path_position[0] - radius * normal[0],
                path_position[1] - radius * normal[1],
            )
            center_x = structure.position[0] + panel.center[0]
            center_y = structure.position[1] + panel.center[1]
            offset_x = impact_position[0] - center_x
            offset_y = impact_position[1] - center_y
            along = (
                offset_x * panel.long_axis[0]
                + offset_y * panel.long_axis[1]
            )
            # The official 10×10 mm center is on the vertical armor face.
            # This plan projection has no vertical axis, so only its mapped
            # horizontal face axis is tested; projectile radius expands it.
            center_hit = (
                abs(along) <= profile.center_area_size_mm / 2 + radius + 1e-9
            )
            module_contacts.append(
                (fraction, panel_index, panel.module_id, normal, center_hit)
            )
    if profile is not None and structure.footprint_shape == "polygon":
        vertices = structure.footprint_vertices
        if len(vertices) >= 3:
            area_twice = sum(
                first[0] * second[1] - second[0] * first[1]
                for first, second in zip(vertices, (*vertices[1:], vertices[0]))
            )
            for edge_index, (local_start, local_end) in enumerate(
                zip(vertices, (*vertices[1:], vertices[0]))
            ):
                edge_start = (
                    structure.position[0] + local_start[0],
                    structure.position[1] + local_start[1],
                )
                edge_end = (
                    structure.position[0] + local_end[0],
                    structure.position[1] + local_end[1],
                )
                tangent = _unit_vector(
                    edge_end[0] - edge_start[0], edge_end[1] - edge_start[1]
                )
                if tangent == (0.0, 0.0):
                    continue
                outward = (
                    (tangent[1], -tangent[0])
                    if area_twice > 0
                    else (-tangent[1], tangent[0])
                )
                edge_length = math.dist(edge_start, edge_end)
                half_width = min(profile.module_width_mm / 2, edge_length / 2)
                offset = profile.deployed_offset_mm if profile.deployed else 0.0
                center = (
                    (edge_start[0] + edge_end[0]) / 2 + outward[0] * offset,
                    (edge_start[1] + edge_end[1]) / 2 + outward[1] * offset,
                )
                # Armor is a 129 mm planar face segment. The 1 mm collider
                # thickness only stabilizes swept-circle contact; the actual
                # deployed extension is provided by the Rules Lab profile.
                half_thickness = 0.5
                panel = tuple(
                    (
                        center[0] + tangent[0] * along + outward[0] * normal,
                        center[1] + tangent[1] * along + outward[1] * normal,
                    )
                    for along, normal in (
                        (-half_width, -half_thickness),
                        (half_width, -half_thickness),
                        (half_width, half_thickness),
                        (-half_width, half_thickness),
                    )
                )
                panel_hit = _polygon_contact(start, end, panel, radius)
                if panel_hit is None:
                    continue
                fraction, normal = panel_hit
                path_position = (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                )
                impact_position = (
                    path_position[0] - radius * normal[0],
                    path_position[1] - radius * normal[1],
                )
                along_center = (
                    (impact_position[0] - center[0]) * tangent[0]
                    + (impact_position[1] - center[1]) * tangent[1]
                )
                module_id = (
                    "base-upper-front"
                    if edge_index == profile.upper_front_edge_index
                    else f"base-armor-{edge_index + 1}"
                )
                module_contacts.append(
                    (
                        fraction,
                        edge_index,
                        module_id,
                        normal,
                        abs(along_center)
                        <= profile.center_area_size_mm / 2 + 1e-9,
                    )
                )

    if structure.footprint_shape == "circle":
        hit = _moving_circle_contact(start, end, structure.position, width / 2 + radius)
        if hit is None:
            body_contact = None
        else:
            fraction, point = hit
            body_contact = _StructureContact(
                fraction,
                _unit_vector(
                    point[0] - structure.position[0], point[1] - structure.position[1]
                ),
            )
    elif structure.footprint_shape == "polygon" and len(structure.footprint_vertices) >= 3:
        vertices = tuple(
            (structure.position[0] + x, structure.position[1] + y)
            for x, y in structure.footprint_vertices
        )
        hit = _polygon_contact(start, end, vertices, radius)
        body_contact = (
            _StructureContact(hit[0], hit[1]) if hit is not None else None
        )
    else:
        bounds = Rectangle(
            structure.position[0] - width / 2,
            structure.position[1] - height / 2,
            width,
            height,
        )
        hit = _rectangle_contact(start, end, radius, bounds)
        body_contact = (
            _StructureContact(hit[0], hit[1]) if hit is not None else None
        )

    if not module_contacts:
        if profile is not None and body_contact is not None:
            # Preserve the pre-existing generic outpost-body damage path when
            # a projectile contacts the structure without touching a rotating
            # armor panel. Base-body contacts remain non-damaging below.
            return _StructureContact(
                body_contact.fraction,
                body_contact.normal,
                module_id=(
                    "outpost-body"
                    if structure.type == "outpost" and profile.armor_panels
                    else None
                ),
                modeled_armor=True,
            )
        return body_contact
    panel_contact = min(module_contacts, key=lambda item: (item[0], item[1]))
    if (
        body_contact is None
        or panel_contact[0] <= body_contact.fraction + 1e-9
        or (structure.type == "outpost" and profile is not None and profile.armor_panels)
    ):
        return _StructureContact(
            fraction=panel_contact[0],
            normal=panel_contact[3],
            module_id=panel_contact[2],
            center_hit=panel_contact[4],
            modeled_armor=True,
        )
    if body_contact is not None and profile is not None:
        return _StructureContact(
            body_contact.fraction,
            body_contact.normal,
            module_id=(
                "outpost-body"
                if structure.type == "outpost" and profile.armor_panels
                else None
            ),
            modeled_armor=True,
        )
    return body_contact


def _rectangle_contact(
    start: tuple[float, float],
    end: tuple[float, float],
    radius: float,
    rectangle: Rectangle,
) -> tuple[float, tuple[float, float]] | None:
    left = rectangle.x - radius
    top = rectangle.y - radius
    right = rectangle.right + radius
    bottom = rectangle.bottom + radius
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    t_min, t_max = 0.0, 1.0
    normal = (0.0, 0.0)
    for p, q, entering_normal in (
        (-dx, start[0] - left, (-1.0, 0.0)),
        (dx, right - start[0], (1.0, 0.0)),
        (-dy, start[1] - top, (0.0, -1.0)),
        (dy, bottom - start[1], (0.0, 1.0)),
    ):
        if abs(p) <= 1e-12:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            if ratio > t_min:
                t_min = ratio
                normal = entering_normal
        else:
            t_max = min(t_max, ratio)
        if t_min > t_max:
            return None
    if not 0.0 <= t_min <= 1.0:
        return None
    if normal == (0.0, 0.0):
        normal = _unit_vector(-dx, -dy)
    return t_min, normal


def _polygon_contact(
    start: tuple[float, float],
    end: tuple[float, float],
    vertices: tuple[tuple[float, float], ...],
    radius: float,
) -> tuple[float, tuple[float, float]] | None:
    if _point_in_polygon(start, vertices):
        edge = min(
            zip(vertices, (*vertices[1:], vertices[0])),
            key=lambda pair: _distance_to_segment(start, pair[0], pair[1]),
        )
        return 0.0, _edge_normal(edge[0], edge[1], vertices)

    hits: list[tuple[float, tuple[float, float]]] = []
    dx, dy = end[0] - start[0], end[1] - start[1]
    for edge_start, edge_end in zip(vertices, (*vertices[1:], vertices[0])):
        endpoint_hits = [
            _moving_circle_contact(start, end, endpoint, radius)
            for endpoint in (edge_start, edge_end)
        ]
        hits.extend(
            (fraction, _unit_vector(point[0] - endpoint[0], point[1] - endpoint[1]))
            for hit, endpoint in zip(endpoint_hits, (edge_start, edge_end))
            if hit is not None
            for fraction, point in (hit,)
        )
        ex, ey = edge_end[0] - edge_start[0], edge_end[1] - edge_start[1]
        edge_length = math.hypot(ex, ey)
        if edge_length <= 1e-9:
            continue
        nx, ny = ey / edge_length, -ex / edge_length
        for offset in (-radius, radius):
            start_distance = (start[0] - edge_start[0]) * nx + (start[1] - edge_start[1]) * ny
            velocity_normal = dx * nx + dy * ny
            if abs(velocity_normal) <= 1e-12:
                continue
            fraction = (offset - start_distance) / velocity_normal
            if not 0.0 <= fraction <= 1.0:
                continue
            point = (start[0] + dx * fraction, start[1] + dy * fraction)
            projection = ((point[0] - edge_start[0]) * ex + (point[1] - edge_start[1]) * ey) / (edge_length * edge_length)
            if 0.0 <= projection <= 1.0:
                normal = (nx, ny) if velocity_normal < 0 else (-nx, -ny)
                hits.append((fraction, normal))

    if not hits:
        return None
    return min(hits, key=lambda item: item[0])


def _moving_circle_contact(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    radius: float,
) -> tuple[float, tuple[float, float]] | None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    ox, oy = start[0] - center[0], start[1] - center[1]
    c = ox * ox + oy * oy - radius * radius
    if c <= 0:
        return 0.0, start
    a = dx * dx + dy * dy
    if a <= 1e-18:
        return None
    b = 2.0 * (ox * dx + oy * dy)
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        return None
    fraction = (-b - math.sqrt(discriminant)) / (2.0 * a)
    if not 0.0 <= fraction <= 1.0:
        return None
    return fraction, (start[0] + dx * fraction, start[1] + dy * fraction)


def _boundary_contact(
    start: tuple[float, float],
    end: tuple[float, float],
    bounds: Rectangle,
) -> tuple[float, tuple[float, float]] | None:
    if not (
        bounds.x <= start[0] <= bounds.right
        and bounds.y <= start[1] <= bounds.bottom
    ):
        return 0.0, _unit_vector(start[0] - min(max(start[0], bounds.x), bounds.right), start[1] - min(max(start[1], bounds.y), bounds.bottom))
    if (
        bounds.x <= end[0] <= bounds.right
        and bounds.y <= end[1] <= bounds.bottom
    ):
        return None
    candidates: list[tuple[float, tuple[float, float]]] = []
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx < 0:
        candidates.append(((bounds.x - start[0]) / dx, (1.0, 0.0)))
    elif dx > 0:
        candidates.append(((bounds.right - start[0]) / dx, (-1.0, 0.0)))
    if dy < 0:
        candidates.append(((bounds.y - start[1]) / dy, (0.0, 1.0)))
    elif dy > 0:
        candidates.append(((bounds.bottom - start[1]) / dy, (0.0, -1.0)))
    valid = [item for item in candidates if 0.0 <= item[0] <= 1.0]
    return min(valid, key=lambda item: item[0]) if valid else None


def _edge_normal(
    start: tuple[float, float],
    end: tuple[float, float],
    vertices: tuple[tuple[float, float], ...],
) -> tuple[float, float]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    # Pick the outward normal by checking which side contains the polygon's
    # vertex-average center; rule geometry is already supplied by the field.
    center_x = sum(point[0] for point in vertices) / len(vertices)
    center_y = sum(point[1] for point in vertices) / len(vertices)
    normal = _unit_vector(dy, -dx)
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    if (center_x - midpoint[0]) * normal[0] + (center_y - midpoint[1]) * normal[1] > 0:
        return (-normal[0], -normal[1])
    return normal


def _unit_vector(x: float, y: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    return (x / length, y / length) if length > 1e-12 else (0.0, 0.0)
