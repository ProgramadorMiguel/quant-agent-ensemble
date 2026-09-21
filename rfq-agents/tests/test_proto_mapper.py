from datetime import date
from pathlib import Path

import pytest

from models.irs_fields import IBOR, OVERNIGHT_COMPOUNDED
from models.schedule import add_months, payment_dates
from proto.proto_mapper import (
    fields_to_textproto,
    parse_irs_textproto,
    validate_textproto,
)


ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / "protos/pricing.proto"


def test_fields_map_to_parseable_textproto(eur_fields):
    text = fields_to_textproto(eur_fields, "test-rfq", PROTO)
    normalized = validate_textproto(text, PROTO)
    assert 'rfq_id: "test-rfq"' in normalized
    assert 'index: "EURIBOR"' in normalized
    assert 'day_count: "30U/360"' in normalized
    assert "rate_type: IBOR" in normalized


def test_the_forecast_curve_lives_inside_the_floating_leg(eur_fields):
    """Acuerdo con el tutor: solo concierne a la pata flotante."""
    text = fields_to_textproto(eur_fields, "test-rfq", PROTO)
    floating_block = text.split("floating_leg {")[1]
    assert 'forecast_curve: "EUR-EURIBOR-6M"' in floating_block
    assert 'discount_curve: "EUR-ESTR"' in text.split("fixed_leg {")[0]


def test_both_legs_carry_their_own_schedule(eur_fields):
    """Cinco fechas en la pata fija anual, diez en la flotante semestral."""
    text = fields_to_textproto(eur_fields, "test-rfq", PROTO)
    fixed_block, floating_block = text.split("floating_leg {")
    assert fixed_block.count('payment_dates: "') == 5
    assert floating_block.count('payment_dates: "') == 10
    assert 'payment_dates: "2031-09-01"' in fixed_block
    assert 'payment_dates: "2027-03-01"' in floating_block  # solo la flotante


def test_a_compounded_overnight_leg_carries_no_tenor(usd_fields):
    text = fields_to_textproto(usd_fields, "test-rfq", PROTO)
    assert "rate_type: OVERNIGHT_COMPOUNDED" in text
    assert "tenor:" not in text


def _irs_text(fields) -> str:
    """Texto del submensaje ``irs`` de la RFQ que produce el mapeador.

    Se extrae con la propia libreria de protobuf y no partiendo la cadena, porque
    el texto tiene llaves anidadas y cualquier corte por indice es fragil.
    """
    from google.protobuf import text_format

    from proto.proto_mapper import _load_pricing_module

    pb = _load_pricing_module(PROTO)
    message = pb.RFQ()
    text_format.Parse(fields_to_textproto(fields, "test-rfq", PROTO), message)
    return text_format.MessageToString(message.irs)


def test_round_trip_preserves_every_term(eur_fields):
    """Serializar y volver a leer no debe perder nada."""
    parsed = parse_irs_textproto(_irs_text(eur_fields), PROTO)
    assert parsed.currency == "EUR"
    assert parsed.discount_curve == "EUR-ESTR"
    assert parsed.floating_leg.rate_type == IBOR
    assert parsed.floating_leg.tenor == "6M"
    assert parsed.floating_leg.forecast_curve == "EUR-EURIBOR-6M"
    assert len(parsed.fixed_leg.payment_dates) == 5
    assert len(parsed.floating_leg.payment_dates) == 10
    assert parsed.fixed_leg.payment_dates[-1] == date(2031, 9, 1)


def test_round_trip_of_an_overnight_leg(usd_fields):
    parsed = parse_irs_textproto(_irs_text(usd_fields), PROTO)
    assert parsed.floating_leg.rate_type == OVERNIGHT_COMPOUNDED
    assert parsed.floating_leg.tenor is None


def test_invalid_textproto_is_rejected():
    with pytest.raises(Exception):
        validate_textproto("not_a_field: 1", PROTO)


# --- El generador regular, que ahora solo sirve de referencia -----------

def test_schedule_helper_is_deterministic():
    """``payment_dates`` ya no produce la RFQ: el agente calcula el calendario.

    Se conserva porque el validador lo usa para comprobar, de forma laxa, que el
    numero de fechas que el agente ha producido es compatible con la frecuencia
    declarada.
    """
    dates = payment_dates(date(2026, 9, 1), date(2028, 9, 1), "6M")
    assert dates == [
        "2026-09-01", "2027-03-01", "2027-09-01", "2028-03-01", "2028-09-01",
    ]


def test_month_end_is_truncated_not_overflowed():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_unknown_frequency_is_rejected():
    with pytest.raises(ValueError, match="Frecuencia de pago no admitida"):
        payment_dates(date(2026, 9, 1), date(2031, 9, 1), "7M")
