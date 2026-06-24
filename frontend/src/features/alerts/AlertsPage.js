import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { useApp } from "../../state/AppContext";
import AlertCard from "./AlertCard";
import { Toolbar } from "../../ui/Toolbar";
import { Button } from "../../ui/Button";
import { Panel } from "../../ui/Panel";
export default function AlertsPage() {
    const { alerts } = useApp();
    const [filter, setFilter] = useState("all");
    const list = useMemo(() => (filter === "unacked" ? alerts.filter((a) => !a.acknowledged) : alerts), [alerts, filter]);
    const unackedCount = useMemo(() => alerts.filter((a) => !a.acknowledged).length, [alerts]);
    return (_jsxs(_Fragment, { children: [_jsxs(Toolbar, { title: "System Alerts", subtitle: `${list.length} shown · ${unackedCount} unacked`, children: [_jsx(Button, { tone: filter === "all" ? "primary" : "outline", size: "sm", onClick: () => setFilter("all"), children: "ALL" }), _jsx(Button, { tone: filter === "unacked" ? "primary" : "outline", size: "sm", onClick: () => setFilter("unacked"), children: "UNACKED" })] }), list.length === 0 ? (_jsx(Panel, { children: _jsx("div", { className: "text-text-dim text-[13px]", children: "No alerts yet." }) })) : (_jsx("div", { className: "grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4", children: list.map((a) => (_jsx(AlertCard, { alert: a }, a.id))) }))] }));
}
