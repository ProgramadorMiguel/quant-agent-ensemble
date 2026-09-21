"""Un termino de convencion que la peticion enuncia se respeta.

Un swap EUR a cinco anos contra EURIBOR 3M pagado trimestralmente no es la
convencion estandar, pero se negocia. Rechazarlo seria rechazar negocio legitimo;
aceptarlo sin mas perderia la comprobacion sobre lo que el modelo deriva cuando la
peticion calla. La distincion se resuelve mirando si la peticion lo menciona.
"""

from datetime import date

from models.conventions import stated_in
from validation.irs_validator import validate_irs


SILENT = (
    "Value as of 2026-09-01 an EUR interest rate swap, notional EUR 10,000,000, "
    "effective 2026-09-01, maturing 2031-09-01. We pay fixed at 2.75%."
)
STATES_QUARTERLY = SILENT + " Floating is 3M EURIBOR paid quarterly."


def _quarterly(eur_fields, dates):
    """El mismo swap con la pata flotante trimestral: veinte fechas, no diez."""
    return eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(update={
            "tenor": "3M", "payment_frequency": "3M",
            "forecast_curve": "EUR-EURIBOR-3M",
            "payment_dates": dates(date(2026, 9, 1), 3, 20),
        })
    })


def test_a_non_standard_convention_is_rejected_when_the_request_is_silent(
        eur_fields, dates):
    """Si la peticion no lo pide, un 3M a cinco anos es un error del modelo."""
    report = validate_irs(_quarterly(eur_fields, dates), SILENT)
    assert not report.is_valid
    assert report.retryable
    assert any("does not state otherwise" in e for e in report.errors)


def test_the_same_convention_is_accepted_when_the_request_states_it(
        eur_fields, dates):
    report = validate_irs(_quarterly(eur_fields, dates), STATES_QUARTERLY)
    assert report.is_valid, report.errors


def test_the_standard_convention_is_always_accepted(eur_fields):
    assert validate_irs(eur_fields, SILENT).is_valid
    assert validate_irs(eur_fields, STATES_QUARTERLY).is_valid


def test_without_a_prompt_the_validation_is_strict(eur_fields, dates):
    """Sin peticion no hay forma de saber que pidio el usuario: se exige la
    convencion, que es el lado seguro del error."""
    report = validate_irs(_quarterly(eur_fields, dates))
    assert not report.is_valid


def test_a_stated_day_count_overrides_the_convention(eur_fields):
    prompt = SILENT + " Fixed leg on an ACT/365 basis."
    fields = eur_fields.model_copy(update={
        "fixed_leg": eur_fields.fixed_leg.model_copy(update={"day_count": "ACT/365"})
    })
    assert validate_irs(fields, prompt).is_valid
    # La misma extraccion sin que la peticion lo mencione si es un error.
    assert not validate_irs(fields, SILENT).is_valid


def test_the_index_and_rate_type_cannot_be_overridden(eur_fields):
    """No son convencion elegible: un EUR contra SOFR es otro producto."""
    prompt = SILENT + " Floating against SOFR."
    fields = eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(update={"index": "SOFR"})
    })
    report = validate_irs(fields, prompt)
    assert not report.is_valid
    assert any("floating_leg.index" in e for e in report.errors)


def test_the_stated_schedule_must_follow_the_stated_frequency(eur_fields, dates):
    """Trimestral a cinco anos son veinte fechas; diez no cuadran."""
    fields = eur_fields.model_copy(update={
        "floating_leg": eur_fields.floating_leg.model_copy(update={
            "tenor": "3M", "payment_frequency": "3M",
            "forecast_curve": "EUR-EURIBOR-3M",
            "payment_dates": dates(date(2026, 9, 1), 6, 10),
        })
    })
    report = validate_irs(fields, STATES_QUARTERLY)
    assert any("needs about" in e for e in report.errors)


# --- El detector lexico, con sus limites a la vista ----------------------

def test_the_detector_recognises_the_documented_shorthand():
    assert stated_in("pay 2.75% vs 3M EURIBOR qtr", "floating_leg.payment_frequency")
    assert stated_in("30/360 basis", "fixed_leg.day_count")
    assert stated_in("vs 6s", "floating_leg.tenor")


def test_the_detector_says_no_when_the_request_is_silent():
    assert not stated_in(SILENT, "floating_leg.tenor")
    assert not stated_in(SILENT, "fixed_leg.day_count")
    assert not stated_in(None, "floating_leg.tenor")


def test_the_index_is_never_treated_as_stated():
    assert not stated_in("floating against SOFR", "floating_leg.index")
    assert not stated_in("compounded overnight", "floating_leg.rate_type")
