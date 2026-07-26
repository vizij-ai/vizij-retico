# Figures

Semio-branded [d2](https://d2lang.com) sources + rendered SVGs.

- `01_architecture.d2` — system architecture, as designed (Fig 1)
- `02_mapping.d2` — IU → WebSocket event → Vizij channel mapping (Fig 2)
- `03_visemes.d2` — client-side vs AWS Polly viseme paths (Fig 3)
- `04_pipeline.d2` — **the pipeline as built** (Fig 4). Supersedes Fig 1 where the two
  disagree: 01 is the original design, 04 is what actually runs — streaming LLM, the
  ASR gate, AffectIU, runtime-swappable providers.
- `_brand.d2` — Semio brand classes (imported by each figure via `...@_brand.d2`)

## Re-rendering

From this directory (the `...@_brand.d2` import is relative):

```bash
d2 --font-regular <path/to/Questrial-Regular.ttf> 01_architecture.d2 01_architecture.svg
```

Questrial is the brand-approved free font (Gilroy/Univia are commercial). For PNG export,
render to SVG then `rsvg-convert 01_architecture.svg -o 01_architecture.png`.

## Brand notes / d2 gotchas learned

- Colors come from `_brand.d2` classes: `primary` (teal), `secondary` (orange, = the novel
  bridge), `highlight` (yellow, = cloud/attention), `neutral` (grey), `emphasis` (bright teal),
  `group` (containers).
- **Avoid `|md ... |` block-string nodes** — this d2 build renders them collapsed/invisible. Use
  plain-text labels with `\n`.
- **No `;` inside a label** — it is a statement separator and splits the node.
- **No `{` `}` inside a label** — parsed as a map; use `<...>` instead (e.g. `poses/<emotion>`).
- Edges default to d2's blue, not the brand grey. Set them all at once with the glob
  `(** -> **)[*].style.stroke: "#555555"`, declared *before* any edge you want to
  override (the WebSocket spine, the provider links).
- An invisible container (`style.opacity: 0`) is a cheap way to force siblings onto one
  row without drawing a box around them — used to pair AffectModule/TTSModule in 04.
- Watch the aspect ratio: `direction: right` on a 4-stage pipeline rendered 8:1, which is
  unusable in print. Vertical flow with `direction: right` *inside* each band gives ~0.8:1,
  matching Fig 1.

Figures 4–6 (evaluation: latency histogram, incremental-vs-baseline timeline, viseme offset) are
generated from recorded runs at build milestone 9 — see [../09-evaluation.md](../09-evaluation.md).
