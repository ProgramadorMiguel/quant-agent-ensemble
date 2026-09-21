from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app_service import PROJECT_ROOT, generate_rfq_from_prompt
from evaluation.metrics import FieldOutcome, compare_fields
from evaluation.telemetry import TelemetryStore
from llm_client import AgentOutputError
from proto.proto_mapper import parse_irs_textproto
from validation.irs_validator import validate_irs, with_defaults

# Etiqueta de producto que se registra cuando un agente responde algo que no
# cumple su contrato de salida (por ejemplo "IRS." en lugar de "IRS"). La fila
# cuenta como fallo del caso: el modelo tuvo la informacion y no la devolvio en
# la forma acordada. Un error de red, en cambio, se excluye del agregado.
MALFORMED = "MALFORMED"


@dataclass(frozen=True)
class Golden:
    """Lo que el caso debe producir, no lo que nos gustaria que produjera.

    Se deriva de los propios ficheros dorados, asi que anadir un caso no exige
    metadatos extra: un dorado al que le faltan terminos obligatorios es, por
    definicion, un caso que el sistema tiene que rechazar.
    """

    fields: dict
    status: str        # VALID / INVALID / NOT_RUN
    product_type: str  # IRS / UNSUPPORTED


def load_golden(cases: Path, case_name: str, prompt: str = "") -> Golden:
    product = "IRS"
    product_file = cases / f"{case_name}.expected.product"
    if product_file.exists():
        product = product_file.read_text(encoding="utf-8").strip().upper()
    expected_path = cases / f"{case_name}.expected.textproto"
    if product != "IRS" or not expected_path.exists():
        # Caso de rechazo: no hay campos que extraer y el flujo debe pararse en
        # el orquestador, de modo que la validacion no llega a ejecutarse.
        return Golden({}, "NOT_RUN", product)
    # El dorado pasa por la misma normalizacion que la extraccion. Sin este paso
    # el diferencial por omision aparecia en lo extraido y no en el dorado, y la
    # comparacion contaba una alucinacion en todos los casos: una diferencia de
    # tratamiento, no del modelo.
    fields = with_defaults(parse_irs_textproto(
        expected_path.read_text(encoding="utf-8"), PROJECT_ROOT / "protos/pricing.proto"
    ))
    status = "VALID" if validate_irs(fields, prompt).is_valid else "INVALID"
    return Golden(fields.model_dump(mode="json"), status, product)


def run_cost(store: TelemetryStore, run_id: str) -> float | None:
    rows = store.query(
        "SELECT SUM(cost_usd) FROM api_calls WHERE run_id = ? AND cost_usd IS NOT NULL",
        (run_id,),
    )
    return rows[0][0] if rows and rows[0][0] is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare RFQ extraction models")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "evaluation/cases")
    parser.add_argument("--repetitions", type=int, default=1,
                        help="Runs per case. Above 1 measures run-to-run stability.")
    # Fecha de referencia fija, no el reloj del sistema: un caso que dice "spot"
    # daria un resultado distinto cada dia y la tanda no seria reproducible ni
    # comparable con las anteriores.
    parser.add_argument("--as-of", type=date.fromisoformat,
                        default=date(2026, 9, 21),
                        help="fecha de referencia YYYY-MM-DD para resolver 'spot' "
                             "y las fechas relativas")
    parser.add_argument("--temperature", type=float, default=None,
                        help="sobreescribe la temperatura de agents.yaml")
    args = parser.parse_args()

    store = TelemetryStore(PROJECT_ROOT / "outputs/evaluations.db")
    # rglob para recorrer las subcarpetas de familia: completos, incompletos,
    # jerga y no_soportados. La familia es el nombre de la carpeta.
    prompt_files = sorted(args.cases.rglob("*.prompt.txt"))
    if not prompt_files:
        print(f"No cases found in {args.cases}")
        return 1

    # Identificador de la tanda. Todas las filas de esta ejecucion lo comparten,
    # de modo que el informe puede aislarla en lugar de agregarla con tandas
    # anteriores que pueden haberse medido contra otras instrucciones u otros
    # casos dorados.
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    failures = 0
    print(f"tanda: {batch_id}   fecha de referencia: {args.as_of.isoformat()}"
          + (f"   temperatura: {args.temperature}"
             if args.temperature is not None else "") + "\n")
    print(f"{'model':<16} {'familia':<14} {'case':<22} {'rep':>3}  "
          f"{'campos':<9} {'detalle':<30} {'ms':>7}")
    print("-" * 110)
    for model in args.models:
        for repetition in range(1, args.repetitions + 1):
            for prompt_path in prompt_files:
                case_name = prompt_path.name.removesuffix(".prompt.txt")
                family = (prompt_path.parent.name
                          if prompt_path.parent != args.cases else "sin_familia")
                golden = load_golden(prompt_path.parent, case_name,
                                     prompt_path.read_text(encoding="utf-8"))
                expected = golden.fields

                started = perf_counter()
                error = None
                malformed = None
                result = None
                try:
                    result = generate_rfq_from_prompt(
                        prompt_path.read_text(encoding="utf-8"),
                        model_override=model, as_of=args.as_of,
                        temperature=args.temperature,
                    )
                    comparison = compare_fields(result.extracted_fields, expected)
                except AgentOutputError as exc:
                    # El modelo respondio, pero fuera de contrato. Es un fallo
                    # del caso y entra en el agregado con producto MALFORMED.
                    comparison = compare_fields({}, expected)
                    malformed = f"{type(exc).__name__}: {exc}"
                    run_id = exc.run_id
                except Exception as exc:
                    # Error de proveedor o de infraestructura: se registra pero
                    # queda fuera de los agregados.
                    comparison = compare_fields({}, expected)
                    error = f"{type(exc).__name__}: {exc}"
                    failures += 1
                    run_id = None
                else:
                    run_id = result.run_id
                elapsed = (perf_counter() - started) * 1000

                product_type = (result.product_type if result
                                else MALFORMED if malformed else None)
                validation_status = result.validation_status if result else None
                store.record_evaluation(
                    evaluation_id=str(uuid4()),
                    run_id=run_id,
                    model=model, provider="openai", case_name=case_name,
                    family=family, batch_id=batch_id,
                    iterations=result.iterations if result else None,
                    temperature=args.temperature, as_of=args.as_of.isoformat(),
                    repetition=repetition, topology="pipeline",
                    product_type=product_type,
                    expected_product_type=golden.product_type,
                    expected_status=golden.status,
                    product_correct=int(product_type == golden.product_type),
                    # Acierto = coincide con lo esperado. Rechazar bien un caso
                    # incompleto es un acierto; contarlo como fallo hacia que la
                    # tasa de validacion no pudiera llegar al 100% por diseno.
                    validation_correct=int(validation_status == golden.status),
                    matched_fields=comparison.matched,
                    total_fields=comparison.total,
                    field_accuracy=comparison.accuracy,
                    field_results=json.dumps(
                        {k: v.value for k, v in comparison.per_field.items()}
                    ),
                    hallucinated_fields=", ".join(comparison.hallucinated_fields) or None,
                    wrong_fields=comparison.count(FieldOutcome.WRONG),
                    missing_fields_count=comparison.count(FieldOutcome.MISSING),
                    hallucinated_count=comparison.count(FieldOutcome.HALLUCINATED),
                    proto_agent_status=result.proto_agent.status if result else None,
                    elapsed_ms=elapsed,
                    cost_usd=run_cost(store, run_id) if run_id else None,
                    output_path=result.output_file_path if result else None,
                    error_text=error,
                )
                # Una fila con error de API se registra pero queda fuera de los
                # agregados: un timeout de red no es "el modelo se dejo los
                # dieciseis campos". Una salida fuera de contrato si cuenta.
                if error:
                    detail = f"EXCLUIDA {error[:21]}"
                elif malformed:
                    detail = f"MALFORMED {malformed[:20]}"
                else:
                    detail = comparison.summary()
                if result and result.iterations > 1:
                    detail += f"  iter:{result.iterations}"
                if result and result.proto_agent.status not in ("MATCH", "NOT_RUN"):
                    detail += f"  proto:{result.proto_agent.status}"
                print(f"{model:<16} {family:<14} {case_name:<22} {repetition:>3}  "
                      f"{comparison.matched:>2}/{comparison.total:<6} {detail:<30} "
                      f"{elapsed:>7.0f}")

    print(f"\nResultados en {PROJECT_ROOT / 'outputs/evaluations.db'}")
    print(f"Informe de esta tanda:  python src/report.py --batch {batch_id}")
    print("Informe de todas:       python src/report.py --all-batches")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
