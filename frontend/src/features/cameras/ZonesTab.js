import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { useCameraCtx } from "./CameraContext";
import PolygonSvg from "./PolygonSvg";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
export default function ZonesTab() {
    const { camera } = useCameraCtx();
    const [t, setT] = useState(0);
    const [imgUrl, setImgUrl] = useState(null);
    const [imgDims, setImgDims] = useState(null);
    const [points, setPoints] = useState([]);
    const [closed, setClosed] = useState(false);
    const [zoneName, setZoneName] = useState("");
    const [newZoneExcluded, setNewZoneExcluded] = useState(false);
    const [zones, setZones] = useState([]);
    const [err, setErr] = useState(null);
    useEffect(() => {
        setPoints([]);
        setClosed(false);
        setZoneName("");
        setErr(null);
        setImgUrl(api.frameUrl(camera.id, t));
        api.listZones(camera.id).then(setZones).catch(console.error);
    }, [camera.id]);
    useEffect(() => {
        setImgUrl(`${api.frameUrl(camera.id, t)}&_=${Date.now()}`);
    }, [t, camera.id]);
    const onImgLoad = useCallback((e) => {
        const img = e.currentTarget;
        setImgDims({ w: img.naturalWidth || 1280, h: img.naturalHeight || 720 });
    }, []);
    const save = useCallback(async () => {
        if (!closed || points.length < 3)
            return;
        setErr(null);
        try {
            const z = await api.createZone(camera.id, zoneName || `zone-${zones.length + 1}`, points, newZoneExcluded);
            setZones((prev) => [...prev, z]);
            setPoints([]);
            setClosed(false);
            setZoneName("");
            setNewZoneExcluded(false);
        }
        catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        }
    }, [camera.id, closed, points, zoneName, newZoneExcluded, zones.length]);
    const toggleExcluded = useCallback(async (zid, excluded) => {
        const updated = await api.updateZone(zid, { excluded });
        setZones((prev) => prev.map((z) => (z.id === zid ? updated : z)));
    }, []);
    const removeZone = useCallback(async (zid) => {
        await api.deleteZone(zid);
        setZones((prev) => prev.filter((z) => z.id !== zid));
    }, []);
    const duration = camera.duration_s ?? 0;
    const dimsForSvg = imgDims ?? { w: 1280, h: 720 };
    return (_jsxs(_Fragment, { children: [_jsxs(Panel, { title: "DRAW ZONE", className: "mb-3", children: [_jsx("div", { className: "text-text-dim text-[12px] mb-2", children: "Click to add vertices. Double-click to close (min 3 points). Drag vertices to adjust." }), _jsxs("div", { className: "editor-wrap", children: [imgUrl && (_jsx("img", { src: imgUrl, onLoad: onImgLoad, draggable: false, style: { maxWidth: "100%", maxHeight: "70vh" } })), imgDims && (_jsx(PolygonSvg, { width: dimsForSvg.w, height: dimsForSvg.h, points: points, onPointsChange: setPoints, closed: closed, onClose: () => setClosed(true) }))] }), _jsxs("div", { className: "flex items-center gap-2.5 mt-3", children: [_jsxs("span", { className: "text-text-dim font-mono text-[12px] tabular-nums", children: ["t=", t.toFixed(2), "s"] }), _jsx("input", { type: "range", min: 0, max: Math.max(0.001, duration), step: 0.1, value: t, onChange: (e) => setT(parseFloat(e.target.value)), className: "flex-1" }), _jsxs("span", { className: "text-text-dim font-mono text-[12px] tabular-nums", children: ["/ ", duration.toFixed(1), "s"] })] }), _jsxs("div", { className: "flex items-center gap-2 mt-3", children: [_jsx("input", { placeholder: "zone name", value: zoneName, onChange: (e) => setZoneName(e.target.value), className: "flex-1" }), _jsxs("label", { className: "flex items-center gap-1.5 text-text-dim text-[11px] tracking-[0.12em] uppercase mr-2", children: [_jsx("input", { type: "checkbox", checked: newZoneExcluded, onChange: (e) => setNewZoneExcluded(e.target.checked) }), "not monitored"] }), _jsx(Button, { tone: "ghost", size: "sm", onClick: () => { setPoints([]); setClosed(false); }, disabled: points.length === 0, children: "RESET" }), _jsx(Button, { tone: "primary", size: "sm", onClick: save, disabled: !closed, children: "SAVE ZONE" })] }), err && (_jsx("div", { className: "mt-3 text-danger text-[12px] font-mono", children: err }))] }), _jsx(Panel, { title: `ZONES (${zones.length})`, children: zones.length === 0 ? (_jsx("div", { className: "text-text-dim text-[13px]", children: "No zones yet." })) : (_jsx("div", { className: "flex flex-col gap-1.5", children: zones.map((z) => (_jsxs("div", { className: "flex items-center gap-3 px-4 py-2.5 rounded-lg border border-border bg-surface-high/20 hover:bg-surface-high/40 transition-colors", children: [_jsx("span", { className: "font-medium text-text", children: z.name }), z.excluded && _jsx(Pill, { tone: "warn", children: "not monitored" }), _jsxs("span", { className: "text-text-dim text-[11px] font-mono tabular-nums", children: [z.polygon.length, " pts"] }), _jsx("span", { className: "flex-1" }), _jsxs("label", { className: "flex items-center gap-1.5 text-text-dim text-[11px] tracking-[0.12em] uppercase", children: [_jsx("input", { type: "checkbox", checked: z.excluded, onChange: (e) => toggleExcluded(z.id, e.target.checked) }), "not monitored"] }), _jsx(Button, { tone: "danger", size: "sm", onClick: () => removeZone(z.id), children: "DELETE" })] }, z.id))) })) })] }));
}
