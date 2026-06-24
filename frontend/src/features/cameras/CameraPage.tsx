import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";
import { api, Camera } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { CameraCtx } from "./CameraContext";
import { Toolbar } from "../../ui/Toolbar";
import { Button } from "../../ui/Button";
import { CameraStatusBadge } from "./CameraStatusBadge";

export default function CameraPage() {
  const { fid, sid, cid } = useParams();
  const [camera, setCamera] = useState<Camera | null>(null);
  const { cameraStatusOverrides } = useApp();

  const refresh = useCallback(async () => {
    if (!cid) return;
    setCamera(await api.getCamera(cid));
  }, [cid]);

  useEffect(() => {
    refresh().catch(console.error);
  }, [refresh]);

  if (!camera) return <div className="text-text-dim text-[13px]">Loading…</div>;

  const override = cameraStatusOverrides[camera.id];
  const status = override?.status ?? camera.status;
  const error = (override?.error ?? camera.error) || null;
  const base = `/factories/${fid}/sites/${sid}/cameras/${cid}`;

  const restart = async () => {
    await api.startCamera(camera.id);
    refresh();
  };
  const cancel = async () => {
    await api.cancelCamera(camera.id);
    refresh();
  };

  return (
    <CameraCtx.Provider value={{ camera, refresh }}>
      <Toolbar
        title={camera.name}
        subtitle={
          <span className="flex items-center gap-2">
            <CameraStatusBadge status={status} />
            <span className="font-mono text-text-dim text-[11px] tabular-nums">
              {camera.sampling_fps > 0 ? `${camera.sampling_fps} fps` : "Auto"} · frame {camera.last_processed_frame_idx}
            </span>
          </span>
        }
      >
        {status === "running" ? (
          <Button tone="danger" size="sm" onClick={cancel}>Cancel</Button>
        ) : (
          <Button tone="primary" size="sm" onClick={restart}>Restart</Button>
        )}
      </Toolbar>

      {error && (
        <div className="mb-3 px-4 py-2 border border-danger-35 bg-danger-10 text-danger text-[12px] font-mono whitespace-pre-wrap rounded-lg">
          {error.split("\n")[0]}
        </div>
      )}

      <nav className="flex gap-2 mb-4">
        {[
          ["Live", "live"],
          ["Zones", "zones"],
          ["Rules", "rules"],
        ].map(([label, slug]) => (
          <NavLink
            key={slug}
            to={`${base}/${slug}`}
            className={({ isActive }) =>
              `
                px-4 py-1.5 rounded-md border font-mono text-[11px] font-semibold uppercase tracking-wider no-underline
                transition-all duration-150
                ${isActive
                  ? "bg-accent-15 border-accent-30 text-accent"
                  : "border-transparent text-text-dim hover:text-text hover:bg-surface-high/40"}
              `
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </CameraCtx.Provider>
  );
}
