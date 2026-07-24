// VizijReticoDriver — applies retico events to the face using RESOLVED controls.
// The rig is driven via resolveFaceControls() control paths + value mappers
// (mapNormalizedControlValue for gaze [-1..1], mapUnitControlValue for blink [0..1]),
// exactly like vizij-web's reference app — NOT the raw inputConstraints keys.

import type { InputDriverFactory } from "@vizij/runtime-react";
import {
  mapNormalizedControlValue,
  mapUnitControlValue,
  type resolveFaceControls,
} from "@vizij/runtime-react";
import type { ReticoEvent, WsClient } from "../net/wsClient";
import { NOD, TURN_POSTURE } from "./reticoMapping";

export type FaceControls = ReturnType<typeof resolveFaceControls>;
type ScalarControl = FaceControls["eyes"]["leftX"];

export type AnimateFn = (
  path: string,
  target: { float: number },
  options?: { duration?: number; easing?: "linear" | "easeIn" | "easeOut" | "easeInOut" },
) => Promise<void>;

const clamp = (v: number, lo = -1, hi = 1) => Math.min(hi, Math.max(lo, v));

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export function createReticoDriver(
  ws: WsClient,
  controls: FaceControls,
  animate: AnimateFn,
): InputDriverFactory {
  return () => {
    let baseGaze = { x: 0, y: 0 };
    let unsub: (() => void) | null = null;
    let started = false;
    let lastState: string | null = null;
    let lastBlinkAt = 0;
    const MIN_BLINK_GAP_MS = 900;

    const animScalar = (
      control: ScalarControl,
      norm: number,
      ms: number,
      unit = false,
    ) => {
      if (!control) return;
      const value = unit
        ? mapUnitControlValue(control, Math.min(1, Math.max(0, norm)))
        : mapNormalizedControlValue(control, clamp(norm));
      void animate(control.path, { float: value }, { duration: ms / 1000, easing: "easeInOut" });
    };

    const setGaze = (x: number, y: number, ms: number) => {
      animScalar(controls.eyes.leftX, x, ms);
      animScalar(controls.eyes.rightX, x, ms);
      animScalar(controls.eyes.leftY, y, ms);
      animScalar(controls.eyes.rightY, y, ms);
    };
    const setLids = (v: number, ms: number) => {
      animScalar(controls.blink, v, ms, true);
      animScalar(controls.eyelids.leftUpper, v, ms, true);
      animScalar(controls.eyelids.rightUpper, v, ms, true);
    };
    const blinkOnce = () => {
      const now = performance.now();
      if (now - lastBlinkAt < MIN_BLINK_GAP_MS) return; // rate-limit blinks
      lastBlinkAt = now;
      setLids(1, 80);
      window.setTimeout(() => setLids(0, 120), 90);
    };

    const onTurn = (e: ReticoEvent) => {
      const state = e.payload.state;
      // turn.state arrives many times/sec in maai mode — only react to TRANSITIONS,
      // otherwise the posture (and its blink) re-fire every frame.
      if (state === lastState) return;
      lastState = state;
      const p = TURN_POSTURE[state];
      if (!p) return;
      baseGaze = p.gaze;
      setGaze(baseGaze.x, baseGaze.y, p.durationMs);
      if (p.blink) blinkOnce();
    };
    const onBackchannel = () => blinkOnce(); // no brow/head on this rig → blink acknowledges
    const onNod = (e: ReticoEvent) => {
      const count = Math.max(1, Math.round(e.payload.count ?? 1));
      const dip = (e.payload.amplitude ?? 0.7) * NOD.dip;
      let i = 0;
      const cycle = () => {
        if (i >= count) return setGaze(baseGaze.x, baseGaze.y, NOD.perCycleMs);
        i += 1;
        setGaze(baseGaze.x, baseGaze.y + dip, NOD.perCycleMs);
        window.setTimeout(() => {
          setGaze(baseGaze.x, baseGaze.y, NOD.perCycleMs);
          window.setTimeout(cycle, NOD.perCycleMs);
        }, NOD.perCycleMs);
      };
      cycle();
    };
    const onGaze = (e: ReticoEvent) => {
      baseGaze = { x: e.payload.x ?? 0, y: e.payload.y ?? 0 };
      setGaze(baseGaze.x, baseGaze.y, (e.payload.durationSeconds ?? 0.25) * 1000);
    };

    // speech: play TTS audio (mouth lip-sync deferred until the rig's mouth
    // channels are drivable; see docs). Audio is audible in both fake and maai modes.
    let audioCtx: AudioContext | null = null;
    const onSpeech = async (e: ReticoEvent) => {
      try {
        if (!audioCtx) audioCtx = new AudioContext();
        if (audioCtx.state === "suspended") await audioCtx.resume();
        const buf = await audioCtx.decodeAudioData(base64ToArrayBuffer(e.payload.data));
        const src = audioCtx.createBufferSource();
        src.buffer = buf;
        src.connect(audioCtx.destination);
        src.start();
      } catch {
        /* ignore */
      }
    };

    const dispatch = (e: ReticoEvent) => {
      switch (e.type) {
        case "turn.state":
          return onTurn(e);
        case "backchannel.cue":
          return onBackchannel();
        case "nod.cue":
          return onNod(e);
        case "gaze.intent":
          return onGaze(e);
        case "speech.audio":
          return void onSpeech(e);
        default:
          return;
      }
    };

    return {
      start() {
        if (started) return;
        started = true;
        setGaze(0, 0, 300); // camera-facing baseline
        unsub = ws.addEventListener(dispatch);
      },
      stop() {
        started = false;
        unsub?.();
        unsub = null;
        audioCtx?.close().catch(() => {});
        audioCtx = null;
      },
      dispose() {
        this.stop();
      },
    };
  };
}
