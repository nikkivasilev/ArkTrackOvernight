import { useEffect, useRef, useState } from "react";

export type TrackEntry = {
  track_id: number;
  label: string;
  bbox: [number, number, number, number];
  activity: string;
  heuristic_activity?: string;
  vlm_activity?: string | null;
  rollup: "working" | "moving" | "idle" | "unclear" | "motion" | "group_idle";
  conf: number;
  vlm_conf?: number;
  phantom?: boolean;
  ghost?: boolean;
  stale_s?: number;
  motion_only?: boolean;
  age_s?: number;
};

export type ZoneOccupancy = {
  // seconds spent at exactly k people, keyed by stringified count
  seconds_at: Record<string, number>;
  total_s: number;
  avg: number;
  peak: number;
};

export type ZoneActivity = {
  // worker-weighted person-seconds per activity in the zone
  seconds: Record<string, number>;
  total_s: number;
  // pct of total person-time per activity (the "30% welding…" breakdown)
  pct: Record<string, number>;
};

export type MetricsSummary = {
  window_s: number;
  worker_seconds: number;
  activity_seconds: Record<string, number>;
  rollup_seconds: Record<string, number>;
  activity_pct: Record<string, number>;
  rollup_pct: Record<string, number>;
  avg_headcount: number;
  peak_headcount: number;
  frames: number;
  zone_occupancy?: Record<string, ZoneOccupancy>;
  zone_activity?: Record<string, ZoneActivity>;
};

export type CameraStateData = {
  camera_id: string;
  frame: number;
  t: number;
  running: boolean;
  src_fps: number;
  yolo_ms: number;
  tracks: TrackEntry[];
  activity_counts: Record<string, number>;
  rollup_counts: Record<string, number>;
  n_dets: number;
  n_phantoms: number;
  n_phantoms_in_grace: number;
  flashes: { cx: number; cy: number; area: number; orphan: boolean }[];
  orphan_welding_count: number;
  groups: any[];
  zones: any[];
  metrics?: MetricsSummary;
};

export type WsMessage =
  | { type: "alert.created"; v: 1; data: any }
  | { type: "alert.acknowledged"; v: 1; data: { id: string; acknowledged_at: string } }
  | { type: "alert.resolved"; v: 1; data: { id: string; end_timestamp_in_video: number } }
  | { type: "alert.deleted"; v: 1; data: { id: string } }
  | { type: "camera.updated"; v: 1; data: { id: string; status: string; error?: string } }
  | { type: "state"; v: 1; data: CameraStateData };

export function useEventsWS(onMessage: (m: WsMessage) => void) {
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/api/ws/events`;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      ws = new WebSocket(url);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (ev) => {
        try {
          handlerRef.current(JSON.parse(ev.data));
        } catch {}
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return { connected };
}
