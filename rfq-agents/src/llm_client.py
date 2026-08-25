from __future__ import annotations

from pathlib import Path
from time import perf_counter

from openai import OpenAI

from evaluation.telemetry import TelemetryStore
from models.irs_fields import IRSFields
from proto.proto_mapper import parse_irs_textproto
from settings import Settings


class LLMClient:
    def __init__(self, settings: Settings, project_root: Path, run_id: str):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.llm_model
        self.project_root = project_root
        self.run_id = run_id
        self.telemetry = TelemetryStore(project_root / "outputs/evaluations.db")

    def _read(self, relative_path: str) -> str:
        return (self.project_root / relative_path).read_text(encoding="utf-8")

    def _call(self, agent: str, system: str, user: str) -> str:
        started = perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=0,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("OpenAI returned an empty response")
            usage = response.usage
            self.telemetry.record_call(
                run_id=self.run_id, agent=agent, model=self.model,
                latency_ms=(perf_counter() - started) * 1000, status="SUCCESS",
                request_text=user, response_text=content,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            )
            return content.strip()
        except Exception as exc:
            self.telemetry.record_call(
                run_id=self.run_id, agent=agent, model=self.model,
                latency_ms=(perf_counter() - started) * 1000, status="ERROR",
                request_text=user, error_text=f"{type(exc).__name__}: {exc}",
            )
            raise

    def classify_product(self, prompt: str) -> str:
        result = self._call("orchestrator", self._read("agents/orchestrator_agent.md"), prompt)
        if result not in {"IRS", "UNSUPPORTED"}:
            raise RuntimeError(f"Invalid product classification: {result!r}")
        return result

    def extract_irs(self, prompt: str) -> IRSFields:
        system = self._read("agents/product_specialist_agent.md")
        system += "\n\n# Product skill\n" + self._read("skills/irs_extraction_skill.md")
        system += "\n\n# pricing.proto\n" + self._read("protos/pricing.proto")
        proto_text = self._call("product_specialist", system, prompt)
        return parse_irs_textproto(proto_text, self.project_root / "protos/pricing.proto")

    def generate_proto_text(self, validated_fields: IRSFields, rfq_id: str) -> str:
        system = self._read("agents/rfq_proto_agent.md")
        system += "\n\n# pricing.proto\n" + self._read("protos/pricing.proto")
        field_lines = [f"rfq_id: {rfq_id}", "Validated IRS fields:"]
        field_lines.extend(f"{key}: {value}" for key, value in
                           validated_fields.model_dump(mode="json").items())
        return self._call("rfq_proto", system, "\n".join(field_lines))
