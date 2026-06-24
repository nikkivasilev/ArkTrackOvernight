/**
 * Fold per-camera MetricsSummary objects into one system-wide summary.
 *
 * Seconds SUM across cameras; percentages are RECOMPUTED from the summed
 * seconds (mirrors the backend `_pct`: sum → normalize → round 1dp) rather
 * than averaging per-camera pcts. `avg_headcount` SUMS — Σ of per-camera
 * time-averaged occupancy = concurrent workers on site. `peak_headcount` is
 * dropped (cross-camera peak is ambiguous: peaks occur at different times).
 * Zone maps are omitted — zones are per-camera and have no system-wide meaning.
 *
 * Output is a valid MetricsSummary so it drops straight into MetricsBreakdown.
 */
function pctFromSeconds(d) {
    const total = Object.values(d).reduce((a, b) => a + b, 0);
    if (total <= 0)
        return {};
    const out = {};
    for (const [k, v] of Object.entries(d))
        out[k] = Math.round((1000 * v) / total) / 10;
    return out;
}
function addInto(dst, src) {
    for (const [k, v] of Object.entries(src ?? {}))
        dst[k] = (dst[k] ?? 0) + v;
}
export function aggregateMetrics(summaries) {
    const activity_seconds = {};
    const rollup_seconds = {};
    let worker_seconds = 0;
    let avg_headcount = 0;
    let frames = 0;
    let window_s = 0;
    for (const s of summaries) {
        worker_seconds += s.worker_seconds ?? 0;
        avg_headcount += s.avg_headcount ?? 0; // Σ per-camera time-avg = workers on site
        frames += s.frames ?? 0;
        window_s = Math.max(window_s, s.window_s ?? 0);
        addInto(activity_seconds, s.activity_seconds);
        addInto(rollup_seconds, s.rollup_seconds);
    }
    return {
        window_s,
        worker_seconds: Math.round(worker_seconds * 10) / 10,
        activity_seconds,
        rollup_seconds,
        activity_pct: pctFromSeconds(activity_seconds),
        rollup_pct: pctFromSeconds(rollup_seconds),
        avg_headcount: Math.round(avg_headcount * 100) / 100,
        peak_headcount: 0, // ambiguous across cameras — not displayed
        frames,
    };
}
