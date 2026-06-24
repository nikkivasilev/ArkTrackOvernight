import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Toolbar } from "../../ui/Toolbar";
import { Panel } from "../../ui/Panel";
import { StatReadout } from "../../ui/StatReadout";
import MetricsBreakdown from "../cameras/MetricsBreakdown";
import { ZoneCard } from "../cameras/ZoneCard";
import StaffingTimelineChart from "./StaffingTimelineChart";
const PERIODS = ["day", "week", "month"];
const hrs = (s) => (s / 3600).toFixed(1);
function todayISO() {
    return new Date().toISOString().slice(0, 10);
}
export default function ReportsPage() {
    const { fid } = useParams();
    const [period, setPeriod] = useState("day");
    const [date, setDate] = useState(todayISO);
    const [view, setView] = useState("bars");
    const [summary, setSummary] = useState(null);
    const [loading, setLoading] = useState(false);
    const [err, setErr] = useState(null);
    // zone_id -> default understaffing N, seeded from authored count_min rules.
    const [zoneN, setZoneN] = useState({});
    useEffect(() => {
        if (!fid)
            return;
        let alive = true;
        setLoading(true);
        setErr(null);
        api
            .getReport(fid, period, date)
            .then((s) => alive && setSummary(s))
            .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
            .finally(() => alive && setLoading(false));
        return () => {
            alive = false;
        };
    }, [fid, period, date]);
    // Seed each zone's default understaffing N from its authored count_min rule
    // (the "count thresholds feed reports" wiring). Falls back to 1 per ZoneCard.
    useEffect(() => {
        if (!summary?.cameras.length) {
            setZoneN({});
            return;
        }
        let alive = true;
        (async () => {
            const map = {};
            await Promise.all(summary.cameras.map(async (cam) => {
                try {
                    const rules = await api.listRulesForCamera(cam.camera_id);
                    for (const r of rules) {
                        const t = Number(r.params?.threshold);
                        if (r.trigger_type === "count_min" && r.zone_id && Number.isFinite(t) && t > 0) {
                            map[r.zone_id] = t;
                        }
                    }
                }
                catch {
                    /* rules are optional for the report */
                }
            }));
            if (alive)
                setZoneN(map);
        })();
        return () => {
            alive = false;
        };
    }, [summary]);
    const fs = summary?.factory_summary;
    const rp = fs?.rollup_pct ?? {};
    return (_jsxs(_Fragment, { children: [_jsx(Toolbar, { title: "Reports", subtitle: summary ? summary.factory_name : "Workforce analysis" }), _jsxs(Panel, { className: "mb-4", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-3", children: [_jsx("div", { className: "window-tabs", children: PERIODS.map((p) => (_jsx("button", { className: `window-tab ${period === p ? "on" : ""}`, onClick: () => setPeriod(p), children: p[0].toUpperCase() + p.slice(1) }, p))) }), _jsx("input", { type: "date", value: date, onChange: (e) => setDate(e.target.value), "aria-label": "anchor date" }), _jsx("div", { className: "window-tabs", children: ["bars", "pie"].map((v) => (_jsx("button", { className: `window-tab ${view === v ? "on" : ""}`, onClick: () => setView(v), children: v === "bars" ? "Bars" : "Pie" }, v))) }), _jsx("a", { className: "ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg no-underline\n                       bg-accent-15 text-accent text-[13px] font-medium hover:bg-surface-highest/40 transition-colors", href: fid ? api.reportPdfUrl(fid, period, date) : "#", target: "_blank", rel: "noreferrer", children: "Download PDF" })] }), summary && (_jsxs("div", { className: "mt-2 text-text-dim text-[12px] font-mono", children: [summary.total_recordings, " recordings \u00B7 ", hrs(summary.total_footage_s), " h of footage \u00B7 timezone ", summary.tz] })), err && _jsx("div", { className: "mt-2 text-danger text-[12px] font-mono", children: err })] }), loading && !summary ? (_jsx("div", { className: "text-text-dim text-[13px]", children: "Loading\u2026" })) : !summary ? null : (_jsxs(_Fragment, { children: [_jsxs("div", { className: "grid grid-cols-2 min-[700px]:grid-cols-5 gap-2 mb-4", children: [_jsx(StatReadout, { label: "worker-hours", value: hrs(fs.worker_seconds), unit: "h", tone: "accent" }), _jsx(StatReadout, { label: "avg people", value: fs.avg_headcount }), _jsx(StatReadout, { label: "peak people", value: fs.peak_headcount }), _jsx(StatReadout, { label: "working", value: (rp.working ?? 0).toFixed(0), unit: "%", tone: "accent" }), _jsx(StatReadout, { label: "idle", value: (rp.idle ?? 0).toFixed(0), unit: "%", tone: "danger" })] }), _jsx(Panel, { title: `Staffing through the ${summary.period}`, className: "mb-4", children: _jsx(StaffingTimelineChart, { timeline: summary.timeline, kind: summary.timeline_kind, tz: summary.tz }) }), _jsx(Panel, { title: "Activity & status \u2014 whole factory", className: "mb-4", children: _jsx(MetricsBreakdown, { metrics: fs }) }), _jsxs("div", { className: "mb-2 font-mono text-label-caps uppercase text-text-dim", children: ["By camera \u00B7 ", summary.cameras.length] }), summary.cameras.length === 0 ? (_jsx("div", { className: "hint", children: "No cameras contributed footage in this period." })) : (_jsx("div", { className: "flex flex-col gap-3", children: summary.cameras.map((cam) => {
                            const occ = cam.summary.zone_occupancy ?? {};
                            const act = cam.summary.zone_activity ?? {};
                            const crp = cam.summary.rollup_pct ?? {};
                            return (_jsxs(Panel, { title: cam.name, children: [_jsxs("div", { className: "text-text-dim text-[12px] font-mono mb-3", children: [hrs(cam.summary.worker_seconds), " h worker-time \u00B7 avg", " ", cam.summary.avg_headcount, " / peak ", cam.summary.peak_headcount, " \u00B7", " ", cam.recordings, " recordings \u00B7 working ", (crp.working ?? 0).toFixed(0), "% idle", " ", (crp.idle ?? 0).toFixed(0), "%"] }), _jsx(MetricsBreakdown, { metrics: cam.summary, showMeta: false }), Object.keys(occ).length > 0 && (_jsx("div", { className: "mt-3", children: Object.entries(occ).map(([zid, o]) => (_jsx(ZoneCard, { name: cam.zone_names[zid] ?? zid, occ: o, act: act[zid], view: view, defaultN: zoneN[zid] }, zid))) }))] }, cam.camera_id));
                        }) }))] }))] }));
}
