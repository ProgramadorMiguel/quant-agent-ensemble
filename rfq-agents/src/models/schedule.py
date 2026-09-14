from __future__ import annotations

from calendar import monthrange
from datetime import date


# Frecuencias admitidas, expresadas en meses. La clave es la etiqueta que se
# escribe en la RFQ.
FREQUENCY_MONTHS: dict[str, int] = {
    "1M": 1,
    "2M": 2,
    "3M": 3,
    "4M": 4,
    "6M": 6,
    "1Y": 12,
    "12M": 12,
}


def add_months(start: date, months: int) -> date:
    """Suma meses de calendario truncando el dia al ultimo del mes destino.

    No aplica ningun ajuste por dias festivos ni por convencion de dias
    habiles. Es la misma simplificacion que adopta el libro de referencia en la
    pagina 63, donde las fechas de devengo se tratan directamente y no se
    modela calendario.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def payment_dates(
    effective_date: date, maturity_date: date, frequency: str
) -> list[str]:
    """Calendario de pagos de una pata, en formato ISO.

    Devuelve la estructura temporal T_0 < T_1 < ... < T_N de la ecuacion 2.37:
    la fecha de inicio, las fechas intermedias segun la frecuencia, y el
    vencimiento. Es el vector ``fixedLegDates`` o ``floatingLegDates`` que
    consume la clase Swap del Codigo 2.11.

    Ningun agente extrae estas fechas: se derivan de forma determinista de la
    fecha de inicio, el vencimiento y la frecuencia de pago. Pedirle a un modelo
    de lenguaje que enumere un calendario de pagos seria pedirle que invente
    informacion que la peticion no contiene.
    """
    months = FREQUENCY_MONTHS.get((frequency or "").upper())
    if months is None:
        raise ValueError(
            f"Frecuencia de pago no admitida: {frequency!r}. "
            f"Admitidas: {', '.join(sorted(FREQUENCY_MONTHS))}"
        )
    if effective_date >= maturity_date:
        raise ValueError("effective_date debe ser anterior a maturity_date")

    dates = [effective_date]
    current = effective_date
    while True:
        current = add_months(current, months)
        if current >= maturity_date:
            break
        dates.append(current)
    dates.append(maturity_date)
    return [day.isoformat() for day in dates]
