from datetime import date
from decimal import Decimal

from models.irs_fields import (
    IBOR,
    OVERNIGHT_COMPOUNDED,
    FixedLegFields,
    FloatingLegFields,
)
from validation.irs_validator import validate_irs, with_defaults


# --- Casos que deben pasar ------------------------------------------------

def test_eur_standard_convention_is_valid(eur_fields):
    report = validate_irs(eur_fields)
    assert report.is_valid, report.errors


def test_usd_sofr_ois_is_valid(usd_fields):
    """Un swap USD es un OIS: sin tenor, ambas patas anuales ACT/360."""
    report = validate_irs(usd_fields)
    assert report.is_valid, report.errors


# --- Terminos que la peticion no enuncio: se reclaman, no se reintentan ---

def test_missing_mandatory_term_is_reported_and_not_retryable(eur_fields):
    fields = eur_fields.model_copy(update={"notional": None})
    report = validate_irs(fields)
    assert not report.is_valid
    assert "notional" in report.missing_fields
    assert "el nocional del swap" in report.clarifications
    # No se reintenta: la peticion no contiene el dato y ninguna pasada
    # adicional lo va a producir.
    assert not report.retryable


def test_a_quote_request_without_a_rate_is_valid(quote_fields):
    """El caso habitual en una mesa: el tipo fijo es lo que se pregunta."""
    report = validate_irs(quote_fields)
    assert report.is_valid, report.errors
    assert report.missing_fields == []


def test_a_quote_request_that_supplies_a_rate_is_incoherent(quote_fields, eur_fields):
    fields = quote_fields.model_copy(update={"fixed_leg": eur_fields.fixed_leg})
    report = validate_irs(fields)
    assert not report.is_valid
    assert any("does not supply one" in e for e in report.errors)


def test_a_valuation_without_a_rate_is_incoherent(eur_fields):
    """Valorar un swap ya contratado exige el tipo al que se cerro."""
    fields = eur_fields.model_copy(
        update={"fixed_leg": eur_fields.fixed_leg.model_copy(update={"rate": None})}
    )
    report = validate_irs(fields)
    assert any("requires the rate it was traded at" in e for e in report.errors)


def test_a_missing_purpose_is_reported(eur_fields):
    report = validate_irs(eur_fields.model_copy(update={"purpose": None}))
    assert "purpose" in report.missing_fields


# --- Errores del modelo: se reintentan -----------------------------------

def test_wrong_eur_tenor_for_the_maturity_is_a_retryable_error(eur_fields):
    """A cinco anos la convencion EUR es EURIBOR 6M, no 3M."""
    fields = eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(
            update={"tenor": "3M", "forecast_curve": "EUR-EURIBOR-3M"}
        )
    })
    report = validate_irs(fields)
    assert not report.is_valid
    assert report.retryable
    assert any("floating_leg.tenor" in e for e in report.errors)


def test_eur_one_year_uses_the_three_month_convention(eur_fields, dates):
    """A un ano la convencion EUR cambia: trimestral contra EURIBOR 3M."""
    _dates = dates
    start = date(2026, 9, 1)
    fields = eur_fields.model_copy(update={
        "maturity_date": date(2027, 9, 1),
        "fixed_leg": eur_fields.fixed_leg.model_copy(
            update={"payment_dates": _dates(start, 12, 1)}
        ),
        "floating_leg": eur_fields.floating_leg.model_copy(update={
            "tenor": "3M", "payment_frequency": "3M",
            "forecast_curve": "EUR-EURIBOR-3M",
            "payment_dates": _dates(start, 3, 4),
        }),
    })
    report = validate_irs(fields)
    assert report.is_valid, report.errors


def test_a_tenor_on_a_compounded_overnight_leg_is_rejected(usd_fields):
    """SOFR capitalizado no tiene plazo de fijacion: declararlo describe un
    producto que no existe."""
    fields = usd_fields.model_copy(update={
        "floating_leg": usd_fields.floating_leg.model_copy(update={"tenor": "3M"})
    })
    report = validate_irs(fields)
    assert not report.is_valid
    assert any("must be absent" in e for e in report.errors)


def test_an_ibor_leg_without_tenor_is_rejected(eur_fields):
    fields = eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(update={"tenor": None})
    })
    report = validate_irs(fields)
    assert any("tenor is required" in e for e in report.errors)


def test_an_unsupported_currency_is_out_of_scope(eur_fields):
    report = validate_irs(eur_fields.model_copy(update={"currency": "GBP"}))
    assert any("out of scope" in e for e in report.errors)


# --- Guardarrailes de sanidad -------------------------------------------

def test_an_impossible_year_is_rejected(eur_fields):
    """El guardarrail que el tutor pidio: fechas del ano 1050."""
    fields = eur_fields.model_copy(update={"effective_date": date(1050, 3, 1)})
    report = validate_irs(fields)
    assert any("outside the plausible range" in e for e in report.errors)


def test_a_negative_notional_is_rejected(eur_fields):
    report = validate_irs(eur_fields.model_copy(update={"notional": Decimal("-1000")}))
    assert "notional must be positive" in report.errors


def test_a_rate_above_one_is_rejected_as_an_undivided_percentage(eur_fields):
    """2.75 en lugar de 0.0275: el porcentaje copiado sin dividir."""
    fields = eur_fields.model_copy(update={
        "fixed_leg": eur_fields.fixed_leg.model_copy(update={"rate": Decimal("2.75")})
    })
    report = validate_irs(fields)
    assert any("decimal fraction" in e for e in report.errors)


def test_a_negative_rate_is_rejected(eur_fields):
    fields = eur_fields.model_copy(update={
        "fixed_leg": eur_fields.fixed_leg.model_copy(update={"rate": Decimal("-0.01")})
    })
    report = validate_irs(fields)
    assert any("must not be negative" in e for e in report.errors)


def test_maturity_below_one_year_is_out_of_scope(eur_fields):
    fields = eur_fields.model_copy(update={"maturity_date": date(2027, 3, 1)})
    report = validate_irs(fields)
    assert any("below one year" in e for e in report.errors)


# --- El calendario que calcula el agente --------------------------------

def test_a_schedule_not_ending_on_maturity_is_rejected(eur_fields):
    fields = eur_fields.model_copy(update={
        "fixed_leg": eur_fields.fixed_leg.model_copy(update={
            "payment_dates": [date(2027, 9, 1), date(2028, 9, 1)]
        })
    })
    report = validate_irs(fields)
    assert any("must end on maturity_date" in e for e in report.errors)


def test_reversed_dates_with_a_schedule_do_not_crash(eur_fields, dates):
    """Un modelo puede devolver un calendario sobre fechas invertidas.

    El generador de referencia no puede producir uno sobre un plazo negativo, asi
    que comprobar el calendario ahi lanzaba una excepcion y convertia un caso
    invalido en una caida del programa. La incoherencia de fechas basta.
    """
    fields = eur_fields.model_copy(update={
        "effective_date": date(2026, 10, 10),
        "maturity_date": date(2024, 10, 10),
    })
    report = validate_irs(fields)
    assert not report.is_valid
    assert "effective_date must be before maturity_date" in report.errors


def test_an_unordered_schedule_is_rejected(eur_fields):
    fields = eur_fields.model_copy(update={
        "fixed_leg": eur_fields.fixed_leg.model_copy(update={
            "payment_dates": [date(2029, 9, 1), date(2027, 9, 1), date(2031, 9, 1)]
        })
    })
    report = validate_irs(fields)
    assert any("ascending order" in e for e in report.errors)


def test_an_empty_schedule_is_rejected(eur_fields):
    fields = eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(update={"payment_dates": []})
    })
    report = validate_irs(fields)
    assert any("payment_dates is empty" in e for e in report.errors)


def test_a_schedule_with_the_wrong_number_of_dates_is_rejected(eur_fields):
    """Diez fechas semestrales en cinco anos; tres no son un calendario 6M."""
    fields = eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(update={
            "payment_dates": [date(2027, 9, 1), date(2029, 9, 1), date(2031, 9, 1)]
        })
    })
    report = validate_irs(fields)
    assert any("needs about" in e for e in report.errors)


def test_a_broken_period_schedule_is_accepted(eur_fields):
    """Un tramo final mas corto es legitimo: es un periodo roto, no un error."""
    fields = eur_fields.model_copy(update={
        "maturity_date": date(2031, 3, 1),
        "fixed_leg": eur_fields.fixed_leg.model_copy(update={
            "payment_dates": [date(2027, 9, 1), date(2028, 9, 1), date(2029, 9, 1),
                              date(2030, 9, 1), date(2031, 3, 1)],
        }),
        "floating_leg": eur_fields.floating_leg.model_copy(update={
            "payment_dates": [date(2027, 3, 1), date(2027, 9, 1), date(2028, 3, 1),
                              date(2028, 9, 1), date(2029, 3, 1), date(2029, 9, 1),
                              date(2030, 3, 1), date(2030, 9, 1), date(2031, 3, 1)],
        }),
    })
    report = validate_irs(fields)
    assert report.is_valid, report.errors


# --- Normalizacion -------------------------------------------------------

def test_lowercase_labels_are_normalised(eur_fields):
    fields = eur_fields.model_copy(update={
        "currency": "eur",
        "floating_leg": eur_fields.floating_leg.model_copy(update={
            "payment_frequency": "6m", "day_count": "act/360", "tenor": "6m",
        }),
    })
    normalised = with_defaults(fields)
    assert normalised.currency == "EUR"
    assert normalised.floating_leg.payment_frequency == "6M"
    assert normalised.floating_leg.day_count == "ACT/360"
    assert validate_irs(normalised).is_valid


def test_an_absent_spread_defaults_to_zero(eur_fields):
    """Unica convencion que si se rellena: un vanilla sin spread tiene spread 0."""
    fields = eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(update={"spread": None})
    })
    assert with_defaults(fields).floating_leg.spread == Decimal(0)


def test_defaults_do_not_invent_any_other_term(eur_fields):
    """Ningun otro termino se rellena: los ausentes se reclaman o se corrigen."""
    fields = eur_fields.model_copy(update={
        "fixed_leg": FixedLegFields(rate=Decimal("0.0275"))
    })
    defaulted = with_defaults(fields)
    assert defaulted.fixed_leg.day_count is None
    assert defaulted.fixed_leg.payment_frequency is None
