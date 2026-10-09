"""Small, immutable facts emitted by the match simulation."""

from dataclasses import dataclass
from enum import StrEnum


class MatchEventType(StrEnum):
    ROBOT_DAMAGED = "robot_damaged"
    ROBOT_DESTROYED = "robot_destroyed"
    STRUCTURE_DAMAGED = "structure_damaged"
    STRUCTURE_DESTROYED = "structure_destroyed"


class ZoneEventType(StrEnum):
    ENTERED = "entered"
    STAYED = "stayed"
    EXITED = "exited"


class RFIDReadSource(StrEnum):
    # V1.4.0 does not publish card footprints or a reader timing model. This
    # event records the simulator's deterministic projected-zone assumption.
    SIMULATED_ZONE_ENTRY = "simulated_zone_entry"


@dataclass(frozen=True)
class ZoneEvent:
    type: ZoneEventType
    time: float
    robot_id: str
    team_id: str
    zone_id: str
    cause: str = "movement"


@dataclass(frozen=True)
class RFIDReadEvent:
    time: float
    robot_id: str
    team_id: str
    zone_id: str
    source: RFIDReadSource = RFIDReadSource.SIMULATED_ZONE_ENTRY
    approximate: bool = True


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
