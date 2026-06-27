import { useEffect, useState } from "react";
import type { MetricsSummary } from "../../types";
import MetricsBreakdown from "./MetricsBreakdown";

/**
 * Workforce analysis panel — a stacked bar of how worker-time split across
 * rollup categories over a selectable historical range, plus a per-activity
 * breakdown. Reads the persisted metric_samples table via
 * GET /api/cameras/{id}/metrics?since=&until=. The breakdown itself is rendered
 * by the shared <MetricsBreakdown> (also used by the dashboard's
 * WorkforceOverview).
 */

const RANGES: { label: string; days: number }[] = [
  { label: "24h", days: 1 },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
];

export default function AnalysisPanel({ cameraId }: { cameraId: string }) {
  const [days, setDays] = useState(1);
  const [metrics, setMetrics] = useState<MetricsSummary | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const until = new Date();
        const since = new Date(until.getTime() - days * 86400_000);
        const url =
          `/api/cameras/${cameraId}/metrics` +
          `?since=${encodeURIComponent(since.toISOString())}` +
          `&until=${encodeURIComponent(until.toISOString())}`;
        const r = await fetch(url);
        if (!r.ok) return;
        const j = await r.json();
        if (alive) setMetrics(j.metrics as MetricsSummary);
      } catch {
        /* transient — keep the last snapshot */
      }
    };
    pull();
    const timer = setInterval(pull, 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [cameraId, days]);

  return (
    <section className="analysis analysis-h">
      <div className="analysis-head">
        <h3>Workflow analysis</h3>
        <div className="window-tabs">
          {RANGES.map((w) => (
            <button
              key={w.days}
              className={`window-tab ${days === w.days ? "on" : ""}`}
              onClick={() => setDays(w.days)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <MetricsBreakdown metrics={metrics} showMeta />
    </section>
  );
}
