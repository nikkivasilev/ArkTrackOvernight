import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { useCameraState } from "../../hooks/useCameraState";
import type { TrackEntry } from "../../hooks/useEventsWS";
import { useCameraCtx } from "./CameraContext";
import AnalysisPanel from "./AnalysisPanel";
import ZoneOccupancyPanel from "./ZoneOccupancyPanel";
import TrackTimeline from "./TrackTimeline";
import LiveZonesOverlay from "./LiveZonesOverlay";
import { Hud, HudItem } from "../../ui/Hud";
import { StatReadout } from "../../ui/StatReadout";
import { Pill } from "../../ui/Pill";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";

// "motion" is no longer a public rollup — unconfirmed motion tracks now feed
// D-FINE as a suggestor only and never enter state.tracks. (See pipeline_render
// step 5.) Keep ROLLUPS in display order.
const ROLLUPS = ["working", "moving", "idle", "group_idle", "unclear"] as const;
type Rollup = typeof ROLLUPS[number];

const ROLLUP_LABEL: Record<Rollup, string> = {
  working: "WORKING",
  moving: "MOVING",
  idle: "IDLE",
  group_idle: "GROUP_IDLE",
  unclear: "UNCLEAR",
};

const ROLLUP_TONE: Record<Rollup, "ok" | "accent" | "warn" | "neutral"> = {
  working: "ok",
  moving: "accent",
  idle: "warn",
  group_idle: "neutral",
  unclear: "neutral",
};

export default function LiveTab() {
  const { camera } = useCameraCtx();
  const [streamKey, setStreamKey] = useState(0);
  const liveUrl = `${api.liveUrl(camera.id)}?_=${streamKey}`;
  const { state, wsConnected } = useCameraState(camera.id);

  const tracks: TrackEntry[] = state?.tracks ?? [];
  const rollupCounts = state?.rollup_counts ?? {};
  const orphanWelders = state?.orphan_welding_count ?? 0;

  const activityCounts = useMemo(
    () =>
      Object.entries(state?.activity_counts ?? {})
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1]),
    [state?.activity_counts],
  );

  const hudItems: HudItem[] = state
    ? [
        { label: "FRAME", value: state.frame, tone: "accent" },
        { label: "T", value: `${state.t.toFixed(1)}s` },
        { label: "SRC FPS", value: state.src_fps },
        { label: "D-FINE", value: `${state.yolo_ms}ms`, tone: state.yolo_ms > 80 ? "warn" : "neutral" },
        { label: "DETS", value: state.n_dets, tone: "accent" },
        ...(state.n_phantoms > 0
          ? [{ label: "PHANTOM", value: state.n_phantoms, tone: "danger" as const }]
          : []),
        { label: "WS", value: wsConnected ? "LIVE" : "OFF", tone: wsConnected ? "ok" : "danger" },
      ]
    : [];

  return (
    <div className="dash">
      <div className="dash-header">
        <div className="flex items-baseline gap-3">
          <h2 className="m-0 font-display text-[18px] font-semibold tracking-tight text-text">
            {camera.name}
          </h2>
          <span className="font-mono text-label-caps text-text-mute uppercase">
            live operator view
          </span>
        </div>
        {state ? (
          <Hud items={hudItems} />
        ) : (
          <span className="text-[11px] tracking-[0.16em] text-text-dim uppercase font-mono">
            waiting for frames…
          </span>
        )}
      </div>

      <div className="dash-body">
        <div className="dash-video">
          <img key={liveUrl} src={liveUrl} alt="live feed" />
          <LiveZonesOverlay cameraId={camera.id} />
          <Button
            tone="ghost"
            size="sm"
            onClick={() => setStreamKey((k) => k + 1)}
            className="absolute bottom-2.5 right-2.5 glass !text-text"
          >
            <Icon name="sync" size={14} /> RECONNECT
          </Button>
        </div>

        <aside className="dash-side">
          <div className="dash-side-inner">
          <h3 className="m-0 mb-2 font-mono text-label-caps uppercase text-accent">
            Status
          </h3>
          <div className="grid grid-cols-2 gap-1.5 mb-4">
            {ROLLUPS.map((r) => (
              <StatReadout
                key={r}
                label={ROLLUP_LABEL[r]}
                value={rollupCounts[r] ?? 0}
                tone={ROLLUP_TONE[r]}
                size="sm"
              />
            ))}
          </div>

          <h3 className="m-0 mb-2 font-mono text-label-caps uppercase text-accent">
            Live workers
          </h3>
          {/*
            Fixed-height 2-row pill box: locks the section's vertical footprint
            so the sidebar below it doesn't jitter when pills enter/leave or
            wrap to a new row. Overflow scrolls vertically when there are more
            workers than fit. Same height in both empty and populated states.
          */}
          <div className="h-[48px] mb-4 overflow-y-auto">
            {activityCounts.length === 0 && orphanWelders === 0 ? (
              <div className="text-text-dim text-[12px]">No active workers yet.</div>
            ) : (
              <div className="flex flex-wrap gap-1 content-start">
                {activityCounts.map(([name, count]) => (
                  <Pill key={name} tone="info">
                    {name} <span className="font-mono tabular-nums">{count}</span>
                  </Pill>
                ))}
                {orphanWelders > 0 ? (
                  <Pill tone="danger" title="arc detected with no attributed worker">
                    welding (anon){" "}
                    <span className="font-mono tabular-nums">{orphanWelders}</span>
                  </Pill>
                ) : null}
              </div>
            )}
          </div>

          <h3 className="m-0 mb-2 font-mono text-label-caps uppercase text-accent">
            Tracks{" "}
            <span className="font-mono tabular-nums text-text">({tracks.length})</span>
          </h3>
          <div className="relative flex-1 min-h-0 max-h-66 overflow-y-auto border border-border rounded-lg no-scrollbar">
            <table className="track-table">
              <thead className="sticky top-0 bg-surface-container z-10">
                <tr>
                  <th>ID</th>
                  <th>Activity</th>
                  <th>Conf</th>
                </tr>
              </thead>
              <tbody>
                {tracks.map((t) => {
                  const rowCls = [
                    `activity-${t.activity}`,
                    t.phantom ? "phantom" : "",
                    t.ghost ? "ghost" : "",
                    t.motion_only ? "motion-only" : "",
                  ].filter(Boolean).join(" ");
                  return (
                    <tr key={t.track_id} className={rowCls}>
                      <td>{t.label}</td>
                      <td>
                        {t.activity}
                        {t.vlm_activity ? <span className="vlm-badge">vlm</span> : null}
                        {t.ghost && t.stale_s !== undefined ? (
                          <span className="stale-badge">stale {t.stale_s.toFixed(1)}s</span>
                        ) : null}
                      </td>
                      <td>{t.conf.toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          </div>
        </aside>
      </div>

      <TrackTimeline state={state} />

      <AnalysisPanel cameraId={camera.id} liveMetrics={state?.metrics} />

      <ZoneOccupancyPanel cameraId={camera.id} liveMetrics={state?.metrics} />
    </div>
  );
}
