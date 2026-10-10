import math
from pathlib import Path
import random

import pytest

from tarsgo_simulator.core.energy_mechanism import LargeEnergyMechanism
from tarsgo_simulator.core.events import MatchEventType
from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.projectiles import Projectile
from tarsgo_simulator.core.robot import Robot
from rmuc_test_support import move_ground_robots_to_unbuffed_region


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = REPOSITORY_ROOT / "configs/scenarios/rmuc-2026-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match(*, spectator_ai: bool = False) -> Match:
    match = Match.from_scenario(SCENARIO, rmuc_spectator_ai=spectator_ai)
    for robot in match.robots:
        robot.speed = 0.0
        robot.attack_cooldown = 9999.0
        robot.path.clear()
    move_ground_robots_to_unbuffed_region(match)
    return match


def _robot(match: Match, robot_id: str) -> Robot:
    return next(robot for robot in match.robots if robot.id == robot_id)


def _team_robot(match: Match, team_id: str, robot_type: str) -> Robot:
    return next(
        robot
        for robot in match.robots
        if robot.team == team_id and robot.type == robot_type
    )


def _start_large(match: Match, team_id: str = RED) -> Robot:
    if match.elapsed_time < 180.0:
        match.update(180.0 - match.elapsed_time)
    robot = _team_robot(match, team_id, "sentry")
    match.ruleset._large_energy_rng_by_team[team_id] = random.Random(0)
    assert match.ruleset.request_large_energy_mechanism_activation(match, robot)
    return robot


def _fire_at_panel(
    match: Match,
    shooter: Robot,
    module_index: int,
    *,
    radial_offset_mm: float = 0.0,
    caliber: str = "17mm",
    speed: float = 25_000.0,
    dt: float = 1.0 / 120.0,
    start_distance_mm: float = 100.0,
    step_until_resolved: bool = False,
):
    rules = match.ruleset
    entity = rules._large_energy_mechanism_entity
    assert entity is not None
    panel = next(
        panel
        for panel in entity.panels_at(match.elapsed_time + dt)
        if panel.module_index == module_index
    )
    start = (
        panel.center[0] - start_distance_mm,
        panel.center[1] + radial_offset_mm,
    )
    projectile = Projectile(
        id=90_000 + len(match.projectile_system.projectiles),
        shooter_id=shooter.id,
        shooter_team_id=shooter.team,
        caliber=caliber,
        damage=20,
        radius=8.4,
        speed=speed,
        effective_range=2_400.0,
        position=start,
        previous_position=start,
        velocity=(speed, 0.0),
        height_mm=match.map.terrain_height_at(start),
        target_id=f"large-energy:{shooter.team}:{module_index}",
    )
    match.projectile_system.projectiles.append(projectile)
    for _ in range(100 if step_until_resolved else 1):
        match.update(dt)
        impact = next(
            (
                impact
                for impact in match.projectile_system.impacts
                if impact.projectile_id == projectile.id
            ),
            None,
        )
        if impact is not None:
            return impact
        if projectile not in match.projectile_system.projectiles:
            return None
    return None


def test_large_mechanism_rotation_integrates_official_speed_and_resumes_base_speed():
    mechanism = LargeEnergyMechanism(
        center=(14_000.0, 7_500.0),
        rotation_direction=1,
    )
    initial = mechanism.angle_at(0.0)
    assert mechanism.angle_at(1.0) - initial == pytest.approx(math.pi / 3.0)

    a, omega = 0.9, 1.95
    mechanism.start_activation(
        3.0,
        speed_a=a,
        speed_omega=omega,
        speed_time_origin=1.0,
    )
    elapsed = 2.0
    expected = mechanism.angle_at(3.0) + (
        a / omega * (math.cos(omega * 2.0) - math.cos(omega * 4.0))
        + (2.090 - a) * elapsed
    )
    assert mechanism.angle_at(5.0) == pytest.approx(expected)
    activation_end = mechanism.angle_at(5.0)
    mechanism.stop_activation(5.0)
    assert mechanism.angle_at(6.0) - activation_end == pytest.approx(
        math.pi / 3.0
    )


def test_large_opportunities_accumulate_and_only_infantry_or_sentry_can_start():
    match = _match()
    rules = match.ruleset
    assert not rules.large_energy_mechanism_activation_available(RED)
    match.update(179.999)
    assert not rules.large_energy_mechanism_activation_available(RED)
    match.update(0.001)
    assert rules.large_energy_mechanism_activation_available(RED)
    assert not rules.request_large_energy_mechanism_activation(
        match,
        _robot(match, "tarsgo-hero"),
    )
    assert not rules.request_large_energy_mechanism_activation(
        match,
        _robot(match, "tarsgo-engineer"),
    )

    red_infantry = _robot(match, "tarsgo-infantry-1")
    red_infantry.alive = False
    assert not rules.request_large_energy_mechanism_activation(match, red_infantry)
    red_infantry.alive = True
    assert rules.request_large_energy_mechanism_activation(match, red_infantry)
    assert rules._large_energy_mechanism_by_team[RED].opportunities_used == 1
    assert rules._large_energy_mechanism_entity._speed_time_origin == pytest.approx(
        180.0
    )
    assert rules._large_energy_opportunities_remaining(RED, 180.0) == 0

    match.update(74.999)
    assert rules._large_energy_opportunities_remaining(RED, 254.999) == 0
    match.update(0.001)
    assert rules._large_energy_opportunities_remaining(RED, 255.0) == 1
    assert rules.large_energy_mechanism_activation_available(RED)
    assert rules.request_large_energy_mechanism_activation(
        match,
        _robot(match, "tarsgo-sentry"),
    )
    assert rules._large_energy_mechanism_by_team[RED].opportunities_used == 2
    assert rules._large_energy_mechanism_entity._speed_time_origin == pytest.approx(
        255.0
    )
    match.update(20.0)
    assert rules._large_energy_mechanism_by_team[RED].status == "inactive"
    match.update(55.0)
    assert match.elapsed_time == pytest.approx(330.0)
    assert rules._large_energy_opportunities_remaining(RED, 330.0) == 1
    assert rules.request_large_energy_mechanism_activation(
        match,
        _robot(match, "tarsgo-sentry"),
    )
    assert rules._large_energy_mechanism_by_team[RED].opportunities_used == 3


def test_large_no_hit_timeout_resets_group_without_refunding_command():
    match = _match()
    sentry = _start_large(match)
    state = match.ruleset._large_energy_mechanism_by_team[RED]
    activation_deadline = state.attempt_deadline
    lit_pair = state.lit_module_indices

    match.update(2.5)

    assert state.status == "activating"
    assert state.failure_count == 1
    assert state.completed_groups == 0
    assert state.ring_scores == []
    assert state.attempt_deadline == pytest.approx(activation_deadline)
    assert state.hit_deadline == pytest.approx(match.elapsed_time + 2.5)
    assert state.lit_module_indices != lit_pair
    assert state.opportunities_used == 1


def test_real_projectile_sequence_scores_rings_optional_lamps_and_existing_reward():
    match = _match()
    sentry = _start_large(match)
    rules = match.ruleset
    state = rules._large_energy_mechanism_by_team[RED]
    impacts = []

    for group in range(5):
        first_module = state.lit_module_indices[0]
        first = _fire_at_panel(match, sentry, first_module)
        impacts.append(first)
        assert first.target_kind == "large_energy_mechanism"
        assert first.outcome in {"large_energy_group_activated", "large_energy_final_group"}
        assert state.completed_groups == group + 1

        if group == 0:
            bonus_module = next(
                index
                for index in state.lit_module_indices
                if index != state.first_hit_module_index
            )
            bonus = _fire_at_panel(
                match,
                sentry,
                bonus_module,
                radial_offset_mm=30.0,
            )
            impacts.append(bonus)
            assert bonus.outcome == "large_energy_bonus_lamp"
            assert state.ring_scores == [10, 8]
        else:
            match.update(1.0)

    assert state.status == "activated"
    assert len(impacts) == 6
    assert len(state.ring_scores) == 6
    assert state.ring_scores == [10, 8, 10, 10, 10, 10]
    assert sum(state.ring_scores) / len(state.ring_scores) == pytest.approx(58 / 6)
    assert rules._effective_attack_multiplier(RED) == pytest.approx(3.0)
    energy_buff = next(
        buff
        for buff in rules._energy_mechanism_buffs_by_team[RED]
        if buff.mechanism == "large"
    )
    assert energy_buff.remaining == pytest.approx(35.0)
    assert energy_buff.defense == pytest.approx(0.50)
    assert energy_buff.cooling_multiplier == pytest.approx(5.0)
    red_experience = sum(
        state.experience
        for robot_id, state in rules._progression_by_robot.items()
        if rules._robots_by_id[robot_id].team == RED
    )
    assert red_experience == pytest.approx(750.0)
    assert rules._large_energy_mechanism_activation_times_by_team[RED] == [180.0]


@pytest.mark.parametrize(
    ("radial_offset_mm", "expected_ring"),
    [(0.0, 10), (30.0, 8)],
)
@pytest.mark.parametrize("dt", [1.0 / 60.0, 0.006, 0.003])
def test_real_projectile_ring_score_is_independent_of_physics_step(
    radial_offset_mm: float,
    expected_ring: int,
    dt: float,
):
    match = _match()
    sentry = _start_large(match)
    rules = match.ruleset
    state = rules._large_energy_mechanism_by_team[RED]
    entity = rules._large_energy_mechanism_entity
    assert entity is not None
    # Hold a single physical target pose so this regression isolates projectile
    # path sampling from the separate moving-target timestep approximation.
    entity.rotation_direction = 0

    impact = _fire_at_panel(
        match,
        sentry,
        state.lit_module_indices[0],
        radial_offset_mm=radial_offset_mm,
        dt=dt,
        start_distance_mm=300.0,
        step_until_resolved=True,
    )

    assert impact is not None
    assert impact.target_kind == "large_energy_mechanism"
    assert impact.outcome == "large_energy_group_activated"
    assert state.ring_scores == [expected_ring]


@pytest.mark.parametrize("dt", [1.0 / 60.0, 0.006, 0.003])
def test_real_projectile_miss_outside_large_mechanism_does_not_score(dt: float):
    match = _match()
    sentry = _start_large(match)
    rules = match.ruleset
    state = rules._large_energy_mechanism_by_team[RED]
    entity = rules._large_energy_mechanism_entity
    assert entity is not None
    entity.rotation_direction = 0

    impact = _fire_at_panel(
        match,
        sentry,
        state.lit_module_indices[0],
        radial_offset_mm=160.0,
        dt=dt,
        start_distance_mm=300.0,
        step_until_resolved=True,
    )

    assert impact is None
    assert match.projectile_system.misses == 1
    assert state.completed_groups == 0
    assert state.ring_scores == []


@pytest.mark.parametrize("final_bonus_hit", [False, True])
def test_five_real_projectile_groups_emit_one_success_and_one_reward(
    final_bonus_hit: bool,
):
    match = _match()
    sentry = _start_large(match)
    rules = match.ruleset
    state = rules._large_energy_mechanism_by_team[RED]
    entity = rules._large_energy_mechanism_entity
    assert entity is not None
    entity.rotation_direction = 0
    observed_successes = []

    def capture_successes() -> None:
        observed_successes.extend(
            event
            for event in match.current_events
            if event.type == MatchEventType.ENERGY_MECHANISM_ACTIVATED
            and event.mechanism_id == "large_energy"
        )

    for group_index in range(5):
        first = _fire_at_panel(
            match,
            sentry,
            state.lit_module_indices[0],
            start_distance_mm=300.0,
            step_until_resolved=True,
        )
        assert first is not None
        assert first.outcome in {
            "large_energy_group_activated",
            "large_energy_final_group",
        }
        capture_successes()

        if group_index < 4:
            match.update(1.0)
            capture_successes()
        elif final_bonus_hit:
            bonus_module = next(
                index
                for index in state.lit_module_indices
                if index != state.first_hit_module_index
            )
            bonus = _fire_at_panel(
                match,
                sentry,
                bonus_module,
                start_distance_mm=300.0,
                step_until_resolved=True,
            )
            assert bonus is not None
            assert bonus.outcome == "large_energy_bonus_lamp"
            capture_successes()
        else:
            match.update(1.0)
            capture_successes()

    assert state.status == "activated"
    assert len(observed_successes) == 1
    success = observed_successes[0]
    assert success.type == MatchEventType.ENERGY_MECHANISM_ACTIVATED
    assert success.mechanism_id == "large_energy"
    assert success.team_id == RED
    assert success.robot_id == sentry.id
    assert 180.0 <= success.time <= match.elapsed_time
    assert rules._large_energy_mechanism_activation_times_by_team[RED] == [180.0]
    assert len(rules._energy_mechanism_buffs_by_team[RED]) == 1
    large_buff = rules._energy_mechanism_buffs_by_team[RED][0]
    assert large_buff.mechanism == "large"
    assert large_buff.remaining == pytest.approx(35.0 if final_bonus_hit else 30.0)
    assert rules._effective_attack_multiplier(RED) == pytest.approx(3.0)
    experience = sum(
        progression.experience
        for robot_id, progression in rules._progression_by_robot.items()
        if rules._robots_by_id[robot_id].team == RED
    )
    assert experience == pytest.approx(750.0)

    match.update(0.25)
    capture_successes()
    assert len(observed_successes) == 1
    assert rules._large_energy_mechanism_activation_times_by_team[RED] == [180.0]
    assert sum(
        progression.experience
        for robot_id, progression in rules._progression_by_robot.items()
        if rules._robots_by_id[robot_id].team == RED
    ) == pytest.approx(750.0)


def test_unlit_hit_and_first_hit_timeout_reset_sequence_within_one_activation():
    match = _match()
    sentry = _start_large(match)
    rules = match.ruleset
    state = rules._large_energy_mechanism_by_team[RED]
    unlit_module = next(index for index in range(5) if index not in state.lit_module_indices)

    wrong_hit = _fire_at_panel(match, sentry, unlit_module)
    assert wrong_hit.outcome == "large_energy_activation_failed"
    assert state.status == "activating"
    assert state.failure_count == 1
    assert state.completed_groups == 0
    assert state.ring_scores == []

    first_module = state.lit_module_indices[0]
    accepted = _fire_at_panel(match, sentry, first_module)
    assert accepted.outcome == "large_energy_group_activated"
    match.update(1.0)
    assert state.status == "activating"
    assert state.completed_groups == 1

    remaining = state.attempt_deadline - match.elapsed_time
    match.update(remaining)
    assert state.status == "inactive"
    assert state.failure_count == 2
    assert state.opportunities_used == 1
    assert rules._large_energy_opportunities_remaining(RED, 200.0) == 0
    assert rules._energy_mechanism_buffs_by_team[RED] == []


def test_large_energy_rejects_illegal_slow_and_outside_circle_shots():
    match = _match()
    sentry = _start_large(match)
    rules = match.ruleset
    state = rules._large_energy_mechanism_by_team[RED]
    module_index = state.lit_module_indices[0]

    illegal = _fire_at_panel(match, sentry, module_index, caliber="42mm")
    slow = _fire_at_panel(match, sentry, module_index, speed=12_000.0)
    outside = _fire_at_panel(
        match,
        sentry,
        module_index,
        radial_offset_mm=151.1,
        speed=100_000.0,
        dt=0.003,
    )

    assert illegal.outcome == "large_energy_illegal_projectile"
    assert slow.outcome == "large_energy_ineffective"
    assert outside.outcome == "large_energy_outside_detection_area"
    assert state.completed_groups == 0
    assert state.ring_scores == []
    assert state.failure_count == 0


@pytest.mark.parametrize("team_id", [RED, BLUE])
def test_large_mechanism_real_hits_are_team_symmetric_and_state_isolated(team_id: str):
    match = _match()
    sentry = _start_large(match, team_id)
    other_team = BLUE if team_id == RED else RED
    own_state = match.ruleset._large_energy_mechanism_by_team[team_id]
    other_state = match.ruleset._large_energy_mechanism_by_team[other_team]

    impact = _fire_at_panel(match, sentry, own_state.lit_module_indices[0])

    assert impact.outcome == "large_energy_group_activated"
    assert own_state.completed_groups == 1
    assert len(own_state.ring_scores) == 1
    assert other_state.completed_groups == 0
    assert other_state.ring_scores == []


def test_spectator_sentry_autonomously_starts_and_fires_real_large_energy_shots():
    match = _match(spectator_ai=True)
    rules = match.ruleset
    sentry = _robot(match, "tarsgo-sentry")
    team_id = sentry.team
    match.elapsed_time = 180.0
    rules._current_time = 180.0
    rules._large_energy_rng_by_team[team_id] = random.Random(0)
    sentry.position = rules.large_energy_mechanism_activation_position(team_id)
    sentry.attack_cooldown = 0.0
    match.robots = [sentry]

    contacts = []
    for _ in range(10 * 60):
        match.update(1.0 / 60.0)
        contacts.extend(
            impact
            for impact in match.projectile_system.impacts
            if impact.target_kind == "large_energy_mechanism"
        )

    state = rules._large_energy_mechanism_by_team[team_id]
    assert state.opportunities_used == 1
    assert any(
        impact.outcome
        in {
            "large_energy_group_activated",
            "large_energy_final_group",
            "large_energy_bonus_lamp",
        }
        for impact in contacts
    )
    assert all(impact.shooter_id == sentry.id for impact in contacts)
    assert state.status == "activating"
    assert state.completed_groups < 5


def test_large_ring_boundaries_and_detection_radius_are_deterministic():
    score = Match.from_scenario(SCENARIO).ruleset._large_energy_ring_score
    center = (100.0, 200.0)
    assert score(center, center) == 10
    assert score((115.0, 200.0), center) == 9
    assert score((249.0, 200.0), center) == 1
    assert score((251.1, 200.0), center) is None


def test_large_activation_reset_clears_rotor_sequence_and_display():
    match = _match()
    sentry = _start_large(match)
    rules = match.ruleset
    state = rules._large_energy_mechanism_by_team[RED]
    entity = rules._large_energy_mechanism_entity
    assert entity is not None
    _fire_at_panel(match, sentry, state.lit_module_indices[0])
    assert state.completed_groups == 1

    match.reset()

    reset_state = rules._large_energy_mechanism_by_team[RED]
    assert match.elapsed_time == 0.0
    assert reset_state.status == "inactive"
    assert reset_state.opportunities_used == 0
    assert reset_state.ring_scores == []
    assert rules._large_energy_mechanism_entity is not entity
    assert rules.display_state.large_energy_mechanism is None


def test_large_energy_pose_and_actual_pygame_frame_share_ruleset_state(monkeypatch):
    import pygame

    from tarsgo_simulator.desktop import app
    from tarsgo_simulator.desktop.visuals import CombatVisualState

    match = _match()
    sentry = _start_large(match)
    state = match.ruleset._large_energy_mechanism_by_team[RED]
    hit = _fire_at_panel(match, sentry, state.lit_module_indices[0])
    assert hit.outcome == "large_energy_group_activated"

    display = match.ruleset.display_state.large_energy_mechanism
    assert display is not None
    hitboxes = match.ruleset.large_energy_mechanism_projectile_hitboxes(
        match.elapsed_time
    )
    assert [panel.center for panel in display.panels] == [
        hitbox.center for hitbox in hitboxes
    ]

    pygame.init()
    screen = pygame.Surface(app.WINDOW_SIZE)
    visual_state = CombatVisualState()
    visual_state.reset(match)
    draw_large = app._draw_rmuc_large_energy_mechanism
    calls = []

    def record_large(*args, **kwargs):
        calls.append(args[-1])
        return draw_large(*args, **kwargs)

    monkeypatch.setattr(app, "_draw_rmuc_large_energy_mechanism", record_large)
    teams = list(match.config.scenario.teams.values())
    app._draw(
        screen,
        app.ui_font(25),
        app.ui_font(18),
        match,
        match.config.scenario.player_team,
        next(team.team_id for team in teams if team.team_id != match.config.scenario.player_team),
        set(),
        None,
        app._viewport_for_match(match),
        visual_state=visual_state,
        hud_font=app.ui_font(12),
        static_field_cache=app.RMUCStaticFieldCache(),
    )

    assert len(calls) == 1
    assert len(visual_state.robots) == len(match.robots)
    assert screen.get_bounding_rect().width == app.WINDOW_SIZE[0]
