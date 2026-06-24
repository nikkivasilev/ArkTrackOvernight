import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const toneClasses = {
    accent: "text-accent",
    ok: "text-accent",
    warn: "text-amber",
    danger: "text-danger",
    neutral: "text-text",
};
export function Hud({ items, className = "" }) {
    return (_jsx("div", { className: `
        inline-flex items-stretch glass rounded-lg
        font-mono divide-x divide-border
        ${className}
      `, children: items.map((it, i) => (_jsxs("div", { className: "flex flex-col px-3 py-1.5 min-w-[72px]", children: [_jsx("span", { className: "text-[9px] tracking-[0.18em] text-text-mute uppercase", children: it.label }), _jsx("span", { className: `text-[13px] tabular-nums font-semibold ${toneClasses[it.tone ?? "neutral"]}`, children: it.value })] }, i))) }));
}
