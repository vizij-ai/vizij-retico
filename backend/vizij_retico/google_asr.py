"""GoogleASRModule — Google Cloud Speech-to-Text over the streamed browser audio.

The third ASR path, and the default for deployed images. It sits between the two
existing options:

- browser  — free and zero-latency, but Chrome-only and the transcript is produced
             outside the retico graph.
- whisper  — fully local, but needs torch and multi-GB weights, so it exists only in
             the `full` image.
- google   — real streaming recognition of the audio the browser is already sending,
             in any browser, with no model to load. Authenticates with ADC, exactly
             like the Vertex LLM, so a deployment needs no API key.

Incremental by construction: interim hypotheses arrive continuously, and each one
REVOKEs the previous hypothesis before ADDing the new one, then a final result COMMITs.
That is the behaviour retico's IU model is for, and unlike the browser path (which only
forwards final results) the partial hypotheses genuinely flow through the graph.
"""

from __future__ import annotations

import queue
import threading
from typing import Optional

import retico_core
from retico_core.audio import AudioIU
from retico_core.text import SpeechRecognitionIU

from .config import CONFIG

# Google closes a streaming_recognize call after ~5 minutes. That is not an error to
# report, it is a normal boundary to roll over — a conversation outlives one stream.
_STREAM_LIMIT_SECONDS = 240
# Bound the generator's wait so a silent mic can't block the thread forever.
_CHUNK_TIMEOUT = 0.5
# Errors that will not fix themselves by retrying: the API is off, or these credentials
# are not allowed to use it. Retrying those spins the thread and floods the log — the
# first version of this module produced 134 KB of identical 403s in a few seconds.
_FATAL = ("PermissionDenied", "Unauthenticated", "InvalidArgument", "NotFound")
_MAX_BACKOFF = 30.0


def available() -> tuple[bool, str]:
    """(usable, reason) — whether streaming recognition can run here."""
    try:
        from google.cloud import speech  # noqa: F401
    except ImportError:
        return False, "google-cloud-speech not installed"
    from . import gcp_auth

    ok, detail = gcp_auth.available()
    if not ok:
        return False, detail
    return True, CONFIG.google_asr_language


class GoogleASRModule(retico_core.AbstractModule):
    @staticmethod
    def name() -> str:
        return "Google ASR Module"

    @staticmethod
    def description() -> str:
        return "Streams browser audio to Google Cloud Speech-to-Text."

    @staticmethod
    def input_ius():
        return [AudioIU]

    @staticmethod
    def output_iu():
        return SpeechRecognitionIU

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._audio: queue.Queue[Optional[bytes]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # IUs added for the current utterance and not yet committed; revoked wholesale
        # when a better hypothesis arrives.
        self._live: list = []
        # Set when recognition stands down on a permanent error.
        self.error: Optional[str] = None

    # --- retico plumbing ---------------------------------------------------

    def process_update(self, update_message):
        for iu, ut in update_message:
            if ut == retico_core.UpdateType.ADD and isinstance(iu, AudioIU):
                self._audio.put(iu.raw_audio)
        return None

    def prepare_run(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._recognize_forever, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._running = False
        self._audio.put(None)  # unblock the request generator

    # --- recognition -------------------------------------------------------

    def _await_audio(self) -> Optional[bytes]:
        """Block until the mic is actually streaming, and return the first chunk.

        Opening a recognition stream before there is audio to put in it is what makes
        Google kill it with OutOfRange after its idle timeout. Waiting here means a stream
        exists only while someone is talking to us.
        """
        while self._running:
            try:
                return self._audio.get(timeout=_CHUNK_TIMEOUT)
            except queue.Empty:
                continue
        return None

    def _requests(self, speech, first: bytes):
        """Yield audio chunks until the stream should roll over or the mic goes away."""
        import time

        started = time.time()
        yield speech.StreamingRecognizeRequest(audio_content=first)
        while self._running and (time.time() - started) < _STREAM_LIMIT_SECONDS:
            try:
                chunk = self._audio.get(timeout=_CHUNK_TIMEOUT)
            except queue.Empty:
                # Note this is silence *not being sent at all* — the browser stops
                # streaming when the user stops listening. Ordinary in-speech pauses do
                # arrive as silent frames and keep the stream alive, which is what lets
                # Google detect the endpoint. Close cleanly instead of waiting to be
                # killed, and let the outer loop park until the mic comes back.
                return
            if chunk is None:
                return
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    def _recognize_forever(self) -> None:
        import time

        from google.api_core.client_options import ClientOptions
        from google.cloud import speech

        # Pin the billing/quota project explicitly. ADC otherwise supplies whatever
        # project the developer's local gcloud happens to point at — which is how this
        # first ran against an unrelated project and failed with "API not enabled".
        project = CONFIG.google_asr_project or CONFIG.vertex_project
        client = speech.SpeechClient(
            client_options=ClientOptions(quota_project_id=project) if project else None
        )
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=CONFIG.google_asr_sample_rate,
            language_code=CONFIG.google_asr_language,
            enable_automatic_punctuation=True,
            model=CONFIG.google_asr_model or None,
        )
        streaming_config = speech.StreamingRecognitionConfig(
            config=config, interim_results=True
        )

        backoff = 0.0
        while self._running:
            first = self._await_audio()
            if first is None:
                break
            try:
                responses = client.streaming_recognize(
                    config=streaming_config, requests=self._requests(speech, first)
                )
                for response in responses:
                    if not self._running:
                        break
                    for result in response.results:
                        if not result.alternatives:
                            continue
                        self._emit(
                            result.alternatives[0].transcript.strip(),
                            bool(result.is_final),
                        )
                backoff = 0.0  # a clean roll-over is not a failure
            except Exception as exc:
                if not self._running:
                    break
                kind = type(exc).__name__
                if kind == "OutOfRange":
                    # Google's idle/duration timeout. Expected punctuation between
                    # utterances, not a failure — backing off here is what previously
                    # left the module asleep for up to 30 s when speech finally started,
                    # swallowing the beginning of the turn.
                    backoff = 0.0
                    continue
                if kind in _FATAL:
                    # Log once and stand down. The provider stays switchable, so the user
                    # can fall back to browser ASR instead of watching the log fill up.
                    self.error = f"{kind}: {str(exc).splitlines()[0][:200]}"
                    print(f"[google-asr] disabled — {self.error}")
                    self._running = False
                    break
                # Transient (stream roll-over, idle timeout, network): back off and
                # re-establish rather than reconnecting in a tight loop.
                backoff = min(_MAX_BACKOFF, (backoff * 2) or 1.0)
                print(f"[google-asr] stream ended ({kind}); retrying in {backoff:.0f}s")
                time.sleep(backoff)

    def _emit(self, text: str, final: bool) -> None:
        if not text:
            return
        update = retico_core.UpdateMessage()

        # Withdraw the previous hypothesis before offering a new one. Without this the
        # downstream accumulators concatenate every revision of the sentence.
        for iu in self._live:
            update.add_iu(iu, retico_core.UpdateType.REVOKE)
        self._live = []

        words = text.split()
        prev = None
        for i, word in enumerate(words):
            iu = self.create_iu(prev)
            iu.set_asr_results([word], word, 0.0, 1.0, final and i == len(words) - 1)
            iu.simulated = False
            update.add_iu(iu, retico_core.UpdateType.ADD)
            self._live.append(iu)
            prev = iu

        if final:
            commit = self.create_iu(prev)
            commit.set_asr_results([text], text, 0.0, 1.0, True)
            commit.simulated = False
            update.add_iu(commit, retico_core.UpdateType.COMMIT)
            self._live = []

        self.append(update)
