"""The single explicit mapping from rule ids to their implementations."""

from collections.abc import Callable

from tarsgo_simulator.core.config import RuleDocument
from tarsgo_simulator.rules.protocol import RuleSet
from tarsgo_simulator.rules.rmul_2026_3v3 import RMUL2026Rules
from tarsgo_simulator.rules.rmuc_2026_region import RMUC2026RegionalRules
from tarsgo_simulator.rules.training_v0 import TrainingV0Rules


class UnknownRuleSetError(ValueError):
    pass


RULESETS: dict[str, Callable[[RuleDocument], RuleSet]] = {
    "training-v0": TrainingV0Rules,
    "rmul-2026-3v3": RMUL2026Rules,
    "rmuc-2026-region-v1.4.0": RMUC2026RegionalRules,
}


def create_ruleset(document: RuleDocument) -> RuleSet:
    factory = RULESETS.get(document.metadata.id)
    if factory is None:
        raise UnknownRuleSetError(f"Unknown RuleSet id `{document.metadata.id}`")
    return factory(document)
