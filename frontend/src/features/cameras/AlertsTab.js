import { jsx as _jsx } from "react/jsx-runtime";
import { useMemo } from "react";
import { useApp } from "../../state/AppContext";
import { useCameraCtx } from "./CameraContext";
import AlertCard from "../alerts/AlertCard";
import { Panel } from "../../ui/Panel";
export default function AlertsTab() {
    const { camera } = useCameraCtx();
    const { alerts } = useApp();
    const forCamera = useMemo(() => alerts.filter((a) => a.camera_id === camera.id), [alerts, camera.id]);
    return (_jsx(Panel, { title: `ALERTS FOR THIS CAMERA (${forCamera.length})`, children: forCamera.length === 0 ? (_jsx("div", { className: "text-text-dim text-[13px]", children: "No alerts yet." })) : (_jsx("div", { className: "grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-2", children: forCamera.map((a) => (_jsx(AlertCard, { alert: a }, a.id))) })) }));
}
