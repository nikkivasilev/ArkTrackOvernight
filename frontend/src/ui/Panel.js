import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function Panel({ variant = "default", title, right, glow, className = "", children, ...rest }) {
    const pad = variant === "flush" ? "" : "p-4";
    const glowClass = glow === "primary" ? "glow-primary" : glow === "secondary" ? "glow-secondary" : "";
    return (_jsxs("section", { ...rest, className: `glass rounded-xl ${glowClass} ${pad} ${className}`, children: [(title || right) && (_jsxs("header", { className: "flex items-center gap-3 mb-3", children: [title && (_jsx("h2", { className: "m-0 font-mono text-label-caps uppercase text-text-dim", children: typeof title === "string" ? title.toUpperCase() : title })), _jsx("div", { className: "ml-auto flex items-center gap-2", children: right })] })), children] }));
}
