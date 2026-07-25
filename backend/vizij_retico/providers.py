"""Provider registry: which ASR / LLM / TTS backends exist, and how to reach them.

Every stage of the pipeline that has more than one possible implementation is described
here rather than hardcoded at its call site, so the frontend can render a selector and
the backend can switch at runtime.

`available` is computed from the environment (API keys present, credentials resolvable),
which lets the UI grey out what can't be selected instead of letting the user pick
something that will fail on first use.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import CONFIG


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    note: str = ""
    requires_key: bool = False
    available: bool = True
    # Free-form provider settings consumed by the module that implements the stage.
    settings: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        """UI-facing summary (never includes secrets)."""
        return {
            "id": self.id,
            "label": self.label,
            "note": self.note,
            "requires_key": self.requires_key,
            "available": self.available,
        }


def _has_aws_credentials() -> bool:
    """True if boto3 will be able to find credentials for Polly."""
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.environ.get("AWS_PROFILE"):
        return True
    try:  # a shared credentials file or instance role also counts
        import boto3

        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def llm_providers() -> dict[str, Provider]:
    gemini_key = CONFIG.gemini_api_key
    return {
        "lmstudio": Provider(
            id="lmstudio",
            label="LM Studio (local)",
            note="OpenAI-compatible server on this machine",
            requires_key=False,
            available=True,  # can't cheaply prove the server is up; errors surface on use
            settings={
                "base_url": CONFIG.llm_base_url,
                "model": CONFIG.llm_model,
                "api_key": "",
                # Qwen3 otherwise answers inside its reasoning channel, leaving content
                # empty; this makes it reply directly (and ~4x faster).
                "system_suffix": " /no_think",
            },
        ),
        "gemini": Provider(
            id="gemini",
            label="Gemini (cloud)",
            note="needs GEMINI_API_KEY" if not gemini_key else CONFIG.gemini_model,
            requires_key=True,
            available=bool(gemini_key),
            settings={
                "base_url": CONFIG.gemini_base_url,
                "model": CONFIG.gemini_model,
                "api_key": gemini_key,
                "system_suffix": "",
            },
        ),
    }


def tts_providers() -> dict[str, Provider]:
    polly_ok = _has_aws_credentials()
    return {
        "gtts": Provider(
            id="gtts",
            label="gTTS",
            note="no key; amplitude lip-sync only",
            available=True,
        ),
        "polly": Provider(
            id="polly",
            label="AWS Polly",
            note=CONFIG.polly_voice if polly_ok else "needs AWS credentials",
            requires_key=True,
            available=polly_ok,
            settings={"voice": CONFIG.polly_voice},
        ),
    }


def asr_providers() -> dict[str, Provider]:
    # retico-whisperasr is an optional extra — the "lite" container omits it, so the
    # option must show as unavailable there rather than failing when selected.
    whisper_ok = importlib.util.find_spec("retico_whisperasr") is not None
    return {
        "browser": Provider(
            id="browser",
            label="Browser (Web Speech)",
            note="transcribes in Chrome, sends text",
        ),
        "whisper": Provider(
            id="whisper",
            label="Whisper (local)",
            note=(
                "retico-whisperasr on the streamed audio"
                if whisper_ok
                else "not installed (this is the 'lite' build)"
            ),
            available=whisper_ok,
        ),
    }


REGISTRY = {"asr": asr_providers, "llm": llm_providers, "tts": tts_providers}


def get(kind: str, provider_id: str) -> Optional[Provider]:
    factory = REGISTRY.get(kind)
    return factory().get(provider_id) if factory else None


def describe(active: dict[str, str]) -> dict[str, Any]:
    """Full registry snapshot for the `hello` message: options + which one is active."""
    return {
        kind: {
            "active": active.get(kind),
            "options": [p.describe() for p in factory().values()],
        }
        for kind, factory in REGISTRY.items()
    }
