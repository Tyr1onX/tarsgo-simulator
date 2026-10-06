"""Helpers for isolating RMUC rule tests from the field's starting buffs."""

from tarsgo_simulator.core.match import Match


def move_ground_robots_to_unbuffed_region(match: Match) -> None:
    """Keep rule-unit tests out of official field zones unless placed there."""
    for side_index, side in enumerate(("red", "blue")):
        team_id = match.config.scenario.teams[side].team_id
        ground_robots = sorted(
            (
                robot
                for robot in match.robots
                if robot.team == team_id and robot.type != "drone"
            ),
            key=lambda robot: robot.id,
        )
        x_origin = 12500.0 if side_index == 0 else 14300.0
        for index, robot in enumerate(ground_robots):
            robot.position = (
                x_origin + (index % 3) * 600.0,
                6000.0 + (index // 3) * 700.0,
            )
