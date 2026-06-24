import { useMemo } from "react";
import type { CameraStateData } from "../../hooks/useEventsWS";
import { useTrackHistory, type TrackHistory } from "../../hooks/useTrackHistory";

/**
 * Per-track 60-second activity strip. One SVG row per active track, colored
 * by rollup, with a small triangular tick marking each VLM verdict change so
 * the operator can see when the model re-classified the worker.
 *
 * Empty state ("No active tracks") when no track has been seen in the last
 * GONE_S seconds (see useTrackHistory).
 */

const WINDOW_S = 60;
const VB_W = 600;
const VB_H = 12;

const ROLLUP_COLOR: Record<string, string> = {
  working: "var(--ru-working)",
  moving: "var(--ru-moving)",
  idle: "var(--ru-idle)",
  motion: "var(--ru-motion)",
  group_idle: "var(--ru-group_idle)",
  unclear: "var(--ru-unclear)",
};

type Segment = {
  x: number;
  w: number;
  color: string;
  rollup: string;
};

function segmentsFor(h: TrackHistory, t0: number): Segment[] {
  if (h.samples.length === 0) return [];
  const segs: Segment[] = [];
  const endT = Math.max(t0 + WINDOW_S, h.lastSeen);
  for (let i = 0; i < h.samples.length; i++) {
    const s = h.samples[i];
    const next = i + 1 < h.samples.length ? h.samples[i + 1].t : endT;
    const start = Math.max(s.t, t0);
    const stop = Math.min(next, t0 + WINDOW_S);
    if (stop <= start) continue;
    const x = ((start - t0) / WINDOW_S) * VB_W;
    const w = Math.max(0.5, ((stop - start) / WINDOW_S) * VB_W);
    segs.push({
      x,
      w,
      color: ROLLUP_COLOR[s.rollup] ?? "var(--ru-unclear)",
      rollup: s.rollup,
    });
  }
  return segs;
}

function vlmTicks(h: TrackHistory, t0: number): number[] {
  const xs: number[] = [];
  let prev: string | null | undefined = undefined;
  for (const s of h.samples) {
    if (s.vlm_activity !== prev && s.vlm_activity) {
      if (s.t >= t0) xs.push(((s.t - t0) / WINDOW_S) * VB_W);
    }
    prev = s.vlm_activity;
  }
  return xs;
}

export default function TrackTimeline({ state }: { state: CameraStateData | null }) {
  const history = useTrackHistory(state);
  const t0 = useMemo(() => (state ? state.t - WINDOW_S : 0), [state?.t]);
  const rows = useMemo(() => [...history.values()], [history]);

  return (
    <section className="track-timeline">
      <div className="track-timeline-head">
        <h3>Track timeline (last {WINDOW_S}s)</h3>
        <div className="track-timeline-legend">
          {Object.keys(ROLLUP_COLOR).map((r) => (
            <span key={r} className="tt-swatch-row">
              <span className="tt-swatch" style={{ background: ROLLUP_COLOR[r] }} />
              {r}
            </span>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="hint ">No active tracks.</div>
      ) : (
        <div className="track-timeline-rows">
          {rows.map((h) => {
            const segs = segmentsFor(h, t0);
            const ticks = vlmTicks(h, t0);
            const latest = h.samples[h.samples.length - 1];
            const latestLabel = latest?.vlm_activity || latest?.rollup || "";
            return (
              <div key={h.track_id} className="tt-row">
                <span className="tt-id">#{h.track_id}</span>
                <svg
                  className="tt-svg"
                  viewBox={`0 0 ${VB_W} ${VB_H}`}
                  preserveAspectRatio="none"
                >
                  {segs.map((s, i) => (
                    <rect
                      key={i}
                      x={s.x}
                      y={0}
                      width={s.w}
                      height={VB_H}
                      fill={s.color}
                    >
                      <title>{s.rollup}</title>
                    </rect>
                  ))}
                  {ticks.map((x, i) => (
                    <polygon
                      key={`t-${i}`}
                      points={`${x - 3},0 ${x + 3},0 ${x},5`}
                      fill="#fff"
                      stroke="#000"
                      strokeWidth={0.5}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </svg>
                <span className="tt-latest">{latestLabel}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
