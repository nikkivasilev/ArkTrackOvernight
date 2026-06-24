import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Camera, Site } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { Panel } from "../../ui/Panel";
import { Toolbar } from "../../ui/Toolbar";
import { Button } from "../../ui/Button";
import { Pill, PillTone } from "../../ui/Pill";
import { ConfirmDialog } from "../../ui/ConfirmDialog";
import { Icon } from "../../ui/Icon";

function statusTone(s: Camera["status"]): PillTone {
  switch (s) {
    case "running": return "ok";
    case "failed": return "danger";
    case "cancelled": return "warn";
    case "completed": return "info";
    default: return "neutral";
  }
}

export default function SitePage() {
  const { fid, sid } = useParams();
  const [site, setSite] = useState<Site | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const { cameraStatusOverrides } = useApp();

  const refresh = useCallback(async () => {
    if (!sid) return;
    const [s, cs] = await Promise.all([api.getSite(sid), api.listCamerasForSite(sid)]);
    setSite(s);
    setCameras(cs);
  }, [sid]);

  useEffect(() => {
    refresh().catch(console.error);
  }, [refresh]);

  const remove = useCallback(
    async (cid: string) => {
      await api.deleteCamera(cid);
      refresh();
    },
    [refresh]
  );

  if (!site) return <div className="text-text-dim text-[13px]">Loading…</div>;

  return (
    <>
      <Toolbar title={site.name} subtitle={site.address || `${cameras.length} cameras in this site`}>
        <Link to={`/factories/${fid}/sites/${sid}/cameras/new`}>
          <Button tone="primary" size="sm"><Icon name="add" size={16} /> ADD CAMERA</Button>
        </Link>
      </Toolbar>

      {cameras.length === 0 ? (
        <Panel>
          <div className="text-text-dim text-[13px]">No cameras yet.</div>
        </Panel>
      ) : (
        <div className="flex flex-col gap-2">
          {cameras.map((c) => {
            const override = cameraStatusOverrides[c.id];
            const status = override?.status ?? c.status;
            const error = (override?.error ?? c.error) || null;
            const isWarn = statusTone(status) === "warn";
            return (
              <div
                key={c.id}
                className="group relative flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer bg-surface-high/30 shadow-lg backdrop-blur-xl hover:bg-surface-highest/40 transition-all duration-200 ease-in-out"
              >
                <Link
                  to={`/factories/${fid}/sites/${sid}/cameras/${c.id}`}
                  aria-label={c.name}
                  className="absolute inset-0 rounded-lg"
                />
                <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                  <span className="font-display text-[15px] text-text font-semibold truncate">
                    {c.name}
                  </span>
                  <div className={`${isWarn ? "text-warn" : "text-accent"} text-[11px] font-mono truncate`}>
                    {c.kind} · {c.duration_s ? `${c.duration_s.toFixed(1)}s` : "—"} ·{" "}
                    {c.sampling_fps > 0 ? `${c.sampling_fps} fps` : "Auto fps"} · frame{" "}
                    <span className="tabular-nums">{c.last_processed_frame_idx}</span>
                  </div>
                  {error && (
                    <div className="text-danger text-[11px] font-mono truncate">
                      {error.split("\n")[0]}
                    </div>
                  )}
                </div>
                <Pill tone={statusTone(status)} dot>{status}</Pill>
                <div className="relative z-10">
                  <ConfirmDialog
                    title="DELETE CAMERA"
                    body={
                      <>
                        Delete <span className="font-medium text-text">{c.name}</span> and all its
                        zones, rules, and alerts? This cannot be undone.
                      </>
                    }
                    confirmLabel="DELETE"
                    onConfirm={() => remove(c.id)}
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
