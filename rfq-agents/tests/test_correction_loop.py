"""Bucle de autocorreccion, probado sin llamar a ningun proveedor.

Se sustituye el cliente por uno falso que devuelve una secuencia de respuestas
preparada. Asi la ruta de reintento se ejercita de forma determinista y gratuita,
que es la unica manera de tener cubierto un camino que en la practica casi nunca
se recorre: cuando los casos salen bien a la primera, el reintento queda sin
probar justo hasta el dia en que hace falta.
"""

from datetime import date
from decimal import Decimal

import pytest

import app_service
from app_service import generate_rfq_from_prompt
from models.irs_fields import (
    IBOR,
    VALUATION,
    FixedLegFields,
    FloatingLegFields,
    IRSFields,
)


PROMPT = "Value as of 2026-09-01 an EUR swap, 10mm, 2026-09-01 to 2031-09-01, pay 2.75%"


class FakeClient:
    """Cliente que devuelve extracciones preparadas y anota lo que ha recibido."""

    def __init__(self, extractions, product="IRS"):
        self.extractions = list(extractions)
        self.product = product
        self.prompts: list[str] = []
        self.config = type("Cfg", (), {"max_iterations": 5})()

    def classify_product(self, prompt):
        return self.product

    def extract_irs(self, prompt):
        self.prompts.append(prompt)
        # La ultima respuesta se repite si se piden mas pasadas de las preparadas.
        index = min(len(self.prompts) - 1, len(self.extractions) - 1)
        return self.extractions[index]

    def generate_proto_text(self, fields, rfq_id):
        raise RuntimeError("el agente proto no se mide en estos tests")


def _fields(**overrides) -> IRSFields:
    """Swap EUR a cinco anos correcto, con los campos que se quieran alterar."""
    from tests.conftest import regular_dates

    effective, maturity = date(2026, 9, 1), date(2031, 9, 1)
    base = IRSFields(
        purpose=VALUATION,
        notional=Decimal("10000000"), currency="EUR", is_fixed_rate_receiver=False,
        valuation_date=effective, effective_date=effective, maturity_date=maturity,
        discount_curve="EUR-ESTR",
        fixed_leg=FixedLegFields(
            rate=Decimal("0.0275"), day_count="30U/360", payment_frequency="1Y",
            payment_dates=regular_dates(effective, 12, 5),
        ),
        floating_leg=FloatingLegFields(
            rate_type=IBOR, index="EURIBOR", tenor="6M", spread=Decimal(0),
            day_count="ACT/360", payment_frequency="6M",
            forecast_curve="EUR-EURIBOR-6M",
            payment_dates=regular_dates(effective, 6, 10),
        ),
    )
    return base.model_copy(update=overrides) if overrides else base


def _wrong_tenor() -> IRSFields:
    """Convencion equivocada: a cinco anos EUR es EURIBOR 6M, no 3M."""
    good = _fields()
    return good.model_copy(update={
        "floating_leg": good.floating_leg.model_copy(
            update={"tenor": "3M", "forecast_curve": "EUR-EURIBOR-3M"}
        )
    })


def _impossible_year() -> IRSFields:
    return _fields(effective_date=date(1050, 3, 1))


def _missing_notional() -> IRSFields:
    """Un termino sin el que no hay swap, y que no se deriva de nada."""
    return _fields(notional=None)


@pytest.fixture
def patched(monkeypatch):
    """Sustituye el cliente y desactiva la medicion del agente proto."""
    def install(extractions, product="IRS"):
        client = FakeClient(extractions, product)
        monkeypatch.setattr(app_service, "LLMClient",
                            lambda *a, **k: client)
        monkeypatch.setattr(app_service, "_measure_proto_agent",
                            lambda *a, **k: app_service.ProtoAgentOutcome(
                                False, False, False))
        return client
    return install


def test_a_good_extraction_needs_one_pass(patched):
    patched([_fields()])
    result = generate_rfq_from_prompt(PROMPT)
    assert result.validation_status == "VALID"
    assert result.iterations == 1
    assert result.iteration_errors == ()


def test_a_wrong_convention_is_corrected_on_the_second_pass(patched):
    client = patched([_wrong_tenor(), _fields()])
    result = generate_rfq_from_prompt(PROMPT)
    assert result.validation_status == "VALID"
    assert result.iterations == 2
    # La traza conserva por que se rechazo el primer intento.
    assert len(result.iteration_errors) == 1
    assert any("tenor" in e for e in result.iteration_errors[0])


def test_the_retry_prompt_carries_the_diagnosis(patched):
    """Reintentar con el mismo texto daria el mismo resultado."""
    client = patched([_wrong_tenor(), _fields()])
    generate_rfq_from_prompt(PROMPT)
    first, second = client.prompts
    assert "Correction required" not in first
    assert "Correction required" in second
    assert "floating_leg.tenor" in second
    # La peticion original sigue estando: el agente necesita los dos.
    assert PROMPT in second


def test_the_loop_stops_at_the_limit_and_returns_an_error(patched):
    """Cota, no condicion de exito: al agotarla se devuelve error."""
    client = patched([_wrong_tenor()])
    result = generate_rfq_from_prompt(PROMPT, max_iterations=5)
    assert result.validation_status == "INVALID"
    assert result.iterations == 5
    assert len(client.prompts) == 5


def test_the_limit_is_configurable(patched):
    client = patched([_wrong_tenor()])
    result = generate_rfq_from_prompt(PROMPT, max_iterations=2)
    assert result.iterations == 2
    assert len(client.prompts) == 2


def test_a_missing_mandatory_term_is_not_retried(patched):
    """La peticion no contiene el dato: ninguna pasada adicional lo va a producir."""
    client = patched([_missing_notional()])
    result = generate_rfq_from_prompt(PROMPT)
    assert result.validation_status == "INVALID"
    assert result.iterations == 1
    assert len(client.prompts) == 1
    assert "notional" in result.missing_fields


def test_a_sanity_violation_is_retried(patched):
    """El guardarrail del ano 1050 alimenta el bucle."""
    client = patched([_impossible_year(), _fields()])
    result = generate_rfq_from_prompt(PROMPT)
    assert result.validation_status == "VALID"
    assert result.iterations == 2
    assert any("plausible range" in e for e in result.iteration_errors[0])


def test_an_unsupported_product_never_reaches_extraction(patched):
    client = patched([_fields()], product="UNSUPPORTED")
    result = generate_rfq_from_prompt(PROMPT)
    assert result.product_type == "UNSUPPORTED"
    assert result.validation_status == "NOT_RUN"
    assert client.prompts == []
