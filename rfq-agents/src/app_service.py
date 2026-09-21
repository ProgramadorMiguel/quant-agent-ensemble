from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from llm_client import LLMClient
from proto.proto_mapper import fields_to_textproto, validate_textproto
from settings import Settings, get_settings
from validation.irs_validator import ValidationReport, validate_irs, with_defaults


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
    # Cuantas pasadas de extraccion se han necesitado. 1 significa que salio a la
    # primera; el maximo significa que se agotaron los intentos.
    iterations: int = 1
    # Errores de cada intento fallido, en orden. Es la traza de la autocorreccion.
    iteration_errors: tuple[tuple[str, ...], ...] = ()


def _retry_prompt(prompt: str, report: ValidationReport) -> str:
    """Peticion original mas el diagnostico del intento anterior.

    Reintentar con el mismo texto daria el mismo resultado. Lo que hace util el
    bucle es devolverle al agente **que** ha fallado, en los mismos terminos en
    que el validador lo ha detectado.
    """
    problems = "\n".join(f"  - {e}" for e in report.errors)
    return (
        f"{prompt}\n\n"
        "--- Correction required ---\n"
        "A previous attempt at this same request was rejected by deterministic\n"
        "validation for the following reasons:\n"
        f"{problems}\n\n"
        "Produce the message again, fixing every point above and changing nothing\n"
        "else. Do not restate the problems; return only the protobuf message."
    )


def _with_reference_date(prompt: str, as_of: date) -> str:
    """Anade la fecha de referencia a la peticion.

    Sin ella el sistema no puede resolver "spot", "el proximo lunes" ni una
    estructura diferida como "2Y1Y": no son datos que la peticion contenga, sino
    expresiones relativas a hoy, y hasta ahora el sistema no sabia que dia era.

    Se suministra como contexto, no como instruccion, y por separado de la
    peticion, de modo que quede claro que no forma parte de lo que pidio el
    cliente.
    """
    return (
        f"Reference date: {as_of.isoformat()} "
        f"({as_of.strftime('%A')}).\n\n"
        f"Request:\n{prompt}"
    )


def generate_rfq_from_prompt(
    prompt: str, *, model_override: str | None = None,
    max_iterations: int | None = None, as_of: date | None = None,
    temperature: float | None = None,
) -> RFQGenerationResult:
    """Servicio de aplicacion: de texto libre a RFQ, o a error.

    El contrato tiene solo dos salidas y no admite revision humana intermedia: o
    una RFQ bien conformada, o un error que dice por que no ha sido posible.

    Cuando la validacion detecta un error **del modelo** (una convencion que no
    corresponde a la divisa, un calendario incoherente, un valor imposible), el
    diagnostico se devuelve al agente y se reintenta, hasta ``max_iterations``
    pasadas. Cuando lo que falta es un termino que la peticion nunca enuncio, no
    se reintenta: la informacion no esta y ninguna pasada adicional la va a
    producir.
    """
    if not prompt.strip():
        raise ValueError("Prompt must not be empty")

    run_id = uuid4().hex
    settings = get_settings()
    if model_override:
        # replace y no un Settings nuevo: construirlo a mano descartaba los
        # campos que no se enumeraban, y con ellos la clave de Anthropic, de modo
        # que --models claude-... fallaba aunque la clave estuviese puesta.
        settings = replace(settings, llm_model=model_override)
    client = LLMClient(settings, PROJECT_ROOT, run_id, temperature=temperature)
    limit = max_iterations or client.config.max_iterations

    # La fecha de referencia se fija una vez por ejecucion. Pasarla explicitamente
    # y no leer el reloj en cada paso mantiene reproducible una tanda de
    # evaluacion: un caso dorado con "spot" tendria resultado distinto cada dia.
    dated_prompt = _with_reference_date(prompt, as_of or date.today())

    product_type = client.classify_product(dated_prompt)
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

    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(exist_ok=True)

    # El bucle solo reenvia al especialista. La clasificacion de producto no se
    # repite: el orquestador ya ha dicho que es un IRS y ningun error de
    # convencion o de calendario cambia esa respuesta, de modo que repetirla
    # gastaria una llamada sin poder alterar el resultado.
    attempt_prompt = dated_prompt
    history: list[tuple[str, ...]] = []
    for iteration in range(1, limit + 1):
        fields = with_defaults(client.extract_irs(attempt_prompt))
        # Se valida contra la peticion ORIGINAL, no contra la del reintento: lo
        # que importa es que enuncio el usuario, y el bloque de correccion que se
        # anade en cada pasada no forma parte de su peticion.
        report = validate_irs(fields, prompt)
        if report.is_valid or not report.retryable or iteration == limit:
            break
        history.append(tuple(report.errors))
        attempt_prompt = _retry_prompt(dated_prompt, report)

    report_path = output_dir / f"validation_{run_id}.txt"
    report_path.write_text(report.to_text(), encoding="utf-8")
    field_dict = fields.model_dump(mode="json")
    common = {
        "run_id": run_id,
        "product_type": product_type,
        "extracted_fields": field_dict,
        "iterations": iteration,
        "iteration_errors": tuple(history),
    }

    if not report.is_valid:
        return RFQGenerationResult(
            validation_status="INVALID",
            validation_errors=report.errors,
            missing_fields=report.missing_fields,
            generated_proto_text=None,
            output_file_path=None,
            **common,
        )

    proto_path = PROJECT_ROOT / "protos/pricing.proto"
    # Source of truth: this is the RFQ the system emits and a pricer consumes.
    proto_text = fields_to_textproto(fields, run_id, proto_path)
    proto_agent = _measure_proto_agent(client, fields, run_id, proto_path, proto_text)

    output_path = output_dir / f"rfq_{run_id}.textproto"
    output_path.write_text(proto_text, encoding="utf-8")
    return RFQGenerationResult(
        validation_status="VALID",
        validation_errors=[],
        missing_fields=[],
        generated_proto_text=proto_text,
        output_file_path=str(output_path),
        proto_agent=proto_agent,
        **common,
    )


def _measure_proto_agent(
    client: LLMClient, fields, run_id: str, proto_path: Path, reference: str
) -> ProtoAgentOutcome:
    """Run the proto agent and compare it against the deterministic mapper.

    The agent receives exactly the terms the mapper receives, payment schedules
    included. Without them it could never match the reference, and the fidelity
    rate would measure an impossibility instead of a capability.

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
