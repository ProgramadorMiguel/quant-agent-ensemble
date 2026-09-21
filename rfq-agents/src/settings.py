from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    llm_model: str | None
    anthropic_api_key: str = ""

    def key_for(self, provider: str) -> str:
        """Clave del proveedor, con un mensaje util cuando falta.

        No se exige tener las dos: un trabajo que solo compare modelos de un
        proveedor no deberia necesitar credenciales del otro.
        """
        key = self.anthropic_api_key if provider == "anthropic" else self.openai_api_key
        if not key:
            variable = ("ANTHROPIC_API_KEY" if provider == "anthropic"
                        else "OPENAI_API_KEY")
            raise RuntimeError(
                f"{variable} is missing, and it is needed for this model. "
                f"Add it to .env."
            )
        return key


def _clean(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value in ("", "your_api_key_here") else value


def get_settings() -> Settings:
    load_dotenv()
    openai_key = _clean(os.getenv("OPENAI_API_KEY"))
    anthropic_key = _clean(os.getenv("ANTHROPIC_API_KEY"))
    if not openai_key and not anthropic_key:
        raise RuntimeError(
            "No API key found. Copy .env.example to .env and set at least one of "
            "OPENAI_API_KEY or ANTHROPIC_API_KEY."
        )
    return Settings(
        openai_api_key=openai_key,
        anthropic_api_key=anthropic_key,
        llm_model=_clean(os.getenv("LLM_MODEL")) or None,
    )
