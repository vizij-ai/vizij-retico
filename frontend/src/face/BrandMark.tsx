/**
 * vizij × retico — what this project actually is: the two systems joined.
 *
 * Both marks are the projects' own — see assets/brand/README.md for provenance.
 *
 * The retico mark ships as an opaque white avatar tile. Two variants are derived from it
 * (see assets/brand/README.md): `retico-on-dark` lifts the outline to near-white, and
 * `retico-on-light` keeps retico's own navy. Its outline is dark navy — almost the value
 * of our bar — so the on-light variant is genuinely illegible on dark and vice versa. The
 * bar is always dark, hence the default; the prop exists for docs and the paper, which
 * are on white.
 *
 * The Vizij mark needs no pair: its shapes are mid-tone and saturated, so it reads on
 * either background.
 */
const BASE = import.meta.env.BASE_URL;

export function BrandMark({
  title,
  on = "dark",
}: {
  title?: string;
  /** Background this sits on — picks the legible retico variant. */
  on?: "dark" | "light";
}) {
  return (
    <span className="flex select-none items-center gap-1.5" title={title}>
      <img
        src={`${BASE}assets/brand/vizij.png`}
        alt=""
        className="h-5 w-5 shrink-0"
        draggable={false}
      />
      <span
        className={`text-sm font-semibold tracking-tight ${
          on === "dark" ? "text-neutral-100" : "text-neutral-900"
        }`}
      >
        vizij
      </span>
      <span aria-hidden className="px-0.5 text-neutral-600">
        ×
      </span>
      <img
        src={`${BASE}assets/brand/retico-on-${on}.png`}
        alt=""
        className="h-5 w-5 shrink-0"
        draggable={false}
      />
      <span
        className={`text-sm font-semibold tracking-tight ${
          on === "dark" ? "text-neutral-100" : "text-neutral-900"
        }`}
      >
        retico
      </span>
      <span className="sr-only">vizij and retico</span>
    </span>
  );
}
