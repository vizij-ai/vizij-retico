import { useEffect, useMemo, useState } from "react";
import { useVizijRuntime, buildRigInputPath } from "@vizij/runtime-react";

/**
 * Step-1 developer panel. Two jobs:
 *  1. Prove the runtime/control surface end-to-end: a slider per input channel
 *     writes a value via `setInput` and moves the face.
 *  2. Discover the rig's channel map — logged to the console once ready — so we
 *     know the real gaze/pose paths and whether a head-pitch (nod) channel
 *     exists (feeds the reticoMapping in step 3).
 *
 * This whole panel is temporary and gets replaced by the real @semio/ui debug
 * panel once the retico driver lands.
 */
export function DevControls() {
  const rt = useVizijRuntime();
  const { ready, setInput, stagePoseNeutral, inputConstraints, outputPaths, faceId } = rt;

  const paths = useMemo(
    () => Object.keys(inputConstraints ?? {}).sort(),
    [inputConstraints],
  );
  const [values, setValues] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!ready) return;
    console.groupCollapsed("[vizij-retico] resolved rig channels");
    console.log("input paths (%d):", paths.length, paths);
    console.log("inputConstraints:", inputConstraints);
    console.log("output paths:", outputPaths);
    console.groupEnd();
  }, [ready, paths, inputConstraints, outputPaths]);

  if (!ready) {
    return (
      <div className="absolute right-3 top-3 rounded bg-neutral-950/80 p-3 text-xs text-neutral-200">
        loading runtime…
      </div>
    );
  }

  const onChange = (path: string, v: number) => {
    setValues((s) => ({ ...s, [path]: v }));
    // inputConstraints keys are RELATIVE; the graph reads the absolute rig path.
    // (Note: many channels only actuate via resolveFaceControls — this raw panel is
    // approximate; the driver uses resolved controls.)
    setInput(buildRigInputPath(faceId ?? "face", path), { float: v });
  };

  return (
    <div className="absolute right-0 top-0 flex h-full w-80 flex-col gap-2 overflow-auto bg-neutral-950/80 p-3 text-xs text-neutral-100 backdrop-blur">
      <div className="flex items-center justify-between">
        <span className="font-semibold">dev controls · {paths.length} inputs</span>
        <button
          className="rounded bg-neutral-700 px-2 py-1 hover:bg-neutral-600"
          onClick={() => stagePoseNeutral(true)}
        >
          neutral
        </button>
      </div>

      {paths.length === 0 && (
        <div className="opacity-70">
          No input channels resolved yet — is <code>public/assets/face.glb</code> present?
        </div>
      )}

      {paths.map((p) => {
        const c = inputConstraints[p] ?? {};
        const min = c.min ?? 0;
        const max = c.max ?? 1;
        const val = values[p] ?? c.defaultValue ?? 0;
        const step = (max - min) / 100 || 0.01;
        return (
          <label key={p} className="block">
            <span className="block truncate opacity-80" title={p}>
              {p}
            </span>
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={val}
              onChange={(e) => onChange(p, Number(e.target.value))}
              className="w-full"
            />
          </label>
        );
      })}
    </div>
  );
}
