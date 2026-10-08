"""Battle-report statistics reduced from match combat events."""

from dataclasses import dataclass
from typing import Iterable, Mapping

from tarsgo_simulator.core.events import MatchEvent, MatchEventType
from tarsgo_simulator.core.robot import Robot
from tarsgo_simulator.core.structure import Structure


@dataclass(frozen=True, slots=True)
class RobotBattleStats:
    robot_id: str
    team_id: str
    robot_type: str
    damage_dealt: int
    virtual_shield_absorbed: int
    kills: int
    deaths: int
    level: int | None
    experience: float | None


@dataclass(frozen=True, slots=True)
class TeamBattleStats:
    team_id: str
    damage_dealt: int
    virtual_shield_absorbed: int
    base_hp: int | None
    base_max_hp: int | None
    outpost_hp: int | None
    outpost_max_hp: int | None


@dataclass(frozen=True, slots=True)
class BattleReport:
    elapsed_seconds: float
    winner_id: str | None
    teams: tuple[TeamBattleStats, ...]
    robots: tuple[RobotBattleStats, ...]


@dataclass(slots=True)
class _RobotTotals:
    damage_dealt: int = 0
    virtual_shield_absorbed: int = 0
    kills: int = 0
    deaths: int = 0


@dataclass(slots=True)
class _TeamTotals:
    damage_dealt: int = 0
    virtual_shield_absorbed: int = 0


class BattleStatistics:
    """Count each emitted combat fact once; never infer damage from HP deltas."""

    def __init__(self, robots: Iterable[Robot]) -> None:
        roster = tuple(robots)
        self._robot_metadata = {
            robot.id: (robot.team, robot.type) for robot in roster
        }
        self._robots = {robot.id: _RobotTotals() for robot in roster}
        self._teams = {
            robot.team: _TeamTotals()
            for robot in roster
        }

    def record(self, event: MatchEvent) -> None:
        if event.type in {
            MatchEventType.ROBOT_DAMAGED,
            MatchEventType.STRUCTURE_DAMAGED,
        }:
            attacker_team = event.attacker_team_id
            if (
                attacker_team in self._teams
                and attacker_team != event.team_id
            ):
                team = self._teams[attacker_team]
                team.damage_dealt += max(0, event.damage)
                team.virtual_shield_absorbed += max(
                    0,
                    event.virtual_shield_absorbed,
                )

                attacker = self._robots.get(event.attacker_id or "")
                metadata = self._robot_metadata.get(event.attacker_id or "")
                if metadata is not None and metadata[0] == attacker_team:
                    attacker.damage_dealt += max(0, event.damage)
                    attacker.virtual_shield_absorbed += max(
                        0,
                        event.virtual_shield_absorbed,
                    )
            return

        if event.type == MatchEventType.ROBOT_DESTROYED:
            victim = self._robots.get(event.robot_id or "")
            if victim is not None:
                victim.deaths += 1
            attacker = self._robots.get(event.attacker_id or "")
            attacker_metadata = self._robot_metadata.get(event.attacker_id or "")
            if (
                attacker is not None
                and attacker_metadata is not None
                and attacker_metadata[0] == event.attacker_team_id
                and event.attacker_team_id != event.team_id
            ):
                attacker.kills += 1

    def snapshot(
        self,
        *,
        elapsed_seconds: float,
        winner_id: str | None,
        structures: Iterable[Structure],
        progression: Mapping[str, tuple[int, float]],
    ) -> BattleReport:
        structure_by_team_and_type = {
            (structure.team, structure.type): structure
            for structure in structures
        }
        teams = []
        for team_id, totals in sorted(self._teams.items()):
            base = structure_by_team_and_type.get((team_id, "base"))
            outpost = structure_by_team_and_type.get((team_id, "outpost"))
            teams.append(
                TeamBattleStats(
                    team_id=team_id,
                    damage_dealt=totals.damage_dealt,
                    virtual_shield_absorbed=totals.virtual_shield_absorbed,
                    base_hp=base.hp if base is not None else None,
                    base_max_hp=base.max_hp if base is not None else None,
                    outpost_hp=outpost.hp if outpost is not None else None,
                    outpost_max_hp=outpost.max_hp if outpost is not None else None,
                )
            )

        robots = []
        for robot_id, (team_id, robot_type) in sorted(self._robot_metadata.items()):
            totals = self._robots[robot_id]
            level_state = progression.get(robot_id)
            robots.append(
                RobotBattleStats(
                    robot_id=robot_id,
                    team_id=team_id,
                    robot_type=robot_type,
                    damage_dealt=totals.damage_dealt,
                    virtual_shield_absorbed=totals.virtual_shield_absorbed,
                    kills=totals.kills,
                    deaths=totals.deaths,
                    level=level_state[0] if level_state is not None else None,
                    experience=level_state[1] if level_state is not None else None,
                )
            )
        return BattleReport(
            elapsed_seconds=max(0.0, elapsed_seconds),
            winner_id=winner_id,
            teams=tuple(teams),
            robots=tuple(robots),
        )
