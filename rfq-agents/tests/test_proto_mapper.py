from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from models.irs_fields import FixedLegFields, FloatingLegFields, IRSFields
from models.schedule import add_months, payment_dates
from proto.proto_mapper import fields_to_textproto, validate_textproto


ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / "protos/pricing.proto"


def sample_fields() -> IRSFields:
    return IRSFields(
        notional=Decimal("10000000"), currency="EUR",
        is_fixed_rate_receiver=False,
        valuation_date=date(2026, 9, 1),
        effective_date=date(2026, 9, 1), maturity_date=date(2031, 9, 1),
        discount_curve="EUR-ESTR", forecast_curve="EUR-EURIBOR-6M",
        fixed_leg=FixedLegFields(
            rate=Decimal("0.0275"), day_count="30/360", payment_frequency="1Y"
        ),
        floating_leg=FloatingLegFields(
            index="EURIBOR", tenor="6M", spread=Decimal("0"),
            day_count="ACT/360", payment_frequency="6M",
        ),
    )


def test_fields_map_to_parseable_textproto():
    text = fields_to_textproto(sample_fields(), "test-rfq", PROTO)
    normalized = validate_textproto(text, PROTO)
    assert 'rfq_id: "test-rfq"' in normalized
    assert "is_fixed_rate_receiver" not in normalized or "false" in normalized
    assert 'index: "EURIBOR"' in normalized
    assert 'day_count: "30/360"' in normalized
    assert 'day_count: "ACT/360"' in normalized


def test_each_leg_carries_its_own_payment_schedule():
    """Definicion 2.19: cada pata tiene su propio calendario de pagos."""
    text = fields_to_textproto(sample_fields(), "test-rfq", PROTO)
    # Pata fija anual y flotante semestral sobre cinco anos: 6 y 11 fechas.
    assert text.count('payment_dates: "') == 6 + 11
    assert 'payment_dates: "2026-09-01"' in text
    assert 'payment_dates: "2031-09-01"' in text
    assert 'payment_dates: "2027-03-01"' in text  # solo la flotante


def test_schedule_is_deterministic_and_ignores_holidays():
    dates = payment_dates(date(2026, 9, 1), date(2028, 9, 1), "6M")
    assert dates == [
        "2026-09-01", "2027-03-01", "2027-09-01", "2028-03-01", "2028-09-01",
    ]


def test_month_end_is_truncated_not_overflowed():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_unknown_frequency_is_rejected():
    with pytest.raises(ValueError, match="Frecuencia de pago no admitida"):
        payment_dates(date(2026, 9, 1), date(2031, 9, 1), "7M")


def test_invalid_textproto_is_rejected():
    with pytest.raises(Exception):
        validate_textproto("not_a_field: 1", PROTO)
