"""Deterministic direct-damage combat for the V0 slice."""

import math

from tarsgo_simulator.core.robot import Robot


def update_combat(robots: list[Robot]) -> None:
    """Let each living robot attack the only opposing living robot in range."""
    for attacker in robots:
        if not attacker.alive or attacker.attack_cooldown > 0:
            continue

        target = next(
            (robot for robot in robots if robot.alive and robot.team != attacker.team),
            None,
        )
        if target is None:
            continue
        if _distance(attacker.position, target.position) > attacker.attack_range:
            continue

        target.take_damage(attacker.damage)
        attacker.attack_cooldown = attacker.attack_interval


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])
