import type { ProviderRegistry } from "./PipelinePanel";

/**
 * Swaps the model behind each pipeline stage at runtime.
 *
 * Options come from the backend registry, which computes `available` from the
 * environment — so a provider that needs a key it doesn't have is shown but disabled,
 * with the reason in the tooltip, rather than being silently missing or failing on use.
 */
const KIND_LABEL: Record<string, string> = {
  asr: "asr",
  fer: "fer",
  llm: "llm",
  tts: "tts",
  turn: "floor",
};

export function ProviderBar({
  registry,
  active,
  busyKind,
  onSelect,
}: {
  registry: ProviderRegistry | undefined;
  active: Record<string, string | null | undefined>;
  busyKind?: string | null;
  onSelect: (kind: string, id: string) => void;
}) {
  if (!registry) return null;
  return (
    <>
      {Object.entries(registry).map(([kind, entry]) => {
        const current = active[kind] ?? entry.active ?? "";
        const busy = busyKind === kind;
        return (
          <span key={kind} className="flex items-center gap-1">
            <span className="opacity-50">{KIND_LABEL[kind] ?? kind}:</span>
            <select
              className="rounded bg-neutral-800 px-1 py-0.5 text-neutral-100 outline-none disabled:opacity-50"
              value={current}
              disabled={busy}
              onChange={(e) => onSelect(kind, e.target.value)}
            >
              {entry.options.map((o) => (
                <option
                  key={o.id}
                  value={o.id}
                  disabled={o.available === false}
                  title={o.note}
                >
                  {o.label}
                  {o.available === false ? " (unavailable)" : ""}
                </option>
              ))}
            </select>
            {busy && <span className="text-amber-300">loading…</span>}
          </span>
        );
      })}
    </>
  );
}
