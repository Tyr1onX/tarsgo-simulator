"""Deterministic direct-damage combat for the V0 slice."""

import math
from collections.abc import Callable

from tarsgo_simulator.core.map import GameMap
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure


def update_combat(
    robots: list[Robot],
    game_map: GameMap,
    *,
    can_attack: Callable[[Robot], bool],
    apply_damage: Callable[[Robot | Structure, int, Robot], int],
    structures: list[Structure] | None = None,
    can_target: Callable[[Robot | Structure], bool] | None = None,
    on_attack_committed: Callable[[Robot], None] | None = None,
) -> None:
    """Let each robot attack its nearest visible legal enemy target in range."""
    attacks: list[tuple[Robot, Robot | Structure, int]] = []
    for attacker in robots:
        if not can_attack(attacker) or attacker.attack_cooldown > 0:
            continue

        targets = [
            target
            for target in [*robots, *(structures or [])]
            if target.alive
            and target.team != attacker.team
            and (can_target is None or can_target(target))
            and _distance(attacker.position, target.position) <= attacker.attack_range
            and game_map.has_line_of_sight(attacker.position, target.position)
        ]
        if not targets:
            continue
        target = min(
            targets,
            key=lambda target: (_distance(attacker.position, target.position), target.id),
        )

        attacker.attack_cooldown = attacker.attack_interval
        attacks.append((attacker, target, attacker.damage))
        if on_attack_committed is not None:
            on_attack_committed(attacker)

    # All attacks are chosen before damage is applied, preserving same-frame
    # attacks even when one robot is destroyed by another intent.
    attacks.sort(key=lambda attack: (attack[1].id, attack[0].id))
    for attacker, target, damage in attacks:
        apply_damage(target, damage, attacker)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])
