import { useMemo, useState } from "react";
import type { ZoneOccupancy, ZoneActivity } from "../../hooks/useEventsWS";

/**
 * Presentational per-zone breakdown card: a worker-weighted activity breakdown
 * + an occupancy distribution (bars or donut) + a client-side "understaffed
 * (< N people)" readout derived from the occupancy histogram. Extracted from
 * ZoneOccupancyPanel so both the Live zone panel and the offline Reports page
 * render zones with one component.
 */

export type ChartView = "bars" | "pie";

export function fmtSeconds(s: number): string {
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

// Color a given occupancy count: 0 (empty) reads as danger, then a cool→warm
// ramp toward higher staffing. Capped so 6+ all share the top color.
function countColor(count: number): string {
  if (count <= 0) return "var(--danger)";
  const ramp = ["#3a4b66", "#3f6fb0", "#4ea1ff", "#54c08a", "#66d39a", "#7fe0a8"];
  return ramp[Math.min(count - 1, ramp.length - 1)];
}

function understaffed(occ: ZoneOccupancy, n: number): { seconds: number; pct: number } {
  let lt = 0;
  for (const [k, s] of Object.entries(occ.seconds_at)) {
    if (parseInt(k, 10) < n) lt += s;
  }
  const pct = occ.total_s > 0 ? (100 * lt) / occ.total_s : 0;
  return { seconds: lt, pct };
}

// Activity label → color. Falls back to the neutral "unknown" swatch for any
// label without a dedicated --act-* var (e.g. sitting / on_phone), so a pie
// segment never renders as an undefined (transparent) color.
function activityColor(key: string): string {
  return `var(--act-${key}, var(--act-unknown))`;
}

type BreakdownItem = { key: string; label: string; pct: number; seconds: number; color: string };

// Shared compact legend: colored dot · name · bold % · muted seconds. Grid
// columns line the % and seconds up across rows. Used beside the donut (pie)
// and below the stacked bar (occupancy in bars view).
function Legend({ items }: { items: BreakdownItem[] }) {
  return (
    <ul className="zone-legend">
      {items.map((it) => (
        <li key={it.key}>
          <span className="dot" style={{ background: it.color }} />
          <span className="nm">{it.label}</span>
          <span className="val">{it.pct}%</span>
          <span className="sub">{fmtSeconds(it.seconds)}</span>
        </li>
      ))}
    </ul>
  );
}

// A donut (conic-gradient ring + hole) beside the shared legend. Segment
// proportions come from `seconds` (exact) rather than the rounded `pct`.
function BreakdownPie({ items }: { items: BreakdownItem[] }) {
  const total = items.reduce((s, it) => s + it.seconds, 0) || 1;
  let acc = 0;
  const stops = items.map((it) => {
    const a = (acc / total) * 360;
    acc += it.seconds;
    const b = (acc / total) * 360;
    return `${it.color} ${a.toFixed(2)}deg ${b.toFixed(2)}deg`;
  });
  return (
    <div className="zone-pie-wrap">
      <div className="zone-pie" style={{ background: `conic-gradient(${stops.join(", ")})` }} />
      <Legend items={items} />
    </div>
  );
}

export function ZoneCard({
  name,
  occ,
  act,
  view,
  defaultN = 1,
}: {
  name: string;
  occ: ZoneOccupancy;
  act?: ZoneActivity;
  view: ChartView;
  // Initial understaffing threshold; seeded from an authored count_min rule on
  // the Reports page, else 1. The operator can still adjust it with the stepper.
  defaultN?: number;
}) {
  const [n, setN] = useState(defaultN);
  const us = understaffed(occ, n);

  const segs = useMemo(
    () =>
      Object.entries(occ.seconds_at)
        .map(([k, s]) => ({ count: parseInt(k, 10), seconds: s }))
        .sort((a, b) => a.count - b.count)
        .filter((d) => d.seconds > 0),
    [occ],
  );
  const total = occ.total_s || 1;

  // What's being done in the zone — worker-weighted activity breakdown.
  const actRows = useMemo(() => {
    const pct = act?.pct ?? {};
    const secs = act?.seconds ?? {};
    return Object.entries(pct)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ key: k, pct: v, seconds: secs[k] ?? 0 }));
  }, [act]);

  // Occupancy distribution as legend/pie items (% of total observed time).
  const occItems: BreakdownItem[] = segs.map((d) => ({
    key: String(d.count),
    label: `${d.count} ${d.count === 1 ? "person" : "people"}`,
    pct: Math.round((100 * d.seconds) / total),
    seconds: d.seconds,
    color: countColor(d.count),
  }));

  return (
    <div className="rounded-lg border border-border bg-surface-high/20 p-3 mb-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium">{name}</span>
        <span className="text-text-dim text-[11px] font-mono">
          avg {occ.avg.toFixed(2)} · peak {occ.peak}
        </span>
      </div>

      <div className="zone-sections">
        {actRows.length > 0 && (
          <div className="zone-section">
            <h4>Activity</h4>
            {view === "pie" ? (
              <BreakdownPie
                items={actRows.map((a) => ({
                  key: a.key,
                  label: a.key,
                  pct: a.pct,
                  seconds: a.seconds,
                  color: activityColor(a.key),
                }))}
              />
            ) : (
              <div className="activity-bars">
                {actRows.map((a) => (
                  <div key={a.key} className="activity-bar-row">
                    <span className={`activity-bar-name activity-${a.key}`}>{a.key}</span>
                    <div className="activity-bar-track">
                      <div
                        className={`activity-bar-fill activity-bg-${a.key}`}
                        style={{ width: `${a.pct}%` }}
                      />
                    </div>
                    <span className="activity-bar-pct">{a.pct}%</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="zone-section">
          <h4>Occupancy</h4>
          {view === "pie" ? (
            <BreakdownPie items={occItems} />
          ) : (
            <>
              <div className="stacked-bar">
                {occItems.map((d) => (
                  <div
                    key={d.key}
                    className="seg"
                    style={{ width: `${(100 * d.seconds) / total}%`, background: d.color }}
                    title={`${d.label} — ${fmtSeconds(d.seconds)}`}
                  />
                ))}
              </div>
              <Legend items={occItems} />
            </>
          )}

          <div className="zone-understaffed">
            <span>understaffed (&lt;</span>
            <div className="zone-stepper">
              <button onClick={() => setN((v) => Math.max(1, v - 1))}>−</button>
              <span>{n}</span>
              <button onClick={() => setN((v) => v + 1)}>+</button>
            </div>
            <span>people):</span>
            <span className="font-mono text-warn">{fmtSeconds(us.seconds)}</span>
            <span className="font-mono">({us.pct.toFixed(0)}%)</span>
          </div>
        </div>
      </div>
    </div>
  );
}
