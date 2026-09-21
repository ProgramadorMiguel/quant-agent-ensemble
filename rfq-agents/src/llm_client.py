from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from time import perf_counter

from agent_config import AgentsConfig, load_agents_config
from evaluation.costs import cost_of
from evaluation.telemetry import TelemetryStore
from models.irs_fields import IRSFields
from proto.proto_mapper import parse_irs_textproto
from providers import TemperatureRejected, build_provider, provider_for
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


class LLMClient:
    """Executes the agent pipeline declared in config/agents.yaml."""

    def __init__(
        self,
        settings: Settings,
        project_root: Path,
        run_id: str,
        config: AgentsConfig | None = None,
        temperature: float | None = None,
    ):
        self.project_root = project_root
        self.run_id = run_id
        self.config = config or load_agents_config(project_root)
        self.model = settings.llm_model or self.config.model
        # El proveedor se deduce del nombre del modelo, de modo que comparar
        # OpenAI con Anthropic no exige tocar nada mas que --models.
        self.provider = provider_for(self.model)
        self.client = build_provider(self.model, settings)
        # La temperatura se puede sobreescribir por ejecucion para barrerla como
        # parametro de experimento sin editar el fichero de configuracion, que
        # dejaria la tanda sin rastro de con que valor se midio.
        self.temperature = (self.config.temperature if temperature is None
                            else temperature)
        # Se descubre en la primera llamada. Los modelos que solo aceptan su
        # temperatura por omision quedan fuera del barrido de ese parametro.
        self.temperature_supported = True
        self.telemetry = TelemetryStore(project_root / "outputs/evaluations.db")

    def _system_prompt(self, agent: str) -> str:
        return self.config.spec(agent).system_prompt(self.project_root)

    def _complete(self, system: str, user: str):
        """Llamada al proveedor, omitiendo la temperatura si el modelo la rechaza.

        La generacion actual de modelos de OpenAI no expone ese parametro: acepta
        solo su valor por omision y devuelve 400 ante cualquier otro. Se detecta
        el rechazo y se reintenta sin el, en lugar de mantener una lista de
        modelos que quedaria obsoleta con cada lanzamiento.

        La consecuencia para los experimentos hay que declararla: en esos modelos
        la temperatura no es un eje que se pueda barrer.
        """
        if self.temperature_supported:
            try:
                return self.client.complete(
                    self.model, system, user, self.temperature
                )
            except TemperatureRejected:
                self.temperature_supported = False
        return self.client.complete(self.model, system, user, None)

    def _call(self, agent: str, user: str) -> str:
        system = self._system_prompt(agent)
        # Identifies the exact agent instructions used, so a result recorded today
        # can still be attributed to a prompt version months from now.
        prompt_hash = sha256(system.encode("utf-8")).hexdigest()[:12]
        started = perf_counter()
        try:
            completion = self._complete(system, user)
            self.telemetry.record_call(
                run_id=self.run_id, agent=agent, model=self.model,
                latency_ms=(perf_counter() - started) * 1000, status="SUCCESS",
                request_text=user, response_text=completion.text,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                total_tokens=completion.total_tokens,
                provider=self.provider, prompt_hash=prompt_hash,
                cached_input_tokens=completion.cached_input_tokens,
                cost_usd=cost_of(self.project_root, self.model,
                                 completion.input_tokens,
                                 completion.output_tokens,
                                 completion.cached_input_tokens),
            )
            return completion.text
        except Exception as exc:
            self.telemetry.record_call(
                run_id=self.run_id, agent=agent, model=self.model,
                latency_ms=(perf_counter() - started) * 1000, status="ERROR",
                request_text=user, error_text=f"{type(exc).__name__}: {exc}",
                provider=self.provider, prompt_hash=prompt_hash,
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
