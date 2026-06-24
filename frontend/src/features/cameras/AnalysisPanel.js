import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import MetricsBreakdown from "./MetricsBreakdown";
/**
 * Workforce analysis panel — a stacked bar of how worker-time split across
 * rollup categories over a selectable window, plus a per-activity breakdown.
 *
 * Live data arrives on the WS `state.metrics` block (default 10-min window).
 * When the operator picks a different window, we fetch it once from
 * GET /api/cameras/{id}/metrics?window_s= and keep showing that snapshot
 * until they switch again. The breakdown itself is rendered by the shared
 * <MetricsBreakdown> (also used by the dashboard's WorkforceOverview).
 */
const WINDOWS = [
    { label: "1 min", value: 60 },
    { label: "10 min", value: 600 },
    { label: "Session", value: 0 },
    // 24h is served by the persisted metric_samples table (since/until).
    // Survives restarts and includes data from stopped cameras.
    { label: "24h", value: 86400 },
];
export default function AnalysisPanel({ cameraId, liveMetrics, }) {
    // Default window is 600 s — matches the window the backend folds into
    // `state.metrics`, so the live stream can drive it with no fetch.
    const [windowS, setWindowS] = useState(600);
    const [fetched, setFetched] = useState(null);
    // For the non-default windows, pull a snapshot from REST and refresh it
    // on an interval (the WS only carries the 600 s window).
    useEffect(() => {
        if (windowS === 600) {
            setFetched(null);
            return;
        }
        let alive = true;
        const pull = async () => {
            try {
                let url;
                if (windowS === 86400) {
                    // Historical window — hits the persisted metric_samples table.
                    const until = new Date();
                    const since = new Date(until.getTime() - 86400000);
                    url =
                        `/api/cameras/${cameraId}/metrics` +
                            `?since=${encodeURIComponent(since.toISOString())}` +
                            `&until=${encodeURIComponent(until.toISOString())}`;
                }
                else {
                    url = `/api/cameras/${cameraId}/metrics?window_s=${windowS}`;
                }
                const r = await fetch(url);
                if (!r.ok)
                    return;
                const j = await r.json();
                if (alive)
                    setFetched(j.metrics);
            }
            catch {
                /* transient — keep the last snapshot */
            }
        };
        pull();
        // 24 h advances slowly — 30 s refresh is fine. Shorter windows want
        // 5 s so the panel reflects live movement.
        const interval = windowS === 86400 ? 30000 : 5000;
        const timer = setInterval(pull, interval);
        return () => {
            alive = false;
            clearInterval(timer);
        };
    }, [cameraId, windowS]);
    const metrics = windowS === 600 ? liveMetrics : fetched ?? undefined;
    return (_jsxs("section", { className: "analysis analysis-h", children: [_jsxs("div", { className: "analysis-head", children: [_jsx("h3", { children: "Workflow analysis" }), _jsx("div", { className: "window-tabs", children: WINDOWS.map((w) => (_jsx("button", { className: `window-tab ${windowS === w.value ? "on" : ""}`, onClick: () => setWindowS(w.value), children: w.label }, w.value))) })] }), _jsx(MetricsBreakdown, { metrics: metrics, showMeta: true })] }));
}
