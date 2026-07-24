from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Runtime configuration, overridable via environment variables."""

    host: str = os.environ.get("VIZIJ_RETICO_HOST", "127.0.0.1")
    # 8765 is taken by the local claude-sc gateway in this environment; use 8770.
    port: int = int(os.environ.get("VIZIJ_RETICO_PORT", "8770"))

    # LLM (OpenAI-compatible; LM Studio by default). Swap base_url/model for a cloud
    # provider later. Empty model => auto-detect the first loaded model.
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
    llm_model: str = os.environ.get("LLM_MODEL", "")
    # The trailing "/no_think" disables Qwen3's chain-of-thought so it answers directly
    # and fast (harmless text for non-Qwen models). Drop it for a cloud model if unwanted.
    llm_system: str = os.environ.get(
        "LLM_SYSTEM",
        "You are a warm, concise embodied assistant on a screen. Reply in one or two "
        "short, natural spoken sentences. No emojis or markdown. /no_think",
    )


CONFIG = Config()
