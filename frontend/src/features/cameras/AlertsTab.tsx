import { useMemo } from "react";
import { useApp } from "../../state/AppContext";
import { useCameraCtx } from "./CameraContext";
import AlertCard from "../alerts/AlertCard";
import { Panel } from "../../ui/Panel";

export default function AlertsTab() {
  const { camera } = useCameraCtx();
  const { alerts } = useApp();
  const forCamera = useMemo(
    () => alerts.filter((a) => a.camera_id === camera.id),
    [alerts, camera.id]
  );

  return (
    <Panel title={`ALERTS FOR THIS CAMERA (${forCamera.length})`}>
      {forCamera.length === 0 ? (
        <div className="text-text-dim text-[13px]">No alerts yet.</div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-2">
          {forCamera.map((a) => (
            <AlertCard key={a.id} alert={a} />
          ))}
        </div>
      )}
    </Panel>
  );
}
