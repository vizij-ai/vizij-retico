import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";

// Note: no <StrictMode> — it double-invokes effects in dev, which double-boots
// the WASM device (and later double-registers the retico input driver).
createRoot(document.getElementById("root")!).render(<App />);
