"""Comprueba que cada caso dorado es coherente antes de gastar una sola llamada.

Un caso dorado mal especificado se lee despues como un fallo del modelo. Este
script verifica que cada fichero esperado parsea contra el esquema y que su estado
de validacion es el que su familia implica: los completos y los de jerga deben
salir VALID, los incompletos INVALID.

Ejecutar desde la raiz del proyecto:  python tools/check_cases.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proto.proto_mapper import parse_irs_textproto  # noqa: E402
from validation.irs_validator import validate_irs, with_defaults  # noqa: E402

PROTO = ROOT / "protos/pricing.proto"
CASES = ROOT / "evaluation/cases"

EXPECTED_BY_FAMILY = {
    "cotizacion": "VALID",
    "valoracion": "VALID",
    "jerga": "VALID",
    "incompletos": "INVALID",
    "no_soportados": "NOT_RUN",
}

problems = 0
for prompt in sorted(CASES.rglob("*.prompt.txt")):
    case = prompt.name.removesuffix(".prompt.txt")
    family = prompt.parent.name
    want = EXPECTED_BY_FAMILY[family]

    product_file = prompt.parent / f"{case}.expected.product"
    if product_file.exists():
        product = product_file.read_text(encoding="utf-8").strip()
        ok = want == "NOT_RUN" and product == "UNSUPPORTED"
        print(f"{'ok ' if ok else 'MAL'} {family:<15} {case:<24} producto={product}")
        problems += 0 if ok else 1
        continue

    golden = prompt.parent / f"{case}.expected.textproto"
    try:
        fields = with_defaults(parse_irs_textproto(
            golden.read_text(encoding="utf-8"), PROTO))
    except Exception as exc:
        print(f"MAL {family:<15} {case:<24} NO PARSEA: {type(exc).__name__}: {exc}")
        problems += 1
        continue

    # Se valida contra la peticion, igual que en produccion: un termino de
    # convencion que la peticion enuncia se respeta aunque no sea el estandar.
    report = validate_irs(fields, prompt.read_text(encoding="utf-8"))
    status = "VALID" if report.is_valid else "INVALID"
    ok = status == want
    detail = ""
    if not ok or status == "INVALID":
        detail = f"  faltan={report.missing_fields or '-'} errores={report.errors or '-'}"
    fixed_n = len(fields.fixed_leg.payment_dates)
    floating_n = len(fields.floating_leg.payment_dates)
    print(f"{'ok ' if ok else 'MAL'} {family:<15} {case:<24} {status:<8} "
          f"fechas {fixed_n}/{floating_n}{detail}")
    problems += 0 if ok else 1

print()
print("TODOS COHERENTES" if not problems else f"{problems} CASOS CON PROBLEMAS")
sys.exit(1 if problems else 0)
