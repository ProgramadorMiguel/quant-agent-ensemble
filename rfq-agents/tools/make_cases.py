"""Genera los casos dorados a partir de una declaracion compacta.

Los ficheros ``.expected.textproto`` son largos y repetitivos: un swap a diez
anos lleva veinte fechas de pago en la pata flotante. Escribirlos a mano invita a
la errata, y una errata en un caso dorado se lee luego como un fallo del modelo,
que es exactamente el error que este trabajo ya ha cometido una vez.

Cada caso se declara por sus terminos economicos; el resto se deriva de la
convencion documentada en ``models.conventions``, la misma que usa el validador.

La fecha de referencia esta fijada: los casos que dicen "spot" o "el proximo
lunes" se resuelven contra ella, de modo que el caso dorado no cambia de un dia
para otro.

Ejecutar desde la raiz del proyecto:  python tools/make_cases.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models.conventions import convention_for  # noqa: E402
from models.irs_fields import PAR_RATE_QUOTE, VALUATION  # noqa: E402
from models.schedule import add_months  # noqa: E402

CASES_DIR = ROOT / "evaluation/cases"

# Lunes 21 de septiembre de 2026. La misma que usa evaluate.py por omision.
AS_OF = date(2026, 9, 21)


def business_days_after(start: date, days: int) -> date:
    """Suma dias habiles sin calendario de festivos, solo saltando el fin de
    semana. Es la simplificacion que adopta todo el proyecto."""
    current = start
    remaining = days
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


SPOT = business_days_after(AS_OF, 2)           # 2026-09-23, miercoles
NEXT_MONDAY = AS_OF + timedelta(days=7)        # 2026-09-28


def years_after(start: date, years: int) -> date:
    return add_months(start, 12 * years)


def schedule(effective: date, maturity: date, frequency: str) -> list[str]:
    """Fechas de pago: fin de cada periodo, terminando en el vencimiento."""
    months = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "12M": 12}[frequency.upper()]
    dates: list[date] = []
    step = 1
    while True:
        nxt = add_months(effective, months * step)
        if nxt >= maturity:
            break
        dates.append(nxt)
        step += 1
    dates.append(maturity)
    return [d.isoformat() for d in dates]


def expected(
    *, notional: int | None, currency: str, receiver: bool | None,
    effective: date, maturity: date, rate: str | None = None,
    valuation: date | None = None, spread: str | None = None,
    tenor: str | None = None, frequency: str | None = None,
) -> str:
    """Textproto esperado. ``rate=None`` produce una peticion de cotizacion."""
    years = (maturity - effective).days / 365.25
    conv = convention_for(currency, years)
    if conv is None:
        raise SystemExit(f"Sin convencion para {currency} a {years:.2f} anos")

    float_tenor = tenor or conv.tenor
    float_freq = frequency or conv.floating_payment_frequency
    forecast = (f"EUR-EURIBOR-{float_tenor}" if currency == "EUR"
                else conv.forecast_curve)

    lines = [f"purpose: {VALUATION if rate else PAR_RATE_QUOTE}"]
    if notional is not None:
        lines.append(f"notional: {notional}")
    lines.append(f'currency: "{currency}"')
    if receiver is not None:
        lines.append(f"is_fixed_rate_receiver: {'true' if receiver else 'false'}")
    lines += [
        f'valuation_date: "{(valuation or AS_OF).isoformat()}"',
        f'effective_date: "{effective.isoformat()}"',
        f'maturity_date: "{maturity.isoformat()}"',
        f'discount_curve: "{conv.discount_curve}"',
        "fixed_leg {",
    ]
    if rate:
        lines.append(f"  rate: {rate}")
    lines += [
        f'  day_count: "{conv.fixed_day_count}"',
        f'  payment_frequency: "{conv.fixed_payment_frequency}"',
    ]
    lines += [f'  payment_dates: "{d}"'
              for d in schedule(effective, maturity, conv.fixed_payment_frequency)]
    lines += ["}", "floating_leg {", f"  rate_type: {conv.rate_type}",
              f'  index: "{conv.index}"']
    if float_tenor:
        lines.append(f'  tenor: "{float_tenor}"')
    if spread:
        lines.append(f"  spread: {spread}")
    lines += [
        f'  day_count: "{conv.floating_day_count}"',
        f'  payment_frequency: "{float_freq}"',
        f'  forecast_curve: "{forecast}"',
    ]
    lines += [f'  payment_dates: "{d}"'
              for d in schedule(effective, maturity, float_freq)]
    lines.append("}")
    return "\n".join(lines) + "\n"


def write(family: str, name: str, prompt: str, golden: str | None) -> None:
    folder = CASES_DIR / family
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.prompt.txt").write_text(prompt.strip() + "\n", encoding="utf-8")
    target = f"{name}.expected." + ("product" if golden is None else "textproto")
    (folder / target).write_text(golden or "UNSUPPORTED\n", encoding="utf-8")


# ==========================================================================
# COTIZACION. El caso habitual en una mesa: el cliente pide precio, asi que no
# aporta el tipo fijo. Los casos fueron elaborados por el autor a partir de las
# pautas del tutor sobre los campos obligatorios y el alcance.
# ==========================================================================

write("cotizacion", "es_spot_5y", """
Cotizame un IRS en EUR por 50M nocional a 5 anos empezando spot, pagamos fijo y
recibimos EURIBOR 6M.
""", expected(notional=50000000, currency="EUR", receiver=False,
              effective=SPOT, maturity=years_after(SPOT, 5)))

write("cotizacion", "en_spot_5y", """
RFQ: 5Y EUR 100m IRS, Pay Fixed vs EURIBOR 6M, Spot start. Please provide fixed
rate.
""", expected(notional=100000000, currency="EUR", receiver=False,
              effective=SPOT, maturity=years_after(SPOT, 5)))

write("cotizacion", "es_fecha_explicita_10y", """
Necesito precio para un Swap 10Y EUR 25M, recibo fijo contra 3M EURIBOR, start
24-Sep-2026.
""", expected(notional=25000000, currency="EUR", receiver=True,
              effective=date(2026, 9, 24), maturity=date(2036, 9, 24),
              tenor="3M", frequency="3M"))

write("cotizacion", "usd_proximo_lunes_3y", """
Como cotiza un IRS 3Y USD 10M empezando el proximo lunes? Nosotros pagamos la
pata fija.
""", expected(notional=10000000, currency="USD", receiver=False,
              effective=NEXT_MONDAY, maturity=years_after(NEXT_MONDAY, 3)))

write("cotizacion", "sin_convenciones_7y", """
Pasanos precio para Swap EUR 15M a 7 anos, pagamos fijo.
""", expected(notional=15000000, currency="EUR", receiver=False,
              effective=SPOT, maturity=years_after(SPOT, 7)))

write("cotizacion", "cobertura_usd_10y", """
Quiero hacer una cobertura de tipo fijo a 10 anos en USD por 100M SOFR.
""", expected(notional=100000000, currency="USD", receiver=False,
              effective=SPOT, maturity=years_after(SPOT, 10)))

# Estructura diferida. "2Y1Y" es dos anos forward, un ano de plazo: el swap
# empieza dentro de dos anos y dura uno. El inicio es el spot de entonces, de modo
# que hay que resolver dos fechas relativas encadenadas.
_FWD_START = years_after(SPOT, 2)
write("cotizacion", "forward_start_2y1y", """
RFQ IRS 2Y1Y EUR 30M. Recibimos fijo.
""", expected(notional=30000000, currency="EUR", receiver=True,
              effective=_FWD_START, maturity=years_after(_FWD_START, 1)))

# ==========================================================================
# JERGA. La misma informacion en taquigrafia de mesa.
# ==========================================================================

write("jerga", "pay_5y_50m_spot", """
Pay 5y 50m EURIBOR6M spot
""", expected(notional=50000000, currency="EUR", receiver=False,
              effective=SPOT, maturity=years_after(SPOT, 5)))

write("jerga", "abreviado_eur_val", """
val 2026-09-01, 10mm EUR from 2026-09-01 to 2031-09-01, pay 2,75%
""", expected(notional=10000000, currency="EUR", receiver=False,
              valuation=date(2026, 9, 1), effective=date(2026, 9, 1),
              maturity=date(2031, 9, 1), rate="0.0275"))

write("jerga", "abreviado_usd_val", """
valn dt 2026-09-01. USD 250k, 2026-09-01 / 2031-09-01. rec fixed 385bp
""", expected(notional=250000, currency="USD", receiver=True,
              valuation=date(2026, 9, 1), effective=date(2026, 9, 1),
              maturity=date(2031, 9, 1), rate="0.0385"))

# ==========================================================================
# VALORACION. El cliente aporta el tipo al que cerro y pide el valor.
# ==========================================================================

write("valoracion", "eur_payer_5y", """
Value as of 2026-09-01 a vanilla EUR interest rate swap with notional
EUR 10,000,000, effective 2026-09-01 and maturing 2031-09-01. We pay fixed at
2.75%.
""", expected(notional=10000000, currency="EUR", receiver=False,
              valuation=date(2026, 9, 1), effective=date(2026, 9, 1),
              maturity=date(2031, 9, 1), rate="0.0275"))

write("valoracion", "eur_receiver_1y", """
Value as of 2026-09-01 an EUR interest rate swap, notional EUR 4,000,000,
effective 2026-09-01, maturing 2027-09-01. The client receives fixed at 2.40%.
""", expected(notional=4000000, currency="EUR", receiver=True,
              valuation=date(2026, 9, 1), effective=date(2026, 9, 1),
              maturity=date(2027, 9, 1), rate="0.024"))

write("valoracion", "usd_sofr_ois_3y", """
Value as of 2026-09-01 a USD interest rate swap, notional USD 50,000,000,
effective 2026-09-01, maturing 2029-09-01. The client receives fixed at 3.85%.
""", expected(notional=50000000, currency="USD", receiver=True,
              valuation=date(2026, 9, 1), effective=date(2026, 9, 1),
              maturity=date(2029, 9, 1), rate="0.0385"))

write("valoracion", "eur_periodo_roto", """
Value as of 2026-09-01 an EUR interest rate swap with notional EUR 7,500,000,
effective 2026-09-01 and maturing 2030-03-01. We pay fixed at 2.95% plus a
spread of 25bp on the floating leg.
""", expected(notional=7500000, currency="EUR", receiver=False,
              valuation=date(2026, 9, 1), effective=date(2026, 9, 1),
              maturity=date(2030, 3, 1), rate="0.0295", spread="0.0025"))

write("valoracion", "eur_no_estandar_3m", """
Value as of 2026-09-01 an EUR interest rate swap, notional EUR 20,000,000,
effective 2026-09-01, maturing 2031-09-01. We pay fixed at 2.80% against 3M
EURIBOR paid quarterly.
""", expected(notional=20000000, currency="EUR", receiver=False,
              valuation=date(2026, 9, 1), effective=date(2026, 9, 1),
              maturity=date(2031, 9, 1), rate="0.028",
              tenor="3M", frequency="3M"))

# ==========================================================================
# NO VALORABLES. El producto es el correcto, pero la peticion no se puede
# valorar: falta un termino sin el que no hay swap, o los datos se contradicen.
# Los detiene la validacion determinista, no el orquestador.
#
# Un tipo fijo ausente NO entra aqui: eso es una cotizacion, y es valida.
# ==========================================================================

write("no_valorables", "sin_nocional", """
Cotizame un swap EUR a 5 anos, pagamos fijo.
""", expected(notional=None, currency="EUR", receiver=False,
              effective=SPOT, maturity=years_after(SPOT, 5)))

write("no_valorables", "sin_direccion", """
Cotizame un IRS EUR 10M a 5 anos empezando spot.
""", expected(notional=10000000, currency="EUR", receiver=None,
              effective=SPOT, maturity=years_after(SPOT, 5)))

# Vencimiento anterior al inicio. El producto descrito es un IRS vanilla, asi que
# el orquestador lo acepta; la incoherencia la detecta la validacion entre
# atributos. El dorado se escribe a mano porque expected() no puede generar un
# calendario sobre un plazo negativo.
write("no_valorables", "fechas_desordenadas", """
IRS 5Y EUR 10M, inicio 10-Oct-2026 y vencimiento 10-Oct-2024.
""", """purpose: PAR_RATE_QUOTE
notional: 10000000
currency: "EUR"
valuation_date: "2026-09-21"
effective_date: "2026-10-10"
maturity_date: "2024-10-10"
discount_curve: "EUR-ESTR"
fixed_leg {
  day_count: "30U/360"
  payment_frequency: "1Y"
}
floating_leg {
  rate_type: IBOR
  index: "EURIBOR"
  tenor: "6M"
  day_count: "ACT/360"
  payment_frequency: "6M"
  forecast_curve: "EUR-EURIBOR-6M"
}
""")

# ==========================================================================
# NO SOPORTADOS. El sistema debe rechazarlos y decir por que.
# ==========================================================================

write("no_soportados", "swaption", """
Necesito precio para una Swaption payer 1Y5Y sobre EURIBOR 6M strike 2.50%.
""", None)

write("no_soportados", "basis_swap", """
Cotizame un EUR basis swap de 20M a 5 anos, pago 3M EURIBOR y recibo 6M EURIBOR
mas 8bp.
""", None)

write("no_soportados", "gbp_fuera_alcance", """
Cotizame un IRS GBP 15M a 2 anos, recibimos fijo contra SONIA.
""", None)

write("no_soportados", "menos_de_un_ano", """
Cotizame un IRS EUR 5M a 6 meses, pagamos fijo.
""", None)

write("no_soportados", "eur_contra_sofr", """
Cotizame un Swap EUR 20M a 5 anos pagando fijo contra SOFR.
""", None)

# ==========================================================================
# EXAMPLES: prompts de demostracion para runner.py.
# ==========================================================================

EXAMPLES = ROOT / "examples"
EXAMPLES.mkdir(exist_ok=True)
for name, source in (
    ("cotizacion_es.txt", "cotizacion/es_spot_5y"),
    ("cotizacion_jerga.txt", "jerga/pay_5y_50m_spot"),
    ("cotizacion_usd.txt", "cotizacion/cobertura_usd_10y"),
    ("valoracion.txt", "valoracion/eur_payer_5y"),
    ("incompleta.txt", "no_valorables/sin_nocional"),
    ("incoherente.txt", "no_valorables/fechas_desordenadas"),
    ("rechazada.txt", "no_soportados/swaption"),
):
    (EXAMPLES / name).write_text(
        (CASES_DIR / f"{source}.prompt.txt").read_text(encoding="utf-8"),
        encoding="utf-8")

print(f"Fecha de referencia {AS_OF}, spot {SPOT}, proximo lunes {NEXT_MONDAY}")
total = len(list(CASES_DIR.rglob("*.prompt.txt")))
print(f"{total} casos en {CASES_DIR}")
for folder in sorted(p for p in CASES_DIR.iterdir() if p.is_dir()):
    print(f"  {folder.name:<16} {len(list(folder.glob('*.prompt.txt')))}")
