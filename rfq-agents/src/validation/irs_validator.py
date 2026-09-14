from __future__ import annotations

from dataclasses import dataclass

from models.irs_fields import IRSFields
from models.schedule import FREQUENCY_MONTHS


# Terminos obligatorios de un swap vanilla, con la ruta del campo y el texto con
# el que se pide al usuario que lo especifique.
#
# El sistema nunca rellena un termino ausente con la convencion de mercado
# habitual: devuelve la lista exacta de lo que la mesa debe confirmar. Inventar
# una convencion produciria una RFQ valorable pero equivocada, que es un fallo
# mucho peor que un rechazo explicito.
REQUIRED_TERMS: tuple[tuple[str, str], ...] = (
    ("notional", "el nocional del swap"),
    ("currency", "la divisa"),
    ("is_fixed_rate_receiver", "si el cliente paga o recibe el tipo fijo"),
    ("valuation_date", "la fecha de valoracion"),
    ("effective_date", "la fecha de inicio"),
    ("maturity_date", "la fecha de vencimiento"),
    ("discount_curve", "la curva de descuento"),
    ("forecast_curve", "la curva de estimacion"),
    ("fixed_leg.rate", "el tipo fijo"),
    ("fixed_leg.day_count", "la base de calculo de la pata fija"),
    ("fixed_leg.payment_frequency", "la frecuencia de pago de la pata fija"),
    ("floating_leg.index", "el indice de referencia de la pata flotante"),
    ("floating_leg.tenor", "el plazo de fijacion del indice"),
    ("floating_leg.day_count", "la base de calculo de la pata flotante"),
    ("floating_leg.payment_frequency", "la frecuencia de pago de la pata flotante"),
)

# El diferencial no es obligatorio: un swap vanilla cotizado sin spread tiene
# spread cero, y eso si es una convencion inequivoca.
DEFAULTED_TERMS: dict[str, object] = {"floating_leg.spread": 0}

DAY_COUNTS = ("ACT/360", "ACT/365", "ACT/365.25", "30/360")


def _get(fields: IRSFields, path: str):
    value: object = fields
    for part in path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    errors: list[str]
    missing_fields: list[str]
    clarifications: list[str]

    def to_text(self) -> str:
        lines = [f"status: {'VALID' if self.is_valid else 'INVALID'}"]
        lines.append("missing_fields: " + (", ".join(self.missing_fields) or "none"))
        lines.append("errors: " + ("; ".join(self.errors) or "none"))
        if self.clarifications:
            lines.append("")
            lines.append("Para poder valorar la peticion es necesario especificar:")
            lines.extend(f"  - {item}" for item in self.clarifications)
        return "\n".join(lines) + "\n"


def validate_irs(fields: IRSFields) -> ValidationReport:
    missing: list[str] = []
    clarifications: list[str] = []
    for path, description in REQUIRED_TERMS:
        if _get(fields, path) in (None, ""):
            missing.append(path)
            clarifications.append(description)

    errors: list[str] = []
    if fields.notional is not None and fields.notional <= 0:
        errors.append("notional must be positive")

    dates = (fields.effective_date, fields.maturity_date)
    if all(d is not None for d in dates) and dates[0] >= dates[1]:
        errors.append("effective_date must be before maturity_date")
    if (
        fields.valuation_date is not None
        and fields.maturity_date is not None
        and fields.valuation_date > fields.maturity_date
    ):
        errors.append("valuation_date must not be after maturity_date")

    for leg_name in ("fixed_leg", "floating_leg"):
        leg = getattr(fields, leg_name)
        if leg.day_count is not None and leg.day_count not in DAY_COUNTS:
            errors.append(
                f"{leg_name}.day_count must be one of {', '.join(DAY_COUNTS)}"
            )
        frequency = leg.payment_frequency
        if frequency is not None and frequency.upper() not in FREQUENCY_MONTHS:
            errors.append(
                f"{leg_name}.payment_frequency must be one of "
                f"{', '.join(sorted(FREQUENCY_MONTHS))}"
            )

    return ValidationReport(
        is_valid=not missing and not errors,
        errors=errors,
        missing_fields=missing,
        clarifications=clarifications,
    )
