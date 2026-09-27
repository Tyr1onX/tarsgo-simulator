"""Small, immutable facts emitted by the match simulation."""

from dataclasses import dataclass
from enum import StrEnum


class MatchEventType(StrEnum):
    ROBOT_DESTROYED = "robot_destroyed"


@dataclass(frozen=True)
class MatchEvent:
    type: MatchEventType
    time: float
    robot_id: str | None = None
    team_id: str | None = None
