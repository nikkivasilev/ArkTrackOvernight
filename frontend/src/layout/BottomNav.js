import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { NavLink } from "react-router-dom";
import { Icon } from "../ui/Icon";
const ITEMS = [
    { to: "/dashboard", icon: "dashboard", label: "Dashboard" },
    { to: "/factories", icon: "factory", label: "Sites" },
    { to: "/alerts", icon: "notifications_active", label: "Alerts" },
];
/** Mobile-only bottom navigation (glass, docked). Hidden at md+. */
export default function BottomNav() {
    return (_jsx("nav", { className: "\r\n        min-[600px]:hidden fixed bottom-0 inset-x-0 z-40 h-16\r\n        flex items-center justify-around px-4\r\n        glass rounded-t-xl\r\n        shadow-[0_-8px_28px_-6px_rgba(0,0,0,0.55),0_-2px_18px_color-mix(in_srgb,var(--accent)_10%,transparent)]\r\n      ", children: ITEMS.map((it) => (_jsx(NavLink, { to: it.to, end: true, className: ({ isActive }) => `flex flex-col items-center justify-center gap-0.5 px-4 py-1 rounded-xl transition-all duration-200 active:scale-90 ${isActive
                ? "bg-accent-15 text-accent glow-primary"
                : "text-text-mute hover:text-text"}`, children: ({ isActive }) => (_jsxs(_Fragment, { children: [_jsx(Icon, { name: it.icon, size: 22, filled: isActive }), _jsx("span", { className: "font-mono text-[9px] uppercase tracking-wider", children: it.label })] })) }, it.to))) }));
}
