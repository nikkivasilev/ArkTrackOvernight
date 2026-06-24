import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { Link } from "react-router-dom";
import { Icon } from "./Icon";
export function DataCard({ to, thumb, title, meta, badge, accentSide = "neutral", feedId, live = false, className = "", }) {
    // Cancelled / warning cameras get an amber flag: a soft orange glow on the
    // card + an orange border on the info container below the feed. Every other
    // card just deepens its shadow on hover.
    const isWarn = accentSide === "warn";
    const inner = (_jsxs(_Fragment, { children: [_jsxs("div", { className: "relative bg-black aspect-video flex items-center justify-center overflow-hidden", children: [_jsx("div", { className: "absolute inset-0 [&>img]:w-full [&>img]:h-full [&>img]:object-cover [&>img]:opacity-80 flex items-center justify-center", children: thumb }), live && (_jsxs("div", { className: "absolute top-2 left-2 flex items-center gap-1.5 glass px-2 py-0.5 rounded-md font-mono text-[10px] uppercase tracking-wider text-accent", children: [_jsxs("span", { className: "relative flex size-1.5", children: [_jsx("span", { className: "animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-70" }), _jsx("span", { className: "relative inline-flex size-1.5 rounded-full bg-danger" })] }), "Live"] })), badge && _jsx("div", { className: "absolute top-2 right-2", children: badge }), feedId && (_jsx("div", { className: "absolute bottom-2 left-2 font-mono text-[10px] tracking-wider text-text-dim glass px-1.5 py-0.5 rounded-md", children: feedId })), _jsx("div", { className: "absolute bottom-2 right-2 size-7 grid place-items-center rounded-md glass text-text-dim opacity-0 group-hover:opacity-100 transition-opacity", children: _jsx(Icon, { name: "fullscreen", size: 16 }) })] }), _jsxs("div", { className: `px-3 py-2.5 border-t glass ${isWarn ? "border-t-warn-muted" : "border-border"}`, children: [_jsx("div", { className: "font-display text-[14px] text-text font-semibold truncate", children: title }), meta && (_jsx("div", { className: "font-mono text-[11px] text-text-dim truncate mt-0.5", children: meta }))] })] }));
    const base = `
    group block rounded-xl overflow-hidden
    transition-all duration-300 ease-in-out
    no-underline text-text cam-card
     ${className}
  `;
    if (to) {
        return (_jsx(Link, { to: to, className: base, children: inner }));
    }
    return _jsx("div", { className: base, children: inner });
}
