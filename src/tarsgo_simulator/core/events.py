"""Small, immutable facts emitted by the match simulation."""

from dataclasses import dataclass
from enum import StrEnum


class MatchEventType(StrEnum):
    ROBOT_DAMAGED = "robot_damaged"
    ROBOT_DESTROYED = "robot_destroyed"
    STRUCTURE_DAMAGED = "structure_damaged"
    STRUCTURE_DESTROYED = "structure_destroyed"


@dataclass(frozen=True)
class MatchEvent:
    type: MatchEventType
    time: float
    robot_id: str | None = None
    structure_id: str | None = None
    team_id: str | None = None
    attacker_id: str | None = None
    attacker_team_id: str | None = None
    damage: int = 0
