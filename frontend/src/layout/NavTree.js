import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { Icon } from "../ui/Icon";
const EXPAND_KEY = "navtree.expanded";
function loadExpanded() {
    try {
        const raw = localStorage.getItem(EXPAND_KEY);
        if (!raw)
            return new Set();
        return new Set(JSON.parse(raw));
    }
    catch {
        return new Set();
    }
}
function saveExpanded(s) {
    localStorage.setItem(EXPAND_KEY, JSON.stringify([...s]));
}
export default function NavTree({ collapsed = false }) {
    const params = useParams();
    // When collapsed, the expanded sections hide at every width (icon-only);
    // otherwise they appear at ≥900px.
    const labelVis = collapsed ? "hidden" : "hidden min-[900px]:block";
    const footerVis = collapsed ? "hidden" : "hidden min-[900px]:flex";
    const { cameraStatusOverrides } = useApp();
    const [factories, setFactories] = useState([]);
    const [sitesByFactory, setSitesByFactory] = useState({});
    const [camerasBySite, setCamerasBySite] = useState({});
    const [expanded, setExpanded] = useState(() => loadExpanded());
    useEffect(() => {
        api.listFactories().then(setFactories).catch(console.error);
    }, []);
    useEffect(() => {
        if (!params.fid)
            return;
        setExpanded((prev) => {
            const next = new Set(prev);
            next.add(`f:${params.fid}`);
            if (params.sid)
                next.add(`s:${params.sid}`);
            saveExpanded(next);
            return next;
        });
    }, [params.fid, params.sid]);
    useEffect(() => {
        for (const key of expanded) {
            if (!key.startsWith("f:"))
                continue;
            const fid = key.slice(2);
            if (sitesByFactory[fid])
                continue;
            api
                .listSitesForFactory(fid)
                .then((sites) => setSitesByFactory((m) => ({ ...m, [fid]: sites })))
                .catch(console.error);
        }
    }, [expanded, sitesByFactory]);
    useEffect(() => {
        for (const key of expanded) {
            if (!key.startsWith("s:"))
                continue;
            const sid = key.slice(2);
            if (camerasBySite[sid])
                continue;
            api
                .listCamerasForSite(sid)
                .then((cams) => setCamerasBySite((m) => ({ ...m, [sid]: cams })))
                .catch(console.error);
        }
    }, [expanded, camerasBySite]);
    const toggle = (key) => {
        setExpanded((prev) => {
            const next = new Set(prev);
            if (next.has(key))
                next.delete(key);
            else
                next.add(key);
            saveExpanded(next);
            return next;
        });
    };
    return (_jsxs("nav", { className: "flex flex-col flex-1 py-3", children: [_jsxs("div", { className: `px-3 pb-3 mb-1 ${labelVis}`, children: [_jsx("div", { className: "font-display text-[15px] font-semibold tracking-tight text-text", children: "ArkTrack" }), _jsx("div", { className: "font-mono text-[10px] uppercase tracking-[0.16em] text-text-mute", children: "Sidebar" })] }), _jsxs("div", { className: "px-2 flex flex-col gap-0.5", children: [_jsx(NavItem, { to: "/dashboard", icon: "dashboard", label: "Dashboard", collapsed: collapsed }), _jsx(NavItem, { to: "/factories", icon: "factory", label: "Factory Sites", collapsed: collapsed }), _jsx(NavItem, { to: "/alerts", icon: "notifications_active", label: "System Alerts", collapsed: collapsed })] }), _jsx("div", { className: `mt-3 px-2 ${labelVis}`, children: _jsx("div", { className: "px-2.5 pb-1 font-mono text-[10px] uppercase tracking-[0.16em] text-text-mute", children: "Explorer" }) }), _jsx("ul", { className: `flex-1 px-1 ${labelVis}`, children: factories.map((f) => {
                    const fk = `f:${f.id}`;
                    const open = expanded.has(fk);
                    const sites = sitesByFactory[f.id] ?? [];
                    return (_jsxs("li", { children: [_jsx(Row, { indent: 0, onChevron: () => toggle(fk), open: open, active: params.fid === f.id && !params.sid, children: _jsx(Link, { to: `/factories/${f.id}`, className: "truncate no-underline text-inherit", children: f.name }) }), open && (_jsxs("ul", { children: [sites.length === 0 && (_jsx("li", { className: "pl-9 py-1 text-text-mute text-[11px] italic", children: "no sites" })), sites.map((s) => {
                                        const sk = `s:${s.id}`;
                                        const sopen = expanded.has(sk);
                                        const cams = camerasBySite[s.id] ?? [];
                                        return (_jsxs("li", { children: [_jsx(Row, { indent: 1, onChevron: () => toggle(sk), open: sopen, active: params.sid === s.id && !params.cid, children: _jsx(Link, { to: `/factories/${f.id}/sites/${s.id}`, className: "truncate no-underline text-inherit", children: s.name }) }), sopen && (_jsxs("ul", { children: [cams.length === 0 && (_jsx("li", { className: "pl-[52px] py-1 text-text-mute text-[11px] italic", children: "no cameras" })), cams.map((c) => {
                                                            const status = cameraStatusOverrides[c.id]?.status ?? c.status;
                                                            return (_jsx("li", { children: _jsx(CameraRow, { name: c.name, status: status, to: `/factories/${f.id}/sites/${s.id}/cameras/${c.id}`, active: params.cid === c.id }) }, c.id));
                                                        })] }))] }, s.id));
                                    })] }))] }, f.id));
                }) }), _jsxs("div", { className: `mt-auto items-center gap-2 px-4 pt-3 pb-2 border-t border-border ${footerVis}`, children: [_jsxs("div", { className: "relative flex size-1.5", children: [_jsx("span", { className: "animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" }), _jsx("span", { className: "relative inline-flex rounded-full size-1.5 bg-accent" })] }), _jsx("span", { className: "font-mono text-[10px] text-text-mute tracking-[0.14em] uppercase", children: "// sys \u00B7 v0.1" })] })] }));
}
function NavItem({ to, icon, label, collapsed = false, }) {
    const justify = collapsed ? "justify-center" : "justify-center min-[900px]:justify-start";
    const labelVis = collapsed ? "hidden" : "hidden min-[900px]:block";
    return (_jsx(NavLink, { to: to, end: true, title: label, className: ({ isActive }) => `
          relative flex items-center ${justify} gap-3 px-2.5 py-2 rounded-lg no-underline
          font-sans text-[14px] font-medium transition-colors duration-150
          ${isActive
            ? "bg-accent-15 text-text " +
                "before:absolute before:-left-2 before:top-1/2 before:h-5 before:w-[3px] " +
                "before:-translate-y-1/2 before:rounded-r-full before:bg-accent"
            : "text-text-dim hover:bg-surface-high/40 hover:text-text"}
        `, children: ({ isActive }) => (_jsxs(_Fragment, { children: [_jsx(Icon, { name: icon, size: 20, filled: isActive, className: "flex-none" }), _jsx("span", { className: `${labelVis} truncate`, children: label })] })) }));
}
function Row({ indent, onChevron, open, active, children, }) {
    const padLeft = 10 + indent * 16;
    return (_jsxs("div", { className: `
        flex items-center gap-1 py-1 pr-2 cursor-default text-[13px] rounded-md
        ${active
            ? "bg-surface-high/50 text-text"
            : "text-text-dim hover:bg-surface-high/30 hover:text-text"}
      `, style: { paddingLeft: padLeft }, children: [_jsx("button", { onClick: onChevron, className: "inline-flex items-center justify-center size-5 text-text-mute hover:text-text bg-transparent border-0 p-0 cursor-pointer", type: "button", children: _jsx(Icon, { name: open ? "expand_more" : "chevron_right", size: 18 }) }), _jsx("div", { className: "flex-1 min-w-0", children: children })] }));
}
function CameraRow({ name, status, to, active, }) {
    return (_jsxs(NavLink, { to: to, className: `
        flex items-center gap-2 py-1 pr-2 pl-[52px] no-underline truncate
        text-[13px] rounded-md transition-colors
        ${active ? "bg-accent-15 text-text" : "text-text-dim hover:bg-surface-high/30 hover:text-text"}
      `, children: [_jsx(StatusDot, { status: status }), _jsx("span", { className: "truncate flex-1", children: name })] }));
}
function StatusDot({ status }) {
    const color = status === "running" ? "bg-accent" :
        status === "failed" ? "bg-danger" :
            status === "cancelled" ? "bg-amber" :
                "bg-text-mute";
    return _jsx("span", { className: `block size-1.5 rounded-full flex-none ${color}` });
}
