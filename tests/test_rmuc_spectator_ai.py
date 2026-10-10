import math
from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match, _collision_right_of_way


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RMUC_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmuc-2026-region-rules-lab.yaml"
)
RMUL_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "rmul-2026-rules-lab.yaml"
)
TRAINING_SCENARIO = (
    REPOSITORY_ROOT
    / "configs"
    / "scenarios"
    / "first-steps.yaml"
)


def _match() -> Match:
    return Match.from_scenario(RMUC_SCENARIO, rmuc_spectator_ai=True)


def _robot(match: Match, robot_id: str):
    return next(robot for robot in match.robots if robot.id == robot_id)


def _zone(match: Match, zone_id: str):
    return next(zone for zone in match.map.zones if zone.id == zone_id)


def _center(zone) -> tuple[float, float]:
    return (zone.x + zone.width / 2, zone.y + zone.height / 2)


def _head_on_match(
    *,
    mirrored: bool = False,
    ramp_edge: bool = False,
    dense_robot_position: tuple[float, float] | None = None,
):
    match = _match()
    red = _robot(match, "tarsgo-infantry-1")
    blue = _robot(match, "opponent-hero")

    if ramp_edge:
        red_position = (10120.13, 300.0)
        blue_position = (10499.4, 300.0)
        red_path = [(14000.0, 300.0), (18000.0, 300.0)]
        blue_path = [(8500.0, 300.0), (7000.0, 300.0)]
    else:
        red_position = (13341.26, 260.92)
        blue_position = (12989.04, 401.59)
        red_path = [(3700.0, 1100.0), (3700.0, 7700.0), (2276.0, 12368.0)]
        blue_path = [(25900.0, 700.0), (25994.0, 1950.0)]

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        if not mirrored:
            return point
        return (match.map.width - point[0], match.map.height - point[1])

    red.position = transform(red_position)
    blue.position = transform(blue_position)
    red.set_path([transform(point) for point in red_path])
    blue.set_path([transform(point) for point in blue_path])
    robots = [red, blue]
    if dense_robot_position is not None:
        dense = _robot(match, "opponent-infantry-1")
        dense.position = transform(dense_robot_position)
        dense.path.clear()
        robots.append(dense)

    match.robots = robots
    for robot in robots:
        power = match.ruleset._chassis_power_by_robot[robot.id]
        power.power_off_remaining = 0.0
        power.blocked_this_frame = False
    return match, red, blue


def _run_collision_case(match: Match, seconds: float):
    dt = 1 / 60
    minimum_distance = 2 * match.map.collision_radius
    robots = list(match.robots)
    longest_collision_stall = {robot.id: 0.0 for robot in robots}
    current_collision_stall = {robot.id: 0.0 for robot in robots}
    snapshots = []
    for _ in range(round(seconds * 60)):
        before = {robot.id: robot.position for robot in robots}
        match._move_robots(dt)
        for robot in robots:
            assert match.map.can_traverse(
                before[robot.id],
                robot.position,
                agent_height_mm=robot.body_height_mm,
            )
            if (
                robot.alive
                and match.ruleset.can_move(robot)
                and robot.path
                and match._was_blocked[robot.id]
            ):
                current_collision_stall[robot.id] += dt
                longest_collision_stall[robot.id] = max(
                    longest_collision_stall[robot.id],
                    current_collision_stall[robot.id],
                )
            else:
                current_collision_stall[robot.id] = 0.0
        for index, first in enumerate(robots):
            for second in robots[index + 1 :]:
                assert math.dist(first.position, second.position) >= (
                    minimum_distance - 1e-6
                )
        snapshots.append(tuple(robot.position for robot in robots))
        match.elapsed_time += dt
    return snapshots, longest_collision_stall


class _FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def test_rmuc_spectator_ai_controls_all_robots_symmetrically() -> None:
    match = _match()

    assert set(match._ai_replan_elapsed) == {robot.id for robot in match.robots}
    assert all(match.is_ai_controlled(robot.id) for robot in match.robots)

    match.update(1.0)

    mirrored_pairs = (
        ("tarsgo-hero", "opponent-hero"),
        ("tarsgo-engineer", "opponent-engineer"),
        ("tarsgo-infantry-1", "opponent-infantry-1"),
        ("tarsgo-infantry-2", "opponent-infantry-2"),
        ("tarsgo-sentry", "opponent-sentry"),
        ("tarsgo-drone", "opponent-drone"),
    )
    for red_id, blue_id in mirrored_pairs:
        red_robot = _robot(match, red_id)
        blue_robot = _robot(match, blue_id)
        assert red_robot.type == blue_robot.type
        assert red_robot.max_hp == blue_robot.max_hp
        assert match.ai_intent(red_id) is not None
        assert match.ai_intent(blue_id) is not None

    red_team = _robot(match, "tarsgo-hero").team
    blue_team = _robot(match, "opponent-hero").team
    assert match.ai_team_strategy(red_team) != match.ai_team_strategy(blue_team)


def test_rmuc_spectator_ai_keeps_mirrored_infantry_moving_past_ramp_side() -> None:
    match = _match()
    red = _robot(match, "tarsgo-infantry-1")
    blue = _robot(match, "opponent-infantry-1")
    longest_stationary = {red.id: 0.0, blue.id: 0.0}
    current_stationary = {red.id: 0.0, blue.id: 0.0}
    dt = 1 / 60
    starts = {red.id: red.position, blue.id: blue.position}

    for _ in range(60 * 60):
        previous = {
            robot_id: _robot(match, robot_id).position
            for robot_id in current_stationary
        }
        match.update(dt)
        for robot_id in current_stationary:
            if _robot(match, robot_id).position == previous[robot_id]:
                current_stationary[robot_id] += dt
                longest_stationary[robot_id] = max(
                    longest_stationary[robot_id], current_stationary[robot_id]
                )
            else:
                current_stationary[robot_id] = 0.0

    assert match.elapsed_time == pytest.approx(60.0)
    assert math.dist(starts[red.id], red.position) > 1_000
    assert math.dist(starts[blue.id], blue.position) > 1_000
    assert longest_stationary[red.id] < 35.0
    assert longest_stationary[blue.id] < 35.0
    assert match._pathfinding_counters["max_queue_length"] <= 16


def test_edge_head_on_collision_uses_a_safe_local_rejoin_and_is_symmetric() -> None:
    outcomes = []
    for mirrored in (False, True):
        match, red, blue = _head_on_match(mirrored=mirrored)
        starts = {red.id: red.position, blue.id: blue.position}
        _snapshots, stalls = _run_collision_case(match, 5.0)

        assert math.dist(starts[red.id], red.position) > 1_000
        assert math.dist(starts[blue.id], blue.position) > 1_000
        assert max(stalls.values()) < 1.0
        assert match.movement_diagnostics["local_replan_searches"] > 0
        assert match.movement_diagnostics["local_replan_failures"] == 0
        outcomes.append(
            (
                math.dist(starts[red.id], red.position),
                math.dist(starts[blue.id], blue.position),
            )
        )

    assert outcomes[0] == pytest.approx(outcomes[1], abs=1e-6)


def test_dense_robot_near_the_rejoin_does_not_cause_overlap_or_deadlock() -> None:
    match, red, blue = _head_on_match(dense_robot_position=(12700.0, 1500.0))
    starts = {red.id: red.position, blue.id: blue.position}

    _snapshots, stalls = _run_collision_case(match, 5.0)

    assert math.dist(starts[red.id], red.position) > 1_000
    assert math.dist(starts[blue.id], blue.position) > 1_000
    assert max(stalls.values()) < 1.0
    assert match.movement_diagnostics["local_replan_searches"] > 0


def test_ramp_edge_collision_preserves_terrain_rules_on_both_field_halves() -> None:
    for mirrored in (False, True):
        match, red, blue = _head_on_match(mirrored=mirrored, ramp_edge=True)
        starts = {red.id: red.position, blue.id: blue.position}

        _snapshots, stalls = _run_collision_case(match, 5.0)

        assert math.dist(starts[red.id], red.position) > 1_000
        assert math.dist(starts[blue.id], blue.position) > 1_000
        assert max(stalls.values()) < 1.0


def test_local_replan_finds_a_terrain_legal_route_around_a_dead_robot() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    blocker = _robot(match, "tarsgo-infantry-2")
    sentry.position = (17895.637, 13773.98)
    sentry.set_path([(17900.0, 14500.0), (10100.0, 14500.0), (2600.0, 13732.0)])
    blocker.position = (18187.4, 14009.7)
    blocker.alive = False
    blocker.path.clear()
    match.robots = [sentry, blocker]
    match.ruleset._chassis_power_by_robot[sentry.id].power_off_remaining = 0.0
    match.ruleset._chassis_power_by_robot[sentry.id].blocked_this_frame = False

    start = sentry.position
    _snapshots, stalls = _run_collision_case(match, 3.0)

    assert math.dist(start, sentry.position) > 1_000
    assert stalls[sentry.id] < 1.0
    assert match.movement_diagnostics["local_replan_searches"] > 0


def test_collision_right_of_way_alternates_fairly_and_deterministically() -> None:
    match, red, blue = _head_on_match()

    first_turn = _collision_right_of_way(red, blue, True, True, 0.0)
    repeated_first_turn = _collision_right_of_way(red, blue, True, True, 0.0)
    second_turn = _collision_right_of_way(red, blue, True, True, 1.0)

    assert first_turn == repeated_first_turn
    assert second_turn == (first_turn[1], first_turn[0])
    assert _collision_right_of_way(red, blue, False, True, 0.0) == (red, blue)


def test_repeated_head_on_recovery_replays_the_same_collision_free_trace() -> None:
    first_match, _first_red, _first_blue = _head_on_match()
    second_match, _second_red, _second_blue = _head_on_match()

    first_trace, _first_stalls = _run_collision_case(first_match, 5.0)
    second_trace, _second_stalls = _run_collision_case(second_match, 5.0)

    assert first_trace == second_trace
    assert first_match.movement_diagnostics == second_match.movement_diagnostics


def test_rmuc_ai_completes_full_420_second_match_without_collision_deadlock() -> None:
    match = _match()
    dt = 1.0 / 60.0
    collision_stall = {robot.id: 0.0 for robot in match.robots}
    longest_collision_stall = {robot.id: 0.0 for robot in match.robots}
    stationary_classes: dict[str, int] = {}
    maximum_path_queue = 0
    small_energy_contacts = []
    large_energy_contacts = []

    for tick in range(420 * 60):
        before = {robot.id: robot.position for robot in match.robots}
        match.update(dt)
        small_energy_contacts.extend(
            impact
            for impact in match.projectile_system.impacts
            if impact.target_kind == "energy_mechanism"
        )
        large_energy_contacts.extend(
            impact
            for impact in match.projectile_system.impacts
            if impact.target_kind == "large_energy_mechanism"
        )
        maximum_path_queue = max(
            maximum_path_queue,
            len(match._path_work_queue),
        )
        for index, first in enumerate(match.robots):
            if first.aerial:
                continue
            for second in match.robots[index + 1 :]:
                if not second.aerial:
                    assert math.dist(first.position, second.position) >= (
                        2 * match.map.collision_radius - 1e-6
                    )
        for robot in match.robots:
            allowed = robot.alive and match.ruleset.can_move(robot)
            moved = math.dist(before[robot.id], robot.position) > 1e-8
            if not moved:
                if not robot.alive:
                    status = "dead_or_respawning"
                elif not allowed:
                    status = "power_or_rule_lock"
                elif not robot.path:
                    status = "legal_wait"
                elif match._was_blocked[robot.id]:
                    status = "collision_yield"
                else:
                    status = "path_without_motion"
                stationary_classes[status] = stationary_classes.get(status, 0) + 1

            if (
                not moved
                and robot.alive
                and allowed
                and robot.path
                and match._was_blocked[robot.id]
            ):
                collision_stall[robot.id] += dt
                longest_collision_stall[robot.id] = max(
                    longest_collision_stall[robot.id],
                    collision_stall[robot.id],
                )
            else:
                collision_stall[robot.id] = 0.0
        if match.finished:
            assert tick == 420 * 60 - 1
            break

    assert match.finished
    assert match.elapsed_time == match.time_limit == 420.0
    assert match.winner is not None
    assert maximum_path_queue <= 16
    assert max(longest_collision_stall.values()) < 3.0
    assert stationary_classes["legal_wait"] > 0
    assert stationary_classes["dead_or_respawning"] > 0
    assert stationary_classes["collision_yield"] > 0
    assert stationary_classes.get("path_without_motion", 0) == 0

    # This is a normal, unassisted match start. Keep any autonomous mechanism
    # contacts tied to real eligible AI fire and to the existing reward event;
    # no near-field teleport/fixture is part of this full-match evidence.
    activation_times = match.ruleset._small_energy_mechanism_activation_times_by_team
    eligible_ai_ids = {
        robot.id
        for robot in match.robots
        if match.is_ai_controlled(robot.id) and robot.type in {"infantry", "sentry"}
    }
    for team_id, state in match.ruleset._small_energy_mechanism_by_team.items():
        completions = [
            impact
            for impact in small_energy_contacts
            if impact.shooter_team_id == team_id
            and impact.outcome == "energy_activated"
        ]
        assert len(completions) == len(activation_times[team_id])
        assert state.opportunities_used <= 2
    assert all(
        impact.caliber == "17mm"
        and impact.shooter_id in eligible_ai_ids
        for impact in small_energy_contacts
    )

    # Large-mechanism contacts and successful rewards must remain backed by
    # the same physical projectile event stream during the standard match.
    large_activation_times = (
        match.ruleset._large_energy_mechanism_activation_times_by_team
    )
    for team_id, state in match.ruleset._large_energy_mechanism_by_team.items():
        completions = [
            impact
            for impact in large_energy_contacts
            if impact.shooter_team_id == team_id
            and impact.outcome == "large_energy_activated"
        ]
        assert len(completions) == len(large_activation_times[team_id])
        assert state.opportunities_used <= 3
        # Standard-match AI has no full-field large-mechanism approach yet.
        # Keep the observed partial coverage explicit until that strategy lands.
        assert state.opportunities_used == 0
        assert large_activation_times[team_id] == []
    assert large_energy_contacts == []
    assert all(
        impact.shooter_id in {robot.id for robot in match.robots}
        and impact.shooter_team_id
        == next(robot.team for robot in match.robots if robot.id == impact.shooter_id)
        for impact in large_energy_contacts
    )


def test_team_strategy_switches_for_structure_crisis_and_finish_opportunity() -> None:
    match = _match()
    red_team = _robot(match, "tarsgo-hero").team
    base = next(
        structure for structure in match.structures
        if structure.team == red_team and structure.type == "base"
    )
    outpost = next(
        structure for structure in match.structures
        if structure.team == red_team and structure.type == "outpost"
    )
    low_enemy = _robot(match, "opponent-hero")

    assert match._desired_rmuc_team_strategy(red_team) == "tech"
    match.elapsed_time = 4.0
    match._refresh_rmuc_team_strategies()
    assert match.ai_team_strategy(red_team) == "科技推进 · 主攻"

    outpost.hp = round(outpost.max_hp * 0.40)
    assert match._desired_rmuc_team_strategy(red_team) == "defend"
    match.elapsed_time = 8.0
    match._refresh_rmuc_team_strategies()
    assert match.ai_team_strategy(red_team) == "防守 · 主攻"

    outpost.hp = outpost.max_hp
    low_enemy.hp = round(low_enemy.max_hp * 0.20)
    assert match._desired_rmuc_team_strategy(red_team) == "focus"
    match.elapsed_time = 12.0
    match._refresh_rmuc_team_strategies()
    assert match.ai_team_strategy(red_team) == "集火 · 主攻"

    low_enemy.hp = low_enemy.max_hp
    base.hp = round(base.max_hp * 0.25)
    assert match._desired_rmuc_team_strategy(red_team) == "return"

    match._refresh_rmuc_team_strategies()
    assert match.ai_team_strategy(red_team) == "紧急回防"
    match.reset()
    assert match.ai_team_strategy(red_team) == "快速主攻"


def test_rmuc_ai_fixed_seed_is_repeatable() -> None:
    first = _match()
    second = _match()

    for _ in range(20):
        first.update(0.5)
        second.update(0.5)

    first_snapshot = [
        (robot.id, robot.position, tuple(robot.path), first.ai_intent(robot.id), robot.hp)
        for robot in first.robots
    ]
    second_snapshot = [
        (robot.id, robot.position, tuple(robot.path), second.ai_intent(robot.id), robot.hp)
        for robot in second.robots
    ]
    assert first_snapshot == second_snapshot


def test_rmuc_ai_replan_phases_are_deterministic_staggered_and_resettable(
    monkeypatch,
) -> None:
    match = _match()
    phases = dict(match._ai_replan_elapsed)

    assert len(phases) == len(match.robots)
    assert len(set(phases.values())) == len(phases)
    sorted_ids = sorted(phases)
    expected_spacing = 0.75 / len(sorted_ids)
    for index, robot_id in enumerate(sorted_ids):
        assert phases[robot_id] == pytest.approx(index * expected_spacing)

    calls_by_update = []
    current_calls = []
    alive_robot_ids = {robot.id for robot in match.robots if robot.alive}

    def record_replan(robot, _display_state):
        if robot.alive:
            current_calls.append(robot.id)

    monkeypatch.setattr(match, "_rmuc_ai_step", record_replan)
    for _ in range(90):
        current_calls = []
        match._update_ai(1 / 60)
        calls_by_update.append(tuple(current_calls))

    active_updates = [calls for calls in calls_by_update if calls]
    assert len(active_updates) > 1
    assert max(len(calls) for calls in active_updates) == 1
    assert {robot_id for calls in active_updates for robot_id in calls} == alive_robot_ids
    for robot_id in alive_robot_ids:
        assert sum(robot_id in calls for calls in active_updates) == 2

    match.reset()
    drone_ids = {"opponent-drone", "tarsgo-drone"}
    match._update_ai(0.1)
    drone_phase_gap = (
        match._ai_replan_elapsed["tarsgo-drone"]
        - match._ai_replan_elapsed["opponent-drone"]
    ) % 0.75
    assert drone_phase_gap == pytest.approx(0.375)
    for robot in match.robots:
        if robot.id in drone_ids:
            robot.alive = True

    drone_replan_frames = {}
    for frame in range(45):
        current_calls = []
        match._update_ai(1 / 60)
        for robot_id in current_calls:
            if robot_id in drone_ids:
                drone_replan_frames.setdefault(robot_id, frame)
    assert set(drone_replan_frames) == drone_ids
    assert drone_replan_frames["opponent-drone"] != drone_replan_frames["tarsgo-drone"]

    match._update_ai(0.31)
    match.reset()
    assert match._ai_replan_elapsed == phases


def _candidate_by_key(match: Match, robot, key: str):
    return next(
        candidate
        for candidate in match._rmuc_tactical_candidates(
            robot,
            match.ruleset.display_state,
        )
        if candidate[0] == key
    )


def _finish_path_requests(match: Match) -> None:
    for _ in range(1000):
        if not match._path_work_queue:
            break
        match._advance_path_requests()
    assert not match._path_work_queue


def test_rmuc_attackers_receive_distinct_structure_approach_slots() -> None:
    match = _match()
    red_team = _robot(match, "tarsgo-hero").team
    target = next(
        structure
        for structure in match.structures
        if structure.team != red_team and structure.type == "outpost"
    )
    points = match.map.structure_approach_points(target.id)
    attackers = sorted(
        (
            robot
            for robot in match.robots
            if robot.team == red_team and robot.alive and not robot.aerial
        ),
        key=lambda robot: robot.id,
    )[: min(2, len(points))]
    assert len(attackers) >= 2

    preferred_slots = []
    for robot in attackers:
        target_key = f"structure:{target.id}"
        match._ai_target_keys[robot.id] = target_key
        match._set_ai_goal(
            robot,
            "进攻前哨站",
            target.position,
            target_key=target_key,
        )
        plan = match._pending_ai_paths[robot.id]
        assert plan.preferred_approach_index is not None
        preferred_slots.append(plan.preferred_approach_index)

    assert len(set(preferred_slots)) == len(attackers)
    _finish_path_requests(match)

    endpoints = [tuple(robot.path[-1]) for robot in attackers]
    assert len(set(endpoints)) == len(attackers)
    assert all(
        any(endpoint == point for point in points)
        for endpoint in endpoints
    )


def test_rmuc_ai_replenishes_and_critical_hp_retreats() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    supply = _zone(match, "red-supply-buff")

    # Stay outside the newly modelled red-outpost footprint.
    infantry.position = (910.0, 750.0)
    match._rmuc_ai_step(infantry, match.ruleset.display_state)
    assert match.ai_intent(infantry.id) == "前往补给区"
    _finish_path_requests(match)
    assert supply.contains(infantry.path[-1])

    hero.hp = max(1, hero.max_hp // 5)
    match._rmuc_ai_step(hero, match.ruleset.display_state)
    assert match.ai_intent(hero.id) == "回撤补给"
    _finish_path_requests(match)
    assert supply.contains(hero.path[-1])


def test_low_hp_raises_retreat_utility_above_combat_choices() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    side = match._team_side(sentry.team)
    retreat_key = f"zone:supply:{side}"

    assert all(
        candidate[1] != "回撤补给"
        for candidate in match._rmuc_tactical_candidates(
            sentry,
            match.ruleset.display_state,
        )
    )

    sentry.hp = round(sentry.max_hp * 0.40)
    candidates = match._rmuc_tactical_candidates(
        sentry,
        match.ruleset.display_state,
    )
    retreat = next(candidate for candidate in candidates if candidate[0] == retreat_key)
    assert retreat[1] == "回撤补给"
    assert retreat[3] == max(candidate[3] for candidate in candidates)


def test_low_hp_enemy_gets_finish_priority_without_forcing_every_robot() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    target = _robot(match, "opponent-infantry-1")
    target_key = f"robot:{target.id}"

    full = _candidate_by_key(match, sentry, target_key)
    target.hp = max(1, round(target.max_hp * 0.20))
    weak = _candidate_by_key(match, sentry, target_key)

    assert weak[1] == "集火残血目标"
    assert weak[3] > full[3] + 1.0


def test_outpost_then_base_structure_priority_tracks_targetability() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    enemy_outpost = next(
        structure
        for structure in match.structures
        if structure.team != hero.team and structure.type == "outpost"
    )
    enemy_base = next(
        structure
        for structure in match.structures
        if structure.team != hero.team and structure.type == "base"
    )

    before = {
        candidate[0]: candidate
        for candidate in match._rmuc_tactical_candidates(
            hero,
            match.ruleset.display_state,
        )
    }
    assert f"structure:{enemy_outpost.id}" in before
    assert f"structure:{enemy_base.id}" not in before

    enemy_outpost.hp = 0
    enemy_outpost.alive = False
    after = {
        candidate[0]: candidate
        for candidate in match._rmuc_tactical_candidates(
            hero,
            match.ruleset.display_state,
        )
    }
    assert f"structure:{enemy_outpost.id}" not in after
    assert after[f"structure:{enemy_base.id}"][1] == "进攻基地"


def test_engineer_advances_resource_assembly_and_tech_core() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    resource = _zone(match, "red-resource")
    assembly = _zone(match, "red-assembly")

    engineer.position = _center(resource)
    match._rmuc_ai_step(engineer, match.ruleset.display_state)
    assert match.ai_intent(engineer.id) == "获取能量单元"
    assert dict(match.ruleset.display_state.engineer_energy_units)[engineer.id] == 1

    engineer.position = _center(assembly)
    match._rmuc_ai_step(engineer, match.ruleset.display_state)
    assert match.ai_intent(engineer.id) == "装配科技核心"
    tech = {
        team_id: (d1, d2, d3, d4)
        for team_id, _cap, d1, d2, d3, d4, _active, _outside
        in match.ruleset.display_state.tech_core_status
    }
    assert tech[engineer.team][0] == 1


def test_protect_engineer_becomes_real_tactical_choice() -> None:
    match = _match()
    engineer = _robot(match, "tarsgo-engineer")
    sentry = _robot(match, "tarsgo-sentry")
    match._ai_intents[engineer.id] = "装配科技核心"

    for enemy in match.robots:
        if enemy.team != sentry.team:
            enemy.alive = False
            enemy.hp = 0
    for structure in match.structures:
        if structure.team != sentry.team:
            structure.alive = False
            structure.hp = 0

    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)
    match._rmuc_ai_step(sentry, match.ruleset.display_state)
    _finish_path_requests(match)

    assert match.ai_intent(sentry.id) == "保护工程"
    assert match._ai_target_keys[sentry.id] == f"support:{engineer.id}"
    assert sentry.path


def test_fortress_utility_is_high_but_occupancy_prevents_full_team_pileup() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    outpost = next(
        structure
        for structure in match.structures
        if structure.team == sentry.team and structure.type == "outpost"
    )
    outpost.hp = 0
    outpost.alive = False

    candidates = match._rmuc_tactical_candidates(
        sentry,
        match.ruleset.display_state,
    )
    fortress_key = f"zone:fortress:{match._team_side(sentry.team)}"
    fortress = next(candidate for candidate in candidates if candidate[0] == fortress_key)
    central = next(
        candidate for candidate in candidates if candidate[1] == "前往中央区域"
    )
    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)

    first = match._choose_utility_candidate(sentry, [fortress, central])
    assert first is not None and first[0] == fortress_key

    match._ai_target_keys["tarsgo-infantry-1"] = fortress_key
    match._ai_target_keys["tarsgo-infantry-2"] = fortress_key
    spread = match._choose_utility_candidate(sentry, [fortress, central])
    assert spread is not None and spread[0] != fortress_key


def test_central_zone_is_secondary_goal_when_higher_priorities_disappear() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    for enemy in match.robots:
        if enemy.team != sentry.team:
            enemy.alive = False
            enemy.hp = 0
    for structure in match.structures:
        if structure.team != sentry.team:
            structure.alive = False
            structure.hp = 0

    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)
    match._rmuc_ai_step(sentry, match.ruleset.display_state)

    assert match.ai_intent(sentry.id) == "前往中央区域"
    assert match._ai_target_keys[sentry.id].startswith("zone:central:")


def test_target_stickiness_uses_hysteresis_but_yields_to_clear_priority_jump() -> None:
    match = _match()
    sentry = _robot(match, "tarsgo-sentry")
    match._rmuc_ai_rng[sentry.id] = _FixedRandom(0.5)
    match._ai_target_keys[sentry.id] = "robot:a"
    match._ai_sticky_until[sentry.id] = match.elapsed_time + 1.0

    close = [
        ("robot:a", "追击敌方步兵", (100.0, 100.0), 1.00),
        ("robot:b", "追击敌方英雄", (200.0, 100.0), 1.30),
    ]
    held = match._choose_utility_candidate(sentry, close)
    assert held is not None and held[0] == "robot:a"

    urgent = [
        ("robot:a", "追击敌方步兵", (100.0, 100.0), 1.00),
        ("robot:b", "集火残血目标", (200.0, 100.0), 1.70),
    ]
    switched = match._choose_utility_candidate(sentry, urgent)
    assert switched is not None and switched[0] == "robot:b"

    target_gone = [
        ("robot:b", "追击敌方英雄", (200.0, 100.0), 1.10),
    ]
    forced = match._choose_utility_candidate(sentry, target_gone)
    assert forced is not None and forced[0] == "robot:b"


def test_team_target_occupancy_penalty_spreads_identical_role_choices() -> None:
    match = _match()
    infantry = _robot(match, "tarsgo-infantry-2")
    match._rmuc_ai_rng[infantry.id] = _FixedRandom(0.5)
    central_key = "zone:central:red"
    choices = [
        (central_key, "前往中央区域", (100.0, 100.0), 2.00),
        ("robot:opponent-hero", "追击敌方英雄", (200.0, 100.0), 1.40),
    ]

    open_choice = match._choose_utility_candidate(infantry, choices)
    assert open_choice is not None and open_choice[0] == central_key

    match._ai_target_keys["tarsgo-infantry-1"] = central_key
    spread_choice = match._choose_utility_candidate(infantry, choices)
    assert spread_choice is not None
    assert spread_choice[0] == "robot:opponent-hero"


def test_infantry_assignments_split_attack_and_control_objectives() -> None:
    match = _match()
    infantry_one = _robot(match, "tarsgo-infantry-1")
    infantry_two = _robot(match, "tarsgo-infantry-2")
    for robot in (infantry_one, infantry_two):
        match._rmuc_ai_rng[robot.id] = _FixedRandom(0.5)

    candidates = [
        ("robot:opponent-hero", "追击敌方英雄", (1800.0, 750.0), 2.0),
        ("zone:central:red", "前往中央区域", (1310.0, 640.0), 1.5),
    ]
    attack = match._choose_utility_candidate(infantry_one, candidates)
    assert attack is not None and attack[0] == "robot:opponent-hero"
    match._remember_ai_decision(infantry_one, attack[0])

    control = match._choose_utility_candidate(infantry_two, candidates)
    assert control is not None and control[0] == "zone:central:red"


def test_team_style_weights_are_distinct_but_use_the_same_candidate_layer() -> None:
    match = _match()
    red_hero = _robot(match, "tarsgo-hero")
    blue_hero = _robot(match, "opponent-hero")

    assert match._rmuc_candidate_bonus(red_hero, "structure:blue-base") > (
        match._rmuc_candidate_bonus(blue_hero, "structure:red-base")
    )
    assert match._rmuc_candidate_bonus(blue_hero, "zone:central:blue") > (
        match._rmuc_candidate_bonus(red_hero, "zone:central:red")
    )


def test_role_scores_make_hero_structural_and_sentry_defensive_biases_visible() -> None:
    match = _match()
    hero = _robot(match, "tarsgo-hero")
    infantry = _robot(match, "tarsgo-infantry-1")
    sentry = _robot(match, "tarsgo-sentry")
    enemy_outpost = next(
        structure
        for structure in match.structures
        if structure.team != hero.team and structure.type == "outpost"
    )
    outpost_key = f"structure:{enemy_outpost.id}"

    hero_attack = _candidate_by_key(match, hero, outpost_key)
    infantry_attack = _candidate_by_key(match, infantry, outpost_key)
    assert hero_attack[3] > infantry_attack[3]

    own_outpost = next(
        structure
        for structure in match.structures
        if structure.team == sentry.team and structure.type == "outpost"
    )
    own_outpost.hp = round(own_outpost.max_hp * 0.50)
    sentry_defense = next(
        candidate
        for candidate in match._rmuc_tactical_candidates(
            sentry,
            match.ruleset.display_state,
        )
        if candidate[1] == "防守前哨站"
    )
    infantry_defense = next(
        candidate
        for candidate in match._rmuc_tactical_candidates(
            infantry,
            match.ruleset.display_state,
        )
        if candidate[1] == "防守前哨站"
    )
    assert sentry_defense[3] > infantry_defense[3]


def test_rmuc_ai_intent_is_exposed_in_chinese_ui_and_opponents_are_selectable() -> None:
    pygame = pytest.importorskip("pygame")
    del pygame
    from tarsgo_simulator.desktop import app

    match = _match()
    match.update(1.0)
    labels = app._rmuc_robot_labels(match)
    opponent = _robot(match, "opponent-hero")

    lines = app._selected_unit_lines(match, {opponent.id}, labels)
    assert f"当前 AI 意图  {match.ai_intent(opponent.id)}" in lines
    assert app._select_player_robot(opponent.position, match) == opponent.id
    assert not match.is_player_controlled(opponent.id)
    assert match.is_ai_controlled(opponent.id)


def test_rmuc_long_smoke_does_not_crash() -> None:
    match = _match()
    for _ in range(4200):
        if match.finished:
            break
        match.update(0.1)
    assert match.elapsed_time > 90 or match.finished
    assert all(match.ai_team_strategy(robot.team) for robot in match.robots)


@pytest.mark.parametrize("scenario", [TRAINING_SCENARIO, RMUL_SCENARIO])
def test_non_rmuc_smoke_is_unchanged(scenario: Path) -> None:
    match = Match.from_scenario(scenario)
    match.update(0.01)
    assert match.elapsed_time == pytest.approx(0.01)
