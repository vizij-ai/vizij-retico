import { Panel } from "./Panel";
import type { ProviderRegistry } from "./PipelinePanel";

/**
 * Every provider selector, grouped by the pipeline stage it belongs to.
 *
 * These used to sit in a single row in the header, which overflowed the window at
 * 1280 px wide — the last selector was clipped off-screen and could not be clicked at
 * all. Grouping them by stage also gives the registry's `note` somewhere to live: it was
 * previously only a tooltip, so the reason an option was unavailable was invisible.
 *
 * Rendered as a plain Panel, like pipeline and dev. It was briefly a scrimmed slide-over,
 * which read as a modal — wrong, because changing a provider is something you do while
 * watching the face, not a mode you enter and leave.
 */

/** kind → section. Kinds not listed still render, under "Other", so a new backend kind
 *  never silently disappears from the UI. */
const SECTIONS: { title: string; hint: string; kinds: string[] }[] = [
  { title: "Hear", hint: "how speech becomes text", kinds: ["asr", "turn"] },
  { title: "Think", hint: "what answers", kinds: ["llm", "model"] },
  { title: "Speak", hint: "how it sounds", kinds: ["tts", "voice"] },
  { title: "See", hint: "how it reads your face", kinds: ["fer"] },
];

const KIND_LABEL: Record<string, string> = {
  asr: "Recognition",
  turn: "Floor",
  llm: "Provider",
  model: "Model",
  tts: "Synthesis",
  voice: "Voice",
  fer: "Expression",
};

export function SettingsDrawer({
  open,
  onClose,
  registry,
  active,
  busyKind,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  registry: ProviderRegistry | undefined;
  active: Record<string, string | null | undefined>;
  busyKind?: string | null;
  onSelect: (kind: string, id: string) => void;
}) {
  if (!open || !registry) return null;

  const known = new Set(SECTIONS.flatMap((s) => s.kinds));
  const extra = Object.keys(registry).filter((k) => !known.has(k));
  const sections = extra.length
    ? [...SECTIONS, { title: "Other", hint: "", kinds: extra }]
    : SECTIONS;

  const row = (kind: string) => {
    const entry = registry[kind];
    if (!entry) return null;
    const current = active[kind] ?? entry.active ?? "";
    const busy = busyKind === kind;
    const note = entry.options.find((o) => o.id === current)?.note;
    return (
      <label key={kind} className="block">
        <span className="mb-1 block text-[11px] uppercase tracking-wide text-neutral-400">
          {KIND_LABEL[kind] ?? kind}
        </span>
        <select
          className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-teal-500 disabled:opacity-50"
          value={current}
          disabled={busy}
          onChange={(e) => onSelect(kind, e.target.value)}
        >
          {entry.options.map((o) => (
            <option key={o.id} value={o.id} disabled={o.available === false}>
              {o.label}
              {o.available === false ? " — unavailable" : ""}
            </option>
          ))}
        </select>
        {/* The note explains *why* something is unavailable; previously tooltip-only. */}
        {(note || busy) && (
          <span className="mt-1 block text-[11px] leading-snug text-neutral-500">
            {busy ? "loading…" : note}
          </span>
        )}
      </label>
    );
  };

  return (
    <Panel title="settings" onClose={onClose} width="w-[20rem]">
      {sections.map((section) => {
        const rows = section.kinds.map(row).filter(Boolean);
        if (!rows.length) return null;
        return (
          <section key={section.title} className="mb-4 last:mb-0">
            <div className="mb-2 flex items-baseline gap-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-300">
                {section.title}
              </h3>
              {section.hint && (
                <span className="text-[11px] text-neutral-600">{section.hint}</span>
              )}
            </div>
            <div className="space-y-3">{rows}</div>
          </section>
        );
      })}
    </Panel>
  );
}
