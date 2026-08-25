from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app_service import generate_rfq_from_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a vanilla IRS protobuf RFQ")
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 prompt file")
    args = parser.parse_args()
    try:
        prompt = args.input.read_text(encoding="utf-8")
        result = generate_rfq_from_prompt(prompt)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"1. Product classification result: {result.product_type}")
    print("2. Extracted fields:")
    for name, value in result.extracted_fields.items():
        print(f"   {name}: {value}")
    print(f"3. Validation report: {result.validation_status}")
    print(f"   Missing fields: {result.missing_fields or 'none'}")
    print(f"   Errors: {result.validation_errors or 'none'}")
    print(f"4. Generated RFQ protobuf path: {result.output_file_path or 'not generated'}")
    return 0 if result.validation_status == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
