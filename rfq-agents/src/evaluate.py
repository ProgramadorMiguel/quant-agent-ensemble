from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app_service import PROJECT_ROOT, generate_rfq_from_prompt
from evaluation.telemetry import TelemetryStore
from models.irs_fields import IRSFields
from proto.proto_mapper import parse_irs_textproto


def accuracy(actual: dict, expected: IRSFields) -> tuple[int, int]:
    expected_data = expected.model_dump(mode="json")
    matched = sum(actual.get(name) == value for name, value in expected_data.items())
    return matched, len(expected_data)


def safe_filename(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_." else "_"
                   for character in value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare RFQ extraction models")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "evaluation/cases")
    args = parser.parse_args()
    store = TelemetryStore(PROJECT_ROOT / "outputs/evaluations.db")
    failures = 0
    for model in args.models:
        for prompt_path in sorted(args.cases.glob("*.prompt.txt")):
            case_name = prompt_path.name.removesuffix(".prompt.txt")
            expected_path = args.cases / f"{case_name}.expected.textproto"
            expected = parse_irs_textproto(
                expected_path.read_text(encoding="utf-8"), PROJECT_ROOT / "protos/pricing.proto"
            )
            started = perf_counter()
            error = None
            result = None
            try:
                result = generate_rfq_from_prompt(
                    prompt_path.read_text(encoding="utf-8"), model_override=model
                )
                matched, total = accuracy(result.extracted_fields, expected)
            except Exception as exc:
                matched, total = 0, len(IRSFields.model_fields)
                error = f"{type(exc).__name__}: {exc}"
                failures += 1
            elapsed = (perf_counter() - started) * 1000
            product_correct = int(result is not None and result.product_type == "IRS")
            validation_correct = int(result is not None and result.validation_status == "VALID")
            store.record_evaluation(
                evaluation_id=str(uuid4()), model=model, case_name=case_name,
                product_correct=product_correct, validation_correct=validation_correct,
                matched_fields=matched, total_fields=total,
                field_accuracy=matched / total, elapsed_ms=elapsed,
                output_path=result.output_file_path if result else None, error_text=error,
            )
            result_path = args.cases / (
                f"{safe_filename(case_name)}__{safe_filename(model)}.result.txt"
            )
            result_path.write_text(
                "\n".join([
                    f"case: {case_name}", f"model: {model}",
                    f"product_correct: {bool(product_correct)}",
                    f"validation_correct: {bool(validation_correct)}",
                    f"matched_fields: {matched}/{total}",
                    f"field_accuracy: {matched / total:.4f}",
                    f"elapsed_ms: {elapsed:.2f}",
                    f"output_path: {result.output_file_path if result else ''}",
                    f"error: {error or 'none'}", "",
                ]), encoding="utf-8",
            )
            print(f"{model} | {case_name} | fields={matched}/{total} | "
                  f"valid={bool(validation_correct)} | {elapsed:.0f} ms | "
                  f"{error or 'OK'} | {result_path.name}")
    print(f"Detailed results: {PROJECT_ROOT / 'outputs/evaluations.db'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
