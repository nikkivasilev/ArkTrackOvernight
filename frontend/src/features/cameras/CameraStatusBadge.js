import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Status semantics (Midnight Obsidian): running → primary blue (active/optimal),
// completed → indigo, cancelled → amber (warning), failed → red (offline/error).
const palette = {
    queued: "border-border       bg-surface-high/50 text-text-dim",
    running: "border-accent-30    bg-accent-15    text-accent",
    completed: "border-accent-2-35  bg-accent-2-15  text-tertiary",
    failed: "border-danger-35    bg-danger-15    text-danger",
    cancelled: "border-amber-35     bg-amber-15     text-amber",
};
export function CameraStatusBadge({ status }) {
    const classes = palette[status] ?? palette.queued;
    return (_jsxs("span", { className: `
        inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5
        font-mono text-[10px] font-semibold uppercase tracking-wider
        ${classes}
      `, children: [status === "running" && (_jsxs("span", { className: "relative flex size-1.5", children: [_jsx("span", { className: "animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" }), _jsx("span", { className: "relative inline-flex size-1.5 rounded-full bg-accent" })] })), status] }));
}
