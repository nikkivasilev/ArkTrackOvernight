import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { useCameraState } from "../../hooks/useCameraState";
import { useCameraCtx } from "./CameraContext";
import AnalysisPanel from "./AnalysisPanel";
import ZoneOccupancyPanel from "./ZoneOccupancyPanel";
import TrackTimeline from "./TrackTimeline";
import LiveZonesOverlay from "./LiveZonesOverlay";
import { Hud } from "../../ui/Hud";
import { StatReadout } from "../../ui/StatReadout";
import { Pill } from "../../ui/Pill";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
// "motion" is no longer a public rollup — unconfirmed motion tracks now feed
// D-FINE as a suggestor only and never enter state.tracks. (See pipeline_render
// step 5.) Keep ROLLUPS in display order.
const ROLLUPS = ["working", "moving", "idle", "group_idle", "unclear"];
const ROLLUP_LABEL = {
    working: "WORKING",
    moving: "MOVING",
    idle: "IDLE",
    group_idle: "GROUP_IDLE",
    unclear: "UNCLEAR",
};
const ROLLUP_TONE = {
    working: "ok",
    moving: "accent",
    idle: "warn",
    group_idle: "neutral",
    unclear: "neutral",
};
export default function LiveTab() {
    const { camera } = useCameraCtx();
    const [streamKey, setStreamKey] = useState(0);
    const liveUrl = `${api.liveUrl(camera.id)}?_=${streamKey}`;
    const { state, wsConnected } = useCameraState(camera.id);
    const tracks = state?.tracks ?? [];
    const rollupCounts = state?.rollup_counts ?? {};
    const orphanWelders = state?.orphan_welding_count ?? 0;
    const activityCounts = useMemo(() => Object.entries(state?.activity_counts ?? {})
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1]), [state?.activity_counts]);
    const hudItems = state
        ? [
            { label: "FRAME", value: state.frame, tone: "accent" },
            { label: "T", value: `${state.t.toFixed(1)}s` },
            { label: "SRC FPS", value: state.src_fps },
            { label: "D-FINE", value: `${state.yolo_ms}ms`, tone: state.yolo_ms > 80 ? "warn" : "neutral" },
            { label: "DETS", value: state.n_dets, tone: "accent" },
            ...(state.n_phantoms > 0
                ? [{ label: "PHANTOM", value: state.n_phantoms, tone: "danger" }]
                : []),
            { label: "WS", value: wsConnected ? "LIVE" : "OFF", tone: wsConnected ? "ok" : "danger" },
        ]
        : [];
    return (_jsxs("div", { className: "dash", children: [_jsxs("div", { className: "dash-header", children: [_jsxs("div", { className: "flex items-baseline gap-3", children: [_jsx("h2", { className: "m-0 font-display text-[18px] font-semibold tracking-tight text-text", children: camera.name }), _jsx("span", { className: "font-mono text-label-caps text-text-mute uppercase", children: "live operator view" })] }), state ? (_jsx(Hud, { items: hudItems })) : (_jsx("span", { className: "text-[11px] tracking-[0.16em] text-text-dim uppercase font-mono", children: "waiting for frames\u2026" }))] }), _jsxs("div", { className: "dash-body", children: [_jsxs("div", { className: "dash-video", children: [_jsx("img", { src: liveUrl, alt: "live feed" }, liveUrl), _jsx(LiveZonesOverlay, { cameraId: camera.id }), _jsxs(Button, { tone: "ghost", size: "sm", onClick: () => setStreamKey((k) => k + 1), className: "absolute bottom-2.5 right-2.5 glass !text-text", children: [_jsx(Icon, { name: "sync", size: 14 }), " RECONNECT"] })] }), _jsx("aside", { className: "dash-side", children: _jsxs("div", { className: "dash-side-inner", children: [_jsx("h3", { className: "m-0 mb-2 font-mono text-label-caps uppercase text-accent", children: "Status" }), _jsx("div", { className: "grid grid-cols-2 gap-1.5 mb-4", children: ROLLUPS.map((r) => (_jsx(StatReadout, { label: ROLLUP_LABEL[r], value: rollupCounts[r] ?? 0, tone: ROLLUP_TONE[r], size: "sm" }, r))) }), _jsx("h3", { className: "m-0 mb-2 font-mono text-label-caps uppercase text-accent", children: "Live workers" }), _jsx("div", { className: "h-[48px] mb-4 overflow-y-auto", children: activityCounts.length === 0 && orphanWelders === 0 ? (_jsx("div", { className: "text-text-dim text-[12px]", children: "No active workers yet." })) : (_jsxs("div", { className: "flex flex-wrap gap-1 content-start", children: [activityCounts.map(([name, count]) => (_jsxs(Pill, { tone: "info", children: [name, " ", _jsx("span", { className: "font-mono tabular-nums", children: count })] }, name))), orphanWelders > 0 ? (_jsxs(Pill, { tone: "danger", title: "arc detected with no attributed worker", children: ["welding (anon)", " ", _jsx("span", { className: "font-mono tabular-nums", children: orphanWelders })] })) : null] })) }), _jsxs("h3", { className: "m-0 mb-2 font-mono text-label-caps uppercase text-accent", children: ["Tracks", " ", _jsxs("span", { className: "font-mono tabular-nums text-text", children: ["(", tracks.length, ")"] })] }), _jsx("div", { className: "relative flex-1 min-h-0 max-h-66 overflow-y-auto border border-border rounded-lg no-scrollbar", children: _jsxs("table", { className: "track-table", children: [_jsx("thead", { className: "sticky top-0 bg-surface-container z-10", children: _jsxs("tr", { children: [_jsx("th", { children: "ID" }), _jsx("th", { children: "Activity" }), _jsx("th", { children: "Conf" })] }) }), _jsx("tbody", { children: tracks.map((t) => {
                                                    const rowCls = [
                                                        `activity-${t.activity}`,
                                                        t.phantom ? "phantom" : "",
                                                        t.ghost ? "ghost" : "",
                                                        t.motion_only ? "motion-only" : "",
                                                    ].filter(Boolean).join(" ");
                                                    return (_jsxs("tr", { className: rowCls, children: [_jsx("td", { children: t.label }), _jsxs("td", { children: [t.activity, t.vlm_activity ? _jsx("span", { className: "vlm-badge", children: "vlm" }) : null, t.ghost && t.stale_s !== undefined ? (_jsxs("span", { className: "stale-badge", children: ["stale ", t.stale_s.toFixed(1), "s"] })) : null] }), _jsx("td", { children: t.conf.toFixed(2) })] }, t.track_id));
                                                }) })] }) })] }) })] }), _jsx(TrackTimeline, { state: state }), _jsx(AnalysisPanel, { cameraId: camera.id, liveMetrics: state?.metrics }), _jsx(ZoneOccupancyPanel, { cameraId: camera.id, liveMetrics: state?.metrics })] }));
}
