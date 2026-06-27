import { useEffect, useMemo, useState } from "react";
import { api, Zone } from "../../api/client";
import type { MetricsSummary } from "../../types";
import { ZoneCard, type ChartView } from "./ZoneCard";

/**
 * Per-zone breakdown panel. For each monitored zone it shows (a) what was being
 * done there — the activity breakdown ("30% welding, 10% idle, …"),
 * worker-weighted over the selected range — and (b) how worker-time split
 * across occupancy levels, with "understaffed time (< N people)" derived
 * client-side from the occupancy histogram. N is query-time; nothing is baked
 * into capture.
 *
 * Reads the persisted metric_samples table via
 * GET /api/cameras/{id}/metrics?since=&until=. The per-zone card itself lives in
 * ./ZoneCard (shared with the Reports page).
 */

const RANGES: { label: string; days: number }[] = [
  { label: "24h", days: 1 },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
];

export default function ZoneOccupancyPanel({ cameraId }: { cameraId: string }) {
  const [days, setDays] = useState(1);
  const [view, setView] = useState<ChartView>("bars");
  const [metrics, setMetrics] = useState<MetricsSummary | undefined>(undefined);
  const [zones, setZones] = useState<Zone[]>([]);

  useEffect(() => {
    api.listZones(cameraId).then(setZones).catch(() => setZones([]));
  }, [cameraId]);

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
        /* transient — keep last snapshot */
      }
    };
    pull();
    const timer = setInterval(pull, 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [cameraId, days]);

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
      </div>

      {cards.length === 0 ? (
        <div className="hint">
          No monitored zones with occupancy data for this range yet. Draw a zone
          (not marked "not monitored") on the Zones tab; data appears after the
          overnight batch processes footage.
        </div>
      ) : (
        cards.map((c) => (
          <ZoneCard key={c.id} name={c.name} occ={c.occ} act={c.act} view={view} />
        ))
      )}
    </section>
  );
}
