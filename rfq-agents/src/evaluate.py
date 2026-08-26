from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app_service import PROJECT_ROOT, generate_rfq_from_prompt
from evaluation.metrics import FieldOutcome, compare_fields
from evaluation.telemetry import TelemetryStore
from models.irs_fields import IRSFields
from proto.proto_mapper import parse_irs_textproto


def expected_fields(case_path: Path) -> dict:
    expected = parse_irs_textproto(
        case_path.read_text(encoding="utf-8"), PROJECT_ROOT / "protos/pricing.proto"
    )
    return expected.model_dump(mode="json")


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
    args = parser.parse_args()

    store = TelemetryStore(PROJECT_ROOT / "outputs/evaluations.db")
    prompt_files = sorted(args.cases.glob("*.prompt.txt"))
    if not prompt_files:
        print(f"No cases found in {args.cases}")
        return 1

    failures = 0
    print(f"{'model':<16} {'case':<24} {'rep':>3}  {'campos':<9} {'detalle':<34} {'ms':>7}")
    print("-" * 100)
    for model in args.models:
        for repetition in range(1, args.repetitions + 1):
            for prompt_path in prompt_files:
                case_name = prompt_path.name.removesuffix(".prompt.txt")
                expected = expected_fields(args.cases / f"{case_name}.expected.textproto")

                started = perf_counter()
                error = None
                result = None
                try:
                    result = generate_rfq_from_prompt(
                        prompt_path.read_text(encoding="utf-8"), model_override=model
                    )
                    comparison = compare_fields(result.extracted_fields, expected)
                except Exception as exc:
                    comparison = compare_fields({}, expected)
                    error = f"{type(exc).__name__}: {exc}"
                    failures += 1
                elapsed = (perf_counter() - started) * 1000

                store.record_evaluation(
                    evaluation_id=str(uuid4()),
                    run_id=result.run_id if result else None,
                    model=model, provider=None, case_name=case_name,
                    repetition=repetition, topology="pipeline",
                    product_type=result.product_type if result else None,
                    product_correct=int(result is not None and result.product_type == "IRS"),
                    validation_correct=int(
                        result is not None and result.validation_status == "VALID"
                    ),
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
                    elapsed_ms=elapsed,
                    cost_usd=run_cost(store, result.run_id) if result else None,
                    output_path=result.output_file_path if result else None,
                    error_text=error,
                )
                detail = error[:34] if error else comparison.summary()
                print(f"{model:<16} {case_name:<24} {repetition:>3}  "
                      f"{comparison.matched:>2}/{comparison.total:<6} {detail:<34} {elapsed:>7.0f}")

    print(f"\nResultados en {PROJECT_ROOT / 'outputs/evaluations.db'}")
    print("Informe comparativo:  python src/report.py")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
