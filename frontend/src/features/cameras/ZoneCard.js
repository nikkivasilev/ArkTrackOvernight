import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMemo, useState } from "react";
export function fmtSeconds(s) {
    if (s < 90)
        return `${Math.round(s)}s`;
    if (s < 5400)
        return `${(s / 60).toFixed(1)}m`;
    return `${(s / 3600).toFixed(1)}h`;
}
// Color a given occupancy count: 0 (empty) reads as danger, then a cool→warm
// ramp toward higher staffing. Capped so 6+ all share the top color.
function countColor(count) {
    if (count <= 0)
        return "var(--danger)";
    const ramp = ["#3a4b66", "#3f6fb0", "#4ea1ff", "#54c08a", "#66d39a", "#7fe0a8"];
    return ramp[Math.min(count - 1, ramp.length - 1)];
}
function understaffed(occ, n) {
    let lt = 0;
    for (const [k, s] of Object.entries(occ.seconds_at)) {
        if (parseInt(k, 10) < n)
            lt += s;
    }
    const pct = occ.total_s > 0 ? (100 * lt) / occ.total_s : 0;
    return { seconds: lt, pct };
}
// Activity label → color. Falls back to the neutral "unknown" swatch for any
// label without a dedicated --act-* var (e.g. sitting / on_phone), so a pie
// segment never renders as an undefined (transparent) color.
function activityColor(key) {
    return `var(--act-${key}, var(--act-unknown))`;
}
// Shared compact legend: colored dot · name · bold % · muted seconds. Grid
// columns line the % and seconds up across rows. Used beside the donut (pie)
// and below the stacked bar (occupancy in bars view).
function Legend({ items }) {
    return (_jsx("ul", { className: "zone-legend", children: items.map((it) => (_jsxs("li", { children: [_jsx("span", { className: "dot", style: { background: it.color } }), _jsx("span", { className: "nm", children: it.label }), _jsxs("span", { className: "val", children: [it.pct, "%"] }), _jsx("span", { className: "sub", children: fmtSeconds(it.seconds) })] }, it.key))) }));
}
// A donut (conic-gradient ring + hole) beside the shared legend. Segment
// proportions come from `seconds` (exact) rather than the rounded `pct`.
function BreakdownPie({ items }) {
    const total = items.reduce((s, it) => s + it.seconds, 0) || 1;
    let acc = 0;
    const stops = items.map((it) => {
        const a = (acc / total) * 360;
        acc += it.seconds;
        const b = (acc / total) * 360;
        return `${it.color} ${a.toFixed(2)}deg ${b.toFixed(2)}deg`;
    });
    return (_jsxs("div", { className: "zone-pie-wrap", children: [_jsx("div", { className: "zone-pie", style: { background: `conic-gradient(${stops.join(", ")})` } }), _jsx(Legend, { items: items })] }));
}
export function ZoneCard({ name, occ, act, view, defaultN = 1, }) {
    const [n, setN] = useState(defaultN);
    const us = understaffed(occ, n);
    const segs = useMemo(() => Object.entries(occ.seconds_at)
        .map(([k, s]) => ({ count: parseInt(k, 10), seconds: s }))
        .sort((a, b) => a.count - b.count)
        .filter((d) => d.seconds > 0), [occ]);
    const total = occ.total_s || 1;
    // What's being done in the zone — worker-weighted activity breakdown.
    const actRows = useMemo(() => {
        const pct = act?.pct ?? {};
        const secs = act?.seconds ?? {};
        return Object.entries(pct)
            .filter(([, v]) => v > 0)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => ({ key: k, pct: v, seconds: secs[k] ?? 0 }));
    }, [act]);
    // Occupancy distribution as legend/pie items (% of total observed time).
    const occItems = segs.map((d) => ({
        key: String(d.count),
        label: `${d.count} ${d.count === 1 ? "person" : "people"}`,
        pct: Math.round((100 * d.seconds) / total),
        seconds: d.seconds,
        color: countColor(d.count),
    }));
    return (_jsxs("div", { className: "rounded-lg border border-border bg-surface-high/20 p-3 mb-3", children: [_jsxs("div", { className: "flex items-center justify-between mb-2", children: [_jsx("span", { className: "text-[13px] font-medium", children: name }), _jsxs("span", { className: "text-text-dim text-[11px] font-mono", children: ["avg ", occ.avg.toFixed(2), " \u00B7 peak ", occ.peak] })] }), _jsxs("div", { className: "zone-sections", children: [actRows.length > 0 && (_jsxs("div", { className: "zone-section", children: [_jsx("h4", { children: "Activity" }), view === "pie" ? (_jsx(BreakdownPie, { items: actRows.map((a) => ({
                                    key: a.key,
                                    label: a.key,
                                    pct: a.pct,
                                    seconds: a.seconds,
                                    color: activityColor(a.key),
                                })) })) : (_jsx("div", { className: "activity-bars", children: actRows.map((a) => (_jsxs("div", { className: "activity-bar-row", children: [_jsx("span", { className: `activity-bar-name activity-${a.key}`, children: a.key }), _jsx("div", { className: "activity-bar-track", children: _jsx("div", { className: `activity-bar-fill activity-bg-${a.key}`, style: { width: `${a.pct}%` } }) }), _jsxs("span", { className: "activity-bar-pct", children: [a.pct, "%"] })] }, a.key))) }))] })), _jsxs("div", { className: "zone-section", children: [_jsx("h4", { children: "Occupancy" }), view === "pie" ? (_jsx(BreakdownPie, { items: occItems })) : (_jsxs(_Fragment, { children: [_jsx("div", { className: "stacked-bar", children: occItems.map((d) => (_jsx("div", { className: "seg", style: { width: `${(100 * d.seconds) / total}%`, background: d.color }, title: `${d.label} — ${fmtSeconds(d.seconds)}` }, d.key))) }), _jsx(Legend, { items: occItems })] })), _jsxs("div", { className: "zone-understaffed", children: [_jsx("span", { children: "understaffed (<" }), _jsxs("div", { className: "zone-stepper", children: [_jsx("button", { onClick: () => setN((v) => Math.max(1, v - 1)), children: "\u2212" }), _jsx("span", { children: n }), _jsx("button", { onClick: () => setN((v) => v + 1), children: "+" })] }), _jsx("span", { children: "people):" }), _jsx("span", { className: "font-mono text-warn", children: fmtSeconds(us.seconds) }), _jsxs("span", { className: "font-mono", children: ["(", us.pct.toFixed(0), "%)"] })] })] })] })] }));
}
