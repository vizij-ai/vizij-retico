import { useCallback, useRef, useState } from "react";
import type { WsClient } from "../net/wsClient";

// Browser-side speech-to-text via the Web Speech API (Chrome: webkitSpeechRecognition).
// Interim results are surfaced locally (for the "listening…" display); only final
// transcripts are sent to the backend as `input.asr`, where BrowserASRModule turns them
// into the same SpeechRecognitionIU stream the Whisper path produces.
//
// This is independent of useMicCapture: the recognizer opens its own mic capture, while
// useMicCapture streams raw PCM for turn-taking. Both run together when listening.

// The Web Speech API isn't in the default TS DOM lib, so type the bits we use loosely.
type SR = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
};

function getSRClass(): (new () => SR) | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function useBrowserSpeech(getWs: () => WsClient | null) {
  const supported = typeof window !== "undefined" && !!getSRClass();
  const [listening, setListening] = useState(false);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const srRef = useRef<SR | null>(null);
  const wantRef = useRef(false); // keep restarting while the user wants to listen

  const stop = useCallback(() => {
    wantRef.current = false;
    try {
      srRef.current?.stop();
    } catch {
      /* ignore */
    }
    srRef.current = null;
    setListening(false);
    setPartial("");
  }, []);

  const start = useCallback(() => {
    const SRClass = getSRClass();
    if (!SRClass) {
      setError("Web Speech API not supported in this browser (use Chrome, or ASR_SOURCE=whisper).");
      return;
    }
    const sr = new SRClass();
    sr.continuous = true;
    sr.interimResults = true;
    sr.lang = "en-US";
    sr.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const text = res[0]?.transcript ?? "";
        if (res.isFinal) {
          const final = text.trim();
          if (final) getWs()?.sendJSON({ type: "input.asr", payload: { text: final, final: true } });
        } else {
          interim += text;
        }
      }
      setPartial(interim.trim());
    };
    sr.onerror = (e: any) => {
      // "no-speech"/"aborted" are routine; surface the rest.
      if (e?.error && e.error !== "no-speech" && e.error !== "aborted") setError(String(e.error));
    };
    sr.onend = () => {
      setPartial("");
      // The API stops itself after silence; restart while the user still wants to listen.
      if (wantRef.current) {
        try {
          sr.start();
        } catch {
          /* already starting */
        }
      } else {
        setListening(false);
      }
    };
    wantRef.current = true;
    srRef.current = sr;
    try {
      sr.start();
      setListening(true);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [getWs]);

  return { supported, listening, partial, error, start, stop };
}
