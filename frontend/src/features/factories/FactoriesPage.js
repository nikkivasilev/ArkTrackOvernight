import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Toolbar } from "../../ui/Toolbar";
export default function FactoriesPage() {
    const [factories, setFactories] = useState([]);
    const [name, setName] = useState("");
    const [address, setAddress] = useState("");
    const [err, setErr] = useState(null);
    const refresh = useCallback(async () => {
        setFactories(await api.listFactories());
    }, []);
    useEffect(() => {
        refresh().catch(console.error);
    }, [refresh]);
    const create = useCallback(async () => {
        setErr(null);
        try {
            await api.createFactory({ name, address: address || undefined });
            setName("");
            setAddress("");
            refresh();
        }
        catch (e) {
            setErr(e instanceof Error ? e.message : String(e));
        }
    }, [name, address, refresh]);
    const remove = useCallback(async (id) => {
        await api.deleteFactory(id);
        refresh();
    }, [refresh]);
    return (_jsxs(_Fragment, { children: [_jsx(Toolbar, { title: "Factory Sites", subtitle: "Manage and monitor industrial facilities globally." }), _jsxs(Panel, { title: "NEW FACTORY", className: "mb-4", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx("input", { placeholder: "Name (e.g. Acme Train Works)", value: name, onChange: (e) => setName(e.target.value), style: { flex: "1 1 200px" } }), _jsx("input", { placeholder: "Address (optional)", value: address, onChange: (e) => setAddress(e.target.value), style: { flex: "1 1 200px" } }), _jsx(Button, { tone: "primary", size: "sm", onClick: create, disabled: !name.trim(), children: "CREATE" })] }), err && _jsx("div", { className: "mt-2 text-danger text-[12px] font-mono", children: err })] }), _jsxs("div", { className: "mb-2 font-mono text-label-caps uppercase text-text-dim", children: ["Factories \u00B7 ", factories.length] }), factories.length === 0 ? (_jsx("div", { className: "text-text-dim text-[13px]", children: "No factories yet. Add one above." })) : (_jsx("div", { className: "flex flex-col gap-2", children: factories.map((f) => (_jsxs("div", { className: "group relative flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer bg-[var(--glass-bg)] backdrop-blur-xl shadow-[0_2px_8px_-2px_rgba(0,0,0,0.35)] hover:bg-surface-highest/40 transition-all duration-200 ease-in-out", children: [_jsx(Link, { to: `/factories/${f.id}`, "aria-label": f.name, className: "absolute inset-0 rounded-lg" }), _jsxs("div", { className: "flex flex-col gap-0.5 flex-1 min-w-0", children: [_jsx("span", { className: "font-display text-[15px] text-text font-semibold truncate", children: f.name }), _jsx("span", { className: "text-accent text-[12px] font-mono truncate", children: f.address ?? "—" })] }), _jsx("div", { className: "relative z-10", children: _jsx(ConfirmDialog, { title: "DELETE FACTORY", body: _jsxs(_Fragment, { children: ["Delete ", _jsx("span", { className: "font-medium text-text", children: f.name }), " and", " ", _jsx("span", { className: "text-danger", children: "all" }), " its sites, cameras, zones, rules, and alerts? This cannot be undone."] }), confirmLabel: "DELETE", onConfirm: () => remove(f.id), trigger: _jsx(Button, { tone: "danger", size: "sm", children: "DELETE" }) }) })] }, f.id))) }))] }));
}
