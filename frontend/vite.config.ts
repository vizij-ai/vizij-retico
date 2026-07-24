import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// Consume the @vizij packages from the locally-built vizij-web `origin/main`
// worktree (the Arora runtime, @vizij/runtime 2.0.0) instead of the broken npm
// releases. runtime-react/render are aliased to the built packages; their
// transitive @vizij deps (runtime/animation-module/value-json/node-graph/utils/
// node-graph-authoring) resolve via web-main's own node_modules. Shared peers are
// deduped so there's a single React/three copy.
//
// The worktree lives at ../../vizij-web-main (sibling of the repo); override with
// VIZIJ_WEB_MAIN. See docs/12-local-vizij-main.md. Swap back to npm deps once the
// fixed @vizij packages are published.
const WEB_MAIN = process.env.VIZIJ_WEB_MAIN ?? resolve(__dirname, "../../vizij-web-main");

const crossOriginIsolation = {
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Embedder-Policy": "require-corp",
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  assetsInclude: ["**/*.glb"],
  resolve: {
    alias: {
      "@vizij/runtime-react": resolve(WEB_MAIN, "packages/@vizij/runtime-react"),
      "@vizij/render": resolve(WEB_MAIN, "packages/@vizij/render"),
    },
    dedupe: ["react", "react-dom", "three", "@react-three/fiber", "@react-three/drei", "zustand"],
  },
  optimizeDeps: {
    // WASM-backed + linked-source packages must not be esbuild pre-bundled.
    exclude: [
      "@vizij/runtime-react",
      "@vizij/render",
      "@vizij/runtime",
      "@vizij/animation-module",
      "@vizij/node-graph",
    ],
  },
  server: {
    headers: crossOriginIsolation,
    // allow serving files from the sibling web-main worktree (+ its .pnpm store)
    fs: { allow: [resolve(__dirname, "../.."), WEB_MAIN] },
  },
  preview: { headers: crossOriginIsolation },
});
