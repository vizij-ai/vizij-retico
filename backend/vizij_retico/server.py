from __future__ import annotations

import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def create_app() -> FastAPI:
    app = FastAPI(title="vizij-retico backend")

    @app.get("/health")
    async def health() -> dict[str, str | int]:
        return {"status": "ok", "service": "vizij-retico-backend", "protocol": 1}

    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        """Step-1 echo endpoint.

        Proves the frontend<->backend WebSocket handshake before step 2 replaces
        this with the real bidirectional protocol (inbound input.audio/input.video
        from the browser; outbound turn/backchannel/nod/speech/emotion/gaze events).
        """
        await sock.accept()
        await sock.send_text(
            json.dumps({"type": "hello", "service": "vizij-retico", "protocol": 1})
        )
        try:
            while True:
                msg = await sock.receive_text()
                try:
                    received: object = json.loads(msg)
                except json.JSONDecodeError:
                    received = msg
                await sock.send_text(json.dumps({"type": "echo", "received": received}))
        except WebSocketDisconnect:
            return

    return app


app = create_app()
