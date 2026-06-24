import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, PeriodSummary, ReportPeriod } from "../../api/client";
import { Toolbar } from "../../ui/Toolbar";
import { Panel } from "../../ui/Panel";
import { StatReadout } from "../../ui/StatReadout";
import MetricsBreakdown from "../cameras/MetricsBreakdown";
import { ZoneCard, type ChartView } from "../cameras/ZoneCard";
import StaffingTimelineChart from "./StaffingTimelineChart";

const PERIODS: ReportPeriod[] = ["day", "week", "month"];

const hrs = (s: number) => (s / 3600).toFixed(1);

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function ReportsPage() {
  const { fid } = useParams();
  const [period, setPeriod] = useState<ReportPeriod>("day");
  const [date, setDate] = useState<string>(todayISO);
  const [view, setView] = useState<ChartView>("bars");
  const [summary, setSummary] = useState<PeriodSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // zone_id -> default understaffing N, seeded from authored count_min rules.
  const [zoneN, setZoneN] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!fid) return;
    let alive = true;
    setLoading(true);
    setErr(null);
    api
      .getReport(fid, period, date)
      .then((s) => alive && setSummary(s))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [fid, period, date]);

  // Seed each zone's default understaffing N from its authored count_min rule
  // (the "count thresholds feed reports" wiring). Falls back to 1 per ZoneCard.
  useEffect(() => {
    if (!summary?.cameras.length) {
      setZoneN({});
      return;
    }
    let alive = true;
    (async () => {
      const map: Record<string, number> = {};
      await Promise.all(
        summary.cameras.map(async (cam) => {
          try {
            const rules = await api.listRulesForCamera(cam.camera_id);
            for (const r of rules) {
              const t = Number(r.params?.threshold);
              if (r.trigger_type === "count_min" && r.zone_id && Number.isFinite(t) && t > 0) {
                map[r.zone_id] = t;
              }
            }
          } catch {
            /* rules are optional for the report */
          }
        }),
      );
      if (alive) setZoneN(map);
    })();
    return () => {
      alive = false;
    };
  }, [summary]);

  const fs = summary?.factory_summary;
  const rp = fs?.rollup_pct ?? {};

  return (
    <>
      <Toolbar
        title="Reports"
        subtitle={summary ? summary.factory_name : "Workforce analysis"}
      />

      <Panel className="mb-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="window-tabs">
            {PERIODS.map((p) => (
              <button
                key={p}
                className={`window-tab ${period === p ? "on" : ""}`}
                onClick={() => setPeriod(p)}
              >
                {p[0].toUpperCase() + p.slice(1)}
              </button>
            ))}
          </div>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            aria-label="anchor date"
          />
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
          <a
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg no-underline
                       bg-accent-15 text-accent text-[13px] font-medium hover:bg-surface-highest/40 transition-colors"
            href={fid ? api.reportPdfUrl(fid, period, date) : "#"}
            target="_blank"
            rel="noreferrer"
          >
            Download PDF
          </a>
        </div>
        {summary && (
          <div className="mt-2 text-text-dim text-[12px] font-mono">
            {summary.total_recordings} recordings · {hrs(summary.total_footage_s)} h of footage ·
            timezone {summary.tz}
          </div>
        )}
        {err && <div className="mt-2 text-danger text-[12px] font-mono">{err}</div>}
      </Panel>

      {loading && !summary ? (
        <div className="text-text-dim text-[13px]">Loading…</div>
      ) : !summary ? null : (
        <>
          <div className="grid grid-cols-2 min-[700px]:grid-cols-5 gap-2 mb-4">
            <StatReadout label="worker-hours" value={hrs(fs!.worker_seconds)} unit="h" tone="accent" />
            <StatReadout label="avg people" value={fs!.avg_headcount} />
            <StatReadout label="peak people" value={fs!.peak_headcount} />
            <StatReadout label="working" value={(rp.working ?? 0).toFixed(0)} unit="%" tone="accent" />
            <StatReadout label="idle" value={(rp.idle ?? 0).toFixed(0)} unit="%" tone="danger" />
          </div>

          <Panel title={`Staffing through the ${summary.period}`} className="mb-4">
            <StaffingTimelineChart
              timeline={summary.timeline}
              kind={summary.timeline_kind}
              tz={summary.tz}
            />
          </Panel>

          <Panel title="Activity & status — whole factory" className="mb-4">
            <MetricsBreakdown metrics={fs} />
          </Panel>

          <div className="mb-2 font-mono text-label-caps uppercase text-text-dim">
            By camera · {summary.cameras.length}
          </div>
          {summary.cameras.length === 0 ? (
            <div className="hint">No cameras contributed footage in this period.</div>
          ) : (
            <div className="flex flex-col gap-3">
              {summary.cameras.map((cam) => {
                const occ = cam.summary.zone_occupancy ?? {};
                const act = cam.summary.zone_activity ?? {};
                const crp = cam.summary.rollup_pct ?? {};
                return (
                  <Panel key={cam.camera_id} title={cam.name}>
                    <div className="text-text-dim text-[12px] font-mono mb-3">
                      {hrs(cam.summary.worker_seconds)} h worker-time · avg{" "}
                      {cam.summary.avg_headcount} / peak {cam.summary.peak_headcount} ·{" "}
                      {cam.recordings} recordings · working {(crp.working ?? 0).toFixed(0)}% idle{" "}
                      {(crp.idle ?? 0).toFixed(0)}%
                    </div>
                    <MetricsBreakdown metrics={cam.summary} showMeta={false} />
                    {Object.keys(occ).length > 0 && (
                      <div className="mt-3">
                        {Object.entries(occ).map(([zid, o]) => (
                          <ZoneCard
                            key={zid}
                            name={cam.zone_names[zid] ?? zid}
                            occ={o}
                            act={act[zid]}
                            view={view}
                            defaultN={zoneN[zid]}
                          />
                        ))}
                      </div>
                    )}
                  </Panel>
                );
              })}
            </div>
          )}
        </>
      )}
    </>
  );
}
