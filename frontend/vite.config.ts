import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// Cross-origin isolation is required by the @vizij WASM runtime.
const crossOriginIsolation = {
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Embedder-Policy": "require-corp",
};

// The @vizij runtime is WASM-backed. On the published runtime-react@0.2.0 build
// the wasm engines are @vizij/orchestrator-wasm + @vizij/node-graph-wasm; they
// must NOT be esbuild pre-bundled. The renderer IS pre-bundled.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  assetsInclude: ["**/*.glb"],
  optimizeDeps: {
    exclude: ["@vizij/orchestrator-wasm", "@vizij/node-graph-wasm"],
    include: ["@vizij/render"],
  },
  server: { headers: crossOriginIsolation },
  preview: { headers: crossOriginIsolation },
});
