from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float
    verified: bool

    def cost_usd(self, input_tokens: int, output_tokens: int, cached: int = 0) -> float:
        billable_input = max(input_tokens - cached, 0)
        return (
            billable_input * self.input_per_mtok
            + cached * self.cached_input_per_mtok
            + output_tokens * self.output_per_mtok
        ) / 1_000_000


@lru_cache(maxsize=4)
def load_prices(project_root: Path) -> dict[str, ModelPrice]:
    path = project_root / "config/model_costs.toml"
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        name: ModelPrice(
            provider=entry.get("provider", "unknown"),
            input_per_mtok=float(entry["input_per_mtok"]),
            output_per_mtok=float(entry["output_per_mtok"]),
            cached_input_per_mtok=float(entry.get("cached_input_per_mtok", 0.0)),
            verified=bool(entry.get("verified", False)),
        )
        for name, entry in (raw.get("models") or {}).items()
    }


def cost_of(
    project_root: Path, model: str, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    """None when the model has no price declared: never guess a cost."""
    price = load_prices(project_root).get(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return price.cost_usd(input_tokens, output_tokens)


def unverified_models(project_root: Path) -> list[str]:
    return sorted(n for n, p in load_prices(project_root).items() if not p.verified)
