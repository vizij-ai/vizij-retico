import { useCallback, useRef, useState } from "react";
import type { WsClient } from "../net/wsClient";

// Capture the mic at 16 kHz mono and stream int16 PCM frames to the backend over
// the shared WebSocket. Requires a secure context (http://localhost is fine; a
// LAN/remote host needs HTTPS).
export function useMicCapture(getWs: () => WsClient | null) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stop = useCallback(() => {
    ctxRef.current?.close().catch(() => {});
    ctxRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setActive(false);
  }, []);

  const start = useCallback(async () => {
    const ws = getWs();
    if (!ws) {
      setError("no websocket");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;
      const ctx = new AudioContext({ sampleRate: 16000 });
      ctxRef.current = ctx;
      await ctx.audioWorklet.addModule(`${import.meta.env.BASE_URL}pcm-worklet.js`);
      const src = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "pcm-worklet");
      node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => ws.sendAudio(e.data);
      // Route through a muted gain so the worklet is pulled without audible playback.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      src.connect(node);
      node.connect(mute);
      mute.connect(ctx.destination);
      if (ctx.state === "suspended") await ctx.resume();
      setActive(true);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      stop();
    }
  }, [getWs, stop]);

  return { active, error, start, stop };
}
