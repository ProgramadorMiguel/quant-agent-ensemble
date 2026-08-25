from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app_service import PROJECT_ROOT, generate_rfq_from_prompt
from proto.proto_mapper import textproto_to_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the agent pipeline over a folder of prompts and save each RFQ"
    )
    parser.add_argument("--prompts", type=Path, default=PROJECT_ROOT / "examples")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "samples")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    proto_path = PROJECT_ROOT / "protos/pricing.proto"
    prompt_files = sorted(args.prompts.glob("*.txt"))
    if not prompt_files:
        print(f"No prompts found in {args.prompts}", file=sys.stderr)
        return 1

    generated = 0
    rejected = 0
    for prompt_path in prompt_files:
        case = prompt_path.stem
        try:
            result = generate_rfq_from_prompt(
                prompt_path.read_text(encoding="utf-8"), model_override=args.model
            )
        except Exception as exc:
            print(f"{case:<28} ERROR      {type(exc).__name__}: {exc}")
            rejected += 1
            continue

        if result.validation_status != "VALID" or not result.generated_proto_text:
            reason = ", ".join(result.missing_fields or result.validation_errors) or "-"
            print(f"{case:<28} {result.validation_status:<10} {reason}")
            (args.out / f"{case}.rejected.txt").write_text(
                f"product_type: {result.product_type}\n"
                f"validation_status: {result.validation_status}\n"
                f"missing_fields: {', '.join(result.missing_fields) or 'none'}\n"
                f"errors: {'; '.join(result.validation_errors) or 'none'}\n",
                encoding="utf-8",
            )
            rejected += 1
            continue

        (args.out / f"{case}.textproto").write_text(
            result.generated_proto_text, encoding="utf-8"
        )
        (args.out / f"{case}.json").write_text(
            textproto_to_json(result.generated_proto_text, proto_path) + "\n",
            encoding="utf-8",
        )
        print(f"{case:<28} VALID      {case}.textproto + {case}.json")
        generated += 1

    print(f"\n{generated} RFQ(s) generated, {rejected} rejected -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
