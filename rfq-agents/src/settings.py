from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    llm_model: str | None


def get_settings() -> Settings:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "your_api_key_here":
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Copy .env.example to .env and set a valid key."
        )
    return Settings(
        openai_api_key=api_key,
        llm_model=os.getenv("LLM_MODEL", "").strip() or None,
    )

