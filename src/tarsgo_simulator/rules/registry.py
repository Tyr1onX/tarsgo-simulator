"""The single explicit mapping from rule ids to their implementations."""

from collections.abc import Callable

from tarsgo_simulator.core.config import RuleDocument
from tarsgo_simulator.rules.protocol import RuleSet
from tarsgo_simulator.rules.training_v0 import TrainingV0Rules


class UnknownRuleSetError(ValueError):
    pass


RULESETS: dict[str, Callable[[RuleDocument], RuleSet]] = {
    "training-v0": TrainingV0Rules,
}


def create_ruleset(document: RuleDocument) -> RuleSet:
    factory = RULESETS.get(document.metadata.id)
    if factory is None:
        raise UnknownRuleSetError(f"Unknown RuleSet id `{document.metadata.id}`")
    return factory(document)
