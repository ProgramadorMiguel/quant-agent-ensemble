from __future__ import annotations

from dataclasses import dataclass

from models.irs_fields import IRSFields


REQUIRED_FIELDS = (
    "notional",
    "currency",
    "direction",
    "effective_date",
    "maturity_date",
    "fixed_rate",
    "floating_index",
    "floating_tenor",
    "discount_curve",
    "forwarding_curve",
)


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    errors: list[str]
    missing_fields: list[str]

    def to_text(self) -> str:
        lines = [f"status: {'VALID' if self.is_valid else 'INVALID'}"]
        lines.append("missing_fields: " + (", ".join(self.missing_fields) or "none"))
        lines.append("errors: " + ("; ".join(self.errors) or "none"))
        return "\n".join(lines) + "\n"


def validate_irs(fields: IRSFields) -> ValidationReport:
    missing = [
        name for name in REQUIRED_FIELDS
        if getattr(fields, name) is None or getattr(fields, name) == ""
    ]
    errors: list[str] = []
    if fields.notional is not None and fields.notional <= 0:
        errors.append("notional must be positive")
    if fields.direction is not None and fields.direction not in {
        "PAYER_FIXED", "RECEIVER_FIXED"
    }:
        errors.append("direction must be PAYER_FIXED or RECEIVER_FIXED")
    if (
        fields.effective_date is not None
        and fields.maturity_date is not None
        and fields.effective_date >= fields.maturity_date
    ):
        errors.append("effective_date must be before maturity_date")
    return ValidationReport(not missing and not errors, errors, missing)

