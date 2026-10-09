import math
from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.projectiles import Projectile
from tarsgo_simulator.core.structure import OUTPOST_ARMOR_MAX_SPEED


ROOT = Path(__file__).resolve().parents[1]
RMUC = ROOT / "configs/scenarios/rmuc-2026-region-rules-lab.yaml"
RMUL = ROOT / "configs/scenarios/rmul-2026-rules-lab.yaml"
TRAINING = ROOT / "configs/scenarios/first-steps.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match(path: Path = RMUC) -> Match:
    match = Match.from_scenario(path)
    for index, robot in enumerate(match.robots):
        robot.position = (12_000.0 + index * 80.0, 13_000.0)
        robot.speed = 0.0
        robot.velocity = (0.0, 0.0)
        robot.attack_cooldown = 9999.0
    return match


def _structure(match: Match, team: str, kind: str):
    return next(
        structure
        for structure in match.structures
        if structure.team == team and structure.type == kind
    )


def _sync_rule_time(match: Match, elapsed: float) -> None:
    match.elapsed_time = elapsed
    match.ruleset.update(match, 0.0)


def _shoot_panel(
    match: Match,
    outpost,
    *,
    panel_index: int = 0,
    profile=None,
    caliber: str = "17mm",
    along_offset: float = 0.0,
    projectile_damage: int | None = None,
):
    profile = profile or match.ruleset.structure_projectile_hitbox_profile(outpost)
    assert profile is not None and profile.armor_panels
    panel = profile.armor_panels[panel_index]
    target = (
        outpost.position[0]
        + panel.center[0]
        + panel.long_axis[0] * along_offset,
        outpost.position[1]
        + panel.center[1]
        + panel.long_axis[1] * along_offset,
    )
    axis = panel.short_axis
    speed = 20_000.0
    start = (target[0] + axis[0] * 500.0, target[1] + axis[1] * 500.0)
    attacker_team = RED if outpost.team == BLUE else BLUE
    shooter_type = "hero" if caliber == "42mm" else "infantry"
    shooter = next(
        robot
        for robot in match.robots
        if robot.team == attacker_team and robot.type == shooter_type
    )
    match.projectile_system.projectiles.append(
        Projectile(
            id=1000 + match.projectile_system.total_impacts,
            shooter_id=shooter.id,
            shooter_team_id=attacker_team,
            caliber=caliber,
            damage=shooter.damage if projectile_damage is None else projectile_damage,
            radius=8.4 if caliber == "17mm" else 21.25,
            speed=speed,
            effective_range=1000.0,
            position=start,
            previous_position=start,
            velocity=(-axis[0] * speed, -axis[1] * speed),
        )
    )
    match.update(0.05)
    return shooter, match.projectile_impacts[-1]


def test_ruleset_owns_one_shared_direction_and_official_rotation_timing() -> None:
    match = _match()
    red_state = match.ruleset._team_states[RED].outpost_rotation
    blue_state = match.ruleset._team_states[BLUE].outpost_rotation
    assert red_state is not None and blue_state is not None
    assert red_state.direction == blue_state.direction
    assert red_state.direction in {-1, 1}

    red_outpost = _structure(match, RED, "outpost")
    blue_outpost = _structure(match, BLUE, "outpost")
    start_pose = match.ruleset.outpost_armor_rotation_angle(red_outpost)
    _sync_rule_time(match, 2.5)
    half_ramp_pose = match.ruleset.outpost_armor_rotation_angle(red_outpost)
    _sync_rule_time(match, 5.0)
    full_ramp_pose = match.ruleset.outpost_armor_rotation_angle(red_outpost)
    _sync_rule_time(match, 5.05)
    max_speed_pose = match.ruleset.outpost_armor_rotation_angle(red_outpost)

    assert start_pose == pytest.approx(0.0)
    assert half_ramp_pose == pytest.approx(red_state.direction * math.pi / 2)
    assert full_ramp_pose == pytest.approx(0.0, abs=1e-9)
    assert abs(max_speed_pose - full_ramp_pose) == pytest.approx(
        OUTPOST_ARMOR_MAX_SPEED * 0.05,
        abs=1e-6,
    )
    assert match.ruleset.outpost_armor_rotation_angle(blue_outpost) == pytest.approx(
        max_speed_pose
    )


def test_three_minute_stop_boundary_returns_to_start_and_never_restarts() -> None:
    match = _match()
    outpost = _structure(match, RED, "outpost")
    rotation = match.ruleset._team_states[RED].outpost_rotation
    assert rotation is not None

    _sync_rule_time(match, 180.0 - 1 / 60)
    assert rotation.stop_time is None
    _sync_rule_time(match, 180.0)
    assert rotation.stop_time == pytest.approx(180.0)
    stopped_angle = rotation.angle_at(180.0)
    assert rotation.angle_at(185.0) != pytest.approx(stopped_angle)
    assert rotation.angle_at(190.0) == pytest.approx(0.0, abs=1e-9)
    _sync_rule_time(match, 200.0)
    assert rotation.stop_time == pytest.approx(180.0)
    assert match.ruleset.outpost_armor_rotation_angle(outpost) == pytest.approx(0.0)


def test_destroyed_outpost_freezes_armor_pose_even_after_rebuild() -> None:
    match = _match()
    outpost = _structure(match, BLUE, "outpost")
    _sync_rule_time(match, 32.0)
    assert match.apply_damage(outpost, 1500, source_team_id=RED) == 1500
    match.ruleset.update(match, 0.0)

    rotation = match.ruleset._team_states[BLUE].outpost_rotation
    assert rotation is not None
    assert rotation.stop_time == pytest.approx(32.0)
    assert rotation.destroyed_at_stop
    frozen = rotation.angle_at(32.0)
    outpost.alive = True
    outpost.hp = 750
    _sync_rule_time(match, 60.0)
    assert rotation.stop_time == pytest.approx(32.0)
    assert rotation.angle_at(60.0) == pytest.approx(frozen)


def test_opponent_base_armor_deployment_stops_and_returns_outpost_armor() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    rotation = match.ruleset._team_states[RED].outpost_rotation
    assert rotation is not None
    _sync_rule_time(match, 31.0)

    assert match.apply_damage(
        base,
        3000,
        source_team_id=RED,
        bypass_invincibility=True,
    ) == 3000
    match.ruleset.update(match, 0.0)

    assert match.ruleset._team_states[BLUE].base_armor_deployed
    assert rotation.stop_time == pytest.approx(31.0)
    assert not rotation.destroyed_at_stop
    assert rotation.angle_at(41.0) == pytest.approx(0.0, abs=1e-9)
    assert rotation.angle_at(45.0) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(("target_team", "attacker_team"), [(BLUE, RED), (RED, BLUE)])
def test_real_projectile_hits_rotating_module_and_records_actual_hp_damage(
    target_team: str,
    attacker_team: str,
) -> None:
    match = _match()
    outpost = _structure(match, target_team, "outpost")
    match.ruleset.grant_attack_buff(attacker_team, 1.25, 5.0)
    original_hp = outpost.hp

    shooter, impact = _shoot_panel(match, outpost)
    hit = impact.structure_hit
    assert impact.target_id == outpost.id
    assert impact.outcome == "damage"
    assert hit is not None
    assert hit.module_id == "outpost-armor-1"
    assert hit.caliber == "17mm"
    assert hit.effective_impact_speed == pytest.approx(20_000.0, rel=0.002)
    assert hit.center_hit
    assert outpost.hp == original_hp - 30  # max(1.25 team, 1.50 center) × 20

    report = match.battle_report()
    shooter_stats = next(item for item in report.robots if item.robot_id == shooter.id)
    attacking_team_stats = next(
        item for item in report.teams if item.team_id == attacker_team
    )
    target_team_stats = next(item for item in report.teams if item.team_id == target_team)
    assert shooter_stats.damage_dealt == 30
    assert attacking_team_stats.damage_dealt == 30
    assert target_team_stats.outpost_hp == outpost.hp


@pytest.mark.parametrize(
    ("caliber", "along_offset", "center_hit", "expected_damage"),
    [
        ("17mm", 13.0, True, 30),
        ("17mm", 14.0, False, 20),
        ("42mm", 26.0, True, 300),
        ("42mm", 29.0, False, 200),
    ],
)
def test_center_region_threshold_uses_projectile_contact_for_both_calibers(
    caliber: str,
    along_offset: float,
    center_hit: bool,
    expected_damage: int,
) -> None:
    match = _match()
    outpost = _structure(match, BLUE, "outpost")
    original_hp = outpost.hp

    _shooter, impact = _shoot_panel(
        match,
        outpost,
        caliber=caliber,
        along_offset=along_offset,
    )

    assert impact.outcome == "damage"
    assert impact.structure_hit is not None
    assert impact.structure_hit.center_hit is center_hit
    assert outpost.hp == original_hp - expected_damage


@pytest.mark.parametrize(("caliber", "expected_damage"), [("17mm", 30), ("42mm", 300)])
def test_outpost_armor_uses_official_damage_independent_of_projectile_metadata(
    caliber: str,
    expected_damage: int,
) -> None:
    match = _match()
    outpost = _structure(match, BLUE, "outpost")
    original_hp = outpost.hp

    _shooter, impact = _shoot_panel(
        match,
        outpost,
        caliber=caliber,
        projectile_damage=1,
    )

    assert impact.outcome == "damage"
    assert impact.structure_hit is not None and impact.structure_hit.center_hit
    assert outpost.hp == original_hp - expected_damage


def test_rotating_pose_changes_contact_and_preserves_generic_body_damage() -> None:
    match = _match()
    outpost = _structure(match, BLUE, "outpost")
    initial_profile = match.ruleset.structure_projectile_hitbox_profile(outpost)
    assert initial_profile is not None

    rotation_time = math.sqrt(10.0 * (math.pi / 3) / OUTPOST_ARMOR_MAX_SPEED)
    _sync_rule_time(match, rotation_time)
    original_hp = outpost.hp
    _shooter, impact = _shoot_panel(
        match,
        outpost,
        profile=initial_profile,
    )

    assert impact.target_id == outpost.id
    assert impact.outcome == "damage"
    assert impact.structure_hit is not None
    assert impact.structure_hit.module_id == "outpost-body"
    assert outpost.hp == original_hp - _shooter.damage


def test_outpost_miss_and_match_reset_clear_rotation_and_report() -> None:
    match = _match()
    outpost = _structure(match, BLUE, "outpost")
    red_rotation = match.ruleset._team_states[RED].outpost_rotation
    blue_rotation = match.ruleset._team_states[BLUE].outpost_rotation
    assert red_rotation is not None and blue_rotation is not None
    red_rotation.stop(20.0)

    before = match.projectile_system.misses
    shooter = next(robot for robot in match.robots if robot.team == RED)
    start = (outpost.position[0] - 800.0, outpost.position[1] - 350.0)
    match.projectile_system.projectiles.append(
        Projectile(
            id=1,
            shooter_id=shooter.id,
            shooter_team_id=RED,
            caliber="17mm",
            damage=shooter.damage,
            radius=8.4,
            speed=20_000.0,
            effective_range=1000.0,
            position=start,
            previous_position=start,
            velocity=(20_000.0, 0.0),
        )
    )
    match.update(0.05)
    assert not match.projectile_impacts
    assert match.projectile_system.misses == before + 1

    match.reset()
    reset_red = match.ruleset._team_states[RED].outpost_rotation
    reset_blue = match.ruleset._team_states[BLUE].outpost_rotation
    assert reset_red is not None and reset_blue is not None
    assert reset_red.stop_time is None and reset_blue.stop_time is None
    assert reset_red.direction == reset_blue.direction
    assert _structure(match, BLUE, "outpost").hp == 1500
    assert match.battle_report().teams[0].damage_dealt == 0


@pytest.mark.parametrize("scenario", [RMUL, TRAINING])
def test_non_rmuc_rulesets_remain_compatible(scenario: Path) -> None:
    match = _match(scenario)
    match.update(1 / 60)
    for structure in match.structures:
        if structure.type != "outpost":
            continue
        profile_for = getattr(match.ruleset, "structure_projectile_hitbox_profile", None)
        profile = profile_for(structure) if profile_for is not None else None
        assert not getattr(profile, "armor_panels", ())
