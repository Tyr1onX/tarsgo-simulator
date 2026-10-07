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
from tarsgo_simulator.core.structure import Structure
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

            target = _nearest_visible_target(
                shooter,
                robot_targets,
                structure_targets,
                game_map,
                can_target,
                min(shooter.attack_range, parameters.effective_range),
            )
            if target is None:
                shooter.aim_target_id = None
                shooter.aim_point = None
                shooter.chassis_angular_velocity = 0.0
                _face_motion(shooter, step, aim_parameters_for(shooter).turret_turn_rate)
                continue

            target_velocity = (
                target.velocity if isinstance(target, Robot) else (0.0, 0.0)
            )
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

            candidates: list[tuple[float, str, Robot | Structure]] = []
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
            if not candidates:
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
            )
            if collision is not None:
                fraction, target, target_kind, normal, surface, armor_face = collision
                point = (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                )
                applied = 0
                outcome = "obstacle" if target is None else "friendly_contact"
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
                if target is not None and target.team != projectile.shooter_team_id:
                    shooter = robot_by_id.get(projectile.shooter_id)
                    impact_speed = abs(
                        projectile.velocity[0] * normal[0]
                        + projectile.velocity[1] * normal[1]
                    )
                    required_speed = 12_000.0 if projectile.caliber == "17mm" else 10_000.0
                    if target_kind == "robot" and surface != "armor":
                        outcome = "non_armor"
                    elif shooter is None or impact_speed <= required_speed:
                        outcome = "ineffective"
                    else:
                        hp_before = target.hp
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
                    )
                )
                self.total_impacts += 1
                continue

            projectile.position = end
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
) -> tuple[float, DamageableTarget | None, str, tuple[float, float], str, str | None] | None:
    candidates: list[
        tuple[float, int, str, DamageableTarget | None, tuple[float, float], str, str | None]
    ] = []
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
            candidates.append((fraction, 0, robot.id, robot, normal, surface, armor_face))

    for structure in structures:
        if not structure.alive or structure.footprint is None:
            continue
        hit = _structure_contact(start, end, projectile_radius, structure)
        if hit is not None:
            fraction, normal = hit
            candidates.append((fraction, 1, structure.id, structure, normal, "structure", None))

    for index, obstacle in enumerate(game_map.obstacles):
        hit = _rectangle_contact(start, end, projectile_radius, obstacle)
        if hit is not None:
            fraction, normal = hit
            candidates.append((fraction, 2, f"obstacle-{index:04d}", None, normal, "obstacle", None))

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
        candidates.append((fraction, 3, "field-boundary", None, normal, "obstacle", None))

    if not candidates:
        return None
    fraction, _priority, _identity, target, normal, surface, armor_face = min(candidates)
    target_kind = "robot" if isinstance(target, Robot) else (
        "structure" if isinstance(target, Structure) else "obstacle"
    )
    return fraction, target, target_kind, normal, surface, armor_face


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
) -> tuple[float, tuple[float, float]] | None:
    width, height = structure.footprint or (0.0, 0.0)
    if structure.footprint_shape == "circle":
        hit = _moving_circle_contact(start, end, structure.position, width / 2 + radius)
        if hit is None:
            return None
        fraction, point = hit
        return fraction, _unit_vector(
            point[0] - structure.position[0], point[1] - structure.position[1]
        )
    if structure.footprint_shape == "polygon" and len(structure.footprint_vertices) >= 3:
        vertices = tuple(
            (structure.position[0] + x, structure.position[1] + y)
            for x, y in structure.footprint_vertices
        )
        hit = _polygon_contact(start, end, vertices, radius)
        if hit is not None:
            return hit
    bounds = Rectangle(
        structure.position[0] - width / 2,
        structure.position[1] - height / 2,
        width,
        height,
    )
    return _rectangle_contact(start, end, radius, bounds)


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
