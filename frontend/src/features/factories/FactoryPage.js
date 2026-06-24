import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Toolbar } from "../../ui/Toolbar";
export default function FactoryPage() {
    const { fid } = useParams();
    const [factory, setFactory] = useState(null);
    const [sites, setSites] = useState([]);
    const [camCounts, setCamCounts] = useState({});
    const [name, setName] = useState("");
    const [address, setAddress] = useState("");
    const [err, setErr] = useState(null);
    const refresh = useCallback(async () => {
        if (!fid)
            return;
        const [f, ss] = await Promise.all([api.getFactory(fid), api.listSitesForFactory(fid)]);
        setFactory(f);
        setSites(ss);
        // Per-site camera counts (active = running) for the row stats.
        const camLists = await Promise.all(ss.map((s) => api.listCamerasForSite(s.id)));
        const counts = {};
        ss.forEach((s, i) => {
            const cams = camLists[i];
            counts[s.id] = {
                active: cams.filter((c) => c.status === "running").length,
                total: cams.length,
            };
        });
        setCamCounts(counts);
    }, [fid]);
    useEffect(() => {
        refresh().catch(console.error);
    }, [refresh]);
    const create = useCallback(async () => {
        if (!fid)
            return;
        setErr(null);
        try {
            await api.createSite(fid, { name, address: address || undefined });
            setName("");
            setAddress("");
            refresh();
        }
        catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        }
    }, [fid, name, address, refresh]);
    const remove = useCallback(async (sid) => {
        await api.deleteSite(sid);
        refresh();
    }, [refresh]);
    if (!factory)
        return _jsx("div", { className: "text-text-dim text-[13px]", children: "Loading\u2026" });
    return (_jsxs(_Fragment, { children: [_jsx(Toolbar, { title: factory.name, subtitle: factory.address || "Factory overview" }), _jsxs("div", { className: "flex flex-wrap gap-2 mb-4", children: [_jsx(Link, { to: `/factories/${fid}/reports`, className: "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg no-underline\r\n                     bg-accent-15 text-accent text-[13px] font-medium hover:bg-surface-highest/40 transition-colors", children: "Reports" }), _jsx(Link, { to: `/factories/${fid}/recordings`, className: "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg no-underline\r\n                     bg-surface-high/40 text-text text-[13px] font-medium hover:bg-surface-highest/40 transition-colors", children: "Recordings" })] }), _jsxs(Panel, { title: "NEW SITE", className: "mb-4", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx("input", { placeholder: "Name (e.g. Plant A)", value: name, onChange: (e) => setName(e.target.value), style: { flex: "1 1 200px" } }), _jsx("input", { placeholder: "Address (optional)", value: address, onChange: (e) => setAddress(e.target.value), style: { flex: "1 1 200px" } }), _jsx(Button, { tone: "primary", size: "sm", onClick: create, disabled: !name.trim(), children: "CREATE" })] }), err && _jsx("div", { className: "mt-2 text-danger text-[12px] font-mono", children: err })] }), _jsxs("div", { className: "mb-2 font-mono text-label-caps uppercase text-text-dim", children: ["Sites \u00B7 ", sites.length] }), sites.length === 0 ? (_jsx("div", { className: "text-text-dim text-[13px]", children: "No sites yet." })) : (_jsx("div", { className: "flex flex-col gap-2", children: sites.map((s) => {
                    const cc = camCounts[s.id];
                    const active = cc?.active ?? 0;
                    const inactive = cc ? cc.total - cc.active : 0;
                    return (_jsxs("div", { className: "group relative flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer bg-[var(--glass-bg)] backdrop-blur-xl shadow-[0_2px_8px_-2px_rgba(0,0,0,0.35)] hover:bg-surface-highest/40 transition-all duration-200 ease-in-out", children: [_jsx(Link, { to: `/factories/${fid}/sites/${s.id}`, "aria-label": s.name, className: "absolute inset-0 rounded-lg" }), _jsxs("div", { className: "flex flex-col gap-0.5 flex-1 min-w-0", children: [_jsx("span", { className: "font-display text-[15px] text-text font-semibold truncate", children: s.name }), _jsx("span", { className: "text-accent text-[12px] font-mono truncate", children: s.address ?? "—" })] }), _jsxs("div", { className: "flex items-center gap-3 font-mono text-[11px] whitespace-nowrap", children: [_jsxs("span", { className: "flex items-center gap-1.5 text-accent", children: [_jsx("span", { className: "size-1.5 rounded-full bg-accent" }), _jsx("span", { className: "tabular-nums", children: active }), " active"] }), _jsxs("span", { className: "flex items-center gap-1.5 text-text-mute", children: [_jsx("span", { className: "size-1.5 rounded-full bg-text-mute" }), _jsx("span", { className: "tabular-nums", children: inactive }), " inactive"] })] }), _jsx("div", { className: "relative z-10", children: _jsx(ConfirmDialog, { title: "DELETE SITE", body: _jsxs(_Fragment, { children: ["Delete ", _jsx("span", { className: "font-medium text-text", children: s.name }), " and all its cameras, zones, rules, and alerts? This cannot be undone."] }), confirmLabel: "DELETE", onConfirm: () => remove(s.id), trigger: _jsx(Button, { tone: "danger", size: "sm", children: "DELETE" }) }) })] }, s.id));
                }) }))] }));
}
