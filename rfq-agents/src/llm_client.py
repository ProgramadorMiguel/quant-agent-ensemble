from __future__ import annotations

from pathlib import Path
from time import perf_counter

from openai import OpenAI

from agent_config import AgentsConfig, load_agents_config
from evaluation.telemetry import TelemetryStore
from models.irs_fields import IRSFields
from proto.proto_mapper import parse_irs_textproto
from settings import Settings


class LLMClient:
    """Executes the agent pipeline declared in config/agents.yaml."""

    def __init__(
        self,
        settings: Settings,
        project_root: Path,
        run_id: str,
        config: AgentsConfig | None = None,
    ):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.project_root = project_root
        self.run_id = run_id
        self.config = config or load_agents_config(project_root)
        self.model = settings.llm_model or self.config.model
        self.telemetry = TelemetryStore(project_root / "outputs/evaluations.db")

    def _system_prompt(self, agent: str) -> str:
        return self.config.spec(agent).system_prompt(self.project_root)

    def _call(self, agent: str, user: str) -> str:
        system = self._system_prompt(agent)
        started = perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=self.config.temperature,
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
        result = self._call("orchestrator", prompt)
        if result not in {"IRS", "UNSUPPORTED"}:
            raise RuntimeError(f"Invalid product classification: {result!r}")
        return result

    def extract_irs(self, prompt: str) -> IRSFields:
        proto_text = self._call("product_specialist", prompt)
        return parse_irs_textproto(proto_text, self.project_root / "protos/pricing.proto")

    def generate_proto_text(self, validated_fields: IRSFields, rfq_id: str) -> str:
        field_lines = [f"rfq_id: {rfq_id}", "Validated IRS fields:"]
        field_lines.extend(f"{key}: {value}" for key, value in
                           validated_fields.model_dump(mode="json").items())
        return self._call("rfq_proto", "\n".join(field_lines))
