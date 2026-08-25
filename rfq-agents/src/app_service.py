from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from llm_client import LLMClient
from proto.proto_mapper import fields_to_textproto, validate_textproto
from settings import Settings, get_settings
from validation.irs_validator import validate_irs


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RFQGenerationResult:
    product_type: str
    extracted_fields: dict[str, Any]
    validation_status: str
    validation_errors: list[str]
    missing_fields: list[str]
    generated_proto_text: str | None
    output_file_path: str | None


def generate_rfq_from_prompt(
    prompt: str, *, model_override: str | None = None
) -> RFQGenerationResult:
    """Reusable application service for CLI and a future Streamlit adapter."""
    if not prompt.strip():
        raise ValueError("Prompt must not be empty")

    run_id = uuid4().hex
    settings = get_settings()
    if model_override:
        settings = Settings(settings.openai_api_key, model_override)
    client = LLMClient(settings, PROJECT_ROOT, run_id)
    product_type = client.classify_product(prompt)
    if product_type != "IRS":
        return RFQGenerationResult(
            product_type=product_type,
            extracted_fields={},
            validation_status="NOT_RUN",
            validation_errors=["Only vanilla IRS is supported in the MVP"],
            missing_fields=[],
            generated_proto_text=None,
            output_file_path=None,
        )

    fields = client.extract_irs(prompt)
    report = validate_irs(fields)
    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(exist_ok=True)
    report_path = output_dir / f"validation_{run_id}.txt"
    report_path.write_text(report.to_text(), encoding="utf-8")

    field_dict = fields.model_dump(mode="json")
    if not report.is_valid:
        return RFQGenerationResult(
            product_type=product_type,
            extracted_fields=field_dict,
            validation_status="INVALID",
            validation_errors=report.errors,
            missing_fields=report.missing_fields,
            generated_proto_text=None,
            output_file_path=None,
        )

    raw_proto = client.generate_proto_text(fields, run_id)
    proto_path = PROJECT_ROOT / "protos/pricing.proto"
    proto_text = validate_textproto(raw_proto, proto_path)
    expected_proto_text = fields_to_textproto(fields, run_id, proto_path)
    if proto_text != expected_proto_text:
        raise RuntimeError("Generated protobuf does not exactly match validated IRS fields")
    output_path = output_dir / f"rfq_{run_id}.textproto"
    output_path.write_text(proto_text, encoding="utf-8")
    return RFQGenerationResult(
        product_type=product_type,
        extracted_fields=field_dict,
        validation_status="VALID",
        validation_errors=[],
        missing_fields=[],
        generated_proto_text=proto_text,
        output_file_path=str(output_path),
    )
