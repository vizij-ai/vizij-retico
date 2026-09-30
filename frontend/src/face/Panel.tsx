import { useEffect, type ReactNode } from "react";

/**
 * The one overlay treatment. Pipeline, settings and dev had drifted into three different
 * looks — a floating rounded card, a flush full-height slab, and a scrimmed modal — so
 * opening them felt like opening three unrelated things.
 *
 * They are all the same kind of object: a panel you toggle from the top bar, floating
 * over the face, dismissible without committing to anything. A scrim in particular was
 * wrong for settings: it implied a modal state to escape, when switching a provider is
 * something you do *while* watching the face react.
 */
export function Panel({
  title,
  onClose,
  width = "w-[22rem]",
  children,
  footer,
}: {
  title: ReactNode;
  onClose: () => void;
  /** Tailwind width class. Panels sit side by side, so this is their share of the row. */
  width?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <section
      className={`pointer-events-auto flex max-h-full min-h-0 ${width} min-w-0 flex-col rounded border border-neutral-800 bg-neutral-950/90 text-xs text-neutral-100 shadow-lg backdrop-blur`}
    >
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-neutral-800 px-3 py-2">
        <span className="truncate font-semibold">{title}</span>
        <button
          className="shrink-0 rounded px-1.5 py-0.5 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-100"
          onClick={onClose}
          title="Close (Esc)"
          aria-label="Close"
        >
          ✕
        </button>
      </header>
      {/* Each panel scrolls itself, so one long panel cannot push the others off-screen. */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">{children}</div>
      {footer && (
        <div className="shrink-0 border-t border-neutral-800 px-3 py-2">{footer}</div>
      )}
    </section>
  );
}

/**
 * Right-aligned row the open panels live in. A row rather than a stack because these are
 * read side by side — watching the pipeline while changing a setting is the normal case.
 * `pointer-events-none` on the container so the face stays draggable/clickable in the
 * gaps between panels.
 */
export function PanelDock({ children }: { children: ReactNode }) {
  return (
    // `bottom-3` rather than a max-height: the panels' own `max-h-full` is a percentage,
    // which only resolves against a *definite* height. With max-height alone the dev
    // panel grew to its full 11 000 px and its lower sliders were unreachable.
    <div className="pointer-events-none absolute inset-y-3 right-3 z-20 flex max-w-[calc(100%-1.5rem)] items-start gap-3">
      {children}
    </div>
  );
}
