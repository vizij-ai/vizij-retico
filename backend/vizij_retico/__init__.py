"""vizij-retico backend: bridges a retico incremental-dialogue network to the
vizij-web expressive face over a bidirectional WebSocket.

Step 1 ships only a `/ws` echo server; the WebInputModule (inbound audio/video)
and VizijWebSocketModule (outbound animation events) land in step 2.
"""

__version__ = "0.1.0"
