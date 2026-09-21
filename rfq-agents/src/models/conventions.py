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


# Formas superficiales con las que una peticion puede enunciar cada termino
# derivable. Sirven para distinguir "la peticion lo dijo" de "el modelo lo
# derivo", que es la unica manera de admitir un swap de convencion no estandar
# sin perder la comprobacion sobre lo que el modelo deriva por su cuenta.
#
# El vocabulario reproduce la tabla de taquigrafia del skill, de modo que las dos
# piezas reconocen lo mismo. Cuando la peticion no usa ninguna de estas formas se
# asume que no enuncio el termino y se exige la convencion: un falso negativo
# devuelve al comportamiento estricto, que es el lado seguro del error.
STATED_FORMS: dict[str, tuple[str, ...]] = {
    "fixed_leg.day_count": (
        "30/360", "30u/360", "30e/360", "act/360", "a/360",
        "act/365", "a/365", "act/365.25",
    ),
    "floating_leg.day_count": (
        "30/360", "30u/360", "30e/360", "act/360", "a/360",
        "act/365", "a/365", "act/365.25",
    ),
    "fixed_leg.payment_frequency": (
        "annual", "annually", "ann", "yearly", "1y",
        "semiannual", "semiannually", "semi", "s/a", "6m",
        "quarterly", "qtr", "3m", "monthly", "1m",
    ),
    "floating_leg.payment_frequency": (
        "annual", "annually", "ann", "yearly", "1y",
        "semiannual", "semiannually", "semi", "s/a", "6m",
        "quarterly", "qtr", "3m", "monthly", "1m",
    ),
    "floating_leg.tenor": ("3m", "6m", "12m", "1y", "vs 3s", "vs 6s"),
    "discount_curve": ("discount", "disc", "estr", "sofr"),
    "floating_leg.forecast_curve": ("forecast", "fwd", "forward", "estimation"),
}

# Terminos que la peticion no puede sobreescribir, porque no son una convencion
# elegible sino una consecuencia de la divisa. Un swap en euros contra SOFR no es
# un vanilla con convencion distinta: es un producto de dos divisas, fuera de
# alcance.
NOT_OVERRIDABLE = ("floating_leg.rate_type", "floating_leg.index")


def stated_in(prompt: str | None, path: str) -> bool:
    """Si la peticion enuncia el termino ``path``.

    Deteccion lexica sobre un vocabulario cerrado. Es una aproximacion: no
    interpreta la frase, solo detecta que el termino se menciona. Basta para lo
    que decide, que es si conviene exigir la convencion estandar o respetar lo
    que la peticion pide.
    """
    if not prompt or path in NOT_OVERRIDABLE:
        return False
    text = prompt.lower()
    return any(form in text for form in STATED_FORMS.get(path, ()))


def forecast_curve_for(currency: str | None, tenor: str | None) -> str | None:
    """Curva de estimacion que corresponde a un indice y su plazo de fijacion.

    No es una convencion independiente: se deriva del tenor. Si la peticion pide
    EURIBOR 3M en lugar del 6M estandar, la curva que proyecta esas fijaciones es
    la de 3M, y exigir la del 6M seria incoherente con lo que se ha pedido.
    """
    if currency is None:
        return None
    code = currency.upper()
    if code == "USD":
        return "USD-SOFR"  # tipo a un dia: no hay plazo del que derivar
    if code == "EUR":
        return f"EUR-EURIBOR-{tenor}" if tenor else None
    return None


def expected_values(
    convention: Convention, tenor: str | None = None, currency: str | None = None
) -> dict[str, object]:
    """Convencion como rutas de campo, para contrastarla con lo extraido.

    ``tenor`` y ``currency`` son los valores realmente extraidos. Se usan para la
    curva de estimacion, que se deriva del tenor y no del estandar: cuando la
    peticion pide un tenor no estandar, la curva debe seguirlo.
    """
    forecast = forecast_curve_for(
        currency or convention.index, tenor or convention.tenor
    )
    return {
        "discount_curve": convention.discount_curve,
        "fixed_leg.day_count": convention.fixed_day_count,
        "fixed_leg.payment_frequency": convention.fixed_payment_frequency,
        "floating_leg.rate_type": convention.rate_type,
        "floating_leg.index": convention.index,
        "floating_leg.tenor": convention.tenor,
        "floating_leg.day_count": convention.floating_day_count,
        "floating_leg.payment_frequency": convention.floating_payment_frequency,
        "floating_leg.forecast_curve": forecast or convention.forecast_curve,
    }
