import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMemo } from "react";
/**
 * Presentational breakdown of a MetricsSummary: a stacked status (rollup) bar
 * + legend, an optional avg/peak/worker-time meta line, and a by-activity
 * breakdown. Shared by the per-camera AnalysisPanel and the system-wide
 * dashboard WorkforceOverview so there's one renderer, not two copies.
 *
 * `showMeta` toggles the "avg N workers · peak M · Xs worker-time" line —
 * AnalysisPanel shows it; the dashboard overview renders its own StatReadouts
 * instead and passes showMeta={false}.
 */
// Order + color for rollup categories. Mirrors the STATUS OVERVIEW palette.
// "motion" is intentionally absent — unconfirmed motion tracks no longer
// surface as a rollup; they only suggest ROIs to D-FINE.
const ROLLUP_ORDER = ["working", "moving", "idle", "group_idle", "unclear"];
const ROLLUP_COLOR = {
    working: "var(--ru-working)",
    moving: "var(--ru-moving)",
    idle: "var(--ru-idle)",
    group_idle: "var(--ru-group_idle)",
    unclear: "var(--ru-unclear)",
};
export function fmtSeconds(s) {
    if (s < 90)
        return `${Math.round(s)}s`;
    if (s < 5400)
        return `${(s / 60).toFixed(1)}m`;
    return `${(s / 3600).toFixed(1)}h`;
}
export default function MetricsBreakdown({ metrics, showMeta = true, }) {
    const rollupRows = useMemo(() => {
        const pct = metrics?.rollup_pct ?? {};
        const secs = metrics?.rollup_seconds ?? {};
        const keys = [
            ...ROLLUP_ORDER.filter((k) => (pct[k] ?? 0) > 0),
            ...Object.keys(pct).filter((k) => !ROLLUP_ORDER.includes(k) && pct[k] > 0),
        ];
        return keys.map((k) => ({
            key: k,
            pct: pct[k] ?? 0,
            seconds: secs[k] ?? 0,
            color: ROLLUP_COLOR[k] ?? "var(--ru-unclear)",
        }));
    }, [metrics]);
    const activityRows = useMemo(() => {
        const pct = metrics?.activity_pct ?? {};
        const secs = metrics?.activity_seconds ?? {};
        return Object.entries(pct)
            .filter(([, v]) => v > 0)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => ({ key: k, pct: v, seconds: secs[k] ?? 0 }));
    }, [metrics]);
    const hasData = (metrics?.worker_seconds ?? 0) > 0;
    if (!hasData)
        return _jsx("div", { className: "hint", children: "No data for this window yet." });
    return (_jsxs(_Fragment, { children: [_jsx("div", { className: "stacked-bar", children: rollupRows.map((r) => (_jsx("div", { className: "seg", style: { width: `${r.pct}%`, background: r.color }, title: `${r.key} — ${r.pct}%` }, r.key))) }), _jsx("div", { className: "analysis-legend", children: rollupRows.map((r) => (_jsxs("div", { className: "legend-row", children: [_jsx("span", { className: "swatch", style: { background: r.color } }), _jsx("span", { className: "legend-name", children: r.key }), _jsxs("span", { className: "legend-pct", children: [r.pct, "%"] }), _jsx("span", { className: "legend-secs", children: fmtSeconds(r.seconds) })] }, r.key))) }), showMeta && (_jsxs("div", { className: "analysis-meta", children: ["avg ", metrics?.avg_headcount ?? 0, " workers \u00B7 peak", " ", metrics?.peak_headcount ?? 0, " \u00B7 ", fmtSeconds(metrics?.worker_seconds ?? 0), " ", "worker-time"] })), activityRows.length > 0 && (_jsxs(_Fragment, { children: [_jsx("h4", { children: "By activity" }), _jsx("div", { className: "activity-bars", children: activityRows.map((a) => (_jsxs("div", { className: "activity-bar-row", children: [_jsx("span", { className: `activity-bar-name activity-${a.key}`, children: a.key }), _jsx("div", { className: "activity-bar-track", children: _jsx("div", { className: `activity-bar-fill activity-bg-${a.key}`, style: { width: `${a.pct}%` } }) }), _jsxs("span", { className: "activity-bar-pct", children: [a.pct, "%"] })] }, a.key))) })] }))] }));
}
