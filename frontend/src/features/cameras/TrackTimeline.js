import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { useMemo } from "react";
import { useTrackHistory } from "../../hooks/useTrackHistory";
/**
 * Per-track 60-second activity strip. One SVG row per active track, colored
 * by rollup, with a small triangular tick marking each VLM verdict change so
 * the operator can see when the model re-classified the worker.
 *
 * Empty state ("No active tracks") when no track has been seen in the last
 * GONE_S seconds (see useTrackHistory).
 */
const WINDOW_S = 60;
const VB_W = 600;
const VB_H = 12;
const ROLLUP_COLOR = {
    working: "var(--ru-working)",
    moving: "var(--ru-moving)",
    idle: "var(--ru-idle)",
    motion: "var(--ru-motion)",
    group_idle: "var(--ru-group_idle)",
    unclear: "var(--ru-unclear)",
};
function segmentsFor(h, t0) {
    if (h.samples.length === 0)
        return [];
    const segs = [];
    const endT = Math.max(t0 + WINDOW_S, h.lastSeen);
    for (let i = 0; i < h.samples.length; i++) {
        const s = h.samples[i];
        const next = i + 1 < h.samples.length ? h.samples[i + 1].t : endT;
        const start = Math.max(s.t, t0);
        const stop = Math.min(next, t0 + WINDOW_S);
        if (stop <= start)
            continue;
        const x = ((start - t0) / WINDOW_S) * VB_W;
        const w = Math.max(0.5, ((stop - start) / WINDOW_S) * VB_W);
        segs.push({
            x,
            w,
            color: ROLLUP_COLOR[s.rollup] ?? "var(--ru-unclear)",
            rollup: s.rollup,
        });
    }
    return segs;
}
function vlmTicks(h, t0) {
    const xs = [];
    let prev = undefined;
    for (const s of h.samples) {
        if (s.vlm_activity !== prev && s.vlm_activity) {
            if (s.t >= t0)
                xs.push(((s.t - t0) / WINDOW_S) * VB_W);
        }
        prev = s.vlm_activity;
    }
    return xs;
}
export default function TrackTimeline({ state }) {
    const history = useTrackHistory(state);
    const t0 = useMemo(() => (state ? state.t - WINDOW_S : 0), [state?.t]);
    const rows = useMemo(() => [...history.values()], [history]);
    return (_jsxs("section", { className: "track-timeline", children: [_jsxs("div", { className: "track-timeline-head", children: [_jsxs("h3", { children: ["Track timeline (last ", WINDOW_S, "s)"] }), _jsx("div", { className: "track-timeline-legend", children: Object.keys(ROLLUP_COLOR).map((r) => (_jsxs("span", { className: "tt-swatch-row", children: [_jsx("span", { className: "tt-swatch", style: { background: ROLLUP_COLOR[r] } }), r] }, r))) })] }), rows.length === 0 ? (_jsx("div", { className: "hint ", children: "No active tracks." })) : (_jsx("div", { className: "track-timeline-rows", children: rows.map((h) => {
                    const segs = segmentsFor(h, t0);
                    const ticks = vlmTicks(h, t0);
                    const latest = h.samples[h.samples.length - 1];
                    const latestLabel = latest?.vlm_activity || latest?.rollup || "";
                    return (_jsxs("div", { className: "tt-row", children: [_jsxs("span", { className: "tt-id", children: ["#", h.track_id] }), _jsxs("svg", { className: "tt-svg", viewBox: `0 0 ${VB_W} ${VB_H}`, preserveAspectRatio: "none", children: [segs.map((s, i) => (_jsx("rect", { x: s.x, y: 0, width: s.w, height: VB_H, fill: s.color, children: _jsx("title", { children: s.rollup }) }, i))), ticks.map((x, i) => (_jsx("polygon", { points: `${x - 3},0 ${x + 3},0 ${x},5`, fill: "#fff", stroke: "#000", strokeWidth: 0.5, vectorEffect: "non-scaling-stroke" }, `t-${i}`)))] }), _jsx("span", { className: "tt-latest", children: latestLabel })] }, h.track_id));
                }) }))] }));
}
