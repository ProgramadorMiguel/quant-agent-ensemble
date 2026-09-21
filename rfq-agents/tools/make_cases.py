"""Genera los casos dorados a partir de una declaracion compacta.

Los ficheros ``.expected.textproto`` son largos y repetitivos: un swap a diez
anos lleva veinte fechas de pago en la pata flotante. Escribirlos a mano invita a
la errata, y una errata en un caso dorado se lee luego como un fallo del modelo,
que es exactamente el error que este trabajo ya ha cometido una vez.

Este script declara cada caso por sus terminos economicos y deriva el resto de la
convencion documentada en ``models.conventions``, la misma que el validador usa
para comprobar. Las fechas las genera ``models.schedule``.

Ejecutar desde la raiz del proyecto:  python tools/make_cases.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models.conventions import convention_for  # noqa: E402
from models.irs_fields import OVERNIGHT_COMPOUNDED  # noqa: E402
from models.schedule import add_months  # noqa: E402

CASES_DIR = ROOT / "evaluation/cases"


def schedule(effective: date, maturity: date, frequency: str) -> list[str]:
    """Fechas de pago: fin de cada periodo, terminando en el vencimiento.

    El ultimo periodo puede ser mas corto que los demas. Eso es un periodo roto y
    es legitimo: se conservan los pasos regulares y la ultima fecha es el
    vencimiento.
    """
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


def expected_textproto(
    *, notional: int, currency: str, receiver: bool, valuation: str,
    effective: str, maturity: str, rate: str, spread: str | None = None,
) -> str:
    eff, mat = date.fromisoformat(effective), date.fromisoformat(maturity)
    years = (mat - eff).days / 365.25
    conv = convention_for(currency, years)
    if conv is None:
        raise SystemExit(f"Sin convencion para {currency} a {years:.2f} anos")

    lines = [
        f"notional: {notional}",
        f'currency: "{currency}"',
        f"is_fixed_rate_receiver: {'true' if receiver else 'false'}",
        f'valuation_date: "{valuation}"',
        f'effective_date: "{effective}"',
        f'maturity_date: "{maturity}"',
        f'discount_curve: "{conv.discount_curve}"',
        "fixed_leg {",
        f"  rate: {rate}",
        f'  day_count: "{conv.fixed_day_count}"',
        f'  payment_frequency: "{conv.fixed_payment_frequency}"',
    ]
    lines += [f'  payment_dates: "{d}"'
              for d in schedule(eff, mat, conv.fixed_payment_frequency)]
    lines += ["}", "floating_leg {", f"  rate_type: {conv.rate_type}",
              f'  index: "{conv.index}"']
    if conv.tenor:
        lines.append(f'  tenor: "{conv.tenor}"')
    if spread:
        lines.append(f"  spread: {spread}")
    lines += [
        f'  day_count: "{conv.floating_day_count}"',
        f'  payment_frequency: "{conv.floating_payment_frequency}"',
        f'  forecast_curve: "{conv.forecast_curve}"',
    ]
    lines += [f'  payment_dates: "{d}"'
              for d in schedule(eff, mat, conv.floating_payment_frequency)]
    lines.append("}")
    return "\n".join(lines) + "\n"


def drop(text: str, *paths: str) -> str:
    """Quita lineas del textproto esperado, para los casos incompletos."""
    keep = []
    for line in text.splitlines():
        field = line.strip().split(":")[0]
        if field in paths:
            continue
        keep.append(line)
    return "\n".join(keep) + "\n"


def write(family: str, name: str, prompt: str, expected: str | None) -> None:
    folder = CASES_DIR / family
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.prompt.txt").write_text(prompt.strip() + "\n", encoding="utf-8")
    if expected is None:
        (folder / f"{name}.expected.product").write_text("UNSUPPORTED\n", encoding="utf-8")
    else:
        (folder / f"{name}.expected.textproto").write_text(expected, encoding="utf-8")


# --------------------------------------------------------------------------
# COMPLETOS: la peticion enuncia los siete obligatorios y nada mas. El sistema
# debe derivar convenciones y calcular los dos calendarios.
# --------------------------------------------------------------------------

write("completos", "eur_payer_5y", """
Value as of 2026-09-01 a vanilla EUR interest rate swap with notional
EUR 10,000,000, effective 2026-09-01 and maturing 2031-09-01. We pay fixed at
2.75%.
""", expected_textproto(
    notional=10000000, currency="EUR", receiver=False, valuation="2026-09-01",
    effective="2026-09-01", maturity="2031-09-01", rate="0.0275"))

write("completos", "eur_receiver_10y", """
Please value as of 2026-10-01 an EUR interest rate swap of EUR 25,000,000
running from 2026-10-01 to 2036-10-01. The client receives fixed at 3.10%.
""", expected_textproto(
    notional=25000000, currency="EUR", receiver=True, valuation="2026-10-01",
    effective="2026-10-01", maturity="2036-10-01", rate="0.031"))

write("completos", "eur_payer_1y", """
Value as of 2026-09-01 an EUR interest rate swap, notional EUR 4,000,000,
effective 2026-09-01, maturing 2027-09-01. We pay fixed at 2.40%.
""", expected_textproto(
    notional=4000000, currency="EUR", receiver=False, valuation="2026-09-01",
    effective="2026-09-01", maturity="2027-09-01", rate="0.024"))

write("completos", "usd_receiver_sofr_3y", """
Value as of 2026-09-01 a USD interest rate swap, notional USD 50,000,000,
effective 2026-09-01, maturing 2029-09-01. The client receives fixed at 3.85%.
""", expected_textproto(
    notional=50000000, currency="USD", receiver=True, valuation="2026-09-01",
    effective="2026-09-01", maturity="2029-09-01", rate="0.0385"))

write("completos", "usd_payer_sofr_7y", """
Generate an RFQ for a USD interest rate swap, notional USD 20,000,000, valued as
of 2026-09-15, starting 2026-09-15 and maturing 2033-09-15. We pay fixed at
4.05%.
""", expected_textproto(
    notional=20000000, currency="USD", receiver=False, valuation="2026-09-15",
    effective="2026-09-15", maturity="2033-09-15", rate="0.0405"))

write("completos", "eur_broken_period", """
Value as of 2026-09-01 an EUR interest rate swap with notional EUR 7,500,000,
effective 2026-09-01 and maturing 2030-03-01. We pay fixed at 2.95% plus a
spread of 25bp on the floating leg.
""", expected_textproto(
    notional=7500000, currency="EUR", receiver=False, valuation="2026-09-01",
    effective="2026-09-01", maturity="2030-03-01", rate="0.0295", spread="0.0025"))

# --------------------------------------------------------------------------
# INCOMPLETOS: falta un termino obligatorio, que no se deriva de nada. El sistema
# debe reclamarlo y no reintentar.
# --------------------------------------------------------------------------

_eur_base = dict(notional=5000000, currency="EUR", receiver=False,
                 valuation="2026-09-01", effective="2026-09-01",
                 maturity="2031-09-01", rate="0.026")

write("incompletos", "sin_tipo_fijo", """
Value as of 2026-09-01 an EUR interest rate swap, notional EUR 5,000,000, from
2026-09-01 to 2031-09-01. We pay fixed.
""", drop(expected_textproto(**_eur_base), "rate"))

write("incompletos", "sin_nocional", """
Value as of 2026-09-01 an EUR interest rate swap from 2026-09-01 to 2031-09-01.
We pay fixed at 2.60%.
""", drop(expected_textproto(**_eur_base), "notional"))

write("incompletos", "sin_fecha_valoracion", """
RFQ for an EUR interest rate swap, notional EUR 5,000,000, effective 2026-09-01
and maturing 2031-09-01. We pay fixed at 2.60%.
""", drop(expected_textproto(**_eur_base), "valuation_date"))

write("incompletos", "sin_direccion", """
Value as of 2026-09-01 an EUR interest rate swap, notional EUR 5,000,000, from
2026-09-01 to 2031-09-01, with a fixed rate of 2.60%.
""", drop(expected_textproto(**_eur_base), "is_fixed_rate_receiver"))

# --------------------------------------------------------------------------
# JERGA: la misma informacion en taquigrafia de mesa.
# --------------------------------------------------------------------------

write("jerga", "abreviado_eur", """
val 2026-09-01, 10mm EUR from 2026-09-01 to 2031-09-01, pay 2,75%
""", expected_textproto(
    notional=10000000, currency="EUR", receiver=False, valuation="2026-09-01",
    effective="2026-09-01", maturity="2031-09-01", rate="0.0275"))

write("jerga", "abreviado_usd", """
valn dt 2026-09-01. USD 250k, 2026-09-01 / 2031-09-01. rec fixed 385bp
""", expected_textproto(
    notional=250000, currency="USD", receiver=True, valuation="2026-09-01",
    effective="2026-09-01", maturity="2031-09-01", rate="0.0385"))

write("jerga", "abreviado_eur_spread", """
Desk request, valn 2026-09-01. EUR 30mm, eff 2026-09-01, mat 2033-09-01.
client pays fixed 3,20 pct, floating +15bp
""", expected_textproto(
    notional=30000000, currency="EUR", receiver=False, valuation="2026-09-01",
    effective="2026-09-01", maturity="2033-09-01", rate="0.032", spread="0.0015"))

# --------------------------------------------------------------------------
# NO SOPORTADOS: el orquestador debe detenerlos.
# --------------------------------------------------------------------------

write("no_soportados", "swaption", """
Price a European swaption on a 5-year EUR interest rate swap, notional
EUR 10,000,000, expiring 2027-09-01, strike 2.75%, payer.
""", None)

write("no_soportados", "basis_swap", """
Value as of 2026-09-01 an EUR basis swap of EUR 20,000,000 from 2026-09-01 to
2031-09-01, paying 3M EURIBOR quarterly and receiving 6M EURIBOR semiannually
plus 8bp.
""", None)

write("no_soportados", "gbp_fuera_alcance", """
Value as of 2026-09-01 a GBP interest rate swap, notional GBP 15,000,000,
effective 2026-09-01, maturing 2028-09-01. The client receives fixed at 4.10%.
""", None)

write("no_soportados", "menos_de_un_ano", """
Value as of 2026-09-01 an EUR interest rate swap, notional EUR 5,000,000,
effective 2026-09-01, maturing 2027-03-01. We pay fixed at 2.10%.
""", None)

# --------------------------------------------------------------------------
# EXAMPLES: prompts de demostracion para runner.py, sin fichero esperado.
# --------------------------------------------------------------------------

EXAMPLES = ROOT / "examples"
EXAMPLES.mkdir(exist_ok=True)
for name, source in (
    ("eur_minimal.txt", "completos/eur_payer_5y"),
    ("usd_sofr_ois.txt", "completos/usd_receiver_sofr_3y"),
    ("broken_period.txt", "completos/eur_broken_period"),
    ("incomplete.txt", "incompletos/sin_tipo_fijo"),
    ("desk_shorthand.txt", "jerga/abreviado_usd"),
):
    text = (CASES_DIR / f"{source}.prompt.txt").read_text(encoding="utf-8")
    (EXAMPLES / name).write_text(text, encoding="utf-8")

total = len(list(CASES_DIR.rglob("*.prompt.txt")))
print(f"{total} casos escritos en {CASES_DIR}")
for folder in sorted(p for p in CASES_DIR.iterdir() if p.is_dir()):
    n = len(list(folder.glob("*.prompt.txt")))
    print(f"  {folder.name:<16} {n}")
print(f"{len(list(EXAMPLES.glob('*.txt')))} prompts de ejemplo en {EXAMPLES}")
