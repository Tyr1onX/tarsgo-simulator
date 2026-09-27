"""Single source of truth for the V0 match state."""

import math
from pathlib import Path

from tarsgo_simulator.core.combat import update_combat
from tarsgo_simulator.core.config import MatchConfig, load_match_config
from tarsgo_simulator.core.map import GameMap
from tarsgo_simulator.core.pathfinding import find_path
from tarsgo_simulator.core.robot import Robot


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
            position = scenario.spawns[team.robot_id]
            if not self.map.is_passable(position):
                raise ValueError(f"机器人出生点不可通行：{team.robot_id} at {position}")
            self.robots.append(
                Robot(
                    id=team.robot_id,
                    team=team.team_id,
                    position=position,
                    hp=infantry.max_hp,
                    max_hp=infantry.max_hp,
                    speed=infantry.move_speed,
                    attack_range=infantry.attack_range,
                    attack_interval=infantry.attack_interval,
                    damage=infantry.damage,
                    type=team.robot_type,
                )
            )
        self.elapsed_time = 0.0
        self.finished = False
        self.winner: str | None = None
        self._opponent_replan_elapsed = 0.0

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
            robot.update(dt, self.map)
        update_combat(self.robots, self.map)
        self.elapsed_time += dt
        self._check_result()

    def _update_opponent_ai(self, dt: float) -> None:
        player_team = self.config.scenario.player_team
        player = next(
            (robot for robot in self.robots if robot.team == player_team and robot.alive),
            None,
        )
        opponent = next(
            (robot for robot in self.robots if robot.team != player_team and robot.alive),
            None,
        )
        if player is None or opponent is None:
            self._opponent_replan_elapsed = 0.0
            if opponent is not None:
                opponent.path.clear()
            return

        distance = math.hypot(
            player.position[0] - opponent.position[0],
            player.position[1] - opponent.position[1],
        )
        if distance <= opponent.attack_range and self.map.has_line_of_sight(
            opponent.position, player.position
        ):
            opponent.path.clear()
            self._opponent_replan_elapsed = 0.0
            return

        self._opponent_replan_elapsed += dt
        if self._opponent_replan_elapsed >= _OPPONENT_REPLAN_INTERVAL:
            self._opponent_replan_elapsed %= _OPPONENT_REPLAN_INTERVAL
            self._set_robot_destination(opponent, player.position)

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
