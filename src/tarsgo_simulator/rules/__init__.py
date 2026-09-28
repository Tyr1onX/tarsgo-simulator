"""Small, explicit rule implementations for the simulator."""

from tarsgo_simulator.rules.protocol import (
    MatchResult,
    RobotParameters,
    RuleSet,
    RuleSetDisplayState,
    StructureParameters,
)
from tarsgo_simulator.rules.rmul_2026_3v3 import RMUL2026Rules
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules

__all__ = [
    "MatchResult",
    "RobotParameters",
    "RuleSet",
    "RuleSetDisplayState",
    "StructureParameters",
    "RMUL2026Rules",
    "RMUC2026RegionalRules",
]
