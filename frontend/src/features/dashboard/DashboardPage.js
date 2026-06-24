import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { Toolbar } from "../../ui/Toolbar";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
import { DataCard } from "../../ui/DataCard";
import { StatReadout } from "../../ui/StatReadout";
import { Panel } from "../../ui/Panel";
import { Icon } from "../../ui/Icon";
import WorkforceOverview from "./WorkforceOverview";
export default function DashboardPage() {
    const [cameras, setCameras] = useState([]);
    const [sites, setSites] = useState([]);
    const [factories, setFactories] = useState([]);
    const [filter, setFilter] = useState("all");
    const { cameraStatusOverrides } = useApp();
    const refresh = async () => {
        const [fs, cs] = await Promise.all([api.listFactories(), api.listAllCameras()]);
        setFactories(fs);
        setCameras(cs);
        const siteLists = await Promise.all(fs.map((f) => api.listSitesForFactory(f.id)));
        setSites(siteLists.flat());
    };
    useEffect(() => {
        refresh().catch(console.error);
    }, []);
    const siteById = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);
    const factoryById = useMemo(() => new Map(factories.map((f) => [f.id, f])), [factories]);
    const merged = useMemo(() => cameras.map((c) => {
        const override = cameraStatusOverrides[c.id];
        return {
            ...c,
            status: (override?.status ?? c.status),
            error: override?.error ?? c.error,
        };
    }), [cameras, cameraStatusOverrides]);
    const runningCount = useMemo(() => merged.filter((c) => c.status === "running").length, [merged]);
    const failedCount = useMemo(() => merged.filter((c) => c.status === "failed").length, [merged]);
    const tiles = useMemo(() => (filter === "running" ? merged.filter((c) => c.status === "running") : merged), [merged, filter]);
    if (cameras.length === 0) {
        return (_jsxs(_Fragment, { children: [_jsx(Toolbar, { title: "Dashboard", subtitle: "Active feeds across your factory sectors. System status nominal." }), _jsx(Panel, { className: "bg-hero-mesh", children: _jsxs("div", { className: "text-text-dim text-[14px]", children: ["No cameras yet. Go to", " ", _jsx(Link, { to: "/factories", className: "text-accent no-underline hover:underline", children: "Factories" }), " ", "to create a factory, site, and upload a camera."] }) })] }));
    }
    return (_jsxs(_Fragment, { children: [_jsxs(Toolbar, { title: "Dashboard", subtitle: "Active feeds across your factory sectors. System status nominal.", children: [_jsx(Button, { tone: filter === "all" ? "primary" : "outline", size: "sm", onClick: () => setFilter("all"), children: "ALL" }), _jsx(Button, { tone: filter === "running" ? "primary" : "outline", size: "sm", onClick: () => setFilter("running"), children: "RUNNING" }), _jsxs(Button, { tone: "ghost", size: "sm", onClick: refresh, children: [_jsx(Icon, { name: "refresh", size: 16 }), " REFRESH"] })] }), _jsxs("div", { className: "grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3 mb-6", children: [_jsx(StatReadout, { label: "Cameras", value: merged.length, tone: "neutral", size: "md" }), _jsx(StatReadout, { label: "Running", value: runningCount, tone: "ok", size: "md" }), _jsx(StatReadout, { label: "Failed", value: failedCount, tone: failedCount > 0 ? "danger" : "neutral", size: "md" }), _jsx(StatReadout, { label: "Sites", value: sites.length, tone: "neutral", size: "md" }), _jsx(StatReadout, { label: "Factories", value: factories.length, tone: "neutral", size: "md" })] }), _jsx(WorkforceOverview, { cameras: merged }), _jsx("div", { className: "grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4 mt-6", children: tiles.map((c) => {
                    const site = siteById.get(c.site_id);
                    const factory = site ? factoryById.get(site.factory_id) : undefined;
                    const camLink = site && factory
                        ? `/factories/${factory.id}/sites/${site.id}/cameras/${c.id}`
                        : `#`;
                    const tone = pillTone(c.status);
                    const side = sideTone(c.status);
                    return (_jsx(DataCard, { to: camLink, accentSide: side, live: c.status === "running", feedId: `CAM-${c.id.slice(0, 4).toUpperCase()}`, badge: _jsx(Pill, { tone: tone, dot: true, children: c.status }), thumb: c.status === "running" ? (_jsx("img", { src: api.liveUrl(c.id), alt: c.name })) : (_jsxs("span", { className: "text-text-mute text-[11px] tracking-[0.14em] uppercase flex items-center gap-1.5", children: [_jsx(Icon, { name: "videocam_off", size: 16 }), " ", c.status] })), title: c.name, meta: _jsxs("span", { children: [factory?.name ?? "—", " ", _jsx("span", { className: "text-text-mute", children: "\u203A" }), " ", site?.name ?? "—"] }) }, c.id));
                }) })] }));
}
function pillTone(s) {
    switch (s) {
        case "running":
            return "ok";
        case "failed":
            return "danger";
        case "cancelled":
            return "warn";
        case "completed":
            return "info";
        default:
            return "neutral";
    }
}
function sideTone(s) {
    switch (s) {
        case "running":
            return "ok";
        case "failed":
            return "danger";
        case "cancelled":
            return "warn";
        case "completed":
            return "info";
        default:
            return "neutral";
    }
}
