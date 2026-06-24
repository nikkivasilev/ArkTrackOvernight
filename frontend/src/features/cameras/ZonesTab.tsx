import { useCallback, useEffect, useState } from "react";
import { api, Zone } from "../../api/client";
import { useCameraCtx } from "./CameraContext";
import PolygonSvg from "./PolygonSvg";
import { Panel } from "../../ui/Panel";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";

export default function ZonesTab() {
  const { camera } = useCameraCtx();
  const [t, setT] = useState(0);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [imgDims, setImgDims] = useState<{ w: number; h: number } | null>(null);
  const [points, setPoints] = useState<[number, number][]>([]);
  const [closed, setClosed] = useState(false);
  const [zoneName, setZoneName] = useState("");
  const [newZoneExcluded, setNewZoneExcluded] = useState(false);
  const [zones, setZones] = useState<Zone[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setPoints([]);
    setClosed(false);
    setZoneName("");
    setErr(null);
    setImgUrl(api.frameUrl(camera.id, t));
    api.listZones(camera.id).then(setZones).catch(console.error);
  }, [camera.id]);

  useEffect(() => {
    setImgUrl(`${api.frameUrl(camera.id, t)}&_=${Date.now()}`);
  }, [t, camera.id]);

  const onImgLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    setImgDims({ w: img.naturalWidth || 1280, h: img.naturalHeight || 720 });
  }, []);

  const save = useCallback(async () => {
    if (!closed || points.length < 3) return;
    setErr(null);
    try {
      const z = await api.createZone(
        camera.id,
        zoneName || `zone-${zones.length + 1}`,
        points,
        newZoneExcluded,
      );
      setZones((prev) => [...prev, z]);
      setPoints([]);
      setClosed(false);
      setZoneName("");
      setNewZoneExcluded(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [camera.id, closed, points, zoneName, newZoneExcluded, zones.length]);

  const toggleExcluded = useCallback(async (zid: string, excluded: boolean) => {
    const updated = await api.updateZone(zid, { excluded });
    setZones((prev) => prev.map((z) => (z.id === zid ? updated : z)));
  }, []);

  const removeZone = useCallback(async (zid: string) => {
    await api.deleteZone(zid);
    setZones((prev) => prev.filter((z) => z.id !== zid));
  }, []);

  const duration = camera.duration_s ?? 0;
  const dimsForSvg = imgDims ?? { w: 1280, h: 720 };

  return (
    <>
      <Panel
        title="DRAW ZONE"
        className="mb-3"
      >
        <div className="text-text-dim text-[12px] mb-2">
          Click to add vertices. Double-click to close (min 3 points). Drag vertices to adjust.
        </div>
        <div className="editor-wrap">
          {imgUrl && (
            <img
              src={imgUrl}
              onLoad={onImgLoad}
              draggable={false}
              style={{ maxWidth: "100%", maxHeight: "70vh" }}
            />
          )}
          {imgDims && (
            <PolygonSvg
              width={dimsForSvg.w}
              height={dimsForSvg.h}
              points={points}
              onPointsChange={setPoints}
              closed={closed}
              onClose={() => setClosed(true)}
            />
          )}
        </div>
        <div className="flex items-center gap-2.5 mt-3">
          <span className="text-text-dim font-mono text-[12px] tabular-nums">
            t={t.toFixed(2)}s
          </span>
          <input
            type="range"
            min={0}
            max={Math.max(0.001, duration)}
            step={0.1}
            value={t}
            onChange={(e) => setT(parseFloat(e.target.value))}
            className="flex-1"
          />
          <span className="text-text-dim font-mono text-[12px] tabular-nums">
            / {duration.toFixed(1)}s
          </span>
        </div>
        <div className="flex items-center gap-2 mt-3">
          <input
            placeholder="zone name"
            value={zoneName}
            onChange={(e) => setZoneName(e.target.value)}
            className="flex-1"
          />
          <label className="flex items-center gap-1.5 text-text-dim text-[11px] tracking-[0.12em] uppercase mr-2">
            <input
              type="checkbox"
              checked={newZoneExcluded}
              onChange={(e) => setNewZoneExcluded(e.target.checked)}
            />
            not monitored
          </label>
          <Button
            tone="ghost"
            size="sm"
            onClick={() => { setPoints([]); setClosed(false); }}
            disabled={points.length === 0}
          >
            RESET
          </Button>
          <Button tone="primary" size="sm" onClick={save} disabled={!closed}>
            SAVE ZONE
          </Button>
        </div>
        {err && (
          <div className="mt-3 text-danger text-[12px] font-mono">{err}</div>
        )}
      </Panel>

      <Panel title={`ZONES (${zones.length})`}>
        {zones.length === 0 ? (
          <div className="text-text-dim text-[13px]">No zones yet.</div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {zones.map((z) => (
              <div
                key={z.id}
                className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-border bg-surface-high/20 hover:bg-surface-high/40 transition-colors"
              >
                <span className="font-medium text-text">{z.name}</span>
                {z.excluded && <Pill tone="warn">not monitored</Pill>}
                <span className="text-text-dim text-[11px] font-mono tabular-nums">
                  {z.polygon.length} pts
                </span>
                <span className="flex-1" />
                <label className="flex items-center gap-1.5 text-text-dim text-[11px] tracking-[0.12em] uppercase">
                  <input
                    type="checkbox"
                    checked={z.excluded}
                    onChange={(e) => toggleExcluded(z.id, e.target.checked)}
                  />
                  not monitored
                </label>
                <Button tone="danger" size="sm" onClick={() => removeZone(z.id)}>
                  DELETE
                </Button>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </>
  );
}
