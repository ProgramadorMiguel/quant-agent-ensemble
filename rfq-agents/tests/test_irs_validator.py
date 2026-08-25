from datetime import date
from decimal import Decimal

from models.irs_fields import IRSFields
from validation.irs_validator import validate_irs


def valid_fields(**overrides):
    data = dict(
        notional=Decimal("10000000"), currency="EUR", direction="PAYER_FIXED",
        effective_date=date(2026, 9, 1), maturity_date=date(2031, 9, 1),
        fixed_rate=Decimal("0.0275"), floating_index="EURIBOR",
        floating_tenor="6M", discount_curve="EUR-OIS",
        forwarding_curve="EUR-EURIBOR-6M",
    )
    data.update(overrides)
    return IRSFields(**data)


def test_valid_irs_passes():
    report = validate_irs(valid_fields())
    assert report.is_valid
    assert report.errors == []
    assert report.missing_fields == []


def test_missing_fields_are_reported():
    report = validate_irs(valid_fields(floating_index=None, discount_curve=None))
    assert not report.is_valid
    assert report.missing_fields == ["floating_index", "discount_curve"]


def test_non_positive_notional_and_date_order_are_rejected():
    report = validate_irs(valid_fields(
        notional=Decimal("0"), maturity_date=date(2026, 9, 1)
    ))
    assert "notional must be positive" in report.errors
    assert "effective_date must be before maturity_date" in report.errors

