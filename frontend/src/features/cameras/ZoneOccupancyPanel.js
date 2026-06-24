import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import { ZoneCard } from "./ZoneCard";
/**
 * Per-zone breakdown panel, embedded in the Live tab below the workflow
 * analysis. For each monitored zone it shows (a) what was being done there —
 * the activity breakdown ("30% welding, 10% idle, …"), worker-weighted over
 * the selectable window — and (b) how worker-time split across occupancy
 * levels, with "understaffed time (< N people)" derived client-side from the
 * occupancy histogram. N is query-time; nothing is baked into capture.
 *
 * Mirrors AnalysisPanel's data plumbing: the default 600 s window is driven by
 * the live WS `state.metrics` (which now carries `zone_occupancy`); other
 * windows fetch once from GET /api/cameras/{id}/metrics and refresh on a timer.
 * The per-zone card itself lives in ./ZoneCard (shared with the Reports page).
 */
const WINDOWS = [
    { label: "1 min", value: 60 },
    { label: "10 min", value: 600 },
    { label: "Session", value: 0 },
    { label: "24h", value: 86400 },
];
export default function ZoneOccupancyPanel({ cameraId, liveMetrics, }) {
    const [windowS, setWindowS] = useState(600);
    const [view, setView] = useState("bars");
    const [fetched, setFetched] = useState(null);
    const [zones, setZones] = useState([]);
    useEffect(() => {
        api.listZones(cameraId).then(setZones).catch(() => setZones([]));
    }, [cameraId]);
    // Non-default windows pull a snapshot from REST (the WS only carries 600 s).
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
                /* transient — keep last snapshot */
            }
        };
        pull();
        const interval = windowS === 86400 ? 30000 : 5000;
        const timer = setInterval(pull, interval);
        return () => {
            alive = false;
            clearInterval(timer);
        };
    }, [cameraId, windowS]);
    const metrics = windowS === 600 ? liveMetrics : fetched ?? undefined;
    // Join occupancy (keyed by zone_id) to names; skip excluded zones.
    const nameById = useMemo(() => {
        const m = {};
        for (const z of zones)
            if (!z.excluded)
                m[z.id] = z.name;
        return m;
    }, [zones]);
    const cards = useMemo(() => {
        const occ = metrics?.zone_occupancy ?? {};
        const act = metrics?.zone_activity ?? {};
        return Object.entries(occ)
            .filter(([zid]) => zid in nameById)
            .map(([zid, o]) => ({ id: zid, name: nameById[zid], occ: o, act: act[zid] }))
            .sort((a, b) => a.name.localeCompare(b.name));
    }, [metrics, nameById]);
    return (_jsxs("section", { className: "analysis", children: [_jsxs("div", { className: "analysis-head", children: [_jsx("h3", { children: "Zone breakdown" }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("div", { className: "window-tabs", children: ["bars", "pie"].map((v) => (_jsx("button", { className: `window-tab ${view === v ? "on" : ""}`, onClick: () => setView(v), children: v === "bars" ? "Bars" : "Pie" }, v))) }), _jsx("div", { className: "window-tabs", children: WINDOWS.map((w) => (_jsx("button", { className: `window-tab ${windowS === w.value ? "on" : ""}`, onClick: () => setWindowS(w.value), children: w.label }, w.value))) })] })] }), cards.length === 0 ? (_jsx("div", { className: "hint", children: "No monitored zones with occupancy data for this window yet. Draw a zone (not marked \"not monitored\") on the Zones tab and let the camera run." })) : (cards.map((c) => (_jsx(ZoneCard, { name: c.name, occ: c.occ, act: c.act, view: view }, c.id))))] }));
}
