"""Contrato de salida de los agentes, sin llamar a OpenAI."""
import shutil
from pathlib import Path

import pytest

from agent_config import load_agents_config
from llm_client import AgentOutputError, LLMClient
from settings import Settings


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    # project_root apunta a un directorio temporal para que la telemetria no
    # toque outputs/evaluations.db. El esquema se copia para poder parsear.
    (tmp_path / "protos").mkdir()
    shutil.copy(ROOT / "protos/pricing.proto", tmp_path / "protos/pricing.proto")
    instance = LLMClient(
        Settings(openai_api_key="test-key", llm_model=None),
        tmp_path, run_id="run-test", config=load_agents_config(ROOT),
    )
    return instance


def test_offcontract_classification_is_an_agent_output_error(client, monkeypatch):
    monkeypatch.setattr(client, "_call", lambda agent, user: "IRS.")
    with pytest.raises(AgentOutputError) as info:
        client.classify_product("anything")
    assert info.value.run_id == "run-test"


def test_valid_classification_passes_through(client, monkeypatch):
    monkeypatch.setattr(client, "_call", lambda agent, user: "UNSUPPORTED")
    assert client.classify_product("anything") == "UNSUPPORTED"


def test_unparseable_extraction_is_an_agent_output_error(client, monkeypatch):
    monkeypatch.setattr(client, "_call", lambda agent, user: "```\nnotional: 1\n```")
    with pytest.raises(AgentOutputError) as info:
        client.extract_irs("anything")
    assert info.value.run_id == "run-test"


def test_parseable_extraction_returns_fields(client, monkeypatch):
    monkeypatch.setattr(
        client, "_call",
        lambda agent, user: 'notional: 10000000\ncurrency: "EUR"\nfixed_leg { rate: 0.0275 }',
    )
    fields = client.extract_irs("anything")
    assert fields.currency == "EUR"
    assert fields.fixed_leg.rate is not None
    assert fields.floating_leg.index is None
