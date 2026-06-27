import { useMemo } from "react";
import type { MetricsSummary } from "../../types";

/**
 * Presentational breakdown of a MetricsSummary: a stacked status (rollup) bar
 * + legend, an optional avg/peak/worker-time meta line, and a by-activity
 * breakdown. Shared by the per-camera AnalysisPanel and the system-wide
 * dashboard WorkforceOverview so there's one renderer, not two copies.
 *
 * `showMeta` toggles the "avg N workers · peak M · Xs worker-time" line —
 * AnalysisPanel shows it; the dashboard overview renders its own StatReadouts
 * instead and passes showMeta={false}.
 */

// Order + color for rollup categories. Mirrors the STATUS OVERVIEW palette.
// "motion" is intentionally absent — unconfirmed motion tracks no longer
// surface as a rollup; they only suggest ROIs to D-FINE.
const ROLLUP_ORDER = ["working", "moving", "idle", "group_idle", "unclear"];
const ROLLUP_COLOR: Record<string, string> = {
  working: "var(--ru-working)",
  moving: "var(--ru-moving)",
  idle: "var(--ru-idle)",
  group_idle: "var(--ru-group_idle)",
  unclear: "var(--ru-unclear)",
};

export function fmtSeconds(s: number): string {
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

export default function MetricsBreakdown({
  metrics,
  showMeta = true,
}: {
  metrics?: MetricsSummary;
  showMeta?: boolean;
}) {
  const rollupRows = useMemo(() => {
    const pct = metrics?.rollup_pct ?? {};
    const secs = metrics?.rollup_seconds ?? {};
    const keys = [
      ...ROLLUP_ORDER.filter((k) => (pct[k] ?? 0) > 0),
      ...Object.keys(pct).filter((k) => !ROLLUP_ORDER.includes(k) && pct[k] > 0),
    ];
    return keys.map((k) => ({
      key: k,
      pct: pct[k] ?? 0,
      seconds: secs[k] ?? 0,
      color: ROLLUP_COLOR[k] ?? "var(--ru-unclear)",
    }));
  }, [metrics]);

  const activityRows = useMemo(() => {
    const pct = metrics?.activity_pct ?? {};
    const secs = metrics?.activity_seconds ?? {};
    return Object.entries(pct)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ key: k, pct: v, seconds: secs[k] ?? 0 }));
  }, [metrics]);

  const hasData = (metrics?.worker_seconds ?? 0) > 0;
  if (!hasData) return <div className="hint">No data for this window yet.</div>;

  return (
    <>
      <div className="stacked-bar">
        {rollupRows.map((r) => (
          <div
            key={r.key}
            className="seg"
            style={{ width: `${r.pct}%`, background: r.color }}
            title={`${r.key} — ${r.pct}%`}
          />
        ))}
      </div>
      <div className="analysis-legend">
        {rollupRows.map((r) => (
          <div key={r.key} className="legend-row">
            <span className="swatch" style={{ background: r.color }} />
            <span className="legend-name">{r.key}</span>
            <span className="legend-pct">{r.pct}%</span>
            <span className="legend-secs">{fmtSeconds(r.seconds)}</span>
          </div>
        ))}
      </div>

      {showMeta && (
        <div className="analysis-meta">
          avg {metrics?.avg_headcount ?? 0} workers · peak{" "}
          {metrics?.peak_headcount ?? 0} · {fmtSeconds(metrics?.worker_seconds ?? 0)}{" "}
          worker-time
        </div>
      )}

      {activityRows.length > 0 && (
        <>
          <h4>By activity</h4>
          <div className="activity-bars">
            {activityRows.map((a) => (
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
        </>
      )}
    </>
  );
}
