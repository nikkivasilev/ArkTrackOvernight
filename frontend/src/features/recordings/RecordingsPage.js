import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Toolbar } from "../../ui/Toolbar";
import { Panel } from "../../ui/Panel";
const FILTERS = [
    { label: "All", value: "" },
    { label: "Done", value: "done" },
    { label: "Processing", value: "processing" },
    { label: "Failed", value: "failed" },
];
const dt = (s) => s ? new Date(s).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" }) : "—";
function StatusPill({ status }) {
    const cls = status === "done"
        ? "bg-accent-15 text-accent"
        : status === "failed"
            ? "bg-danger/15 text-danger"
            : "bg-amber/15 text-amber";
    return (_jsx("span", { className: `inline-block px-2 py-0.5 rounded-full text-[11px] font-mono ${cls}`, children: status }));
}
export default function RecordingsPage() {
    const { fid } = useParams();
    const [recs, setRecs] = useState([]);
    const [status, setStatus] = useState("");
    const [loading, setLoading] = useState(false);
    const [err, setErr] = useState(null);
    useEffect(() => {
        if (!fid)
            return;
        let alive = true;
        setLoading(true);
        setErr(null);
        api
            .listRecordings(fid, status || undefined)
            .then((r) => alive && setRecs(r))
            .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
            .finally(() => alive && setLoading(false));
        return () => {
            alive = false;
        };
    }, [fid, status]);
    return (_jsxs(_Fragment, { children: [_jsx(Toolbar, { title: "Recordings", subtitle: "Ingested footage & processing status" }), _jsxs(Panel, { className: "mb-4", children: [_jsx("div", { className: "window-tabs", children: FILTERS.map((f) => (_jsx("button", { className: `window-tab ${status === f.value ? "on" : ""}`, onClick: () => setStatus(f.value), children: f.label }, f.value))) }), err && _jsx("div", { className: "mt-2 text-danger text-[12px] font-mono", children: err })] }), loading && recs.length === 0 ? (_jsx("div", { className: "text-text-dim text-[13px]", children: "Loading\u2026" })) : recs.length === 0 ? (_jsx("div", { className: "hint", children: "No recordings yet. Drop NVR files into the watched folder (data/incoming) \u2014 the batch ingest creates a camera per label and processes each file automatically." })) : (_jsx("div", { className: "overflow-x-auto glass rounded-xl", children: _jsxs("table", { className: "w-full text-[12px] border-collapse", children: [_jsx("thead", { children: _jsxs("tr", { className: "text-text-dim font-mono uppercase text-[10px] tracking-wider", children: [_jsx("th", { className: "text-left px-3 py-2 font-medium", children: "Camera" }), _jsx("th", { className: "text-left px-3 py-2 font-medium", children: "File" }), _jsx("th", { className: "text-left px-3 py-2 font-medium", children: "Recorded" }), _jsx("th", { className: "text-right px-3 py-2 font-medium", children: "Footage" }), _jsx("th", { className: "text-right px-3 py-2 font-medium", children: "Frames" }), _jsx("th", { className: "text-left px-3 py-2 font-medium", children: "Status" }), _jsx("th", { className: "text-left px-3 py-2 font-medium", children: "On disk" })] }) }), _jsx("tbody", { children: recs.map((r) => (_jsxs("tr", { className: "border-t border-border align-top", children: [_jsx("td", { className: "px-3 py-2 whitespace-nowrap", children: r.camera_name ?? "—" }), _jsxs("td", { className: "px-3 py-2 max-w-[280px]", children: [_jsx("div", { className: "truncate font-mono", title: r.filename, children: r.filename }), r.error && (_jsx("div", { className: "text-danger text-[11px] font-mono mt-0.5 truncate", title: r.error, children: r.error }))] }), _jsxs("td", { className: "px-3 py-2 whitespace-nowrap font-mono text-text-dim", children: [dt(r.recorded_start), " \u2192 ", dt(r.recorded_end)] }), _jsxs("td", { className: "px-3 py-2 text-right tabular-nums", children: [(r.footage_s / 3600).toFixed(2), " h"] }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: r.frames.toLocaleString() }), _jsx("td", { className: "px-3 py-2", children: _jsx(StatusPill, { status: r.status }) }), _jsx("td", { className: "px-3 py-2", children: r.file_exists ? (_jsx("span", { className: "text-accent text-[11px] font-mono", children: "\u25CF yes" })) : (_jsx("span", { className: "text-amber text-[11px] font-mono", children: "\u25CF missing" })) })] }, r.id))) })] }) }))] }));
}
