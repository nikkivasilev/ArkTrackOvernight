import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import * as Dialog from "@radix-ui/react-dialog";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
export default function CommandPalette() {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const [factories, setFactories] = useState([]);
    const [sites, setSites] = useState([]);
    const [cameras, setCameras] = useState([]);
    const [selected, setSelected] = useState(0);
    const navigate = useNavigate();
    const inputRef = useRef(null);
    const refresh = useCallback(async () => {
        try {
            const fs = await api.listFactories();
            setFactories(fs);
            const cs = await api.listAllCameras();
            setCameras(cs);
            const sl = await Promise.all(fs.map((f) => api.listSitesForFactory(f.id)));
            setSites(sl.flat());
        }
        catch (e) {
            console.error(e);
        }
    }, []);
    useEffect(() => {
        refresh();
    }, [refresh]);
    // Global Cmd-K / Ctrl-K to open.
    useEffect(() => {
        const onKey = (e) => {
            if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
                e.preventDefault();
                setOpen((o) => !o);
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);
    // Refetch index whenever the palette opens, so newly-created entities appear.
    useEffect(() => {
        if (open) {
            refresh();
            setQuery("");
            setSelected(0);
            // Focus after Radix mounts the input.
            setTimeout(() => inputRef.current?.focus(), 0);
        }
    }, [open, refresh]);
    const entries = useMemo(() => {
        const factoryById = new Map(factories.map((f) => [f.id, f]));
        const siteById = new Map(sites.map((s) => [s.id, s]));
        const list = [];
        for (const f of factories) {
            list.push({
                kind: "factory",
                id: f.id,
                label: f.name,
                subtitle: "factory",
                to: `/factories/${f.id}`,
            });
        }
        for (const s of sites) {
            const f = factoryById.get(s.factory_id);
            list.push({
                kind: "site",
                id: s.id,
                label: s.name,
                subtitle: `site · ${f?.name ?? "?"}`,
                to: `/factories/${s.factory_id}/sites/${s.id}`,
            });
        }
        for (const c of cameras) {
            const s = siteById.get(c.site_id);
            const f = s ? factoryById.get(s.factory_id) : undefined;
            const to = s && f
                ? `/factories/${f.id}/sites/${s.id}/cameras/${c.id}/live`
                : `/dashboard`;
            list.push({
                kind: "camera",
                id: c.id,
                label: c.name,
                subtitle: `camera · ${f?.name ?? "?"} › ${s?.name ?? "?"}`,
                to,
            });
        }
        return list;
    }, [factories, sites, cameras]);
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return entries.slice(0, 50);
        return entries
            .map((e) => ({ e, score: score(e, q) }))
            .filter((x) => x.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, 50)
            .map((x) => x.e);
    }, [entries, query]);
    useEffect(() => {
        if (selected >= filtered.length)
            setSelected(0);
    }, [filtered.length, selected]);
    const onSelect = (entry) => {
        setOpen(false);
        navigate(entry.to);
    };
    const onKeyDown = (e) => {
        if (e.key === "ArrowDown") {
            e.preventDefault();
            setSelected((i) => Math.min(filtered.length - 1, i + 1));
        }
        else if (e.key === "ArrowUp") {
            e.preventDefault();
            setSelected((i) => Math.max(0, i - 1));
        }
        else if (e.key === "Enter") {
            e.preventDefault();
            if (filtered[selected])
                onSelect(filtered[selected]);
        }
    };
    return (_jsx(Dialog.Root, { open: open, onOpenChange: setOpen, children: _jsxs(Dialog.Portal, { children: [_jsx(Dialog.Overlay, { className: "fixed inset-0 bg-black/60 backdrop-blur-sm z-50" }), _jsxs(Dialog.Content, { className: "\r\n            fixed left-1/2 top-[18%] -translate-x-1/2 z-50\r\n            w-[min(640px,92vw)]\r\n            glass rounded-xl shadow-xl\r\n            focus:outline-none overflow-hidden\r\n          ", children: [_jsx(Dialog.Title, { className: "sr-only", children: "Command palette" }), _jsx("input", { ref: inputRef, value: query, onChange: (e) => setQuery(e.target.value), onKeyDown: onKeyDown, placeholder: "Jump to factory, site, or camera\u2026", className: "\r\n              w-full px-4 py-3 bg-transparent text-text\r\n              border-0 border-b border-border\r\n              outline-none\r\n              placeholder:text-text-dim\r\n              font-mono text-[14px]\r\n            " }), _jsxs("div", { className: "max-h-[50vh] overflow-y-auto", children: [filtered.length === 0 && (_jsx("div", { className: "px-4 py-6 text-center text-text-dim text-[12px]", children: "no matches" })), filtered.map((e, idx) => (_jsxs("button", { onClick: () => onSelect(e), onMouseEnter: () => setSelected(idx), className: `
                  w-full text-left flex items-baseline gap-3 px-4 py-2
                  bg-transparent border-0 cursor-pointer
                  ${idx === selected ? "bg-panel-2" : ""}
                `, type: "button", children: [_jsx("span", { className: `
                    inline-block w-1.5 h-1.5 rounded-full
                    ${e.kind === "camera"
                                                ? "bg-accent"
                                                : e.kind === "site"
                                                    ? "bg-tertiary"
                                                    : "bg-amber"}
                  ` }), _jsx("span", { className: "text-text font-medium truncate", children: e.label }), _jsx("span", { className: "text-text-dim text-[11px] tracking-[0.12em] truncate ml-auto", children: e.subtitle })] }, `${e.kind}-${e.id}`)))] }), _jsxs("div", { className: "\r\n            flex items-center gap-4 px-4 py-2 border-t border-border\r\n            text-[10px] tracking-[0.16em] text-text-dim\r\n          ", children: [_jsx("span", { children: "\u2191\u2193 NAV" }), _jsx("span", { children: "\u21B5 JUMP" }), _jsx("span", { children: "ESC CLOSE" })] })] })] }) }));
}
function score(e, q) {
    const label = e.label.toLowerCase();
    const sub = e.subtitle.toLowerCase();
    if (label.startsWith(q))
        return 100;
    if (label.includes(q))
        return 60;
    if (sub.includes(q))
        return 20;
    // Fuzzy: every char of q in label in order.
    let i = 0;
    for (const ch of label) {
        if (ch === q[i])
            i++;
        if (i === q.length)
            return 10;
    }
    return 0;
}
