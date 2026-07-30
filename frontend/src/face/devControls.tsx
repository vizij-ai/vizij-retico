import { useEffect, useMemo, useState } from "react";
import { useVizijRuntime, buildRigInputPath } from "@vizij/runtime-react";

/**
 * Dev panel: search + drive any rig input channel, with live values.
 *
 * Note: many channels only actuate via resolveFaceControls (the driver uses those);
 * this raw panel writes buildRigInputPath(faceId, key) and is approximate for the
 * non-resolved channels.
 */
const MAX_ROWS = 250;

/** Text-injection tools, moved here from the top bar. They are debug affordances — they
 *  drive the pipeline without a microphone — and previously sat beside `listen` looking
 *  like part of the product. */
export interface DebugTools {
  sayText: string;
  setSayText: (v: string) => void;
  say: () => void;
  userText: string;
  setUserText: (v: string) => void;
  simulateUserTurn: () => void;
}

export function DevControls({ debug }: { debug?: DebugTools }) {
  const rt = useVizijRuntime();
  const {
    ready,
    setInput,
    animateValue,
    stagePoseNeutral,
    inputConstraints,
    outputPaths,
    faceId,
    setAnimationActive,
    isAnimationActive,
    controllers,
  } = rt;

  const allPaths = useMemo(
    () => Object.keys(inputConstraints ?? {}).sort(),
    [inputConstraints],
  );
  const [query, setQuery] = useState("");
  const [values, setValues] = useState<Record<string, number>>({});
  const [animOn, setAnimOn] = useState(false);

  useEffect(() => {
    if (!ready) return;
    setAnimOn(isAnimationActive?.() ?? false);
    console.groupCollapsed("[vizij-retico] resolved rig channels");
    console.log("input paths (%d):", allPaths.length, allPaths);
    console.log("output paths:", outputPaths);
    console.log("controllers:", controllers);
    console.groupEnd();
    // Dev aid: expose the rig's inputs + a setter for inspection from the console/tooling.
    (window as unknown as Record<string, unknown>).__vizijRig = {
      inputPaths: allPaths,
      inputConstraints,
      outputPaths,
      controllers,
      faceId,
      set: (path: string, v: number) =>
        setInput(buildRigInputPath(faceId ?? "face", path), { float: v }),
      get: (path: string) => rt.getValueSnapshot?.(buildRigInputPath(faceId ?? "face", path)),
      animate: (path: string, v: number, ms = 400) =>
        animateValue(buildRigInputPath(faceId ?? "face", path), { float: v }, {
          duration: ms / 1000,
          easing: "easeInOut",
        }),
    };
  }, [ready, allPaths, outputPaths, controllers, isAnimationActive]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? allPaths.filter((p) => p.toLowerCase().includes(q)) : allPaths;
    return list;
  }, [allPaths, query]);
  const shown = filtered.slice(0, MAX_ROWS);

  if (!ready) {
    return (
      <div className="absolute right-3 top-3 rounded bg-neutral-950/80 p-3 text-xs text-neutral-200">
        loading runtime…
      </div>
    );
  }

  const onChange = (path: string, v: number) => {
    setValues((s) => ({ ...s, [path]: v }));
    setInput(buildRigInputPath(faceId ?? "face", path), { float: v });
  };

  const toggleAnim = () => {
    const next = !animOn;
    setAnimationActive?.(next);
    setAnimOn(next);
  };

  return (
    <div className="absolute right-0 top-0 z-20 flex h-full w-96 flex-col bg-neutral-950/85 text-xs text-neutral-100 backdrop-blur">
      {debug && (
        <div className="flex flex-col gap-1.5 border-b border-neutral-800 p-3">
          <span className="text-[11px] uppercase tracking-wide text-neutral-400">
            drive the pipeline without a mic
          </span>
          <div className="flex gap-1">
            <input
              className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-800 px-2 py-1 outline-none focus:border-teal-500"
              value={debug.userText}
              onChange={(e) => debug.setUserText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && debug.simulateUserTurn()}
              placeholder="say this as the user…"
            />
            <button
              className="shrink-0 rounded bg-indigo-700 px-2 py-1 hover:bg-indigo-600"
              onClick={debug.simulateUserTurn}
              title="Inject as a user turn: ASR → turn gate → LLM → TTS → face"
            >
              user↵
            </button>
          </div>
          <div className="flex gap-1">
            <input
              className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-800 px-2 py-1 outline-none focus:border-teal-500"
              value={debug.sayText}
              onChange={(e) => debug.setSayText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && debug.say()}
              placeholder="make the agent say…"
            />
            <button
              className="shrink-0 rounded bg-teal-700 px-2 py-1 hover:bg-teal-600"
              onClick={debug.say}
              title="TTS only — skips ASR and the LLM"
            >
              say
            </button>
          </div>
        </div>
      )}
      <div className="flex flex-col gap-2 border-b border-neutral-800 p-3">
        <div className="flex items-center justify-between">
          <span className="font-semibold">dev · {filtered.length}/{allPaths.length} inputs</span>
          <div className="flex gap-1">
            <button
              className={`rounded px-2 py-1 ${animOn ? "bg-amber-600" : "bg-neutral-700"} hover:opacity-90`}
              onClick={toggleAnim}
              title="toggle the rig's built-in animation/program"
            >
              anim {animOn ? "on" : "off"}
            </button>
            <button
              className="rounded bg-neutral-700 px-2 py-1 hover:bg-neutral-600"
              onClick={() => stagePoseNeutral(true)}
            >
              neutral
            </button>
          </div>
        </div>
        <input
          autoFocus
          className="w-full rounded bg-neutral-800 px-2 py-1 text-neutral-100 outline-none"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search channels… (e.g. eye, mouth, pose_a, brow)"
        />
      </div>

      <div className="flex flex-1 flex-col gap-2 overflow-auto p-3">
        {shown.map((p) => {
          const c = inputConstraints[p] ?? {};
          const min = c.min ?? 0;
          const max = c.max ?? 1;
          const val = values[p] ?? c.defaultValue ?? 0;
          const step = (max - min) / 100 || 0.01;
          return (
            <label key={p} className="block">
              <span className="flex items-center justify-between gap-2">
                <span className="truncate opacity-80" title={p}>
                  {p}
                </span>
                <span className="shrink-0 tabular-nums opacity-60">{val.toFixed(2)}</span>
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
        {filtered.length > MAX_ROWS && (
          <div className="opacity-60">
            …{filtered.length - MAX_ROWS} more — refine the search to see them.
          </div>
        )}
        {filtered.length === 0 && <div className="opacity-60">no channels match “{query}”.</div>}
      </div>
    </div>
  );
}
