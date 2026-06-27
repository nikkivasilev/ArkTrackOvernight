import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, Factory, PeriodSummary, ReportPeriod } from "../../api/client";
import { Toolbar } from "../../ui/Toolbar";
import { Panel } from "../../ui/Panel";
import { StatReadout } from "../../ui/StatReadout";
import { Icon } from "../../ui/Icon";
import MetricsBreakdown from "../cameras/MetricsBreakdown";
import { ZoneCard, type ChartView } from "../cameras/ZoneCard";
import StaffingTimelineChart from "../reports/StaffingTimelineChart";

const hrs = (s: number) => (s / 3600).toFixed(1);

const todayISO = () => new Date().toISOString().slice(0, 10);
function daysAgoISO(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

type PresetKey = ReportPeriod | "7d" | "30d" | "all" | "custom";
const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "all", label: "All-time" },
  { key: "custom", label: "Custom" },
];
const PERIOD_KEYS: PresetKey[] = ["day", "week", "month"];

type Query =
  | { kind: "period"; period: ReportPeriod; date: string }
  | { kind: "range"; start: string; end: string };

export default function DashboardPage() {
  const [params, setParams] = useSearchParams();

  const [factories, setFactories] = useState<Factory[]>([]);
  const [factoryId, setFactoryId] = useState<string>(params.get("factory") ?? "");
  const [preset, setPreset] = useState<PresetKey>("all");
  const [anchorDate, setAnchorDate] = useState<string>(todayISO);
  const [customStart, setCustomStart] = useState<string>("");
  const [customEnd, setCustomEnd] = useState<string>("");
  const [extent, setExtent] = useState<{ min: string | null; max: string | null } | null>(null);
  const [view, setView] = useState<ChartView>("bars");

  const [summary, setSummary] = useState<PeriodSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [zoneN, setZoneN] = useState<Record<string, number>>({});

  // Load factories; default the selection to the URL's ?factory or the first.
  useEffect(() => {
    api.listFactories().then((fs) => {
      setFactories(fs);
      setFactoryId((cur) => cur || params.get("factory") || fs[0]?.id || "");
    }).catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the URL in sync so per-factory links (/dashboard?factory=…) deep-link.
  useEffect(() => {
    if (!factoryId) return;
    if (params.get("factory") !== factoryId) {
      setParams((p) => { p.set("factory", factoryId); return p; }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [factoryId]);

  // Data extent powers "All-time" and seeds the Custom pickers.
  useEffect(() => {
    if (!factoryId) return;
    setExtent(null);
    api.dataExtent(factoryId).then((ext) => {
      setExtent(ext);
      if (ext.min && ext.max) {
        setCustomStart((s) => s || ext.min!.slice(0, 10));
        setCustomEnd((e) => e || ext.max!.slice(0, 10));
      }
    }).catch(() => setExtent({ min: null, max: null }));
  }, [factoryId]);

  // Resolve the active controls into a concrete query (or null while pending).
  const query: Query | null = useMemo(() => {
    if (PERIOD_KEYS.includes(preset)) {
      return { kind: "period", period: preset as ReportPeriod, date: anchorDate };
    }
    if (preset === "7d") return { kind: "range", start: daysAgoISO(6), end: todayISO() };
    if (preset === "30d") return { kind: "range", start: daysAgoISO(29), end: todayISO() };
    if (preset === "all") {
      if (!extent?.min || !extent?.max) return null;
      return { kind: "range", start: extent.min.slice(0, 10), end: extent.max.slice(0, 10) };
    }
    if (preset === "custom") {
      if (!customStart || !customEnd) return null;
      return { kind: "range", start: customStart, end: customEnd };
    }
    return null;
  }, [preset, anchorDate, customStart, customEnd, extent]);

  // Fetch the summary whenever the factory or query changes.
  useEffect(() => {
    if (!factoryId || !query) {
      setSummary(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setErr(null);
    const p = query.kind === "period"
      ? api.getReport(factoryId, query.period, query.date)
      : api.getReportRange(factoryId, query.start, query.end);
    p.then((s) => alive && setSummary(s))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [factoryId, query]);

  // Seed each zone's understaffing N from its authored count_min rule.
  useEffect(() => {
    if (!summary?.cameras.length) { setZoneN({}); return; }
    let alive = true;
    (async () => {
      const map: Record<string, number> = {};
      await Promise.all(summary.cameras.map(async (cam) => {
        try {
          const rules = await api.listRulesForCamera(cam.camera_id);
          for (const r of rules) {
            const t = Number(r.params?.threshold);
            if (r.trigger_type === "count_min" && r.zone_id && Number.isFinite(t) && t > 0) {
              map[r.zone_id] = t;
            }
          }
        } catch { /* rules optional */ }
      }));
      if (alive) setZoneN(map);
    })();
    return () => { alive = false; };
  }, [summary]);

  const pdfHref = !factoryId || !query
    ? "#"
    : query.kind === "period"
      ? api.reportPdfUrl(factoryId, query.period, query.date)
      : api.reportRangePdfUrl(factoryId, query.start, query.end);

  const fs = summary?.factory_summary;
  const rp = fs?.rollup_pct ?? {};

  return (
    <>
      <Toolbar title="Analytics" subtitle={summary?.factory_name ?? "Processed workforce metrics"}>
        {factories.length > 0 && (
          <select
            value={factoryId}
            onChange={(e) => setFactoryId(e.target.value)}
            aria-label="factory"
            className="h-9 px-3 rounded-lg border border-input bg-surface-low/60 text-text text-[13px]
                       hover:border-accent-40 focus:outline-none focus:border-accent transition-colors"
          >
            {factories.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        )}
      </Toolbar>

      <Panel className="mb-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="window-tabs">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                className={`window-tab ${preset === p.key ? "on" : ""}`}
                onClick={() => setPreset(p.key)}
              >
                {p.label}
              </button>
            ))}
          </div>

          {PERIOD_KEYS.includes(preset) && (
            <input
              type="date"
              value={anchorDate}
              onChange={(e) => setAnchorDate(e.target.value)}
              aria-label="anchor date"
            />
          )}
          {preset === "custom" && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={customStart}
                max={customEnd || undefined}
                onChange={(e) => setCustomStart(e.target.value)}
                aria-label="from date"
              />
              <span className="text-text-dim text-[12px]">to</span>
              <input
                type="date"
                value={customEnd}
                min={customStart || undefined}
                onChange={(e) => setCustomEnd(e.target.value)}
                aria-label="to date"
              />
            </div>
          )}

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
            className={`ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg no-underline
                       text-[13px] font-medium transition-colors
                       ${query ? "bg-accent-15 text-accent hover:bg-surface-highest/40"
                               : "bg-surface-high/30 text-text-mute pointer-events-none"}`}
            href={pdfHref}
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="download" size={16} /> Download PDF
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

      {!factoryId ? (
        <Panel><div className="text-text-dim text-[13px]">No factories yet. Create one under Factory Sites.</div></Panel>
      ) : loading && !summary ? (
        <div className="text-text-dim text-[13px]">Loading…</div>
      ) : !summary ? (
        preset === "all" && extent && !extent.min ? (
          <Panel><div className="text-text-dim text-[13px]">No processed metrics for this factory yet. Run the overnight batch to populate analytics.</div></Panel>
        ) : null
      ) : (
        <>
          <div className="grid grid-cols-2 min-[700px]:grid-cols-5 gap-2 mb-4">
            <StatReadout label="worker-hours" value={hrs(fs!.worker_seconds)} unit="h" tone="accent" />
            <StatReadout label="avg people" value={fs!.avg_headcount} />
            <StatReadout label="peak people" value={fs!.peak_headcount} />
            <StatReadout label="working" value={(rp.working ?? 0).toFixed(0)} unit="%" tone="accent" />
            <StatReadout label="idle" value={(rp.idle ?? 0).toFixed(0)} unit="%" tone="danger" />
          </div>

          <Panel title="Staffing over the selected range" className="mb-4">
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
            <div className="hint">No cameras contributed footage in this range.</div>
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
