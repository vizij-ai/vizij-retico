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


def _running_in_container() -> bool:
    """Cloud Run sets K_SERVICE; Docker leaves /.dockerenv behind."""
    if os.environ.get("K_SERVICE"):
        return True
    return os.path.exists("/.dockerenv")


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_loopback(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        return (urlparse(url).hostname or "") in _LOOPBACK_HOSTS
    except ValueError:
        return False


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
    # We can't cheaply prove a local server is up, so a reachable-looking LM Studio stays
    # selectable and errors surface on use. But in a container, loopback *is* the
    # container — there is definitively nothing there, and the first deploy showed
    # lmstudio advertised as available on Cloud Run. Only rule out that specific case, so
    # pointing LLM_BASE_URL at a real host still works from inside a container.
    lmstudio_ok = not (
        _running_in_container() and _is_loopback(CONFIG.llm_base_url)
    )
    return {
        "lmstudio": Provider(
            id="lmstudio",
            label="LM Studio (local)",
            note=(
                "OpenAI-compatible server on this machine"
                if lmstudio_ok
                else "unreachable — localhost is this container, not your machine"
            ),
            requires_key=False,
            available=lmstudio_ok,
            settings={
                "base_url": CONFIG.llm_base_url,
                "model": CONFIG.llm_model,
                "api_key": "",
                # Qwen3 otherwise answers inside its reasoning channel, leaving content
                # empty; this makes it reply directly (and ~4x faster).
                "system_suffix": " /no_think",
            },
        ),
        "vertex": _vertex_provider(),
    }


# Gemini models selectable at runtime, as (id, label, location).
#
# The location is part of the choice, not a separate setting: gemini-3.5-flash-lite is
# served only from `global` and 404s in us-central1, so picking the model necessarily
# picks where it runs. That matters for latency — measured from a laptop, the `global`
# endpoint's routing cost more than the newer model saved, but the service runs in
# us-central1 so the in-region numbers are the ones that decide. Hence the picker.
VERTEX_MODELS: list[tuple[str, str, str]] = [
    ("gemini-2.5-flash-lite", "2.5 Flash Lite · us-central1", "us-central1"),
    ("gemini-3.5-flash-lite", "3.5 Flash Lite · global", "global"),
    ("gemini-2.5-flash", "2.5 Flash · us-central1", "us-central1"),
]


def vertex_base_url(project: str, location: str) -> str:
    """OpenAI-compat base URL for a Vertex location.

    `global` is not a region: its host has no location prefix. Building the URL as
    f"{location}-aiplatform..." unconditionally yields `global-aiplatform...`, which does
    not resolve — so the newer models, which are global-only, were unreachable.
    """
    host = (
        "https://aiplatform.googleapis.com"
        if location == "global"
        else f"https://{location}-aiplatform.googleapis.com"
    )
    return f"{host}/v1beta1/projects/{project}/locations/{location}/endpoints/openapi"


def model_providers() -> dict[str, Provider]:
    """Which Gemini model the Vertex provider uses. Only meaningful when llm=vertex."""
    from . import gcp_auth

    ok, _ = gcp_auth.available()
    project = CONFIG.vertex_project or (gcp_auth.project() if ok else "")
    return {
        mid: Provider(
            id=mid,
            label=label,
            note=f"{location}{'' if project else ' · no credentials'}",
            available=bool(project),
            settings={"model": f"google/{mid}", "location": location},
        )
        for mid, label, location in VERTEX_MODELS
    }


def _vertex_provider() -> Provider:
    """Gemini via Vertex AI — the only Gemini path.

    The AI Studio endpoint (generativelanguage.googleapis.com + a static API key) was
    removed: it bills through prepayment credits that are separate from the project's
    Cloud billing account, so it fails with 429 while the key authenticates perfectly —
    a confusing failure to leave selectable. Vertex serves the same models over the same
    OpenAI protocol, bills to Cloud billing, and authenticates with ADC, so a deployment
    needs no API key secret at all.
    """
    from . import gcp_auth

    ok, detail = gcp_auth.available()
    project = CONFIG.vertex_project or (gcp_auth.project() if ok else "")
    if not project:
        ok = False
    # The active model carries its own location (3.5-flash-lite is global-only).
    bare = _ACTIVE_MODEL or CONFIG.vertex_model.split("/")[-1]
    location = _model_location(bare) or CONFIG.vertex_location
    # The OpenAI-compat surface wants the publisher prefix; _ACTIVE_MODEL holds the bare
    # id so it can be matched against VERTEX_MODELS and shown in the picker.
    model = f"google/{bare}"
    base_url = vertex_base_url(project, location)
    return Provider(
        id="vertex",
        label="Gemini (Vertex AI)",
        note=(
            f"{bare} · {location} · Cloud billing"
            if ok
            else f"no credentials — {detail}"
        ),
        requires_key=False,  # ADC, not a key
        available=ok,
        settings={
            "base_url": base_url,
            "model": model,
            "api_key": "",
            "auth": "adc",
            "system_suffix": "",
            # Gemini 2.5 thinks by default: measured 575 reasoning tokens to produce a
            # 20-token sentence, which is latency this loop cannot spend. Note that
            # reasoning_effort:"none" is rejected by this endpoint (only
            # high/low/medium/minimal), so the budget has to be zeroed explicitly.
            "extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}},
        },
    )


def tts_providers() -> dict[str, Provider]:
    polly_ok = _has_aws_credentials()
    from . import google_tts

    gtts_ok, gtts_detail = google_tts.available()
    return {
        "google": Provider(
            id="google",
            label="Google Cloud TTS",
            note=(
                f"{gtts_detail}; no key — amplitude lip-sync"
                if gtts_ok
                else f"unavailable — {gtts_detail}"
            ),
            requires_key=False,  # ADC, same credentials as Vertex and Cloud STT
            available=gtts_ok,
        ),
        "gtts": Provider(
            id="gtts",
            label="gTTS (Translate)",
            note="unofficial endpoint; accents only, amplitude lip-sync",
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
    from . import google_asr

    google_ok, google_detail = google_asr.available()
    return {
        "google": Provider(
            id="google",
            label="Google Cloud STT",
            note=(
                f"streaming recognition · {google_detail}"
                if google_ok
                else f"unavailable — {google_detail}"
            ),
            requires_key=False,  # ADC, same credentials as Vertex
            available=google_ok,
        ),
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


def fer_providers() -> dict[str, Provider]:
    """Who perceives the user's expression.

    The licences differ and that matters for deployment: MediaPipe is Apache-2.0 and runs
    in the page, EmoNet is CC BY-NC-ND (research only, non-commercial).
    """
    from . import emonet_fer

    emonet_ok = emonet_fer.available()
    return {
        "browser": Provider(
            id="browser",
            label="Browser (MediaPipe)",
            note="52 blendshapes in-page; no video leaves the browser",
        ),
        "emonet": Provider(
            id="emonet",
            label="EmoNet (server)",
            note=(
                "retico-fer, valence/arousal — research use only (CC BY-NC-ND)"
                if emonet_ok
                else "not installed — retico-fer/retico-vision, CC BY-NC-ND"
            ),
            available=emonet_ok,
        ),
    }


# Which voices each TTS provider offers. Deliberately a curated shortlist rather than
# Polly's full catalogue: this is a character's voice, and a 100-entry dropdown is worse
# for that than a handful that actually suit an embodied face. All neural-capable.
VOICES: dict[str, list[tuple[str, str]]] = {
    "polly": [
        ("Joanna", "Joanna · US, warm"),
        ("Matthew", "Matthew · US, warm"),
        ("Ruth", "Ruth · US, expressive"),
        ("Stephen", "Stephen · US, expressive"),
        ("Amy", "Amy · UK"),
        ("Brian", "Brian · UK"),
        ("Olivia", "Olivia · AU"),
        ("Aria", "Aria · NZ"),
    ],
    # Cloud TTS Neural2. language_code is derived from the name, so these must be real
    # voice ids, not labels.
    "google": [
        ("en-US-Neural2-F", "US · warm female"),
        ("en-US-Neural2-C", "US · bright female"),
        ("en-US-Neural2-D", "US · male"),
        ("en-US-Neural2-J", "US · deep male"),
        ("en-GB-Neural2-A", "UK · female"),
        ("en-GB-Neural2-B", "UK · male"),
        ("en-AU-Neural2-A", "AU · female"),
        ("en-IN-Neural2-A", "India · female"),
    ],
    # gTTS has no voices, only locales — the accent is the only thing you can pick.
    "gtts": [
        ("en", "English · US"),
        ("en-uk", "English · UK"),
        ("en-au", "English · AU"),
        ("en-in", "English · India"),
    ],
}


# Which TTS the voice list should describe. A module-level setting rather than a
# parameter because the registry factories take no arguments, and rather than reaching
# into the hub because providers.py must not depend on it.
_ACTIVE_TTS = CONFIG.tts_provider
# Selected Gemini model, as a bare id ("gemini-2.5-flash-lite"). Same pattern as
# _ACTIVE_TTS: the registry factories take no arguments, and providers.py must not
# depend on the hub.
_ACTIVE_MODEL = CONFIG.vertex_model.split("/")[-1]


def set_active_model(model_id: str) -> None:
    global _ACTIVE_MODEL
    _ACTIVE_MODEL = model_id.split("/")[-1]


def _model_location(model_id: str) -> str:
    bare = model_id.split("/")[-1]
    for mid, _label, location in VERTEX_MODELS:
        if mid == bare:
            return location
    return ""


def set_active_tts(provider_id: str) -> None:
    """Point the voice list at a different TTS. Called when the TTS provider changes."""
    global _ACTIVE_TTS
    _ACTIVE_TTS = provider_id


def default_voice(provider_id: str) -> str:
    entries = VOICES.get(provider_id) or VOICES["gtts"]
    return entries[0][0]


def voice_providers() -> dict[str, Provider]:
    """Voices for whichever TTS provider is active.

    Keyed off the active TTS rather than listing everything, because a Polly voice name
    means nothing to gTTS and vice versa — offering both at once would let you pick a
    combination that cannot work.
    """
    entries = VOICES.get(_ACTIVE_TTS) or VOICES["gtts"]
    return {
        vid: Provider(id=vid, label=label, note=f"{_ACTIVE_TTS} voice")
        for vid, label in entries
    }


def turn_providers() -> dict[str, Provider]:
    """Whether the agent waits for the floor before replying.

    This used to be decided at build time — it was the real behavioural difference
    between the `lite` and `full` images. It is a boolean, so it belongs here: with the
    VAP models present you can flip between "replies the moment you stop talking" and
    "waits until the turn model hands over the floor" mid-conversation, which is the
    clearest way to show what the turn-taking model actually buys.
    """
    vap_ok = importlib.util.find_spec("retico_maai") is not None
    return {
        "vap": Provider(
            id="vap",
            label="VAP turn-taking",
            note=(
                "wait for retico-maai to yield the floor"
                if vap_ok
                else "not installed (this is the 'lite' build)"
            ),
            available=vap_ok,
        ),
        "off": Provider(
            id="off",
            label="Reply immediately",
            note="answer as soon as a transcript commits",
        ),
    }


REGISTRY = {
    "asr": asr_providers,
    "turn": turn_providers,
    "model": model_providers,
    "voice": voice_providers,
    "fer": fer_providers,
    "llm": llm_providers,
    "tts": tts_providers,
}


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
