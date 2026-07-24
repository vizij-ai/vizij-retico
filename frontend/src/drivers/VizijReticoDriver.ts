// VizijReticoDriver — applies retico events to the face using RESOLVED controls.
// The rig is driven via resolveFaceControls() control paths + value mappers
// (mapNormalizedControlValue for gaze [-1..1], mapUnitControlValue for blink [0..1]),
// exactly like vizij-web's reference app — NOT the raw inputConstraints keys.

import type { InputDriverFactory } from "@vizij/runtime-react";
import {
  buildRigInputPath,
  mapNormalizedControlValue,
  mapUnitControlValue,
  type resolveFaceControls,
} from "@vizij/runtime-react";
import type { ReticoEvent, WsClient } from "../net/wsClient";
import {
  EMOTION,
  EMOTION_ALIASES,
  EMOTION_BLEND,
  EMOTION_POSE,
  GAZE,
  LIPSYNC,
  NOD,
  TURN_POSTURE,
} from "./reticoMapping";

export type FaceControls = ReturnType<typeof resolveFaceControls>;
type ScalarControl = FaceControls["eyes"]["leftX"];

export type AnimateFn = (
  path: string,
  target: { float: number },
  options?: { duration?: number; easing?: "linear" | "easeIn" | "easeOut" | "easeInOut" },
) => Promise<void>;

export type SetInputFn = (path: string, value: { float: number }) => void;

/** Runtime handles the driver needs beyond the resolved controls. */
export interface RigHandles {
  faceId: string;
  setInput: SetInputFn;
}

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
  rig: RigHandles,
): InputDriverFactory {
  return () => {
    let baseGaze = { x: 0, y: 0 };
    let unsub: (() => void) | null = null;
    let started = false;
    let lastState: string | null = null;
    let lastBlinkAt = 0;
    let lastTurnAt = 0;
    let idleWatch: number | null = null;
    const MIN_BLINK_GAP_MS = 900;
    const IDLE_RETURN_MS = 3500; // ease back to camera if no turn events arrive for this long

    // Absolute rig path for a raw input channel (poses, jaw, …).
    const rigPath = (p: string) => buildRigInputPath(rig.faceId, p);
    const animRig = (p: string, v: number, ms: number) =>
      void animate(rigPath(p), { float: v }, { duration: ms / 1000, easing: "easeInOut" });

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
      lastTurnAt = performance.now();
      // turn.state arrives many times/sec in maai mode — only react to TRANSITIONS,
      // otherwise the posture (and its blink) re-fire every frame.
      if (state === lastState) return;
      lastState = state;
      const p = TURN_POSTURE[state];
      if (!p) return;
      if (p.blink) blinkOnce();
      if (p.transient) {
        // Brief glance to the posture gaze, then ease back to the resting (camera) gaze
        // so we never get stuck looking away.
        setGaze(p.gaze.x, p.gaze.y, p.durationMs);
        window.setTimeout(() => setGaze(baseGaze.x, baseGaze.y, 450), p.durationMs + 300);
      } else {
        baseGaze = p.gaze;
        setGaze(baseGaze.x, baseGaze.y, p.durationMs);
      }
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

    // --- emotion: cross-fade a *blend* of the rig's composite emotion poses ----
    let currentEmotion: string | null = null; // the active blend key (null = neutral)
    let fadeTimer: number | null = null;
    const setEmotion = (name: string, intensity: number) => {
      const key = EMOTION_ALIASES[name] ?? name;
      // Resolve to a blend: an explicit entry, else an identity blend for a base pose,
      // else neutral (empty → everything fades to 0).
      const blend =
        EMOTION_BLEND[key] ?? (EMOTION_POSE[key as keyof typeof EMOTION_POSE] ? { [key]: 1 } : {});
      const amt = clamp(intensity, 0, 1);
      // Every base pose fades to its blended weight × intensity (0 if not in the blend).
      for (const [k, path] of Object.entries(EMOTION_POSE)) {
        const w = (blend as Record<string, number>)[k] ?? 0;
        animRig(path, clamp(w * amt, 0, 1), EMOTION.fadeMs);
      }
      currentEmotion = Object.keys(blend).length ? key : null;
    };
    const onEmotion = (e: ReticoEvent) => {
      if (fadeTimer !== null) {
        window.clearTimeout(fadeTimer);
        fadeTimer = null;
      }
      setEmotion(e.payload.emotion ?? "neutral", Number(e.payload.intensity ?? 0.8));
    };
    const scheduleEmotionRelease = () => {
      if (!currentEmotion) return;
      if (fadeTimer !== null) window.clearTimeout(fadeTimer);
      fadeTimer = window.setTimeout(() => {
        setEmotion("neutral", 0);
        fadeTimer = null;
      }, EMOTION.holdAfterSpeechMs);
    };

    // --- speech: play TTS audio and drive jaw_open from its amplitude ----------
    let audioCtx: AudioContext | null = null;
    const setJaw = (v: number) =>
      rig.setInput(rigPath(LIPSYNC.channel), { float: clamp(v, 0, LIPSYNC.max) });
    const onSpeech = async (e: ReticoEvent) => {
      try {
        if (!audioCtx) audioCtx = new AudioContext();
        if (audioCtx.state === "suspended") await audioCtx.resume();
        const buf = await audioCtx.decodeAudioData(base64ToArrayBuffer(e.payload.data));
        const src = audioCtx.createBufferSource();
        src.buffer = buf;
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        const data = new Uint8Array(analyser.fftSize);
        src.connect(analyser);
        analyser.connect(audioCtx.destination);

        let level = 0;
        let raf = 0;
        const pump = () => {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) {
            const s = (data[i] - 128) / 128;
            sum += s * s;
          }
          const rms = Math.sqrt(sum / data.length); // ~0..0.3 for speech
          level += (rms * LIPSYNC.gain - level) * LIPSYNC.smoothing;
          setJaw(level);
          raf = requestAnimationFrame(pump);
        };
        src.onended = () => {
          cancelAnimationFrame(raf);
          setJaw(0); // close the mouth
        };
        src.start();
        pump();
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
        case "emotion.affect":
        case "emotion.fer":
          return onEmotion(e);
        case "speech.audio":
          return void onSpeech(e);
        case "speech.end":
          return scheduleEmotionRelease();
        default:
          return;
      }
    };

    return {
      start() {
        if (started) return;
        started = true;
        baseGaze = { ...GAZE.camera };
        setGaze(baseGaze.x, baseGaze.y, 300); // camera-facing baseline
        lastTurnAt = performance.now();
        unsub = ws.addEventListener(dispatch);
        // Idle watchdog: if turn events stop (e.g. mic off), ease back to the camera
        // once instead of freezing at the last posture.
        idleWatch = window.setInterval(() => {
          if (lastState !== null && performance.now() - lastTurnAt > IDLE_RETURN_MS) {
            baseGaze = { ...GAZE.camera };
            setGaze(baseGaze.x, baseGaze.y, 600);
            lastState = null;
          }
        }, 1000);
      },
      stop() {
        started = false;
        unsub?.();
        unsub = null;
        if (idleWatch !== null) {
          window.clearInterval(idleWatch);
          idleWatch = null;
        }
        if (fadeTimer !== null) {
          window.clearTimeout(fadeTimer);
          fadeTimer = null;
        }
        setEmotion("neutral", 0); // release any held expression
        setJaw(0);
        audioCtx?.close().catch(() => {});
        audioCtx = null;
      },
      dispose() {
        this.stop();
      },
    };
  };
}
