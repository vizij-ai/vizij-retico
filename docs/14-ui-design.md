# 14. UI redesign

## Why

The interface grew by accretion: one absolutely-positioned box at `left-3 top-3` that
every new control was appended to. It now holds connection status, two primary actions,
six provider selectors, two debug inputs and two panel toggles, with no grouping and no
width constraint. That is not only untidy — it has produced two real bugs.

**Measured on the deployed app at 1280×720:**

| | |
|---|---|
| `document.body.scrollWidth` | **1806 px** against a 1280 px viewport |
| consequence | the `fer:` selector is clipped off-screen and **cannot be reached** |
| face visible at 1280×720 | **no** — the header pushes the stage below the fold |
| face visible at 1280×1100 | yes |

So the current layout has an unreachable control and a hero element that disappears on a
laptop screen. Screenshot toggles already exist and work; this is about the everyday
working experience.

## Decisions

| question | choice |
|---|---|
| the six selectors | **all in the settings drawer** — the bar keeps only conversation controls |
| pipeline panel | **overlays** the face; the face never moves or resizes |
| `say` / inject-a-turn | **into the dev panel** |
| visual style | **restructure only** — keep the dark utilitarian look, no rebrand |

Consistent set: the top bar ends up holding six things, everything else lives behind a
toggle, and the face never shifts. Good for screenshots and cheap against the deadline.

## Principles

1. **The face is the hero.** It should always be fully visible and centred in whatever
   space is left, at any window size.
2. **Separate three kinds of control.** Things you touch mid-conversation (listen, watch
   me), things you configure occasionally (the six selectors), and things that only exist
   for debugging (say, inject-a-turn). Today they look identical and sit together.
3. **The face never moves.** Panels overlay it rather than resizing the stage, so the
   framing is identical whether a panel is open or not — which is what makes screenshots
   and video comparable across shots.
4. **Nothing gets wider than the window.** Ever.

## Structure

```
┌──────────────────────────────────────────────────────────┐
│ ● retico      [ listen ] [ watch me ]   ⚙  pipeline  dev │  top bar, fixed height
├──────────────────────────────────────────────────────────┤
│                                     ┌──────────────────┐ │
│                                     │ pipeline         │ │
│               ( face )              │ heard: …         │ │
│         always centred, always      │ ▸ LLM  0.40s     │ │  overlay,
│           the same size             │ ▸ TTS            │ │  face unchanged
│                                     └──────────────────┘ │
│                          [camera]                        │
└──────────────────────────────────────────────────────────┘
```

- **Top bar** — status, the two primary actions, and the panel toggles. Only what you
  touch during a conversation.
- **Stage** — flex child with `min-h-0` so the canvas fits the remaining height instead
  of overflowing it. This is what fixes the 720 px case.
- **Pipeline panel** — overlays the stage, top-right, with its own scroll. The face is
  laid out independently of it, so opening or closing it never reflows the face.
- **Settings drawer** (the ⚙) — a slide-over holding *all six* selectors, grouped by
  pipeline stage rather than listed flat:

  | group | controls |
  |---|---|
  | Hear | asr · floor |
  | Think | llm · model |
  | Speak | tts · voice |
  | See | fer |

  Each row is `label / select / note`, where the note is the registry's own `note` field
  (currently only visible as a tooltip). Unavailable options keep their explanation.
- **Debug** — `say` and the inject-a-turn box move into the dev panel, behind the `dev`
  toggle where they belong. They are not production controls and should not sit beside
  `listen`.
- **Notices** (mic/stt/camera errors, `asrNotice`) become a small toast stack rather than
  lines that grow the header.

## Additions worth having

- **Presenter mode** — one control that hides every panel at once, leaving only the face.
  The individual toggles already allow this but it takes four clicks; the paper and the
  demo video both want it in one.
- **Keyboard**: `space` to toggle listen, `p`/`d` for the panels, `esc` to close the
  drawer. This is an instrument that gets driven repeatedly during testing.

## Files

- `frontend/src/face/FaceStage.tsx` — owns the layout; the absolute box at line ~282
  becomes the top bar plus a flex column.
- `frontend/src/face/ProviderBar.tsx` — becomes the grouped settings drawer. It already
  renders every registry kind generically, so the change is presentational; the grouping
  is a static map from kind → section.
- `frontend/src/face/PipelinePanel.tsx` — unchanged in content, re-homed into the sidebar.
- `frontend/src/face/devControls.tsx` — gains the debug inputs.
- New: a small `TopBar.tsx` and `SettingsDrawer.tsx` so `FaceStage` stops being the place
  everything accumulates. That is the actual root cause of the current state.

## Verification

- At 1280×720, 1440×900 and 1024×768: the face is fully visible and centred, and
  `document.body.scrollWidth === window.innerWidth` (no horizontal overflow) with panels
  both open and closed.
- Every provider selector is reachable and still switches (the registry refresh landed
  separately, so switching TTS must still repopulate voices).
- Presenter mode leaves only the face.
- Screenshots at each breakpoint, before and after, in the PR.
