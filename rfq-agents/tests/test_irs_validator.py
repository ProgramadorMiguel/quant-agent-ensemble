from datetime import date
from decimal import Decimal

from models.irs_fields import FixedLegFields, FloatingLegFields, IRSFields
from validation.irs_validator import validate_irs, with_defaults


def valid_fields(**overrides) -> IRSFields:
    data = dict(
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
    data.update(overrides)
    return IRSFields(**data)


def test_valid_irs_passes():
    report = validate_irs(valid_fields())
    assert report.is_valid
    assert report.errors == []
    assert report.missing_fields == []
    assert report.clarifications == []


def test_missing_terms_are_reported_with_a_request_to_specify():
    report = validate_irs(valid_fields(
        discount_curve=None,
        floating_leg=FloatingLegFields(index="EURIBOR", tenor="6M"),
    ))
    assert not report.is_valid
    assert "discount_curve" in report.missing_fields
    assert "floating_leg.day_count" in report.missing_fields
    assert "la curva de descuento" in report.clarifications
    assert "Para poder valorar" in report.to_text()


def test_the_system_never_defaults_a_market_convention():
    """Una base de calculo ausente se pide, no se rellena con la habitual."""
    report = validate_irs(valid_fields(
        fixed_leg=FixedLegFields(rate=Decimal("0.0275"), payment_frequency="1Y")
    ))
    assert not report.is_valid
    assert report.missing_fields == ["fixed_leg.day_count"]


def test_non_positive_notional_and_date_order_are_rejected():
    report = validate_irs(valid_fields(
        notional=Decimal("0"), maturity_date=date(2026, 9, 1)
    ))
    assert "notional must be positive" in report.errors
    assert "effective_date must be before maturity_date" in report.errors


def test_an_absent_spread_defaults_to_zero():
    """Unica convencion que si se rellena: un vanilla sin spread tiene spread 0."""
    fields = valid_fields(floating_leg=FloatingLegFields(
        index="EURIBOR", tenor="6M", day_count="ACT/360", payment_frequency="6M"
    ))
    assert fields.floating_leg.spread is None
    assert with_defaults(fields).floating_leg.spread == Decimal(0)


def test_a_stated_spread_is_left_untouched():
    fields = valid_fields()
    assert with_defaults(fields).floating_leg.spread == Decimal("0")
    with_spread = valid_fields(floating_leg=FloatingLegFields(
        index="EURIBOR", tenor="6M", spread=Decimal("0.0025"),
        day_count="ACT/360", payment_frequency="6M",
    ))
    assert with_defaults(with_spread).floating_leg.spread == Decimal("0.0025")


def test_defaults_do_not_touch_any_other_term():
    """Ningun otro termino se rellena: los ausentes se reclaman."""
    fields = valid_fields(fixed_leg=FixedLegFields(rate=Decimal("0.0275")))
    defaulted = with_defaults(fields)
    assert defaulted.fixed_leg.day_count is None
    assert defaulted.fixed_leg.payment_frequency is None


def test_unknown_conventions_are_rejected():
    report = validate_irs(valid_fields(
        fixed_leg=FixedLegFields(
            rate=Decimal("0.0275"), day_count="ACT/999", payment_frequency="7M"
        )
    ))
    assert any("day_count must be one of" in e for e in report.errors)
    assert any("payment_frequency must be one of" in e for e in report.errors)


def test_lowercase_frequency_passes_validation_and_is_normalised():
    """El validador acepta '6m'; with_defaults la lleva a '6M' para que la RFQ
    no salga en minuscula."""
    fields = valid_fields(
        fixed_leg=FixedLegFields(
            rate=Decimal("0.0275"), day_count="30/360", payment_frequency="1y"
        ),
        floating_leg=FloatingLegFields(
            index="EURIBOR", tenor="6M", day_count="ACT/360", payment_frequency="6m"
        ),
    )
    assert validate_irs(fields).is_valid
    defaulted = with_defaults(fields)
    assert defaulted.fixed_leg.payment_frequency == "1Y"
    assert defaulted.floating_leg.payment_frequency == "6M"
    assert defaulted.floating_leg.spread == Decimal(0)
