import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { Panel } from "../../ui/Panel";
import { Toolbar } from "../../ui/Toolbar";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Icon } from "../../ui/Icon";
function statusTone(s) {
    switch (s) {
        case "running": return "ok";
        case "failed": return "danger";
        case "cancelled": return "warn";
        case "completed": return "info";
        default: return "neutral";
    }
}
export default function SitePage() {
    const { fid, sid } = useParams();
    const [site, setSite] = useState(null);
    const [cameras, setCameras] = useState([]);
    const { cameraStatusOverrides } = useApp();
    const refresh = useCallback(async () => {
        if (!sid)
            return;
        const [s, cs] = await Promise.all([api.getSite(sid), api.listCamerasForSite(sid)]);
        setSite(s);
        setCameras(cs);
    }, [sid]);
    useEffect(() => {
        refresh().catch(console.error);
    }, [refresh]);
    const remove = useCallback(async (cid) => {
        await api.deleteCamera(cid);
        refresh();
    }, [refresh]);
    if (!site)
        return _jsx("div", { className: "text-text-dim text-[13px]", children: "Loading\u2026" });
    return (_jsxs(_Fragment, { children: [_jsx(Toolbar, { title: site.name, subtitle: site.address || `${cameras.length} cameras in this site`, children: _jsx(Link, { to: `/factories/${fid}/sites/${sid}/cameras/new`, children: _jsxs(Button, { tone: "primary", size: "sm", children: [_jsx(Icon, { name: "add", size: 16 }), " ADD CAMERA"] }) }) }), cameras.length === 0 ? (_jsx(Panel, { children: _jsx("div", { className: "text-text-dim text-[13px]", children: "No cameras yet." }) })) : (_jsx("div", { className: "flex flex-col gap-2", children: cameras.map((c) => {
                    const override = cameraStatusOverrides[c.id];
                    const status = override?.status ?? c.status;
                    const error = (override?.error ?? c.error) || null;
                    const isWarn = statusTone(status) === "warn";
                    return (_jsxs("div", { className: "group relative flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer bg-surface-high/30 shadow-lg backdrop-blur-xl hover:bg-surface-highest/40 transition-all duration-200 ease-in-out", children: [_jsx(Link, { to: `/factories/${fid}/sites/${sid}/cameras/${c.id}`, "aria-label": c.name, className: "absolute inset-0 rounded-lg" }), _jsxs("div", { className: "flex flex-col gap-0.5 flex-1 min-w-0", children: [_jsx("span", { className: "font-display text-[15px] text-text font-semibold truncate", children: c.name }), _jsxs("div", { className: `${isWarn ? "text-warn" : "text-accent"} text-[11px] font-mono truncate`, children: [c.kind, " \u00B7 ", c.duration_s ? `${c.duration_s.toFixed(1)}s` : "—", " \u00B7", " ", c.sampling_fps > 0 ? `${c.sampling_fps} fps` : "Auto fps", " \u00B7 frame", " ", _jsx("span", { className: "tabular-nums", children: c.last_processed_frame_idx })] }), error && (_jsx("div", { className: "text-danger text-[11px] font-mono truncate", children: error.split("\n")[0] }))] }), _jsx(Pill, { tone: statusTone(status), dot: true, children: status }), _jsx("div", { className: "relative z-10", children: _jsx(ConfirmDialog, { title: "DELETE CAMERA", body: _jsxs(_Fragment, { children: ["Delete ", _jsx("span", { className: "font-medium text-text", children: c.name }), " and all its zones, rules, and alerts? This cannot be undone."] }), confirmLabel: "DELETE", onConfirm: () => remove(c.id), trigger: _jsx(Button, { tone: "danger", size: "sm", children: "DELETE" }) }) })] }, c.id));
                }) }))] }));
}
