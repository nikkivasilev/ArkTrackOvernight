import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo } from "react";
/**
 * Dependency-free staffing chart for the Reports page — bars of average
 * concurrent headcount. Matches the PDF's two shapes: an intraday curve (a day
 * report's per-bin timeline) vs per-calendar-day bars (week/month). Labels are
 * formatted in the factory timezone; a sparse subset is shown to avoid crowding.
 */
function fmtLabel(t, kind, tz) {
    const d = new Date(t);
    if (kind === "daily")
        return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: tz });
    return d.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: tz,
    });
}
export default function StaffingTimelineChart({ timeline, kind, tz, }) {
    const max = useMemo(() => Math.max(0, ...timeline.map((p) => p.avg_headcount)), [timeline]);
    if (!timeline.length || max <= 0)
        return _jsx("div", { className: "hint", children: "No staffing data for this period." });
    // Show at most ~10 axis labels evenly spaced.
    const step = Math.max(1, Math.ceil(timeline.length / 10));
    return (_jsxs("div", { children: [_jsxs("div", { className: "font-mono text-[10px] text-text-mute mb-1", children: ["peak ", max.toFixed(1), " avg people"] }), _jsx("div", { className: "flex items-end gap-[2px] h-40 border-b border-border", children: timeline.map((p, i) => (_jsx("div", { className: "flex-1 min-w-[2px] rounded-t-sm bg-[var(--ru-working)] transition-[height]", style: { height: `${(p.avg_headcount / max) * 100}%` }, title: `${fmtLabel(p.t, kind, tz)} · ${p.avg_headcount} avg` }, i))) }), _jsx("div", { className: "flex gap-[2px] mt-1", children: timeline.map((p, i) => (_jsx("div", { className: "flex-1 text-center text-[9px] text-text-mute font-mono overflow-hidden whitespace-nowrap", children: i % step === 0 ? fmtLabel(p.t, kind, tz) : "" }, i))) })] }));
}
