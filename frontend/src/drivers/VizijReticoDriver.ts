// VizijReticoDriver — a registerInputDriver factory that applies retico events to
// the face. Generic dispatch over the editable reticoMapping; a small gaze base so
// transient overlays (backchannel brow flash, nod eye-dip) return to the posture set
// by turn.state. start()/stop() are idempotent (safe if the provider also invokes them).

import type { InputDriverFactory } from "@vizij/runtime-react";
import type { ReticoEvent, WsClient } from "../net/wsClient";
import {
  BACKCHANNEL,
  LIPSYNC,
  NOD,
  TURN_POSTURE,
  resolveChannels,
} from "./reticoMapping";

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

// animateValue lives on the runtime context (not InputDriverContext), so the caller
// passes it in. Signature matches @vizij/runtime-react's AnimateValueOptions loosely.
export type AnimateFn = (
  path: string,
  target: { float: number },
  options?: { duration?: number; easing?: "linear" | "easeIn" | "easeOut" | "easeInOut" },
) => Promise<void>;

export function createReticoDriver(
  ws: WsClient,
  inputPaths: string[],
  animate: AnimateFn,
): InputDriverFactory {
  return (ctx) => {
    const ch = resolveChannels(inputPaths);
    let baseGaze = { x: 0, y: 0 };
    let baseBrow = 0;
    let unsub: (() => void) | null = null;
    let started = false;

    const setF = (path: string | undefined, v: number, ms?: number) => {
      if (!path) return;
      if (ms && ms > 0) {
        void animate(path, { float: v }, { duration: ms / 1000, easing: "easeInOut" });
      } else {
        ctx.setInput(path, { float: v });
      }
    };
    const setGaze = (x: number, y: number, ms: number) => {
      setF(ch.gazeX, x, ms);
      setF(ch.gazeY, y, ms);
    };
    const setBrow = (v: number, ms: number) => ch.brow.forEach((p) => setF(p, v, ms));
    const blink = () => {
      if (!ch.blink) return;
      const path = ch.blink;
      void animate(path, { float: 1 }, { duration: 0.08 }).then(() =>
        animate(path, { float: 0 }, { duration: 0.12 }),
      );
    };

    const onTurn = (e: ReticoEvent) => {
      const p = TURN_POSTURE[e.payload.state];
      if (!p) return;
      baseGaze = p.gaze;
      baseBrow = p.browRaise;
      setGaze(baseGaze.x, baseGaze.y, p.durationMs);
      setBrow(baseBrow, p.durationMs);
      if (p.blink) blink();
    };
    const onBackchannel = (e: ReticoEvent) => {
      const amp = Math.min(1, e.payload.intensity ?? 0.5) * BACKCHANNEL.browRaise;
      setBrow(Math.max(baseBrow, amp), BACKCHANNEL.upMs);
      setTimeout(() => setBrow(baseBrow, BACKCHANNEL.downMs), BACKCHANNEL.upMs);
    };
    const onNod = (e: ReticoEvent) => {
      const count = Math.max(1, Math.round(e.payload.count ?? 1));
      const dip = (e.payload.amplitude ?? 0.7) * NOD.dip;
      let i = 0;
      const cycle = () => {
        if (i >= count) {
          setGaze(baseGaze.x, baseGaze.y, NOD.perCycleMs);
          return;
        }
        i += 1;
        setGaze(baseGaze.x, baseGaze.y + dip, NOD.perCycleMs); // eyes dip (no head channel)
        setTimeout(() => {
          setGaze(baseGaze.x, baseGaze.y, NOD.perCycleMs);
          setTimeout(cycle, NOD.perCycleMs);
        }, NOD.perCycleMs);
      };
      cycle();
    };
    const onGaze = (e: ReticoEvent) => {
      baseGaze = { x: e.payload.x ?? 0, y: e.payload.y ?? 0 };
      setGaze(baseGaze.x, baseGaze.y, (e.payload.durationSeconds ?? 0.25) * 1000);
    };

    // --- speech: play TTS audio + amplitude-driven jaw lip-sync ---
    let audioCtx: AudioContext | null = null;
    let lipTimer: ReturnType<typeof setInterval> | null = null;
    const stopLip = () => {
      if (lipTimer) clearInterval(lipTimer);
      lipTimer = null;
      if (ch.mouthOpen) ctx.setInput(ch.mouthOpen, { float: 0 });
    };
    const onSpeech = async (e: ReticoEvent) => {
      if (!ch.mouthOpen) return;
      try {
        if (!audioCtx) audioCtx = new AudioContext();
        if (audioCtx.state === "suspended") await audioCtx.resume();
        const buf = await audioCtx.decodeAudioData(base64ToArrayBuffer(e.payload.data));
        const src = audioCtx.createBufferSource();
        src.buffer = buf;
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        src.connect(analyser);
        analyser.connect(audioCtx.destination);
        const data = new Float32Array(analyser.fftSize);
        stopLip();
        lipTimer = setInterval(() => {
          analyser.getFloatTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
          const rms = Math.sqrt(sum / data.length);
          const open = Math.min(LIPSYNC.max, rms * LIPSYNC.gain);
          ctx.setInput(ch.mouthOpen!, { float: open });
        }, LIPSYNC.intervalMs);
        src.onended = stopLip;
        src.start();
      } catch {
        stopLip();
      }
    };

    const dispatch = (e: ReticoEvent) => {
      switch (e.type) {
        case "turn.state":
          return onTurn(e);
        case "backchannel.cue":
          return onBackchannel(e);
        case "nod.cue":
          return onNod(e);
        case "gaze.intent":
          return onGaze(e);
        case "speech.audio":
          void onSpeech(e);
          return;
        case "speech.end":
          return; // mouth zeroes on audio 'ended'
        default:
          return; // unknown types ignored (forward-compatible)
      }
    };

    return {
      start() {
        if (started) return;
        started = true;
        setGaze(0, 0, 300); // neutral, camera-facing baseline
        setBrow(0, 300);
        unsub = ws.addEventListener(dispatch);
      },
      stop() {
        started = false;
        unsub?.();
        unsub = null;
        stopLip();
        audioCtx?.close().catch(() => {});
        audioCtx = null;
      },
      dispose() {
        started = false;
        unsub?.();
        unsub = null;
        stopLip();
        audioCtx?.close().catch(() => {});
        audioCtx = null;
      },
    };
  };
}
