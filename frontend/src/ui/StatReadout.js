import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const toneClasses = {
    accent: "text-accent text-glow-primary",
    ok: "text-accent text-glow-primary",
    warn: "text-amber text-glow-secondary",
    danger: "text-danger",
    neutral: "text-text",
};
export function StatReadout({ label, value, unit, tone = "neutral", size = "md", className = "", }) {
    const numSize = size === "lg" ? "font-display text-stats" :
        size === "sm" ? "text-[20px] leading-none" :
            "text-[30px] leading-none";
    const unitSize = size === "lg" ? "text-[16px]" : "text-[12px]";
    return (_jsxs("div", { className: `glass rounded-xl flex flex-col gap-1.5 px-4 py-3 ${className}`, children: [_jsx("div", { className: "font-mono text-label-caps uppercase text-text-dim", children: label }), _jsxs("div", { className: `font-display tabular-nums font-semibold ${numSize} ${toneClasses[tone]}`, children: [value, unit && _jsx("span", { className: `ml-1 text-text-dim font-normal ${unitSize}`, children: unit })] })] }));
}
