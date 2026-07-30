/**
 * vizij × retico — what this project actually is: the two systems joined.
 *
 * Both marks are the projects' own. The Vizij icon is copied from
 * `vizij-web/apps/vizij-showcase/public/assets/vizij-icon.png`; the retico mark is the
 * retico-team organisation avatar. Both downscaled to 128px, which is ample for a 20px
 * render at 3x DPI.
 *
 * The retico mark is an opaque white tile with no alpha, so it is clipped to a rounded
 * chip rather than keyed out — the artwork contains white too, so removing the
 * background would eat parts of the logo.
 */
const BASE = import.meta.env.BASE_URL;

export function BrandMark({ title }: { title?: string }) {
  return (
    <span className="flex select-none items-center gap-1.5" title={title}>
      <img
        src={`${BASE}assets/brand/vizij.png`}
        alt=""
        className="h-5 w-5 shrink-0"
        draggable={false}
      />
      <span className="text-sm font-semibold tracking-tight text-neutral-100">vizij</span>
      <span aria-hidden className="px-0.5 text-neutral-600">
        ×
      </span>
      <img
        src={`${BASE}assets/brand/retico.png`}
        alt=""
        className="h-5 w-5 shrink-0 rounded-[5px]"
        draggable={false}
      />
      <span className="text-sm font-semibold tracking-tight text-neutral-100">retico</span>
      <span className="sr-only">vizij and retico</span>
    </span>
  );
}
