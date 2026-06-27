// Shared metric value types — read from GET /api/cameras/{id}/metrics and the
// offline report payloads. Transport-agnostic (formerly colocated with the
// live WebSocket hook).

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
