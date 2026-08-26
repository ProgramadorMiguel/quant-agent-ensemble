from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class FieldOutcome(str, Enum):
    """Per-field result. Distinguishing these four is the whole point."""

    MATCH = "MATCH"                # expected value reproduced (or correctly left empty)
    WRONG = "WRONG"                # a value was extracted, but not the right one
    MISSING = "MISSING"            # the prompt stated it, the model dropped it
    HALLUCINATED = "HALLUCINATED"  # the prompt never stated it, the model invented it


@dataclass(frozen=True)
class FieldComparison:
    per_field: dict[str, FieldOutcome]

    def count(self, outcome: FieldOutcome) -> int:
        return sum(1 for value in self.per_field.values() if value is outcome)

    @property
    def total(self) -> int:
        return len(self.per_field)

    @property
    def matched(self) -> int:
        return self.count(FieldOutcome.MATCH)

    @property
    def accuracy(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def hallucinated_fields(self) -> list[str]:
        return sorted(name for name, outcome in self.per_field.items()
                      if outcome is FieldOutcome.HALLUCINATED)

    def summary(self) -> str:
        parts = [f"{outcome.value.lower()}={self.count(outcome)}"
                 for outcome in FieldOutcome if self.count(outcome)]
        return " ".join(parts)


def _empty(value: object) -> bool:
    return value is None or value == ""


def compare_fields(actual: dict, expected: dict) -> FieldComparison:
    """Classify every field of the golden case against what the model produced."""
    per_field: dict[str, FieldOutcome] = {}
    for name in expected:
        want, got = expected.get(name), actual.get(name)
        if _empty(want) and _empty(got):
            per_field[name] = FieldOutcome.MATCH
        elif _empty(want):
            per_field[name] = FieldOutcome.HALLUCINATED
        elif _empty(got):
            per_field[name] = FieldOutcome.MISSING
        elif str(want) == str(got):
            per_field[name] = FieldOutcome.MATCH
        else:
            per_field[name] = FieldOutcome.WRONG
    return FieldComparison(per_field)


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion.

    Reported alongside every rate: with a handful of cases, 6/6 and 60/60 are
    not the same evidence even though both are 100%.
    """
    if trials == 0:
        return (0.0, 0.0)
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def format_rate(successes: int, trials: int) -> str:
    if trials == 0:
        return "n/a"
    low, high = wilson_interval(successes, trials)
    return f"{successes / trials:6.1%}  [{low:.0%}-{high:.0%}]  ({successes}/{trials})"


def mcnemar(a_correct: list[bool], b_correct: list[bool]) -> tuple[int, int, float]:
    """Paired comparison of two models over the same cases.

    Returns (a_only, b_only, p_value) using the exact binomial test on the
    discordant pairs. Only the cases where the two models disagree carry
    information, which is exactly why the paired test beats comparing two rates.
    """
    a_only = sum(1 for a, b in zip(a_correct, b_correct) if a and not b)
    b_only = sum(1 for a, b in zip(a_correct, b_correct) if b and not a)
    n = a_only + b_only
    if n == 0:
        return (0, 0, 1.0)
    k = min(a_only, b_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return (a_only, b_only, min(1.0, 2 * tail))
