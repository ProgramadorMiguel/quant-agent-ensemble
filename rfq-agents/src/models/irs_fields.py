from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Extractable(BaseModel):
    """Base de los modelos de extraccion.

    Todos los campos son opcionales a proposito: estos modelos guardan lo que un
    modelo de lenguaje ha producido, no un contrato valido. Juzgar si esta
    completo es tarea de ``validation.irs_validator``, que devuelve la lista de
    terminos que hay que especificar en lugar de lanzar una excepcion. Si el tipo
    fuese estricto, un error de extraccion se convertiria en una caida del
    programa y dejaria de ser un dato medible.
    """

    model_config = ConfigDict(extra="forbid")


class FixedLegFields(_Extractable):
    """Pata fija. Definicion 2.19 del libro de referencia."""

    rate: Decimal | None = None
    day_count: str | None = None
    payment_frequency: str | None = None


class FloatingLegFields(_Extractable):
    """Pata flotante.

    El indice y su plazo de fijacion no son intercambiables: determinan que
    curva de estimacion proyecta los tipos forward.
    """

    index: str | None = None
    tenor: str | None = None
    spread: Decimal | None = None
    day_count: str | None = None
    payment_frequency: str | None = None


class IRSFields(_Extractable):
    """Terminos de un swap de tipos de interes vanilla, tal como se extraen.

    La estructura reproduce la de la clase ``Swap`` del Codigo 2.11 del libro:
    terminos comunes, dos patas y dos curvas.
    """

    notional: Decimal | None = None
    currency: str | None = None
    is_fixed_rate_receiver: bool | None = None
    valuation_date: date | None = None
    effective_date: date | None = None
    maturity_date: date | None = None
    discount_curve: str | None = None
    forecast_curve: str | None = None
    fixed_leg: FixedLegFields = FixedLegFields()
    floating_leg: FloatingLegFields = FloatingLegFields()
