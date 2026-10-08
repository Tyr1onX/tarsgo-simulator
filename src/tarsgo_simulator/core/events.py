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
    # Actual HP removed after defenses and shields. Virtual shield absorption
    # is recorded separately and never counted as HP damage or experience.
    damage: int = 0
    virtual_shield_absorbed: int = 0
    award_experience: bool = True
