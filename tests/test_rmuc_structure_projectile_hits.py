import math
from pathlib import Path

import pytest

from tarsgo_simulator.core.match import Match
from tarsgo_simulator.core.projectiles import Projectile
from tarsgo_simulator.core.structure import Structure


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "configs" / "scenarios" / "rmuc-2026-region-rules-lab.yaml"
RED = "tarsgo-rmuc-2026-region"
BLUE = "opponent-rmuc-2026-region"


def _match() -> Match:
    match = Match.from_scenario(SCENARIO)
    for index, robot in enumerate(match.robots):
        robot.position = (12_000.0 + index * 80.0, 13_000.0)
        robot.speed = 0.0
        robot.velocity = (0.0, 0.0)
        robot.attack_cooldown = 9999.0
    return match


def _structure(match: Match, team: str, structure_type: str) -> Structure:
    return next(
        structure
        for structure in match.structures
        if structure.team == team and structure.type == structure_type
    )


def _module_geometry(
    match: Match,
    base: Structure,
    edge_index: int,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    vertices = base.footprint_vertices
    start_local = vertices[edge_index]
    end_local = vertices[(edge_index + 1) % len(vertices)]
    start = (base.position[0] + start_local[0], base.position[1] + start_local[1])
    end = (base.position[0] + end_local[0], base.position[1] + end_local[1])
    length = math.dist(start, end)
    tangent = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
    area_twice = sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(vertices, (*vertices[1:], vertices[0]))
    )
    outward = (
        (tangent[1], -tangent[0])
        if area_twice > 0
        else (-tangent[1], tangent[0])
    )
    profile = match.ruleset.structure_projectile_hitbox_profile(base)
    assert profile is not None
    offset = profile.deployed_offset_mm if profile.deployed else 0.0
    center = (
        (start[0] + end[0]) / 2 + outward[0] * offset,
        (start[1] + end[1]) / 2 + outward[1] * offset,
    )
    return center, tangent, outward


def _fire_structure_projectile(
    match: Match,
    base: Structure,
    *,
    caliber: str = "17mm",
    speed: float = 20_000.0,
    edge_index: int | None = None,
    tangent_offset: float = 0.0,
):
    profile = match.ruleset.structure_projectile_hitbox_profile(base)
    assert profile is not None
    if edge_index is None:
        edge_index = profile.upper_front_edge_index
    center, tangent, outward = _module_geometry(match, base, edge_index)
    impact_target = (
        center[0] + tangent[0] * tangent_offset,
        center[1] + tangent[1] * tangent_offset,
    )
    attacker_team = RED if base.team == BLUE else BLUE
    shooter_type = "hero" if caliber == "42mm" else "infantry"
    shooter = next(
        robot
        for robot in match.robots
        if robot.team == attacker_team and robot.type == shooter_type
    )
    projectile_id = 1000 + match.projectile_system.total_impacts
    radius = 8.4 if caliber == "17mm" else 21.25
    start = (
        impact_target[0] + outward[0] * 500.0,
        impact_target[1] + outward[1] * 500.0,
    )
    match.projectile_system.projectiles.append(
        Projectile(
            id=projectile_id,
            shooter_id=shooter.id,
            shooter_team_id=shooter.team,
            caliber=caliber,
            damage=shooter.damage,
            radius=radius,
            speed=speed,
            effective_range=1000.0,
            position=start,
            previous_position=start,
            velocity=(-outward[0] * speed, -outward[1] * speed),
        )
    )
    match.update(0.05)
    assert match.projectile_impacts
    return shooter, match.projectile_impacts[-1]


def test_real_projectile_records_base_module_impact_facts_and_applies_center_gain() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(match, base)

    hit = impact.structure_hit
    assert hit is not None
    assert impact.target_id == base.id
    assert impact.outcome == "damage"
    assert hit.module_id == "base-upper-front"
    assert hit.caliber == "17mm"
    assert hit.effective_impact_speed == pytest.approx(20_000.0)
    assert hit.center_hit
    assert hit.normal[0] != 0.0 or hit.normal[1] != 0.0
    assert base.hp == original_hp - 8  # floor(5 raw × 150% Attack + 0.5)


@pytest.mark.parametrize(
    ("base_team", "attacker_team"),
    [(RED, BLUE), (BLUE, RED)],
)
def test_upper_front_module_damage_and_hit_context_are_team_symmetric(
    base_team: str,
    attacker_team: str,
) -> None:
    match = _match()
    base = _structure(match, base_team, "base")
    _structure(match, base_team, "outpost").alive = False
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(match, base)

    assert impact.target_id == base.id
    assert impact.shooter_team_id == attacker_team
    assert impact.structure_hit is not None
    assert impact.structure_hit.module_id == "base-upper-front"
    assert base.hp == original_hp - 8


@pytest.mark.parametrize(
    ("caliber", "special_edge", "tangent_offset", "expected_damage"),
    [
        ("17mm", True, 0.0, 8),
        ("17mm", False, 0.0, 30),
        ("17mm", False, 5.0, 30),
        ("17mm", False, 5.1, 20),
        ("17mm", False, 6.0, 20),
        ("42mm", False, 0.0, 300),
        ("42mm", False, 5.0, 300),
        ("42mm", False, 5.1, 200),
        ("42mm", False, 6.0, 200),
    ],
)
def test_base_module_damage_table_and_center_area(
    caliber: str,
    special_edge: bool,
    tangent_offset: float,
    expected_damage: int,
) -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    profile = match.ruleset.structure_projectile_hitbox_profile(base)
    assert profile is not None
    edge_index = profile.upper_front_edge_index if special_edge else next(
        index for index in range(6) if index != profile.upper_front_edge_index
    )
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(
        match,
        base,
        caliber=caliber,
        edge_index=edge_index,
        tangent_offset=tangent_offset,
    )

    assert impact.structure_hit is not None
    assert impact.structure_hit.center_hit is (tangent_offset <= 5.0)
    assert base.hp == original_hp - expected_damage


@pytest.mark.parametrize(
    ("caliber", "speed", "expected_damage"),
    [
        ("17mm", 12_000.0, 0),
        ("17mm", 12_001.0, 8),
        ("42mm", 10_000.0, 0),
        ("42mm", 10_001.0, 300),
    ],
)
def test_structure_projectile_uses_strict_effective_normal_speed_threshold(
    caliber: str,
    speed: float,
    expected_damage: int,
) -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(
        match,
        base,
        caliber=caliber,
        speed=speed,
    )

    assert impact.structure_hit is not None
    assert impact.structure_hit.effective_impact_speed == pytest.approx(speed)
    assert base.hp == original_hp - expected_damage
    if expected_damage == 0:
        assert impact.outcome == "ineffective"


def test_base_stays_immune_and_virtual_shield_is_not_consumed_while_outpost_lives() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    state = match.ruleset._team_states[BLUE]
    state.base_virtual_shield = 50
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(match, base, caliber="42mm")

    assert impact.structure_hit is not None
    assert impact.outcome == "immune"
    assert impact.applied_damage == 0
    assert base.hp == original_hp
    assert state.base_virtual_shield == 50


@pytest.mark.parametrize(
    ("initial_hp", "expected_hp", "deployed"),
    [(2021, 2001, False), (2020, 2000, True)],
)
def test_base_armor_deploys_at_exactly_2000_hp_from_projectile_damage(
    initial_hp: int,
    expected_hp: int,
    deployed: bool,
) -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    base.hp = initial_hp
    profile = match.ruleset.structure_projectile_hitbox_profile(base)
    assert profile is not None and not profile.deployed
    edge_index = next(
        index
        for index in range(6)
        if index != profile.upper_front_edge_index
    )

    _shooter, impact = _fire_structure_projectile(
        match,
        base,
        edge_index=edge_index,
        tangent_offset=6.0,
    )

    assert impact.applied_damage == 20
    assert base.hp == expected_hp
    assert match.ruleset._team_states[BLUE].base_armor_deployed is deployed
    assert match.ruleset.structure_projectile_hitbox_profile(base).deployed is deployed


def test_deployed_base_armor_moves_real_projectile_contact_and_reset_clears_it() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    base.hp = 2020
    profile = match.ruleset.structure_projectile_hitbox_profile(base)
    assert profile is not None and not profile.deployed
    edge_index = next(
        index
        for index in range(6)
        if index != profile.upper_front_edge_index
    )

    _shooter, closed_impact = _fire_structure_projectile(
        match,
        base,
        edge_index=edge_index,
        tangent_offset=6.0,
    )
    assert base.hp == 2000
    assert match.ruleset._team_states[BLUE].base_armor_deployed

    _shooter, deployed_impact = _fire_structure_projectile(
        match,
        base,
        edge_index=edge_index,
        tangent_offset=6.0,
    )
    assert closed_impact.structure_hit is not None
    assert deployed_impact.structure_hit is not None
    _center, _tangent, outward = _module_geometry(match, base, edge_index)
    displacement = (
        deployed_impact.structure_hit.impact_position[0]
        - closed_impact.structure_hit.impact_position[0],
        deployed_impact.structure_hit.impact_position[1]
        - closed_impact.structure_hit.impact_position[1],
    )
    assert displacement[0] * outward[0] + displacement[1] * outward[1] == pytest.approx(
        profile.deployed_offset_mm,
        abs=0.1,
    )

    match.reset()
    reset_base = _structure(match, BLUE, "base")
    reset_state = match.ruleset._team_states[BLUE]
    assert not reset_state.base_armor_deployed
    assert reset_state.base_virtual_shield == 0
    assert not match.ruleset.structure_projectile_hitbox_profile(reset_base).deployed


def test_center_attack_gain_resolves_before_virtual_shield_and_actual_hp() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    state = match.ruleset._team_states[BLUE]
    state.base_virtual_shield = 3
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(match, base, caliber="17mm")

    assert impact.structure_hit is not None and impact.structure_hit.center_hit
    assert impact.applied_damage == 5
    assert base.hp == original_hp - 5
    assert state.base_virtual_shield == 0


def test_center_attack_gain_is_inside_existing_defense_rounding() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    match.ruleset._team_states[BLUE].tech_core_defense = 0.5
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(match, base, caliber="17mm")

    assert impact.structure_hit is not None and impact.structure_hit.center_hit
    assert impact.applied_damage == 4  # round(5 × 150% Attack × (1 - 50% Defense))
    assert base.hp == original_hp - 4


@pytest.mark.parametrize(
    ("team_attack_multiplier", "tangent_offset", "expected_damage"),
    [
        (1.0, 6.0, 20),  # no team buff, non-center
        (1.0, 0.0, 30),  # center is the only Attack buff
        (1.5, 6.0, 30),
        (1.5, 0.0, 30),  # equal buffs do not stack
        (2.0, 6.0, 40),
        (2.0, 0.0, 40),  # 200% team buff wins over center
        (3.0, 6.0, 60),
        (3.0, 0.0, 60),  # 300% team buff wins over center
    ],
)
def test_real_projectile_uses_max_of_team_and_center_attack_buffs(
    team_attack_multiplier: float,
    tangent_offset: float,
    expected_damage: int,
) -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    profile = match.ruleset.structure_projectile_hitbox_profile(base)
    assert profile is not None
    other_module = next(
        index for index in range(6) if index != profile.upper_front_edge_index
    )
    if team_attack_multiplier > 1.0:
        assert match.ruleset.grant_attack_buff(RED, team_attack_multiplier, 10.0)
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(
        match,
        base,
        edge_index=other_module,
        tangent_offset=tangent_offset,
    )

    assert impact.structure_hit is not None
    assert impact.structure_hit.center_hit is (tangent_offset == 0.0)
    assert impact.applied_damage == expected_damage
    assert base.hp == original_hp - expected_damage


def test_real_projectile_applies_max_attack_buff_before_half_up_rounding() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    match.ruleset._team_states[BLUE].tech_core_defense = 0.4
    assert match.ruleset.grant_attack_buff(RED, 1.5, 10.0)
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(match, base, caliber="17mm")

    assert impact.structure_hit is not None and impact.structure_hit.center_hit
    # 5 raw × max(150% team, 150% center) × (1 - 40% Defense) = 4.5;
    # the existing final half-up settlement yields 5, not multiplied-buff 7.
    assert impact.applied_damage == 5
    assert base.hp == original_hp - 5


def test_real_projectile_applies_virtual_shield_after_max_attack_buff() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    target_state = match.ruleset._team_states[BLUE]
    target_state.base_virtual_shield = 6
    assert match.ruleset.grant_attack_buff(RED, 2.0, 10.0)
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(match, base, caliber="17mm")

    assert impact.structure_hit is not None and impact.structure_hit.center_hit
    # 10 damage after max(200% team, 150% center); shield absorbs six.
    assert impact.applied_damage == 4
    assert base.hp == original_hp - 4
    assert target_state.base_virtual_shield == 0


def test_real_projectile_hitting_base_body_between_modules_does_not_damage_hp() -> None:
    match = _match()
    base = _structure(match, BLUE, "base")
    _structure(match, BLUE, "outpost").alive = False
    profile = match.ruleset.structure_projectile_hitbox_profile(base)
    assert profile is not None
    edge_index = next(
        index for index in range(6) if index != profile.upper_front_edge_index
    )
    body_offset = profile.module_width_mm / 2 + 8.4 + 10.0
    target_state = match.ruleset._team_states[BLUE]
    target_state.base_virtual_shield = 37
    original_hp = base.hp

    _shooter, impact = _fire_structure_projectile(
        match,
        base,
        edge_index=edge_index,
        tangent_offset=body_offset,
    )

    assert impact.target_id == base.id
    assert impact.structure_hit is not None
    assert impact.structure_hit.module_id is None
    assert impact.outcome == "structure_body"
    assert impact.applied_damage == 0
    assert base.hp == original_hp
    assert target_state.base_virtual_shield == 37


@pytest.mark.parametrize(
    ("scenario", "attacker_team", "target_team"),
    [
        ("first-steps.yaml", "tarsgo", "opponent-balanced"),
        ("rmul-2026-rules-lab.yaml", "tarsgo-rmul-2026", "opponent-rmul-2026"),
    ],
)
def test_training_and_rmul_keep_existing_damage_semantics(
    scenario: str,
    attacker_team: str,
    target_team: str,
) -> None:
    match = Match.from_scenario(ROOT / "configs" / "scenarios" / scenario)
    attacker = next(robot for robot in match.robots if robot.team == attacker_team)
    target = next(robot for robot in match.robots if robot.team == target_team)
    original_hp = target.hp

    assert not match.uses_physical_projectiles
    assert match.ruleset.resolve_damage(
        target,
        17,
        attacker.team,
        attack_multiplier=3.0,
    ) == 17
    assert match.apply_damage(target, 17, source_robot=attacker) == 17
    assert target.hp == original_hp - 17
