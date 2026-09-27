"""Deterministic direct-damage combat for the V0 slice."""

import math
from collections.abc import Callable

from tarsgo_simulator.core.map import GameMap
from tarsgo_simulator.core.robot import Robot


def update_combat(
    robots: list[Robot],
    game_map: GameMap,
    *,
    can_attack: Callable[[Robot], bool],
    apply_damage: Callable[[Robot, int, Robot], int],
) -> None:
    """Let each robot attack its nearest visible living enemy in range."""
    attacks: list[tuple[Robot, Robot, int]] = []
    for attacker in robots:
        if not can_attack(attacker) or attacker.attack_cooldown > 0:
            continue

        targets = [
            robot
            for robot in robots
            if robot.alive
            and robot.team != attacker.team
            and _distance(attacker.position, robot.position) <= attacker.attack_range
            and game_map.has_line_of_sight(attacker.position, robot.position)
        ]
        if not targets:
            continue
        target = min(
            targets,
            key=lambda robot: (_distance(attacker.position, robot.position), robot.id),
        )

        attacker.attack_cooldown = attacker.attack_interval
        attacks.append((attacker, target, attacker.damage))

    # All attacks are chosen before damage is applied, preserving same-frame
    # attacks even when one robot is destroyed by another intent.
    attacks.sort(key=lambda attack: (attack[1].id, attack[0].id))
    for attacker, target, damage in attacks:
        apply_damage(target, damage, attacker)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])
