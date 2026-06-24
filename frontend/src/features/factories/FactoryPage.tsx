import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Factory, Site } from "../../api/client";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Toolbar } from "../../ui/Toolbar";

export default function FactoryPage() {
  const { fid } = useParams();
  const [factory, setFactory] = useState<Factory | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [camCounts, setCamCounts] = useState<Record<string, { active: number; total: number }>>({});
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!fid) return;
    const [f, ss] = await Promise.all([api.getFactory(fid), api.listSitesForFactory(fid)]);
    setFactory(f);
    setSites(ss);
    // Per-site camera counts (active = running) for the row stats.
    const camLists = await Promise.all(ss.map((s) => api.listCamerasForSite(s.id)));
    const counts: Record<string, { active: number; total: number }> = {};
    ss.forEach((s, i) => {
      const cams = camLists[i];
      counts[s.id] = {
        active: cams.filter((c) => c.status === "running").length,
        total: cams.length,
      };
    });
    setCamCounts(counts);
  }, [fid]);

  useEffect(() => {
    refresh().catch(console.error);
  }, [refresh]);

  const create = useCallback(async () => {
    if (!fid) return;
    setErr(null);
    try {
      await api.createSite(fid, { name, address: address || undefined });
      setName("");
      setAddress("");
      refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [fid, name, address, refresh]);

  const remove = useCallback(
    async (sid: string) => {
      await api.deleteSite(sid);
      refresh();
    },
    [refresh]
  );

  if (!factory) return <div className="text-text-dim text-[13px]">Loading…</div>;

  return (
    <>
      <Toolbar
        title={factory.name}
        subtitle={factory.address || "Factory overview"}
      />

      <div className="flex flex-wrap gap-2 mb-4">
        <Link
          to={`/factories/${fid}/reports`}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg no-underline
                     bg-accent-15 text-accent text-[13px] font-medium hover:bg-surface-highest/40 transition-colors"
        >
          Reports
        </Link>
        <Link
          to={`/factories/${fid}/recordings`}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg no-underline
                     bg-surface-high/40 text-text text-[13px] font-medium hover:bg-surface-highest/40 transition-colors"
        >
          Recordings
        </Link>
      </div>

      <Panel title="NEW SITE" className="mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <input
            placeholder="Name (e.g. Plant A)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ flex: "1 1 200px" }}
          />
          <input
            placeholder="Address (optional)"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            style={{ flex: "1 1 200px" }}
          />
          <Button tone="primary" size="sm" onClick={create} disabled={!name.trim()}>
            CREATE
          </Button>
        </div>
        {err && <div className="mt-2 text-danger text-[12px] font-mono">{err}</div>}
      </Panel>

      <div className="mb-2 font-mono text-label-caps uppercase text-text-dim">
        Sites · {sites.length}
      </div>
      {sites.length === 0 ? (
        <div className="text-text-dim text-[13px]">No sites yet.</div>
      ) : (
        <div className="flex flex-col gap-2">
          {sites.map((s) => {
            const cc = camCounts[s.id];
            const active = cc?.active ?? 0;
            const inactive = cc ? cc.total - cc.active : 0;
            return (
              <div
                key={s.id}
                className="group relative flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer bg-[var(--glass-bg)] backdrop-blur-xl shadow-[0_2px_8px_-2px_rgba(0,0,0,0.35)] hover:bg-surface-highest/40 transition-all duration-200 ease-in-out"
              >
                <Link
                  to={`/factories/${fid}/sites/${s.id}`}
                  aria-label={s.name}
                  className="absolute inset-0 rounded-lg"
                />
                <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                  <span className="font-display text-[15px] text-text font-semibold truncate">
                    {s.name}
                  </span>
                  <span className="text-accent text-[12px] font-mono truncate">
                    {s.address ?? "—"}
                  </span>
                </div>
                <div className="flex items-center gap-3 font-mono text-[11px] whitespace-nowrap">
                  <span className="flex items-center gap-1.5 text-accent">
                    <span className="size-1.5 rounded-full bg-accent" />
                    <span className="tabular-nums">{active}</span> active
                  </span>
                  <span className="flex items-center gap-1.5 text-text-mute">
                    <span className="size-1.5 rounded-full bg-text-mute" />
                    <span className="tabular-nums">{inactive}</span> inactive
                  </span>
                </div>
                <div className="relative z-10">
                  <ConfirmDialog
                    title="DELETE SITE"
                    body={
                      <>
                        Delete <span className="font-medium text-text">{s.name}</span> and all its
                        cameras, zones, rules, and alerts? This cannot be undone.
                      </>
                    }
                    confirmLabel="DELETE"
                    onConfirm={() => remove(s.id)}
                    trigger={<Button tone="danger" size="sm">DELETE</Button>}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
