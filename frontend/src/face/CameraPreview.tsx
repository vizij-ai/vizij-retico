import { useEffect, useRef } from "react";
import type { ReticoEvent } from "../net/wsClient";

/**
 * Small self-view shown while the camera is on.
 *
 * Worth having beyond reassurance: when the face reads "neutral" it is otherwise
 * impossible to tell whether the model disagrees with you or your face is simply out of
 * frame. Showing the feed alongside the reading makes that immediate.
 *
 * Mirrored, because a self-view that isn't mirrored feels wrong to look at.
 */
export function CameraPreview({
  stream,
  log,
  frames,
}: {
  stream: MediaStream | null;
  log: ReticoEvent[];
  frames: number;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const el = videoRef.current;
    if (el && stream && el.srcObject !== stream) el.srcObject = stream;
  }, [stream]);

  if (!stream) return null;
  const fer = log.find((e) => e.type === "emotion.fer");

  return (
    <div className="absolute bottom-3 right-3 z-20 w-56 overflow-hidden rounded bg-neutral-950/85 text-xs text-neutral-100 backdrop-blur">
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className="block w-full -scale-x-100"
      />
      <div className="px-2 py-1.5">
        <div className="flex items-center justify-between">
          <span className="opacity-60">what the face sees</span>
          <span className="tabular-nums opacity-40">{frames}</span>
        </div>
        {fer ? (
          <div className="mt-0.5">
            <span className="text-emerald-300">{fer.payload.emotion}</span>
            <span className="opacity-70">
              {" "}
              · valence {Number(fer.payload.valence ?? 0).toFixed(2)} · arousal{" "}
              {Number(fer.payload.arousal ?? 0).toFixed(2)}
            </span>
          </div>
        ) : (
          <div className="mt-0.5 opacity-50">no reading yet…</div>
        )}
      </div>
    </div>
  );
}
