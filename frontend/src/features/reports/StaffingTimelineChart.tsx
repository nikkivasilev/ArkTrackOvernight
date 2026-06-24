import { useMemo } from "react";
import type { TimelinePoint } from "../../api/client";

/**
 * Dependency-free staffing chart for the Reports page — bars of average
 * concurrent headcount. Matches the PDF's two shapes: an intraday curve (a day
 * report's per-bin timeline) vs per-calendar-day bars (week/month). Labels are
 * formatted in the factory timezone; a sparse subset is shown to avoid crowding.
 */
function fmtLabel(t: string, kind: "intraday" | "daily", tz: string): string {
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

export default function StaffingTimelineChart({
  timeline,
  kind,
  tz,
}: {
  timeline: TimelinePoint[];
  kind: "intraday" | "daily";
  tz: string;
}) {
  const max = useMemo(
    () => Math.max(0, ...timeline.map((p) => p.avg_headcount)),
    [timeline],
  );

  if (!timeline.length || max <= 0)
    return <div className="hint">No staffing data for this period.</div>;

  // Show at most ~10 axis labels evenly spaced.
  const step = Math.max(1, Math.ceil(timeline.length / 10));

  return (
    <div>
      <div className="font-mono text-[10px] text-text-mute mb-1">peak {max.toFixed(1)} avg people</div>
      <div className="flex items-end gap-[2px] h-40 border-b border-border">
        {timeline.map((p, i) => (
          <div
            key={i}
            className="flex-1 min-w-[2px] rounded-t-sm bg-[var(--ru-working)] transition-[height]"
            style={{ height: `${(p.avg_headcount / max) * 100}%` }}
            title={`${fmtLabel(p.t, kind, tz)} · ${p.avg_headcount} avg`}
          />
        ))}
      </div>
      <div className="flex gap-[2px] mt-1">
        {timeline.map((p, i) => (
          <div
            key={i}
            className="flex-1 text-center text-[9px] text-text-mute font-mono overflow-hidden whitespace-nowrap"
          >
            {i % step === 0 ? fmtLabel(p.t, kind, tz) : ""}
          </div>
        ))}
      </div>
    </div>
  );
}
