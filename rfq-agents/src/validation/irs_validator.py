"""Validacion determinista de los terminos extraidos.

Distingue dos clases de problema, y la distincion es el eje del diseno:

**Terminos ausentes en la peticion.** Los siete terminos obligatorios no se pueden
derivar de nada: si la peticion no los enuncia, no hay swap. El sistema devuelve
la lista de lo que la mesa debe especificar y se detiene. Reintentar no serviria:
la informacion no esta.

**Errores del modelo.** Una convencion derivada que no corresponde a la divisa y
el plazo, un calendario de pagos incoherente, una fecha imposible o un valor
negativo donde no procede. Aqui la informacion si estaba, y el modelo la ha
tratado mal. Estos errores se devuelven al orquestador para que reintente.

Separarlos permite que el bucle solo reintente lo que tiene arreglo, y que la
metrica no confunda una peticion incompleta con un fallo del modelo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from models.conventions import (
    SUPPORTED_CURRENCIES,
    convention_for,
    expected_values,
)
from models.irs_fields import IBOR, OVERNIGHT_COMPOUNDED, RATE_TYPES, IRSFields
from models.schedule import FREQUENCY_MONTHS, payment_dates


# Terminos que la peticion debe enunciar. No se derivan de ninguna convencion.
REQUIRED_TERMS: tuple[tuple[str, str], ...] = (
    ("rate", "el tipo fijo"),
    ("maturity_date", "la fecha de vencimiento"),
    ("valuation_date", "la fecha de valoracion"),
    ("effective_date", "la fecha de inicio"),
    ("currency", "la divisa"),
    ("notional", "el nocional del swap"),
    ("is_fixed_rate_receiver", "si el cliente paga o recibe el tipo fijo"),
)

# Terminos derivables de la convencion de mercado. El agente debe producirlos; si
# faltan o no corresponden a la divisa y el plazo, es un error suyo y el bucle
# reintenta.
DERIVABLE_TERMS: tuple[str, ...] = (
    "discount_curve",
    "fixed_leg.day_count",
    "fixed_leg.payment_frequency",
    "floating_leg.rate_type",
    "floating_leg.index",
    "floating_leg.day_count",
    "floating_leg.payment_frequency",
    "floating_leg.forecast_curve",
)

DAY_COUNTS = ("ACT/360", "ACT/365", "ACT/365.25", "30/360", "30U/360")

# Guardarrailes de sanidad. Una fecha del ano 1050 o un vencimiento a doscientos
# anos no son errores de convencion: son senales de que el modelo ha inventado.
MIN_YEAR = 1990
MAX_YEAR = 2125
# Un tipo fijo se expresa en tanto por uno. Por encima del 100% lo mas probable
# es que el modelo haya copiado el porcentaje sin dividir.
MAX_RATE = Decimal("1.0")
MAX_TENOR_YEARS = 60


def _get(fields: IRSFields, path: str):
    value: object = fields
    for part in path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _tenor_years(fields: IRSFields) -> float | None:
    if fields.effective_date is None or fields.maturity_date is None:
        return None
    return (fields.maturity_date - fields.effective_date).days / 365.25


def _upper(value: str | None) -> str | None:
    return value.upper() if value is not None else value


def with_defaults(fields: IRSFields) -> IRSFields:
    """Normaliza los terminos antes de validarlos y serializarlos.

    Se aplica una sola vez, antes de que los terminos lleguen al mapeador
    determinista y al agente proto, para que ambos partan exactamente de la misma
    entrada. Cuando el valor por omision se aplicaba dentro del mapeador, el
    agente recibia una entrada distinta y la comparacion entre los dos media esa
    diferencia de entrada en lugar de su capacidad de serializar.

    Normaliza a mayusculas las etiquetas que el validador acepta sin distinguir
    mayusculas, para que una frecuencia ``6m`` no llegue asi a la RFQ. El unico
    valor por omision que se aplica es el diferencial: un vanilla cotizado sin
    spread tiene spread cero, y eso si es una convencion inequivoca.
    """
    fixed = fields.fixed_leg
    floating = fields.floating_leg
    return fields.model_copy(update={
        "currency": _upper(fields.currency),
        "fixed_leg": fixed.model_copy(update={
            "payment_frequency": _upper(fixed.payment_frequency),
            "day_count": _upper(fixed.day_count),
        }),
        "floating_leg": floating.model_copy(update={
            "payment_frequency": _upper(floating.payment_frequency),
            "day_count": _upper(floating.day_count),
            "rate_type": _upper(floating.rate_type),
            "index": _upper(floating.index),
            "tenor": _upper(floating.tenor),
            "spread": floating.spread if floating.spread is not None else Decimal(0),
        }),
    })


@dataclass(frozen=True)
class ValidationReport:
    """Resultado de la validacion.

    ``missing_fields`` y ``clarifications`` describen lo que la peticion no dijo.
    ``errors`` describe lo que el modelo hizo mal, y es lo que el bucle devuelve
    al orquestador. ``retryable`` es verdadero cuando hay errores del modelo y no
    faltan terminos obligatorios: solo entonces tiene sentido reintentar.
    """

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    clarifications: list[str] = field(default_factory=list)

    @property
    def retryable(self) -> bool:
        return bool(self.errors) and not self.missing_fields

    def to_text(self) -> str:
        lines = [f"status: {'VALID' if self.is_valid else 'INVALID'}"]
        lines.append("missing_fields: " + (", ".join(self.missing_fields) or "none"))
        lines.append("errors: " + ("; ".join(self.errors) or "none"))
        if self.clarifications:
            lines.append("")
            lines.append("Para poder valorar la peticion es necesario especificar:")
            lines.extend(f"  - {item}" for item in self.clarifications)
        return "\n".join(lines) + "\n"


def _check_sanity(fields: IRSFields, errors: list[str]) -> None:
    """Guardarrailes contra valores que ninguna operacion real tendria."""
    if fields.notional is not None and fields.notional <= 0:
        errors.append("notional must be positive")
    rate = fields.fixed_leg.rate
    if rate is not None:
        if rate < 0:
            errors.append("fixed_leg.rate must not be negative")
        elif rate > MAX_RATE:
            errors.append(
                f"fixed_leg.rate {rate} is above {MAX_RATE}: a rate is expressed "
                "as a decimal fraction, so 2.75% is 0.0275"
            )

    for path in ("valuation_date", "effective_date", "maturity_date"):
        value = _get(fields, path)
        if isinstance(value, date) and not (MIN_YEAR <= value.year <= MAX_YEAR):
            errors.append(
                f"{path} {value.isoformat()} is outside the plausible range "
                f"{MIN_YEAR}-{MAX_YEAR}"
            )

    if fields.effective_date and fields.maturity_date:
        if fields.effective_date >= fields.maturity_date:
            errors.append("effective_date must be before maturity_date")
        else:
            years = _tenor_years(fields)
            if years is not None and years > MAX_TENOR_YEARS:
                errors.append(
                    f"the swap spans {years:.0f} years, above the {MAX_TENOR_YEARS} "
                    "year limit"
                )
    if fields.valuation_date and fields.maturity_date:
        if fields.valuation_date > fields.maturity_date:
            errors.append("valuation_date must not be after maturity_date")


def _check_enums(fields: IRSFields, errors: list[str]) -> None:
    for leg_name in ("fixed_leg", "floating_leg"):
        leg = getattr(fields, leg_name)
        if leg.day_count is not None and leg.day_count not in DAY_COUNTS:
            errors.append(
                f"{leg_name}.day_count must be one of {', '.join(DAY_COUNTS)}"
            )
        if (leg.payment_frequency is not None
                and leg.payment_frequency not in FREQUENCY_MONTHS):
            errors.append(
                f"{leg_name}.payment_frequency must be one of "
                f"{', '.join(sorted(FREQUENCY_MONTHS))}"
            )

    rate_type = fields.floating_leg.rate_type
    if rate_type is not None and rate_type not in RATE_TYPES:
        errors.append(
            f"floating_leg.rate_type must be one of {', '.join(RATE_TYPES)}"
        )
    # El tenor solo existe cuando hay plazo de fijacion. Declararlo en un tipo a
    # un dia capitalizado describe un producto que no existe.
    tenor = fields.floating_leg.tenor
    if rate_type == IBOR and tenor is None:
        errors.append("floating_leg.tenor is required when rate_type is IBOR")
    if rate_type == OVERNIGHT_COMPOUNDED and tenor is not None:
        errors.append(
            "floating_leg.tenor must be absent when rate_type is "
            "OVERNIGHT_COMPOUNDED: a compounded overnight rate has no fixing tenor"
        )


def _check_convention(fields: IRSFields, errors: list[str]) -> None:
    """Contrasta los terminos derivados contra la convencion de la divisa."""
    if fields.currency and fields.currency not in SUPPORTED_CURRENCIES:
        errors.append(
            f"currency {fields.currency} is out of scope: only "
            f"{' and '.join(SUPPORTED_CURRENCIES)} are supported"
        )
        return

    years = _tenor_years(fields)
    convention = convention_for(fields.currency, years)
    if convention is None:
        if fields.currency and years is not None and years < 0.99:
            errors.append(
                "maturities below one year are out of scope: they follow money "
                "market conventions, not swap conventions"
            )
        return

    for path, expected in expected_values(convention).items():
        actual = _get(fields, path)
        if expected is None:
            continue  # la ausencia ya la comprueba _check_enums
        if actual is None:
            errors.append(
                f"{path} is missing: the {fields.currency} convention for this "
                f"maturity is {expected}"
            )
        elif str(actual) != str(expected):
            errors.append(
                f"{path} is {actual!r} but the {fields.currency} convention for "
                f"this maturity is {expected!r}"
            )


def _check_schedules(fields: IRSFields, errors: list[str]) -> None:
    """Comprueba el calendario que ha calculado el agente.

    No se le exige coincidir con un calendario regular, porque la peticion puede
    pedir periodos rotos. Se le exige ser un calendario: fechas crecientes, dentro
    del plazo, y terminando en el vencimiento.
    """
    if not fields.effective_date or not fields.maturity_date:
        return
    for leg_name in ("fixed_leg", "floating_leg"):
        leg = getattr(fields, leg_name)
        dates = leg.payment_dates
        if not dates:
            errors.append(f"{leg_name}.payment_dates is empty")
            continue
        if list(dates) != sorted(dates):
            errors.append(f"{leg_name}.payment_dates must be in ascending order")
        if len(set(dates)) != len(dates):
            errors.append(f"{leg_name}.payment_dates contains duplicates")
        if dates[0] <= fields.effective_date:
            errors.append(
                f"{leg_name}.payment_dates must start after effective_date: a "
                "payment date is the end of a period, not its start"
            )
        if dates[-1] != fields.maturity_date:
            errors.append(
                f"{leg_name}.payment_dates must end on maturity_date "
                f"{fields.maturity_date.isoformat()}, not {dates[-1].isoformat()}"
            )
        if any(d > fields.maturity_date for d in dates):
            errors.append(f"{leg_name}.payment_dates goes beyond maturity_date")

        # Cuantas fechas cabrian con la frecuencia declarada. Se compara de forma
        # laxa, con una fecha de margen, porque un periodo roto cambia el conteo.
        frequency = leg.payment_frequency
        if frequency in FREQUENCY_MONTHS:
            regular = payment_dates(
                fields.effective_date, fields.maturity_date, frequency
            )
            expected_count = len(regular) - 1  # el primer elemento es el inicio
            if abs(len(dates) - expected_count) > 1:
                errors.append(
                    f"{leg_name}.payment_dates has {len(dates)} dates but a "
                    f"{frequency} schedule over this period needs about "
                    f"{expected_count}"
                )


def validate_irs(fields: IRSFields) -> ValidationReport:
    missing: list[str] = []
    clarifications: list[str] = []
    for path, description in REQUIRED_TERMS:
        # rate vive en la pata fija, pero para la peticion es un termino unico.
        lookup = "fixed_leg.rate" if path == "rate" else path
        if _get(fields, lookup) in (None, ""):
            missing.append(lookup)
            clarifications.append(description)

    errors: list[str] = []
    _check_sanity(fields, errors)
    _check_enums(fields, errors)
    _check_convention(fields, errors)
    _check_schedules(fields, errors)

    return ValidationReport(
        is_valid=not missing and not errors,
        errors=errors,
        missing_fields=missing,
        clarifications=clarifications,
    )
