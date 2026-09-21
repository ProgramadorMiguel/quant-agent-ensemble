from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from time import perf_counter

from openai import OpenAI

from agent_config import AgentsConfig, load_agents_config
from evaluation.costs import cost_of
from evaluation.telemetry import TelemetryStore
from models.irs_fields import IRSFields
from proto.proto_mapper import parse_irs_textproto
from settings import Settings


class AgentOutputError(RuntimeError):
    """The model answered, but not with the contract its instructions demand.

    Distinct from a provider failure on purpose: a timeout is not a fact about
    the model, whereas ``IRS.`` instead of ``IRS`` is. The evaluator counts the
    former as an excluded run and the latter as a failed case.

    Carries the ``run_id`` so the evaluation row can still be linked to the
    ``api_calls`` that were recorded before the failure.
    """

    def __init__(self, message: str, run_id: str | None = None):
        super().__init__(message)
        self.run_id = run_id


def _cached_tokens(usage) -> int | None:
    """Tokens de entrada servidos desde la cache de prompt, si el proveedor lo informa."""
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None:
        return None
    return getattr(details, "cached_tokens", None)


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
        # Identifies the exact agent instructions used, so a result recorded today
        # can still be attributed to a prompt version months from now.
        prompt_hash = sha256(system.encode("utf-8")).hexdigest()[:12]
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
            input_tokens = getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "completion_tokens", None)
            # OpenAI cachea automaticamente los prefijos de prompt largos y los
            # factura a tarifa reducida. El prompt de sistema del especialista
            # (instrucciones + skill + esquema) supera ese umbral, asi que sin
            # este dato el coste calculado sobreestima la factura real.
            cached_tokens = _cached_tokens(usage)
            self.telemetry.record_call(
                run_id=self.run_id, agent=agent, model=self.model,
                latency_ms=(perf_counter() - started) * 1000, status="SUCCESS",
                request_text=user, response_text=content,
                input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=getattr(usage, "total_tokens", None),
                provider="openai", prompt_hash=prompt_hash,
                cached_input_tokens=cached_tokens,
                cost_usd=cost_of(self.project_root, self.model, input_tokens,
                                 output_tokens, cached_tokens),
            )
            return content.strip()
        except Exception as exc:
            self.telemetry.record_call(
                run_id=self.run_id, agent=agent, model=self.model,
                latency_ms=(perf_counter() - started) * 1000, status="ERROR",
                request_text=user, error_text=f"{type(exc).__name__}: {exc}",
                provider="openai", prompt_hash=prompt_hash,
            )
            raise

    def classify_product(self, prompt: str) -> str:
        result = self._call("orchestrator", prompt)
        if result not in {"IRS", "UNSUPPORTED"}:
            raise AgentOutputError(
                f"Invalid product classification: {result!r}", self.run_id
            )
        return result

    def extract_irs(self, prompt: str) -> IRSFields:
        proto_text = self._call("product_specialist", prompt)
        try:
            return parse_irs_textproto(
                proto_text, self.project_root / "protos/pricing.proto"
            )
        except Exception as exc:
            # Texto que no es un InterestRateSwap parseable: fallo del modelo
            # frente a su contrato de salida, no de la infraestructura.
            raise AgentOutputError(
                f"Product specialist output is not a valid InterestRateSwap: {exc}",
                self.run_id,
            ) from exc

    def generate_proto_text(self, validated_fields: IRSFields, rfq_id: str) -> str:
        """Pide al agente proto que serialice los terminos ya validados.

        Recibe exactamente los mismos terminos que el mapeador determinista,
        calendarios de pago incluidos. Sin ellos no podria coincidir nunca con la
        RFQ de referencia, que si los contiene, y su tasa de fidelidad mediria una
        imposibilidad en lugar de una capacidad.
        """
        data = validated_fields.model_dump(mode="json")
        lines = [f"rfq_id: {rfq_id}", "", "Validated IRS fields:"]

        def render(key: str, value: object, indent: str = "") -> None:
            if value is None:
                return
            if isinstance(value, dict):
                lines.append(f"{indent}{key}:")
                for sub_key, sub_value in value.items():
                    render(sub_key, sub_value, indent + "  ")
            elif isinstance(value, list):
                # Campo repetido: una linea por elemento, para que el agente vea
                # la misma forma que debe emitir.
                for item in value:
                    lines.append(f"{indent}{key}: {item}")
            else:
                lines.append(f"{indent}{key}: {value}")

        for key, value in data.items():
            render(key, value)
        return self._call("rfq_proto", "\n".join(lines))
