import { useCallback, useRef, useState } from "react";
import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import type { WsClient } from "../net/wsClient";

// Facial expression recognition in the browser, via MediaPipe Face Landmarker.
//
// Only the 52 blendshape coefficients are sent to the backend — never the image. That is
// a privacy property worth having (the camera feed never leaves the machine) and it also
// keeps the bandwidth trivial compared with streaming video for server-side FER.
//
// Turning those coefficients into an emotion happens on the backend, so the
// perception→affect step stays a retico module (see backend/vizij_retico/fer.py).

// MediaPipe fetches its WASM runtime and model from a CDN. That is an external runtime
// dependency; to run fully offline, vendor these into public/ and point at them instead.
const WASM_BASE =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

/** Expression is continuous; ~6 Hz is plenty for driving a face and keeps traffic small. */
const SEND_INTERVAL_MS = 160;

export function useFaceExpression(getWs: () => WsClient | null) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [frames, setFrames] = useState(0);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const landmarkerRef = useRef<FaceLandmarker | null>(null);
  const rafRef = useRef<number>(0);
  const lastSentRef = useRef(0);
  const wantRef = useRef(false);

  const stop = useCallback(() => {
    wantRef.current = false;
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    videoRef.current?.remove();
    videoRef.current = null;
    setActive(false);
    setFrames(0);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" },
      });
      streamRef.current = stream;

      // Offscreen video element: we only need frames to feed the landmarker.
      const video = document.createElement("video");
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();
      videoRef.current = video;

      if (!landmarkerRef.current) {
        const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
        landmarkerRef.current = await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
          outputFaceBlendshapes: true,
          runningMode: "VIDEO",
          numFaces: 1,
        });
      }

      wantRef.current = true;
      setActive(true);
      setLoading(false);

      const pump = () => {
        if (!wantRef.current) return;
        const landmarker = landmarkerRef.current;
        const el = videoRef.current;
        if (landmarker && el && el.readyState >= 2) {
          const now = performance.now();
          const result = landmarker.detectForVideo(el, now);
          const categories = result.faceBlendshapes?.[0]?.categories;
          if (categories && now - lastSentRef.current > SEND_INTERVAL_MS) {
            lastSentRef.current = now;
            const blendshapes: Record<string, number> = {};
            for (const c of categories) {
              // Drop near-zero coefficients — most of the 52 are idle at any moment.
              if (c.score > 0.02 && c.categoryName) blendshapes[c.categoryName] = +c.score.toFixed(3);
            }
            getWs()?.sendJSON({ type: "input.fer", payload: { blendshapes } });
            setFrames((n) => n + 1);
          }
        }
        rafRef.current = requestAnimationFrame(pump);
      };
      pump();
    } catch (err: unknown) {
      setLoading(false);
      setError(err instanceof Error ? err.message : String(err));
      stop();
    }
  }, [getWs, stop]);

  return { active, loading, error, frames, start, stop };
}
