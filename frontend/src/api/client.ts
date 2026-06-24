import type { MetricsSummary } from "../hooks/useEventsWS";

export type Factory = { id: string; name: string; address: string | null; created_at: string };
export type Site = { id: string; factory_id: string; name: string; address: string | null; created_at: string };
export type Camera = {
  id: string;
  site_id: string;
  name: string;
  kind: string;
  path_or_url: string;
  duration_s: number | null;
  sampling_fps: number;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  last_processed_frame_idx: number;
  error: string | null;
  created_at: string;
};
export type Zone = {
  id: string;
  camera_id: string;
  name: string;
  polygon: [number, number][];
  excluded: boolean;
  created_at: string;
};
export type Severity = "info" | "warn" | "critical";
export type TriggerType =
  | "detection" | "count_min" | "count_max" | "duration" | "absence" | "resting_worker";

export type Rule = {
  id: string;
  name: string;
  trigger_type: TriggerType;
  severity: Severity;
  camera_id: string | null;
  zone_id: string | null;
  params: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
};
export type Alert = {
  id: string;
  camera_id: string;
  rule_id: string;
  zone_id: string | null;
  severity: Severity;
  acknowledged: boolean;
  acknowledged_at: string | null;
  start_timestamp_in_video: number;
  end_timestamp_in_video: number | null;
  wall_clock_at: string | null;
  detection_box: { x1: number; y1: number; x2: number; y2: number } | null;
  confidence: number | null;
  has_clip: boolean;
  created_at: string;
};

// ---- Offline reports / recordings ----
export type ReportPeriod = "day" | "week" | "month";
export type TimelinePoint = { t: string; date?: string; avg_headcount: number };
export type CameraDaySummary = {
  camera_id: string;
  name: string;
  summary: MetricsSummary;
  zone_names: Record<string, string>;
  recordings: number;
  footage_s: number;
};
export type PeriodSummary = {
  factory_id: string;
  factory_name: string;
  period: ReportPeriod;
  start: string;
  end: string;
  tz: string;
  generated_at: string;
  start_utc: string;
  end_utc: string;
  factory_summary: MetricsSummary;
  timeline: TimelinePoint[];
  timeline_kind: "intraday" | "daily";
  cameras: CameraDaySummary[];
  zone_names: Record<string, string>;
  total_recordings: number;
  total_footage_s: number;
};
export type ProcessedRecording = {
  id: string;
  camera_id: string;
  camera_name: string | null;
  path: string;
  filename: string;
  recorded_start: string;
  recorded_end: string | null;
  frames: number;
  footage_s: number;
  status: string;
  error: string | null;
  processed_at: string | null;
  created_at: string;
  file_exists: boolean;
};

const BASE = "/api";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return resp.json() as Promise<T>;
}
async function okOnly(resp: Response): Promise<void> {
  if (!resp.ok) throw new Error(await resp.text());
}
const jsonHeaders = { "Content-Type": "application/json" };

export const api = {
  // Factories
  listFactories: () => fetch(`${BASE}/factories`).then(json<Factory[]>),
  getFactory: (id: string) => fetch(`${BASE}/factories/${id}`).then(json<Factory>),
  createFactory: (payload: { name: string; address?: string }) =>
    fetch(`${BASE}/factories`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then(json<Factory>),
  deleteFactory: (id: string) =>
    fetch(`${BASE}/factories/${id}`, { method: "DELETE" }).then(okOnly),

  // Sites
  listSitesForFactory: (fid: string) =>
    fetch(`${BASE}/factories/${fid}/sites`).then(json<Site[]>),
  getSite: (sid: string) => fetch(`${BASE}/sites/${sid}`).then(json<Site>),
  createSite: (fid: string, payload: { name: string; address?: string }) =>
    fetch(`${BASE}/factories/${fid}/sites`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then(json<Site>),
  deleteSite: (sid: string) =>
    fetch(`${BASE}/sites/${sid}`, { method: "DELETE" }).then(okOnly),

  // Cameras
  listCamerasForSite: (sid: string) =>
    fetch(`${BASE}/sites/${sid}/cameras`).then(json<Camera[]>),
  listAllCameras: () => fetch(`${BASE}/cameras`).then(json<Camera[]>),
  getCamera: (cid: string) => fetch(`${BASE}/cameras/${cid}`).then(json<Camera>),
  uploadCamera: (sid: string, file: File, name?: string, samplingFps?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    if (name) fd.append("name", name);
    if (samplingFps !== undefined) fd.append("sampling_fps", String(samplingFps));
    return fetch(`${BASE}/sites/${sid}/cameras`, { method: "POST", body: fd }).then(json<Camera>);
  },
  startCamera: (cid: string) =>
    fetch(`${BASE}/cameras/${cid}/start`, { method: "POST" }).then(json<Camera>),
  cancelCamera: (cid: string) =>
    fetch(`${BASE}/cameras/${cid}/cancel`, { method: "POST" }).then(json<Camera>),
  deleteCamera: (cid: string) =>
    fetch(`${BASE}/cameras/${cid}`, { method: "DELETE" }).then(okOnly),
  frameUrl: (cid: string, t: number) =>
    `${BASE}/cameras/${cid}/frame?t=${encodeURIComponent(t)}`,
  liveUrl: (cid: string) => `${BASE}/cameras/${cid}/live.mjpg`,

  // Zones
  listZones: (cid: string) =>
    fetch(`${BASE}/cameras/${cid}/zones`).then(json<Zone[]>),
  createZone: (cid: string, name: string, polygon: [number, number][], excluded = false) =>
    fetch(`${BASE}/cameras/${cid}/zones`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ name, polygon, excluded }) }).then(json<Zone>),
  updateZone: (zid: string, patch: Partial<{ name: string; excluded: boolean }>) =>
    fetch(`${BASE}/zones/${zid}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(patch) }).then(json<Zone>),
  deleteZone: (zid: string) =>
    fetch(`${BASE}/zones/${zid}`, { method: "DELETE" }).then(okOnly),

  // Rules
  listRulesForCamera: (cid: string) =>
    fetch(`${BASE}/cameras/${cid}/rules`).then(json<Rule[]>),
  createCameraRule: (cid: string, payload: { name: string; trigger_type: TriggerType; severity: Severity; params: Record<string, unknown>; enabled?: boolean }) =>
    fetch(`${BASE}/cameras/${cid}/rules`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then(json<Rule>),
  createZoneRule: (zid: string, payload: { name: string; trigger_type: TriggerType; severity: Severity; params: Record<string, unknown>; enabled?: boolean }) =>
    fetch(`${BASE}/zones/${zid}/rules`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }).then(json<Rule>),
  updateRule: (rid: string, patch: Partial<{ name: string; severity: Severity; params: Record<string, unknown>; enabled: boolean }>) =>
    fetch(`${BASE}/rules/${rid}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(patch) }).then(json<Rule>),
  deleteRule: (rid: string) =>
    fetch(`${BASE}/rules/${rid}`, { method: "DELETE" }).then(okOnly),

  // Alerts
  listAlerts: (params: { factory_id?: string; site_id?: string; camera_id?: string; acknowledged?: boolean; limit?: number } = {}) => {
    const u = new URLSearchParams();
    if (params.factory_id) u.set("factory_id", params.factory_id);
    if (params.site_id) u.set("site_id", params.site_id);
    if (params.camera_id) u.set("camera_id", params.camera_id);
    if (params.acknowledged !== undefined) u.set("acknowledged", String(params.acknowledged));
    if (params.limit) u.set("limit", String(params.limit));
    return fetch(`${BASE}/alerts?${u.toString()}`).then(json<Alert[]>);
  },
  ackAlert: (aid: string) =>
    fetch(`${BASE}/alerts/${aid}/ack`, { method: "POST" }).then(json<Alert>),
  deleteAlert: (aid: string) =>
    fetch(`${BASE}/alerts/${aid}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`delete failed: ${r.status}`);
    }),
  alertThumbnailUrl: (aid: string) => `${BASE}/alerts/${aid}/thumbnail`,
  alertClipUrl: (aid: string) => `${BASE}/alerts/${aid}/clip`,

  // Live-pipeline controls (Phase 1: d-fine / motion / overlay)
  setCameraModules: (cid: string, modules: Partial<{ yolo_enabled: boolean; motion_enabled: boolean; overlay_enabled: boolean }>) =>
    fetch(`${BASE}/cameras/${cid}/modules`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(modules),
    }).then(json<{ camera_id: string; modules: Record<string, any>; persisted: Record<string, boolean> }>),

  // Offline reports
  getReport: (fid: string, period: ReportPeriod, date?: string) => {
    const u = new URLSearchParams({ period });
    if (date) u.set("date", date);
    return fetch(`${BASE}/factories/${fid}/report?${u.toString()}`).then(json<PeriodSummary>);
  },
  reportPdfUrl: (fid: string, period: ReportPeriod, date?: string) => {
    const u = new URLSearchParams({ period });
    if (date) u.set("date", date);
    return `${BASE}/factories/${fid}/report.pdf?${u.toString()}`;
  },

  // Processed-recording ledger
  listRecordings: (fid: string, status?: string) => {
    const u = new URLSearchParams();
    if (status) u.set("status", status);
    const qs = u.toString();
    return fetch(`${BASE}/factories/${fid}/recordings${qs ? `?${qs}` : ""}`).then(
      json<ProcessedRecording[]>,
    );
  },
};
