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
class ProtoAgentOutcome:
    """Result of the RFQ proto agent, which is measured but never trusted.

    The deterministic mapper produces the RFQ the system actually emits. This
    agent runs alongside it and its output is compared, so that "can an LLM
    serialise correctly against a schema it is given?" becomes a measurement
    instead of an assumption. A mismatch is a datapoint, not a failure.
    """

    ran: bool
    parsed: bool
    matched: bool
    error: str | None = None

    @property
    def status(self) -> str:
        if not self.ran:
            return "NOT_RUN"
        if not self.parsed:
            return "UNPARSEABLE"
        return "MATCH" if self.matched else "MISMATCH"


@dataclass(frozen=True)
class RFQGenerationResult:
    run_id: str
    product_type: str
    extracted_fields: dict[str, Any]
    validation_status: str
    validation_errors: list[str]
    missing_fields: list[str]
    generated_proto_text: str | None
    output_file_path: str | None
    proto_agent: ProtoAgentOutcome = ProtoAgentOutcome(False, False, False)


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
            run_id=run_id,
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
            run_id=run_id,
            product_type=product_type,
            extracted_fields=field_dict,
            validation_status="INVALID",
            validation_errors=report.errors,
            missing_fields=report.missing_fields,
            generated_proto_text=None,
            output_file_path=None,
        )

    proto_path = PROJECT_ROOT / "protos/pricing.proto"
    # Source of truth: this is the RFQ the system emits and a pricer consumes.
    proto_text = fields_to_textproto(fields, run_id, proto_path)
    proto_agent = _measure_proto_agent(client, fields, run_id, proto_path, proto_text)

    output_path = output_dir / f"rfq_{run_id}.textproto"
    output_path.write_text(proto_text, encoding="utf-8")
    return RFQGenerationResult(
        run_id=run_id,
        product_type=product_type,
        extracted_fields=field_dict,
        validation_status="VALID",
        validation_errors=[],
        missing_fields=[],
        generated_proto_text=proto_text,
        output_file_path=str(output_path),
        proto_agent=proto_agent,
    )


def _measure_proto_agent(
    client: LLMClient, fields, run_id: str, proto_path: Path, reference: str
) -> ProtoAgentOutcome:
    """Run the proto agent and compare it against the deterministic mapper.

    Never raises: a badly serialised RFQ is an observation about the model, not
    a reason to abort a run that already has a valid RFQ.
    """
    try:
        raw = client.generate_proto_text(fields, run_id)
    except Exception as exc:
        return ProtoAgentOutcome(False, False, False, f"{type(exc).__name__}: {exc}")
    try:
        normalised = validate_textproto(raw, proto_path)
    except Exception as exc:
        return ProtoAgentOutcome(True, False, False, f"{type(exc).__name__}: {exc}")
    return ProtoAgentOutcome(True, True, normalised == reference)
