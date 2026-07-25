from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Runtime configuration, overridable via environment variables."""

    host: str = os.environ.get("VIZIJ_RETICO_HOST", "127.0.0.1")
    # 8765 is taken by the local claude-sc gateway in this environment; use 8770.
    port: int = int(os.environ.get("VIZIJ_RETICO_PORT", "8770"))

    # Which ASR feeds the LLM transcript:
    #  - "browser": Web Speech API in the browser -> text over the WebSocket (default;
    #    lower latency, no local Whisper/webrtcvad, but Chrome + internet).
    #  - "whisper": retico-whisperasr transcribes the streamed audio on the backend
    #    (fully local/offline). Audio is streamed to the backend for turn-taking either way.
    asr_source: str = os.environ.get("ASR_SOURCE", "browser")

    # Which LLM provider is selected at startup ("lmstudio" | "gemini"); switchable at
    # runtime from the UI. See providers.py for the registry.
    llm_provider: str = os.environ.get("LLM_PROVIDER", "lmstudio")

    # LM Studio (OpenAI-compatible, local). Empty model => auto-detect the first loaded one.
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
    llm_model: str = os.environ.get("LLM_MODEL", "")

    # Gemini speaks the OpenAI protocol, so it's the same client with a different
    # base_url + a bearer key. The trailing slash matters (without it: 404).
    gemini_base_url: str = os.environ.get(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")

    # Base persona. Provider-specific suffixes (e.g. Qwen3's "/no_think") are appended
    # by the provider spec, so a cloud model never sees a local model's control tokens.
    llm_system: str = os.environ.get(
        "LLM_SYSTEM",
        "You are a warm, concise embodied assistant on a screen. Reply in one or two "
        "short, natural spoken sentences. No emojis or markdown.",
    )

    # TTS provider ("gtts" | "polly"). Polly also gives phoneme-timed visemes.
    tts_provider: str = os.environ.get("TTS_PROVIDER", "gtts")
    polly_voice: str = os.environ.get("POLLY_VOICE", "Joanna")


CONFIG = Config()
