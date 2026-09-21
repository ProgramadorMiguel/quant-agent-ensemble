"""Acceso a los proveedores de modelos, tras una interfaz comun.

Las dos APIs difieren en lo justo para que mezclarlas en el cliente lo
ensuciase: Anthropic lleva el prompt de sistema en un parametro aparte en lugar
de como primer mensaje, exige un limite de tokens de salida, y nombra el consumo
con otras claves. Aqui se normaliza todo eso a una sola forma, de modo que el
resto del sistema no sabe con quien habla.

La temperatura se trata como algo que el proveedor puede rechazar, no como algo
que siempre se pueda fijar. Ninguna de las dos generaciones actuales la expone: los
modelos de OpenAI devuelven 400 ante cualquier valor distinto del suyo por
omision, y el SDK de Anthropic no admite siquiera el parametro. La consecuencia
para el trabajo es que la temperatura deja de ser un eje de experimentacion, y la
reproducibilidad de una tanda no se puede apoyar en fijarla.
"""

from __future__ import annotations

from dataclasses import dataclass


# Limite de tokens de salida. Anthropic lo exige; se fija con holgura porque el
# caso mas largo, un swap a diez anos con pata trimestral, emite unas cuarenta
# fechas de pago.
MAX_OUTPUT_TOKENS = 8192


def provider_for(model: str) -> str:
    """Proveedor que sirve un modelo, deducido de su nombre.

    Deducirlo del nombre evita tener que declararlo en cada invocacion y en cada
    fichero de configuracion, a costa de depender de la nomenclatura. Es una
    convencion estable en los dos proveedores.
    """
    return "anthropic" if model.startswith("claude") else "openai"


@dataclass(frozen=True)
class Completion:
    """Respuesta normalizada, con el consumo que hace falta para el coste."""

    text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_input_tokens: int | None


class TemperatureRejected(Exception):
    """El modelo no admite el valor de temperatura solicitado."""


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)

    def complete(self, model: str, system: str, user: str,
                 temperature: float | None) -> Completion:
        from openai import BadRequestError

        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                **kwargs,
            )
        except BadRequestError as exc:
            if temperature is not None and "temperature" in str(exc):
                raise TemperatureRejected(str(exc)) from exc
            raise

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty response")
        usage = response.usage
        # OpenAI cachea automaticamente los prefijos de prompt largos y los
        # factura a tarifa reducida. El prompt de sistema del especialista supera
        # ese umbral, asi que sin este dato el coste sobreestima la factura.
        details = getattr(usage, "prompt_tokens_details", None)
        return Completion(
            text=content.strip(),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            cached_input_tokens=getattr(details, "cached_tokens", None),
        )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, model: str, system: str, user: str,
                 temperature: float | None) -> Completion:
        # El SDK actual no admite el parametro: lo rechaza en Python, antes de
        # llegar a la API. Se senala como rechazo para que el cliente reintente
        # sin el, con el mismo mecanismo que usa cuando lo rechaza OpenAI.
        if temperature is not None:
            raise TemperatureRejected(
                "the Anthropic SDK does not accept a temperature parameter"
            )
        # El prompt de sistema va en su propio parametro, no como primer mensaje.
        response = self._client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # La respuesta es una lista de bloques; solo interesan los de texto.
        text = "".join(block.text for block in response.content
                       if getattr(block, "type", None) == "text")
        if not text.strip():
            raise RuntimeError("Anthropic returned an empty response")
        usage = response.usage
        read = getattr(usage, "cache_read_input_tokens", None) or 0
        written = getattr(usage, "cache_creation_input_tokens", None) or 0
        entrada = getattr(usage, "input_tokens", None)
        salida = getattr(usage, "output_tokens", None)
        # Anthropic informa los tokens leidos de cache aparte de input_tokens, al
        # contrario que OpenAI, que los incluye. Se suman para que la cifra de
        # entrada signifique lo mismo en los dos proveedores y el coste sea
        # comparable.
        total_entrada = None if entrada is None else entrada + read + written
        return Completion(
            text=text.strip(),
            input_tokens=total_entrada,
            output_tokens=salida,
            total_tokens=(None if total_entrada is None or salida is None
                          else total_entrada + salida),
            cached_input_tokens=read or None,
        )


def build_provider(model: str, settings):
    """Proveedor listo para el modelo pedido."""
    name = provider_for(model)
    key = settings.key_for(name)
    return AnthropicProvider(key) if name == "anthropic" else OpenAIProvider(key)
