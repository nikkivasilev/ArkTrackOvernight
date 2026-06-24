import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Status semantics: ok/info → primary blue, warn → amber, danger → red.
const toneClasses = {
    info: "border-accent-30   bg-accent-15   text-accent",
    ok: "border-accent-30   bg-accent-15   text-accent",
    warn: "border-amber-35    bg-amber-15    text-amber",
    danger: "border-danger-35   bg-danger-15   text-danger",
    neutral: "border-border      bg-surface-high/50 text-text-dim",
};
const dotColor = {
    info: "bg-accent",
    ok: "bg-accent",
    warn: "bg-amber",
    danger: "bg-danger",
    neutral: "bg-text-mute",
};
export function Pill({ tone = "neutral", dot = false, className = "", children, ...rest }) {
    return (_jsxs("span", { ...rest, className: `
        inline-flex items-center gap-1.5 px-2 py-0.5
        font-mono text-[10px] font-semibold uppercase tracking-wider
        border rounded-md
        ${toneClasses[tone]} ${className}
      `, children: [dot && _jsx("span", { className: `size-1.5 rounded-full ${dotColor[tone]}` }), children] }));
}
