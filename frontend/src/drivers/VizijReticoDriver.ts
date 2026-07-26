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
  BLINK,
  EMOTION,
  EMOTION_ALIASES,
  EMOTION_BLEND,
  EMOTION_POSE,
  GAZE,
  HEAD,
  LIPSYNC,
  NOD,
  POLLY_VISEME_POSE,
  TURN_POSTURE,
  visemePosePath,
} from "./reticoMapping";

export type FaceControls = ReturnType<typeof resolveFaceControls>;
type ScalarControl = FaceControls["eyes"]["leftX"];

export type AnimateFn = (
  path: string,
  target: { float: number },
  options?: { duration?: number; easing?: "linear" | "easeIn" | "easeOut" | "easeInOut" },
) => Promise<void>;

export type SetInputFn = (path: string, value: { float: number }) => void;

/** Head pose in CSS units (degrees / pixels). */
interface HeadPose {
  pitch: number;
  yaw: number;
  roll: number;
  drop: number;
}

/** Runtime handles the driver needs beyond the resolved controls. */
export interface RigHandles {
  faceId: string;
  setInput: SetInputFn;
  /** Element wrapping the face canvas, transformed for head motion. */
  headElement?: () => HTMLElement | null;
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
    let idleBlinkTimer: number | null = null;
    const IDLE_RETURN_MS = 3500; // ease back to camera if no turn events arrive for this long

    // Absolute rig path for a raw input channel (poses, jaw, …).
    const rigPath = (p: string) => buildRigInputPath(rig.faceId, p);
    const animRig = (p: string, v: number, ms: number) =>
      void animate(rigPath(p), { float: v }, { duration: ms / 1000, easing: "easeInOut" });

    // --- head motion (compositing layer; see HEAD in reticoMapping for why) ---
    let headBusy = false;
    let tiltDeg = 0; // held while a quizzical emotion is active

    const applyHead = (
      { pitch = 0, yaw = 0, roll = tiltDeg, drop = 0 }: Partial<HeadPose>,
      ms: number,
    ) => {
      const el = rig.headElement?.();
      if (!el) return;
      el.style.transition = `transform ${ms}ms ease-in-out`;
      el.style.transform =
        `perspective(${HEAD.perspectivePx}px) translateY(${drop}px) ` +
        `rotateX(${pitch}deg) rotateY(${yaw}deg) rotateZ(${roll}deg)`;
    };
    const headRestore = (ms = HEAD.restMs) => applyHead({}, ms);

    /** Nod `count` times: drop + pitch forward, back up, repeat, then settle. */
    const headNod = (count: number) => {
      if (headBusy) return;
      headBusy = true;
      const { pitchDeg, dropPx, halfPeriodMs } = HEAD.nod;
      let i = 0;
      const down = () => {
        if (i >= count) {
          headRestore();
          headBusy = false;
          return;
        }
        i += 1;
        applyHead({ pitch: pitchDeg, drop: dropPx }, halfPeriodMs);
        window.setTimeout(() => {
          applyHead({}, halfPeriodMs);
          window.setTimeout(down, halfPeriodMs);
        }, halfPeriodMs);
      };
      down();
    };

    /** Shake side to side — a "no" gesture. Exported on the driver for future cues. */
    const headShake = () => {
      if (headBusy) return;
      headBusy = true;
      const { yawDeg, halfPeriodMs, cycles } = HEAD.shake;
      let i = 0;
      const swing = (dir: number) => {
        if (i >= cycles * 2) {
          headRestore();
          headBusy = false;
          return;
        }
        i += 1;
        applyHead({ yaw: yawDeg * dir }, halfPeriodMs);
        window.setTimeout(() => swing(-dir), halfPeriodMs);
      };
      swing(1);
    };
    void headShake;

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
      if (now - lastBlinkAt < BLINK.minGapMs) return; // rate-limit blinks
      lastBlinkAt = now;
      setLids(1, BLINK.closeMs);
      window.setTimeout(() => setLids(0, BLINK.openMs), BLINK.holdMs);
    };

    /** Spontaneous blinking, so the face stays alive between conversational cues. */
    const scheduleIdleBlink = () => {
      const { idleMinMs, idleMaxMs } = BLINK;
      const delay = idleMinMs + Math.random() * (idleMaxMs - idleMinMs);
      idleBlinkTimer = window.setTimeout(() => {
        blinkOnce();
        scheduleIdleBlink();
      }, delay);
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
    const onBackchannel = () => blinkOnce(); // brief acknowledgement
    const onNod = (e: ReticoEvent) => {
      const count = Math.max(1, Math.round(e.payload.count ?? 1));
      // A real head nod, with a small synchronized eye dip as an accent.
      headNod(count);
      const dip = (e.payload.amplitude ?? 0.7) * NOD.dip;
      setGaze(baseGaze.x, baseGaze.y + dip, NOD.perCycleMs);
      window.setTimeout(
        () => setGaze(baseGaze.x, baseGaze.y, NOD.perCycleMs),
        HEAD.nod.halfPeriodMs * 2 * count,
      );
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
      // A head tilt reads as puzzlement far more strongly than the face pose alone.
      const wantsTilt = key === "concerned" || key === "confused";
      tiltDeg = wantsTilt ? HEAD.tilt.rollDeg * amt : 0;
      if (!headBusy) applyHead({}, HEAD.tilt.ms);
    };
    /** The agent's own affect outranks mirroring, and holds while it speaks. */
    let agentAffectUntil = 0;

    const onEmotion = (e: ReticoEvent) => {
      if (fadeTimer !== null) {
        window.clearTimeout(fadeTimer);
        fadeTimer = null;
      }
      agentAffectUntil = performance.now() + EMOTION.agentHoldMs;
      setEmotion(e.payload.emotion ?? "neutral", Number(e.payload.intensity ?? 0.8));
    };

    /**
     * Empathic mirroring: reflect the user's expression back, but faintly, and only when
     * the agent isn't expressing something of its own. Mirroring at full strength reads
     * as mimicry rather than empathy, and letting it override the agent's own affect
     * would mean the face contradicts what it is saying.
     */
    const onFer = (e: ReticoEvent) => {
      if (performance.now() < agentAffectUntil) return;
      const confidence = Number(e.payload.confidence ?? 0);
      if (confidence < EMOTION.mirrorMinConfidence) return;
      setEmotion(e.payload.emotion ?? "neutral", confidence * EMOTION.mirrorScale);
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
    // Viseme lip-sync: only one viseme pose is raised at a time, so the mouth can't
    // smear into a blend of every phoneme in the utterance.
    let activeViseme: string | null = null;
    const setViseme = (poseId: string | null) => {
      if (poseId === activeViseme) return;
      if (activeViseme) animRig(visemePosePath(activeViseme), 0, LIPSYNC.visemeFadeMs);
      if (poseId) animRig(visemePosePath(poseId), 1, LIPSYNC.visemeFadeMs);
      activeViseme = poseId;
    };

    const onSpeech = (e: ReticoEvent) => {
      // Polly-style speech marks: [{time: ms, type: "viseme", value: "p"}, …].
      const marks: { t: number; pose: string | null }[] = (e.payload.visemes ?? []).map(
        (m: { time?: number; value?: string }) => ({
          t: Number(m.time) || 0,
          pose: POLLY_VISEME_POSE[String(m.value ?? "")] ?? null, // "sil" → null
        }),
      );
      const useVisemes = marks.length > 0;

      // The mouth animation runs off its own clock and starts immediately, so it is not
      // hostage to audio: if playback is blocked (autoplay policy) or decoding fails,
      // the face still speaks rather than freezing mid-utterance.
      let analyser: AnalyserNode | null = null;
      let data = new Uint8Array(0);
      let level = 0;
      let next = 0;
      let raf = 0;
      let finished = false;
      const startedAt = performance.now();

      const finish = () => {
        if (finished) return;
        finished = true;
        cancelAnimationFrame(raf);
        window.clearTimeout(guard);
        setViseme(null); // release the last phoneme
        setJaw(0); // close the mouth
      };

      const pump = () => {
        if (useVisemes) {
          // Advance to whichever mark the playhead has reached.
          const elapsed = performance.now() - startedAt;
          let pose = activeViseme;
          while (next < marks.length && marks[next].t <= elapsed) pose = marks[next++].pose;
          setViseme(pose);
          setJaw(pose ? LIPSYNC.visemeJaw : 0);
        } else if (analyser) {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) {
            const s = (data[i] - 128) / 128;
            sum += s * s;
          }
          const rms = Math.sqrt(sum / data.length); // ~0..0.3 for speech
          level += (rms * LIPSYNC.gain - level) * LIPSYNC.smoothing;
          setJaw(level);
        }
        raf = requestAnimationFrame(pump);
      };

      // Backstop: end the animation even if audio never plays (so `onended` never fires).
      const lastMark = marks.length ? marks[marks.length - 1].t : 0;
      const guard = window.setTimeout(finish, lastMark + 1500);
      pump();

      void (async () => {
        try {
          if (!audioCtx) audioCtx = new AudioContext();
          const buf = await audioCtx.decodeAudioData(base64ToArrayBuffer(e.payload.data));
          const src = audioCtx.createBufferSource();
          src.buffer = buf;
          analyser = audioCtx.createAnalyser();
          analyser.fftSize = 512;
          data = new Uint8Array(analyser.fftSize);
          src.connect(analyser);
          analyser.connect(audioCtx.destination);
          src.onended = finish;
          // Don't await resume(): a blocked AudioContext leaves it pending forever.
          if (audioCtx.state === "suspended") void audioCtx.resume();
          src.start();
          window.clearTimeout(guard);
          window.setTimeout(finish, buf.duration * 1000 + 400); // in case onended is missed
        } catch (err) {
          console.warn("[retico] speech playback failed; animating without audio", err);
        }
      })();
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
          return onEmotion(e);
        case "emotion.fer":
          return onFer(e);
        case "speech.audio":
          return onSpeech(e);
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
        headRestore(300);
        setLids(0, 120); // start with eyes open
        scheduleIdleBlink();
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
        if (idleBlinkTimer !== null) {
          window.clearTimeout(idleBlinkTimer);
          idleBlinkTimer = null;
        }
        if (fadeTimer !== null) {
          window.clearTimeout(fadeTimer);
          fadeTimer = null;
        }
        setEmotion("neutral", 0); // release any held expression
        setViseme(null);
        tiltDeg = 0;
        headBusy = false;
        headRestore(200); // never leave the head off-axis
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
