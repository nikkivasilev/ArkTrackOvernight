import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { aggregateMetrics } from "./aggregateMetrics";
import MetricsBreakdown, { fmtSeconds } from "../cameras/MetricsBreakdown";
import { Panel } from "../../ui/Panel";
import { StatReadout } from "../../ui/StatReadout";
/**
 * System-wide workforce overview for the dashboard. Fans out the per-camera
 * GET /api/cameras/{id}/metrics for every camera, aggregates the responses
 * client-side (see aggregateMetrics), and renders headline StatReadouts + the
 * shared MetricsBreakdown (status bar + activity breakdown).
 *
 * Live (10-min rolling) hits each camera's live aggregator / DB fallback;
 * Today (24h) hits the persisted metric_samples table (includes stopped
 * cameras). No backend aggregation endpoint — the fold is pure arithmetic.
 */
const WINDOWS = [
    { label: "Live", value: 600 },
    { label: "Today", value: 86400 },
];
export default function WorkforceOverview({ cameras }) {
    const [windowS, setWindowS] = useState(600);
    const [agg, setAgg] = useState(null);
    const [loading, setLoading] = useState(true);
    // Stable id list so the fetch effect doesn't re-run on every live WS
    // status-override churn (which re-creates the `cameras` array identity).
    const cameraIds = useMemo(() => cameras.map((c) => c.id).sort().join(","), [cameras]);
    useEffect(() => {
        const ids = cameraIds ? cameraIds.split(",") : [];
        if (ids.length === 0) {
            setAgg(null);
            setLoading(false);
            return;
        }
        let alive = true;
        const pull = async () => {
            const urls = ids.map((id) => windowS === 86400
                ? `/api/cameras/${id}/metrics?since=${encodeURIComponent(new Date(Date.now() - 86400000).toISOString())}&until=${encodeURIComponent(new Date().toISOString())}`
                : `/api/cameras/${id}/metrics?window_s=${windowS}`);
            const res = await Promise.allSettled(urls.map((u) => fetch(u).then((r) => (r.ok ? r.json() : null))));
            if (!alive)
                return;
            const summaries = res
                .filter((r) => r.status === "fulfilled" && r.value)
                .map((r) => r.value.metrics);
            setAgg(aggregateMetrics(summaries));
            setLoading(false);
        };
        setLoading(true);
        pull();
        // 24h advances slowly → 30s; live → 5s (same cadence as AnalysisPanel).
        const timer = setInterval(pull, windowS === 86400 ? 30000 : 5000);
        return () => {
            alive = false;
            clearInterval(timer);
        };
    }, [cameraIds, windowS]);
    const rollupPct = agg?.rollup_pct ?? {};
    const idlePct = Math.round(((rollupPct.idle ?? 0) + (rollupPct.group_idle ?? 0)) * 10) / 10;
    const windowTabs = (_jsx("div", { className: "window-tabs", children: WINDOWS.map((w) => (_jsx("button", { className: `window-tab ${windowS === w.value ? "on" : ""}`, onClick: () => setWindowS(w.value), children: w.label }, w.value))) }));
    return (_jsx(Panel, { title: "Workforce overview", right: windowTabs, className: "mb-4", children: loading && !agg ? (_jsx("div", { className: "hint", children: "Loading workforce metrics\u2026" })) : (_jsxs(_Fragment, { children: [_jsxs("div", { className: "grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2 mb-4", children: [_jsx(StatReadout, { label: "Workers on site", value: Math.round(agg?.avg_headcount ?? 0), tone: "accent", size: "md" }), _jsx(StatReadout, { label: "% working", value: rollupPct.working ?? 0, unit: "%", tone: "ok", size: "md" }), _jsx(StatReadout, { label: "% idle", value: idlePct, unit: "%", tone: "warn", size: "md" }), _jsx(StatReadout, { label: "Worker-time", value: fmtSeconds(agg?.worker_seconds ?? 0), tone: "neutral", size: "md" })] }), _jsx(MetricsBreakdown, { metrics: agg ?? undefined, showMeta: false })] })) }));
}
