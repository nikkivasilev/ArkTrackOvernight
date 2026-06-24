import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ProcessedRecording } from "../../api/client";
import { Toolbar } from "../../ui/Toolbar";
import { Panel } from "../../ui/Panel";

const FILTERS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "Done", value: "done" },
  { label: "Processing", value: "processing" },
  { label: "Failed", value: "failed" },
];

const dt = (s: string | null) =>
  s ? new Date(s).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" }) : "—";

function StatusPill({ status }: { status: string }) {
  const cls =
    status === "done"
      ? "bg-accent-15 text-accent"
      : status === "failed"
        ? "bg-danger/15 text-danger"
        : "bg-amber/15 text-amber";
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-mono ${cls}`}>
      {status}
    </span>
  );
}

export default function RecordingsPage() {
  const { fid } = useParams();
  const [recs, setRecs] = useState<ProcessedRecording[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!fid) return;
    let alive = true;
    setLoading(true);
    setErr(null);
    api
      .listRecordings(fid, status || undefined)
      .then((r) => alive && setRecs(r))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [fid, status]);

  return (
    <>
      <Toolbar title="Recordings" subtitle="Ingested footage & processing status" />

      <Panel className="mb-4">
        <div className="window-tabs">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              className={`window-tab ${status === f.value ? "on" : ""}`}
              onClick={() => setStatus(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
        {err && <div className="mt-2 text-danger text-[12px] font-mono">{err}</div>}
      </Panel>

      {loading && recs.length === 0 ? (
        <div className="text-text-dim text-[13px]">Loading…</div>
      ) : recs.length === 0 ? (
        <div className="hint">
          No recordings yet. Drop NVR files into the watched folder (data/incoming) — the
          batch ingest creates a camera per label and processes each file automatically.
        </div>
      ) : (
        <div className="overflow-x-auto glass rounded-xl">
          <table className="w-full text-[12px] border-collapse">
            <thead>
              <tr className="text-text-dim font-mono uppercase text-[10px] tracking-wider">
                <th className="text-left px-3 py-2 font-medium">Camera</th>
                <th className="text-left px-3 py-2 font-medium">File</th>
                <th className="text-left px-3 py-2 font-medium">Recorded</th>
                <th className="text-right px-3 py-2 font-medium">Footage</th>
                <th className="text-right px-3 py-2 font-medium">Frames</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-left px-3 py-2 font-medium">On disk</th>
              </tr>
            </thead>
            <tbody>
              {recs.map((r) => (
                <tr key={r.id} className="border-t border-border align-top">
                  <td className="px-3 py-2 whitespace-nowrap">{r.camera_name ?? "—"}</td>
                  <td className="px-3 py-2 max-w-[280px]">
                    <div className="truncate font-mono" title={r.filename}>
                      {r.filename}
                    </div>
                    {r.error && (
                      <div className="text-danger text-[11px] font-mono mt-0.5 truncate" title={r.error}>
                        {r.error}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap font-mono text-text-dim">
                    {dt(r.recorded_start)} → {dt(r.recorded_end)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {(r.footage_s / 3600).toFixed(2)} h
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.frames.toLocaleString()}</td>
                  <td className="px-3 py-2">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="px-3 py-2">
                    {r.file_exists ? (
                      <span className="text-accent text-[11px] font-mono">● yes</span>
                    ) : (
                      <span className="text-amber text-[11px] font-mono">● missing</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
