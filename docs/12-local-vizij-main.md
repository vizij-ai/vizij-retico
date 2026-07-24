# 12 · Running against vizij-web `origin/main` (Arora runtime)

The published npm `@vizij/*` packages don't drive this face: `0.2.0` won't build
(broken transitive deps) and `0.1.0` renders but its rig graph doesn't evaluate
inputs. So the frontend consumes the **`@vizij` packages built from `vizij-web`
`origin/main`** (the Arora runtime, `@vizij/runtime@2.0.0`), where inputs actuate
the face. Swap back to npm deps once fixed packages are published.

## The critical lesson (why inputs did nothing before)

Do **not** `setInput` the raw `inputConstraints` keys (e.g. `/gaze/left_right`,
`/lids/blink`). Those aren't the paths the graph reads. Drive the face through
**`resolveFaceControls(assetBundle, faceId, inputConstraints)`**:

```ts
const controls = resolveFaceControls(assetBundle, faceId, inputConstraints);
// gaze (−1..1):
setInput(controls.eyes.leftX.path, { float: mapNormalizedControlValue(controls.eyes.leftX, x) });
// blink / eyelids (0..1):
setInput(controls.blink.path, { float: mapUnitControlValue(controls.blink, v) });
```

`control.path` is the absolute rig input path (`buildRigInputPath(faceId, …)`) and
the value must be mapped via `mapNormalizedControlValue` / `mapUnitControlValue`.
This mirrors vizij-web's `tutorial-agent-face` hooks (`useMouseGaze`,
`useIdleGazeBehavior`). Verified: `turn.state` now moves the eyes end-to-end.

## One-time setup

```bash
# 1. Add a detached worktree of origin/main next to the repo (no clobber of any
#    branch you have checked out in vizij-web):
git -C /path/to/vizij-web worktree add --detach ../vizij-web-main origin/main

# 2. Build the @vizij packages (pnpm workspace; resolves the wasm deps from npm):
cd ../vizij-web-main && pnpm install && pnpm run build:packages
```

The worktree must sit at `../../vizij-web-main` relative to `frontend/` (i.e. a
sibling of `vizij-retico/`), or set `VIZIJ_WEB_MAIN=/abs/path` when running Vite.

## How the frontend wires it (`frontend/vite.config.ts`)

- `resolve.alias`: `@vizij/runtime-react` + `@vizij/render` → the built packages in
  `web-main`. Their transitive `@vizij/*` deps (runtime, animation-module,
  value-json, node-graph, utils, node-graph-authoring) resolve via web-main's own
  `node_modules`.
- `resolve.dedupe`: `react`, `react-dom`, `three`, `@react-three/fiber`,
  `@react-three/drei`, `zustand` — a single shared copy (avoids duplicate React/three).
- `server.fs.allow`: includes the web-main worktree so Vite can serve its files.
- `optimizeDeps.exclude`: the wasm-backed packages.
- `frontend/tsconfig.json` `paths` point `@vizij/runtime-react`/`@vizij/render` at
  web-main's built `.d.ts` so typecheck matches the runtime.

## Reverting to published packages (later)

When fixed `@vizij` packages ship: `npm i @vizij/runtime-react@<new> …`, then delete
the `resolve.alias`/`dedupe`, the `fs.allow` widening, and the tsconfig `paths`.
