"""Single source of truth for the V0 match state."""

import math
from pathlib import Path

from tarsgo_simulator.core.combat import update_combat
from tarsgo_simulator.core.config import MatchConfig, load_match_config
from tarsgo_simulator.core.map import GameMap
from tarsgo_simulator.core.pathfinding import find_path
from tarsgo_simulator.core.robot import MovementProposal, Robot


_OPPONENT_REPLAN_INTERVAL = 0.5


class Match:
    def __init__(self, config: MatchConfig) -> None:
        self.config = config
        self.reset()

    @classmethod
    def from_scenario(cls, scenario_path: str | Path) -> "Match":
        return cls(load_match_config(scenario_path))

    def reset(self) -> None:
        scenario = self.config.scenario
        infantry = self.config.infantry
        self.map = GameMap(
            scenario.map_width,
            scenario.map_height,
            scenario.obstacles,
            infantry.collision_radius,
        )
        self.robots: list[Robot] = []
        for side in ("red", "blue"):
            team = scenario.teams[side]
            for definition in team.robots:
                position = scenario.spawns[definition.id]
                if not self.map.is_passable(position):
                    raise ValueError(f"机器人出生点不可通行：{definition.id} at {position}")
                self.robots.append(
                    Robot(
                        id=definition.id,
                        team=team.team_id,
                        position=position,
                        hp=infantry.max_hp,
                        max_hp=infantry.max_hp,
                        speed=infantry.move_speed,
                        attack_range=infantry.attack_range,
                        attack_interval=infantry.attack_interval,
                        damage=infantry.damage,
                        type=definition.type,
                    )
                )
        self._validate_spawn_separation()
        self.elapsed_time = 0.0
        self.finished = False
        self.winner: str | None = None
        player_team = scenario.player_team
        self._opponent_replan_elapsed = {
            robot.id: 0.0 for robot in self.robots if robot.team != player_team
        }

    def order_move(self, robot_id: str, goal: tuple[float, float]) -> bool:
        if self.finished:
            return False
        robot = next((item for item in self.robots if item.id == robot_id), None)
        if robot is None or not robot.alive or robot.team != self.config.scenario.player_team:
            return False
        return self._set_robot_destination(robot, goal)

    def _set_robot_destination(self, robot: Robot, goal: tuple[float, float]) -> bool:
        path = find_path(self.map, robot.position, goal)
        if path is None:
            return False
        robot.set_path(path)
        return True

    def update(self, dt: float) -> None:
        if self.finished:
            return
        if dt < 0:
            raise ValueError("dt 不能小于 0")

        self._update_opponent_ai(dt)
        for robot in self.robots:
            robot.update_cooldown(dt)
        self._move_robots(dt)
        update_combat(self.robots, self.map)
        self.elapsed_time += dt
        self._check_result()

    def _validate_spawn_separation(self) -> None:
        minimum_distance = self.map.collision_radius * 2
        for index, first in enumerate(self.robots):
            for second in self.robots[index + 1 :]:
                if math.dist(first.position, second.position) < minimum_distance:
                    raise ValueError(
                        f"机器人出生点冲突：{first.id} 与 {second.id} 的距离小于 "
                        f"{minimum_distance:g}"
                    )

    def _move_robots(self, dt: float) -> None:
        proposals: dict[str, MovementProposal] = {}
        for robot in self.robots:
            proposals[robot.id] = (
                robot.propose_movement(dt, self.map)
                if robot.alive
                else (robot.position, list(robot.path))
            )

        blocked: set[str] = set()
        minimum_distance = self.map.collision_radius * 2
        while True:
            final_positions = {
                robot.id: (
                    robot.position if robot.id in blocked else proposals[robot.id][0]
                )
                for robot in self.robots
            }
            conflicts: set[str] = set()
            for index, first in enumerate(self.robots):
                for second in self.robots[index + 1 :]:
                    if _movement_conflicts(
                        first.position,
                        final_positions[first.id],
                        second.position,
                        final_positions[second.id],
                        minimum_distance,
                    ):
                        conflicts.update((first.id, second.id))

            new_conflicts = conflicts - blocked
            if not new_conflicts:
                break
            blocked.update(new_conflicts)

        for robot in self.robots:
            if robot.alive and robot.id not in blocked:
                robot.commit_movement(proposals[robot.id])

    def _update_opponent_ai(self, dt: float) -> None:
        player_team = self.config.scenario.player_team
        players = [robot for robot in self.robots if robot.team == player_team and robot.alive]
        for opponent in self.robots:
            if opponent.team == player_team:
                continue
            if not opponent.alive or not players:
                opponent.path.clear()
                self._opponent_replan_elapsed[opponent.id] = 0.0
                continue

            target = min(
                players,
                key=lambda robot: (
                    math.dist(opponent.position, robot.position),
                    robot.id,
                ),
            )
            distance = math.dist(opponent.position, target.position)
            if distance <= opponent.attack_range and self.map.has_line_of_sight(
                opponent.position, target.position
            ):
                opponent.path.clear()
                self._opponent_replan_elapsed[opponent.id] = 0.0
                continue

            elapsed = self._opponent_replan_elapsed[opponent.id] + dt
            if elapsed >= _OPPONENT_REPLAN_INTERVAL:
                elapsed %= _OPPONENT_REPLAN_INTERVAL
                self._set_robot_destination(opponent, target.position)
            self._opponent_replan_elapsed[opponent.id] = elapsed

    def _check_result(self) -> None:
        living_teams = {robot.team for robot in self.robots if robot.alive}
        if len(living_teams) <= 1:
            self.finished = True
            self.winner = next(iter(living_teams), None)
            return

        if self.elapsed_time >= self.config.match_duration:
            self.finished = True
            hp_by_team = {
                team.team_id: sum(robot.hp for robot in self.robots if robot.team == team.team_id)
                for team in self.config.scenario.teams.values()
            }
            highest_hp = max(hp_by_team.values())
            leaders = [team_id for team_id, hp in hp_by_team.items() if hp == highest_hp]
            self.winner = leaders[0] if len(leaders) == 1 else None

    def team_name(self, team_id: str) -> str:
        for team in self.config.scenario.teams.values():
            if team.team_id == team_id:
                return team.display_name
        return team_id


def _movement_conflicts(
    start_a: tuple[float, float],
    end_a: tuple[float, float],
    start_b: tuple[float, float],
    end_b: tuple[float, float],
    minimum_distance: float,
) -> bool:
    """Check the closest relative separation during this frame's proposed moves."""
    relative_start = (start_a[0] - start_b[0], start_a[1] - start_b[1])
    relative_change = (
        (end_a[0] - start_a[0]) - (end_b[0] - start_b[0]),
        (end_a[1] - start_a[1]) - (end_b[1] - start_b[1]),
    )
    change_squared = relative_change[0] ** 2 + relative_change[1] ** 2
    if change_squared == 0:
        closest = relative_start
    else:
        progress = -(
            relative_start[0] * relative_change[0]
            + relative_start[1] * relative_change[1]
        ) / change_squared
        progress = min(1.0, max(0.0, progress))
        closest = (
            relative_start[0] + relative_change[0] * progress,
            relative_start[1] + relative_change[1] * progress,
        )
    return math.hypot(*closest) < minimum_distance
