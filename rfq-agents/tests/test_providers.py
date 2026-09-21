"""Capa de proveedores, sin llamar a ninguna API.

Lo que se comprueba aqui es la normalizacion: que las dos APIs, que difieren en
donde va el prompt de sistema y en como nombran el consumo, lleguen al resto del
sistema con la misma forma. Si esa traduccion falla, el coste de un proveedor no
es comparable con el del otro y la comparativa entre modelos deja de significar
nada.
"""

import pytest

from providers import (
    AnthropicProvider,
    Completion,
    OpenAIProvider,
    TemperatureRejected,
    provider_for,
)
from settings import Settings


# --- A quien pertenece cada modelo ---------------------------------------

@pytest.mark.parametrize("model,expected", [
    ("gpt-5.6-luna", "openai"),
    ("gpt-5.6-terra", "openai"),
    ("gpt-4.1-mini", "openai"),
    ("claude-sonnet-5", "anthropic"),
    ("claude-haiku-4-5", "anthropic"),
    ("claude-opus-5", "anthropic"),
])
def test_the_provider_is_deduced_from_the_model_name(model, expected):
    assert provider_for(model) == expected


# --- Las claves se exigen solo cuando hacen falta -------------------------

def test_only_the_key_of_the_provider_in_use_is_required():
    """Comparar modelos de un proveedor no debe exigir credenciales del otro."""
    only_openai = Settings(openai_api_key="sk-x", llm_model=None)
    assert only_openai.key_for("openai") == "sk-x"
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        only_openai.key_for("anthropic")


def test_the_error_names_the_variable_to_set():
    only_anthropic = Settings(
        openai_api_key="", llm_model=None, anthropic_api_key="sk-ant"
    )
    assert only_anthropic.key_for("anthropic") == "sk-ant"
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        only_anthropic.key_for("openai")


# --- Normalizacion del consumo -------------------------------------------

class _Stub:
    """Objeto con los atributos que se le pidan, para imitar una respuesta."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_openai_usage_is_read_including_the_prompt_cache(monkeypatch):
    provider = OpenAIProvider.__new__(OpenAIProvider)
    response = _Stub(
        choices=[_Stub(message=_Stub(content="  IRS  "))],
        usage=_Stub(prompt_tokens=1000, completion_tokens=50, total_tokens=1050,
                    prompt_tokens_details=_Stub(cached_tokens=800)),
    )
    provider._client = _Stub(chat=_Stub(completions=_Stub(
        create=lambda **kwargs: response)))

    result = provider.complete("gpt-5.6-luna", "sys", "user", 0)
    assert result.text == "IRS"          # se recortan los espacios
    assert result.input_tokens == 1000
    assert result.cached_input_tokens == 800


def test_anthropic_input_tokens_include_the_cache_so_costs_are_comparable():
    """Anthropic informa los tokens de cache aparte; OpenAI los incluye.

    Sin sumarlos, la entrada significaria cosas distintas en cada proveedor y el
    coste por pasada no seria comparable, que es justo lo que la comparativa mide.
    """
    provider = AnthropicProvider.__new__(AnthropicProvider)
    response = _Stub(
        content=[_Stub(type="text", text="IRS")],
        usage=_Stub(input_tokens=200, output_tokens=50,
                    cache_read_input_tokens=800,
                    cache_creation_input_tokens=0),
    )
    provider._client = _Stub(messages=_Stub(create=lambda **kwargs: response))

    result = provider.complete("claude-sonnet-5", "sys", "user", None)
    assert result.text == "IRS"
    assert result.input_tokens == 1000   # 200 + 800 leidos de cache
    assert result.cached_input_tokens == 800
    assert result.total_tokens == 1050


def test_anthropic_gets_the_system_prompt_in_its_own_parameter():
    """No como primer mensaje, que es donde lo pone OpenAI."""
    captured = {}
    provider = AnthropicProvider.__new__(AnthropicProvider)

    def create(**kwargs):
        captured.update(kwargs)
        return _Stub(content=[_Stub(type="text", text="IRS")],
                     usage=_Stub(input_tokens=10, output_tokens=1))

    provider._client = _Stub(messages=_Stub(create=create))
    provider.complete("claude-sonnet-5", "las instrucciones", "la peticion", None)

    assert captured["system"] == "las instrucciones"
    assert captured["messages"] == [{"role": "user", "content": "la peticion"}]
    assert captured["max_tokens"] > 0    # Anthropic lo exige
    assert "temperature" not in captured  # no se envia si no se pide


def test_anthropic_joins_only_the_text_blocks():
    provider = AnthropicProvider.__new__(AnthropicProvider)
    response = _Stub(
        content=[_Stub(type="text", text="notional: 10"),
                 _Stub(type="thinking", thinking="ignorar esto"),
                 _Stub(type="text", text="\ncurrency: EUR")],
        usage=_Stub(input_tokens=10, output_tokens=5),
    )
    provider._client = _Stub(messages=_Stub(create=lambda **kwargs: response))
    result = provider.complete("claude-sonnet-5", "s", "u", None)
    assert result.text == "notional: 10\ncurrency: EUR"


def test_an_empty_answer_is_an_error_not_an_empty_string():
    provider = AnthropicProvider.__new__(AnthropicProvider)
    response = _Stub(content=[], usage=_Stub(input_tokens=10, output_tokens=0))
    provider._client = _Stub(messages=_Stub(create=lambda **kwargs: response))
    with pytest.raises(RuntimeError, match="empty response"):
        provider.complete("claude-sonnet-5", "s", "u", None)


# --- Temperatura rechazada ------------------------------------------------

def _bad_request(message: str):
    """Error 400 del proveedor, construido como lo construye su cliente."""
    import httpx
    from openai import BadRequestError

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return BadRequestError(
        message, response=httpx.Response(400, request=request), body=None
    )


def test_a_rejected_temperature_is_raised_as_such():
    """Para que el cliente pueda reintentar sin el parametro."""
    provider = OpenAIProvider.__new__(OpenAIProvider)

    def create(**kwargs):
        raise _bad_request("Unsupported value: 'temperature' does not support 0.0")

    provider._client = _Stub(chat=_Stub(completions=_Stub(create=create)))
    with pytest.raises(TemperatureRejected):
        provider.complete("gpt-5.6-luna", "s", "u", 0)


def test_other_bad_requests_are_not_swallowed():
    """Un modelo inexistente no debe confundirse con una temperatura rechazada."""
    from openai import BadRequestError

    provider = OpenAIProvider.__new__(OpenAIProvider)

    def create(**kwargs):
        raise _bad_request("model not found")

    provider._client = _Stub(chat=_Stub(completions=_Stub(create=create)))
    with pytest.raises(BadRequestError):
        provider.complete("gpt-inexistente", "s", "u", 0)


def test_the_temperature_is_not_sent_when_it_is_not_requested():
    captured = {}
    provider = OpenAIProvider.__new__(OpenAIProvider)

    def create(**kwargs):
        captured.update(kwargs)
        return _Stub(choices=[_Stub(message=_Stub(content="IRS"))],
                     usage=_Stub(prompt_tokens=10, completion_tokens=1))

    provider._client = _Stub(chat=_Stub(completions=_Stub(create=create)))
    provider.complete("gpt-5.6-luna", "s", "u", None)
    assert "temperature" not in captured
