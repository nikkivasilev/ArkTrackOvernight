import { useEffect, useMemo, useState } from "react";
import { api, Zone } from "../../api/client";
import type { MetricsSummary } from "../../hooks/useEventsWS";
import { ZoneCard, type ChartView } from "./ZoneCard";

/**
 * Per-zone breakdown panel, embedded in the Live tab below the workflow
 * analysis. For each monitored zone it shows (a) what was being done there —
 * the activity breakdown ("30% welding, 10% idle, …"), worker-weighted over
 * the selectable window — and (b) how worker-time split across occupancy
 * levels, with "understaffed time (< N people)" derived client-side from the
 * occupancy histogram. N is query-time; nothing is baked into capture.
 *
 * Mirrors AnalysisPanel's data plumbing: the default 600 s window is driven by
 * the live WS `state.metrics` (which now carries `zone_occupancy`); other
 * windows fetch once from GET /api/cameras/{id}/metrics and refresh on a timer.
 * The per-zone card itself lives in ./ZoneCard (shared with the Reports page).
 */

const WINDOWS: { label: string; value: number }[] = [
  { label: "1 min", value: 60 },
  { label: "10 min", value: 600 },
  { label: "Session", value: 0 },
  { label: "24h", value: 86400 },
];

export default function ZoneOccupancyPanel({
  cameraId,
  liveMetrics,
}: {
  cameraId: string;
  liveMetrics?: MetricsSummary;
}) {
  const [windowS, setWindowS] = useState(600);
  const [view, setView] = useState<ChartView>("bars");
  const [fetched, setFetched] = useState<MetricsSummary | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);

  useEffect(() => {
    api.listZones(cameraId).then(setZones).catch(() => setZones([]));
  }, [cameraId]);

  // Non-default windows pull a snapshot from REST (the WS only carries 600 s).
  useEffect(() => {
    if (windowS === 600) {
      setFetched(null);
      return;
    }
    let alive = true;
    const pull = async () => {
      try {
        let url: string;
        if (windowS === 86400) {
          const until = new Date();
          const since = new Date(until.getTime() - 86400_000);
          url =
            `/api/cameras/${cameraId}/metrics` +
            `?since=${encodeURIComponent(since.toISOString())}` +
            `&until=${encodeURIComponent(until.toISOString())}`;
        } else {
          url = `/api/cameras/${cameraId}/metrics?window_s=${windowS}`;
        }
        const r = await fetch(url);
        if (!r.ok) return;
        const j = await r.json();
        if (alive) setFetched(j.metrics as MetricsSummary);
      } catch {
        /* transient — keep last snapshot */
      }
    };
    pull();
    const interval = windowS === 86400 ? 30000 : 5000;
    const timer = setInterval(pull, interval);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [cameraId, windowS]);

  const metrics = windowS === 600 ? liveMetrics : fetched ?? undefined;

  // Join occupancy (keyed by zone_id) to names; skip excluded zones.
  const nameById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const z of zones) if (!z.excluded) m[z.id] = z.name;
    return m;
  }, [zones]);

  const cards = useMemo(() => {
    const occ = metrics?.zone_occupancy ?? {};
    const act = metrics?.zone_activity ?? {};
    return Object.entries(occ)
      .filter(([zid]) => zid in nameById)
      .map(([zid, o]) => ({ id: zid, name: nameById[zid], occ: o, act: act[zid] }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [metrics, nameById]);

  return (
    <section className="analysis">
      <div className="analysis-head">
        <h3>Zone breakdown</h3>
        <div className="flex items-center gap-3">
          <div className="window-tabs">
            {(["bars", "pie"] as ChartView[]).map((v) => (
              <button
                key={v}
                className={`window-tab ${view === v ? "on" : ""}`}
                onClick={() => setView(v)}
              >
                {v === "bars" ? "Bars" : "Pie"}
              </button>
            ))}
          </div>
          <div className="window-tabs">
            {WINDOWS.map((w) => (
              <button
                key={w.value}
                className={`window-tab ${windowS === w.value ? "on" : ""}`}
                onClick={() => setWindowS(w.value)}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {cards.length === 0 ? (
        <div className="hint">
          No monitored zones with occupancy data for this window yet. Draw a zone
          (not marked "not monitored") on the Zones tab and let the camera run.
        </div>
      ) : (
        cards.map((c) => (
          <ZoneCard key={c.id} name={c.name} occ={c.occ} act={c.act} view={view} />
        ))
      )}
    </section>
  );
}
