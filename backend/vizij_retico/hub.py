"""Shared WebSocket server for the retico backend.

One FastAPI + uvicorn server (on a background thread) is shared by the
`WebInputModule` (inbound browser audio/video → retico IUs) and the
`VizijWebSocketModule` (outbound animation events → browser). Keeping a single
hub means one port, one client set, and one place that owns the asyncio loop.

Wire protocol (see docs/03-websocket-protocol.md):
- client → server: binary frames = raw PCM audio; text `input.audio` / `input.video`
  (base64) and `control` / `hello` messages.
- server → client: JSON event envelopes broadcast to every connected client.
"""

from __future__ import annotations

import asyncio
import base64
import json
import queue
import threading
import time
from typing import Any, Callable, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect


class WebSocketHub:
    def __init__(self, host: str = "127.0.0.1", port: int = 8770) -> None:
        self.host = host
        self.port = port

        # Inbound media from the browser (thread-safe; drained by WebInputModule).
        self.audio_in: "queue.Queue[bytes]" = queue.Queue()
        self.video_in: "queue.Queue[bytes]" = queue.Queue()
        # Browser Web Speech API transcripts (drained by BrowserASRModule): {text, final}.
        self.asr_in: "queue.Queue[dict]" = queue.Queue()

        # Audio format most recently advertised by a client (browser capture).
        self.audio_rate = 16000
        self.audio_width = 2  # bytes/sample (s16le)
        self.audio_channels = 1

        self._clients: set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None

        # Set by the network to handle a "say" control message (text -> speech events).
        self.say_handler: Optional[Callable[[str], None]] = None
        # Set by the network: opens the LLM floor gate for a simulated user turn.
        self.simulate_turn_handler: Optional[Callable[[], None]] = None
        # Set by the network: switches the active ASR source at runtime.
        self.set_asr_source_handler: Optional[Callable[[str], None]] = None
        # Set by the network: switches any pipeline stage's provider (kind, id).
        self.set_provider_handler: Optional[Callable[[str, str], None]] = None
        # Set by the network: broadcasts a cue event on demand (debug harness).
        self.emit_cue_handler: Optional[Callable[[str, dict], None]] = None
        # Advertised to clients in the hello message (e.g. "fake" | "maai").
        self.mode: str = "fake"
        # Advertised to clients so the browser only runs Web Speech STT when the
        # backend is actually consuming it ("browser" | "whisper").
        self.asr_source: str = "browser"
        # Which provider each pipeline stage is currently using.
        self.active_providers: dict[str, str] = {}
        self.tts_provider: str = "gtts"
        # Descriptor of the active pipeline stages (set by the network); sent in hello so
        # the debug pipeline preview can show what's wired.
        self.pipeline: dict[str, Any] = {}

    # ---- server plumbing -------------------------------------------------

    def build_app(self) -> FastAPI:
        app = FastAPI(title="vizij-retico hub")

        # The frontend is served from a different origin in dev (Vite on :5173), and the
        # TTS routes are plain HTTP rather than the WebSocket, so they need CORS.
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # local dev tool; not exposed publicly as-is
            allow_methods=["*"],
            allow_headers=["*"],
        )

        from . import polly
        from .config import CONFIG

        polly.register_routes(app, CONFIG.polly_voice)

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "service": "vizij-retico",
                "protocol": 1,
                "clients": len(self._clients),
            }

        @app.websocket("/ws")
        async def ws(sock: WebSocket) -> None:
            await sock.accept()
            self._clients.add(sock)
            await sock.send_text(
                json.dumps(
                    {
                        "type": "hello",
                        "service": "vizij-retico",
                        "protocol": 1,
                        "mode": self.mode,
                        "asr_source": self.asr_source,
                        "pipeline": self.pipeline,
                    }
                )
            )
            try:
                while True:
                    msg = await sock.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    data_bytes = msg.get("bytes")
                    if data_bytes is not None:
                        self.audio_in.put(data_bytes)  # binary = raw PCM
                        continue
                    text = msg.get("text")
                    if text is not None:
                        self._on_text(text)
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(sock)

        return app

    def _on_text(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        typ = data.get("type")
        payload = data.get("payload", {})
        if typ == "input.audio":
            self.audio_rate = int(payload.get("sampleRate", self.audio_rate))
            self.audio_channels = int(payload.get("channels", self.audio_channels))
            b64 = payload.get("data")
            if b64:
                self.audio_in.put(base64.b64decode(b64))
        elif typ == "input.video":
            b64 = payload.get("data")
            if b64:
                self.video_in.put(base64.b64decode(b64))
        elif typ == "input.asr":
            # Browser Web Speech API transcript. Only final results feed the graph;
            # interim results are shown live in the browser panel (no round trip).
            if payload.get("final") and (payload.get("text") or "").strip():
                self.asr_in.put({"text": payload["text"], "final": True})
        elif typ == "control" and data.get("action") == "say" and self.say_handler:
            # Run TTS off the asyncio loop (gTTS makes a blocking network call).
            threading.Thread(
                target=self.say_handler, args=(data.get("text", ""),), daemon=True
            ).start()
        elif typ == "control" and data.get("action") == "emit_cue":
            # Debug harness: broadcast a cue event (nod.cue, backchannel.cue,
            # emotion.affect, …) without waiting for a model to fire it. Lets the face
            # behaviours be exercised and reviewed on demand.
            cue = data.get("cue")
            if cue and self.emit_cue_handler is not None:
                self.emit_cue_handler(str(cue), data.get("payload") or {})
        elif typ == "control" and data.get("action") == "set_provider":
            if self.set_provider_handler is not None:
                self.set_provider_handler(str(data.get("kind", "")), str(data.get("id", "")))
        elif typ == "control" and data.get("action") == "set_asr_source":
            if self.set_asr_source_handler is not None:
                self.set_asr_source_handler(str(data.get("source", "browser")))
        elif typ == "control" and data.get("action") == "simulate_user_turn":
            # Test harness: inject text as if the user just spoke it, through the full
            # graph (ASR IU -> turn gate -> LLM -> emotion -> TTS -> face). Open the floor
            # gate first so the reply fires promptly without live VAP audio.
            sim_text = (data.get("text") or "").strip()
            if sim_text:
                if self.simulate_turn_handler is not None:
                    self.simulate_turn_handler()
                # `simulated` keeps the harness working whichever ASR is active (the
                # gate always forwards simulated turns).
                self.asr_in.put({"text": sim_text, "final": True, "simulated": True})
        # other "control" / "hello" messages are accepted and ignored.

    # ---- outbound --------------------------------------------------------

    def broadcast(self, event: dict[str, Any]) -> None:
        """Thread-safe: called from retico's thread, sends on the asyncio loop."""
        loop = self._loop
        if loop is None:
            return
        text = json.dumps(event)
        for sock in list(self._clients):
            asyncio.run_coroutine_threadsafe(self._safe_send(sock, text), loop)

    async def _safe_send(self, sock: WebSocket, text: str) -> None:
        try:
            await sock.send_text(text)
        except Exception:
            self._clients.discard(sock)

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        config = uvicorn.Config(
            self.build_app(), host=self.host, port=self.port, log_level="warning"
        )
        server = uvicorn.Server(config)
        # We run off the main thread, so disable uvicorn's signal handlers.
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self._server = server

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.run_until_complete(server.serve())

        self._thread = threading.Thread(target=_run, name="vizij-ws-hub", daemon=True)
        self._thread.start()
        # Wait until the loop + server are actually up.
        for _ in range(100):
            if self._loop is not None and self._server is not None and self._server.started:
                return
            time.sleep(0.05)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=3.0)
