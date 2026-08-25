from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class IRSFields(BaseModel):
    """LLM extraction result. Optional fields allow deterministic validation."""

    model_config = ConfigDict(extra="forbid")

    notional: Decimal | None = None
    currency: str | None = None
    direction: Literal["PAYER_FIXED", "RECEIVER_FIXED"] | str | None = None
    effective_date: date | None = None
    maturity_date: date | None = None
    fixed_rate: Decimal | None = None
    floating_index: str | None = None
    floating_tenor: str | None = None
    discount_curve: str | None = None
    forwarding_curve: str | None = None

