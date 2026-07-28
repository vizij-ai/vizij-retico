from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Runtime configuration, overridable via environment variables."""

    # Cloud Run injects PORT and requires binding on 0.0.0.0; locally we stay on
    # loopback. (8765 is taken by the local claude-sc gateway, hence 8770.)
    host: str = os.environ.get("VIZIJ_RETICO_HOST") or (
        "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    )
    port: int = int(os.environ.get("PORT") or os.environ.get("VIZIJ_RETICO_PORT", "8770"))

    # When set, the built frontend is served from this directory by the same server, so
    # one container serves both the SPA and the WebSocket.
    static_dir: str = os.environ.get("VIZIJ_RETICO_STATIC", "")

    # Which ASR feeds the LLM transcript. Audio is streamed to the backend regardless,
    # because turn-taking needs it:
    #  - "google": Cloud Speech-to-Text on the streamed audio (default). Works in any
    #    browser, no model to load, and authenticates with the same ADC as Vertex.
    #  - "browser": Web Speech API in the browser -> text over the WebSocket. Free and
    #    fast, but Chrome-only and the transcript is produced outside the retico graph.
    #  - "whisper": retico-whisperasr on the backend, fully local/offline. Only present
    #    in the "full" build; falls back to browser elsewhere.
    asr_source: str = os.environ.get("ASR_SOURCE", "google")

    # Which FER source perceives the user: "browser" (MediaPipe blendshapes, Apache-2.0,
    # nothing leaves the page) or "emonet" (retico-fer, server-side, CC BY-NC-ND).
    fer_source: str = os.environ.get("FER_SOURCE", "browser")

    # Which LLM provider is selected at startup ("lmstudio" | "vertex"); switchable at
    # runtime from the UI. See providers.py for the registry.
    llm_provider: str = os.environ.get("LLM_PROVIDER", "lmstudio")

    # LM Studio (OpenAI-compatible, local). Empty model => auto-detect the first loaded one.
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
    llm_model: str = os.environ.get("LLM_MODEL", "")

    # Google Cloud Speech-to-Text. Same ADC credentials as Vertex, so no extra key.
    # 16 kHz LINEAR16 mono is what the browser worklet already sends.
    # Quota/billing project for STT. Defaults to vertex_project so one setting
    # covers both; ADC's own default is the developer's local gcloud project.
    google_asr_project: str = os.environ.get("GOOGLE_ASR_PROJECT", "")
    google_asr_language: str = os.environ.get("GOOGLE_ASR_LANGUAGE", "en-US")
    google_asr_sample_rate: int = int(os.environ.get("GOOGLE_ASR_SAMPLE_RATE", "16000"))
    # Empty => let the service pick. "latest_short" suits conversational turns.
    google_asr_model: str = os.environ.get("GOOGLE_ASR_MODEL", "latest_short")

    # Vertex AI: the same Gemini models and the same OpenAI protocol, but billed to the
    # project's ordinary Cloud billing account rather than AI Studio prepayment credits,
    # and authenticated with ADC instead of an API key — so a Cloud Run deployment needs
    # no secret at all. Project defaults to whatever ADC resolves (see gcp_auth.py).
    vertex_project: str = os.environ.get("VERTEX_PROJECT", "")
    vertex_location: str = os.environ.get("VERTEX_LOCATION", "us-central1")
    # The OpenAI-compat surface wants the publisher prefix.
    vertex_model: str = os.environ.get("VERTEX_MODEL", "google/gemini-2.5-flash")

    # Base persona. Provider-specific suffixes (e.g. Qwen3's "/no_think") are appended
    # by the provider spec, so a cloud model never sees a local model's control tokens.
    # The affect instruction is appended in network.py from affect.AFFECT_INSTRUCTION, so
    # the label set stays defined next to the code that parses it.
    llm_system: str = os.environ.get(
        "LLM_SYSTEM",
        "You are a warm, concise embodied assistant on a screen. Reply in one or two "
        "short, natural spoken sentences. No emojis or markdown.",
    )

    # TTS provider ("gtts" | "polly"). Polly also gives phoneme-timed visemes.
    tts_provider: str = os.environ.get("TTS_PROVIDER", "gtts")
    polly_voice: str = os.environ.get("POLLY_VOICE", "Joanna")


CONFIG = Config()
