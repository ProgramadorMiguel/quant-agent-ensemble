"""Convenciones de mercado por divisa y plazo.

Verificadas el 21/09/2026 contra OpenGamma Strata, que codifica las convenciones
del documento sectorial *Interest Rate Instruments and Market Conventions Guide*.
El detalle, con las citas literales, esta en ``docs/CONVENCIONES_MERCADO.md``.

Por que estas tablas viven en Python si es el agente quien deriva las
convenciones: no se usan para rellenar los campos, sino para **comprobarlos**. La
derivacion la hace el modelo, y eso es precisamente lo que el trabajo mide; el
validador contrasta el resultado contra la convencion documentada y, cuando no
coincide, produce un error que el bucle devuelve al orquestador. Sin esta tabla el
bucle no tendria nada que corregir, y una derivacion equivocada pasaria a la RFQ
sin ser detectada.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.irs_fields import IBOR, OVERNIGHT_COMPOUNDED


@dataclass(frozen=True)
class Convention:
    """Convencion estandar de un swap vanilla para una divisa y un plazo."""

    fixed_day_count: str
    fixed_payment_frequency: str
    rate_type: str
    index: str
    tenor: str | None
    floating_day_count: str
    floating_payment_frequency: str
    discount_curve: str
    forecast_curve: str


# EUR. La convencion depende del plazo: para un ano la pata flotante es
# trimestral contra EURIBOR 3M, y para plazos superiores semestral contra
# EURIBOR 6M. Verificado en StandardFixedIborSwapConventions, constantes
# EUR_FIXED_1Y_EURIBOR_3M y EUR_FIXED_1Y_EURIBOR_6M.
EUR_1Y = Convention(
    fixed_day_count="30U/360", fixed_payment_frequency="1Y",
    rate_type=IBOR, index="EURIBOR", tenor="3M",
    floating_day_count="ACT/360", floating_payment_frequency="3M",
    discount_curve="EUR-ESTR", forecast_curve="EUR-EURIBOR-3M",
)

EUR_OVER_1Y = Convention(
    fixed_day_count="30U/360", fixed_payment_frequency="1Y",
    rate_type=IBOR, index="EURIBOR", tenor="6M",
    floating_day_count="ACT/360", floating_payment_frequency="6M",
    discount_curve="EUR-ESTR", forecast_curve="EUR-EURIBOR-6M",
)

# USD. No existe convencion de swap fijo contra SOFR con plazo de fijacion: tras
# el cese del LIBOR en junio de 2023 el swap vanilla en dolares es un OIS, con
# las dos patas anuales en ACT/360 y el tipo a un dia capitalizado. Verificado en
# StandardFixedOvernightSwapConventions, constante USD_FIXED_1Y_SOFR_OIS.
USD = Convention(
    fixed_day_count="ACT/360", fixed_payment_frequency="1Y",
    rate_type=OVERNIGHT_COMPOUNDED, index="SOFR", tenor=None,
    floating_day_count="ACT/360", floating_payment_frequency="1Y",
    discount_curve="USD-SOFR", forecast_curve="USD-SOFR",
)

SUPPORTED_CURRENCIES = ("EUR", "USD")


def convention_for(currency: str | None, years: float | None) -> Convention | None:
    """Convencion aplicable, o ``None`` si queda fuera del alcance.

    ``years`` es el plazo del swap en anos. Los vencimientos inferiores a un ano
    devuelven ``None``: siguen convenciones de mercado monetario, con un unico
    periodo y sin cupones intermedios, y estan fuera del alcance del trabajo.
    """
    if currency is None or years is None:
        return None
    code = currency.upper()
    if years < 0.99:  # margen para que un ano exacto no caiga por redondeo
        return None
    if code == "USD":
        return USD
    if code == "EUR":
        return EUR_1Y if years < 1.5 else EUR_OVER_1Y
    return None


def expected_values(convention: Convention) -> dict[str, object]:
    """Convencion como rutas de campo, para contrastarla con lo extraido."""
    return {
        "discount_curve": convention.discount_curve,
        "fixed_leg.day_count": convention.fixed_day_count,
        "fixed_leg.payment_frequency": convention.fixed_payment_frequency,
        "floating_leg.rate_type": convention.rate_type,
        "floating_leg.index": convention.index,
        "floating_leg.tenor": convention.tenor,
        "floating_leg.day_count": convention.floating_day_count,
        "floating_leg.payment_frequency": convention.floating_payment_frequency,
        "floating_leg.forecast_curve": convention.forecast_curve,
    }
