import {
  VizijRuntimeProvider,
  VizijRuntimeFace,
  type VizijAssetBundle,
} from "@vizij/runtime-react";
import { DevControls } from "./devControls";

// Our own GLB, hosted under frontend/public/assets/. Replace face.glb with the
// rigged face (a Quori GLB works — see docs/10-build-plan.md).
const GLB_URL = `${import.meta.env.BASE_URL}assets/face.glb`;

const assetBundle: VizijAssetBundle = {
  namespace: "vizij-retico",
  glb: { kind: "url", src: GLB_URL, aggressiveImport: true },
  // Stage a neutral pose on load, but leave color channels alone.
  pose: { stageNeutralFilter: (_id, path) => !path.includes("/color/") },
};

export function FaceStage() {
  return (
    <VizijRuntimeProvider assetBundle={assetBundle} autostart>
      <div className="relative h-full w-full">
        <VizijRuntimeFace />
        <DevControls />
      </div>
    </VizijRuntimeProvider>
  );
}
