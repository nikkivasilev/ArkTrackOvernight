import { useCameraCtx } from "./CameraContext";
import AnalysisPanel from "./AnalysisPanel";
import ZoneOccupancyPanel from "./ZoneOccupancyPanel";

/**
 * Per-camera analysis view — historical workforce + per-zone breakdowns read
 * from the persisted metric_samples produced by the overnight batch. Replaces
 * the old live operator feed.
 */
export default function AnalysisTab() {
  const { camera } = useCameraCtx();
  return (
    <div className="flex flex-col gap-6">
      <AnalysisPanel cameraId={camera.id} />
      <ZoneOccupancyPanel cameraId={camera.id} />
    </div>
  );
}
