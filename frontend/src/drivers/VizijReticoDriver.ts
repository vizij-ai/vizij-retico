// VizijReticoDriver — a registerInputDriver factory that applies retico events to
// the face. Generic dispatch over the editable reticoMapping; a small gaze base so
// transient overlays (backchannel brow flash, nod eye-dip) return to the posture set
// by turn.state. start()/stop() are idempotent (safe if the provider also invokes them).

import type { InputDriverFactory } from "@vizij/runtime-react";
import type { ReticoEvent, WsClient } from "../net/wsClient";
import {
  BACKCHANNEL,
  NOD,
  TURN_POSTURE,
  resolveChannels,
} from "./reticoMapping";

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
      },
      dispose() {
        started = false;
        unsub?.();
        unsub = null;
      },
    };
  };
}
