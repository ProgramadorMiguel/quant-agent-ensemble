from datetime import date
from decimal import Decimal
from pathlib import Path

from models.irs_fields import IRSFields
from proto.proto_mapper import fields_to_textproto, validate_textproto


ROOT = Path(__file__).resolve().parents[1]


def test_fields_map_to_parseable_textproto():
    fields = IRSFields(
        notional=Decimal("10000000"), currency="EUR", direction="PAYER_FIXED",
        effective_date=date(2026, 9, 1), maturity_date=date(2031, 9, 1),
        fixed_rate=Decimal("0.0275"), floating_index="EURIBOR",
        floating_tenor="6M", discount_curve="EUR-OIS",
        forwarding_curve="EUR-EURIBOR-6M",
    )
    text = fields_to_textproto(fields, "test-rfq", ROOT / "protos/pricing.proto")
    normalized = validate_textproto(text, ROOT / "protos/pricing.proto")
    assert 'rfq_id: "test-rfq"' in normalized
    assert "direction: PAYER_FIXED" in normalized
    assert 'floating_tenor: "6M"' in normalized


def test_invalid_textproto_is_rejected():
    import pytest
    with pytest.raises(Exception):
        validate_textproto("not_a_field: 1", ROOT / "protos/pricing.proto")

