from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# Naturaleza del tipo flotante. Ver el enum FloatingRateType de pricing.proto.
IBOR = "IBOR"
OVERNIGHT_COMPOUNDED = "OVERNIGHT_COMPOUNDED"
RATE_TYPES = (IBOR, OVERNIGHT_COMPOUNDED)

# Para que se pide la RFQ. Ver el enum RFQPurpose de pricing.proto.
#
# En una peticion de cotizacion el tipo fijo es lo que se pregunta: el motor lee
# la curva y calcula el tipo que hace cero el valor presente neto. En una
# valoracion el cliente aporta el tipo al que cerro la operacion y pide su valor
# de mercado. La presencia del tipo es lo que distingue los dos casos.
PAR_RATE_QUOTE = "PAR_RATE_QUOTE"
VALUATION = "VALUATION"
PURPOSES = (PAR_RATE_QUOTE, VALUATION)


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
    payment_dates: list[date] = []


class FloatingLegFields(_Extractable):
    """Pata flotante.

    ``rate_type`` distingue las dos estructuras de producto que el sistema
    admite. Con ``IBOR`` el tenor es obligatorio, porque identifica el plazo de
    fijacion del indice; con ``OVERNIGHT_COMPOUNDED`` no existe plazo de fijacion
    y el tenor debe quedar ausente.
    """

    rate_type: str | None = None
    index: str | None = None
    tenor: str | None = None
    spread: Decimal | None = None
    day_count: str | None = None
    payment_frequency: str | None = None
    forecast_curve: str | None = None
    payment_dates: list[date] = []


class IRSFields(_Extractable):
    """Terminos de un swap de tipos de interes vanilla, tal como se extraen.

    La estructura reproduce la de la clase ``Swap`` del Codigo 2.11 del libro:
    terminos comunes, dos patas y dos curvas. La curva de estimacion vive dentro
    de la pata flotante porque solo proyecta las fijaciones de esa pata.
    """

    purpose: str | None = None
    notional: Decimal | None = None
    currency: str | None = None
    is_fixed_rate_receiver: bool | None = None
    valuation_date: date | None = None
    effective_date: date | None = None
    maturity_date: date | None = None
    discount_curve: str | None = None
    fixed_leg: FixedLegFields = FixedLegFields()
    floating_leg: FloatingLegFields = FloatingLegFields()
