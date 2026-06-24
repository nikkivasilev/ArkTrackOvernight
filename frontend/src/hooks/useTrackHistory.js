import { useEffect, useRef, useState } from "react";
const WINDOW_S = 60;
const GONE_S = 5;
/**
 * Buffer per-track (t, rollup, vlm_activity) samples over the last
 * WINDOW_S seconds of state updates, then surface the map at most once
 * per animation frame. Tracks not seen for GONE_S seconds are evicted.
 *
 * The buffer lives in a ref so high-frequency WS frames don't trigger
 * intermediate renders — a single setState fires on the next rAF.
 */
export function useTrackHistory(state) {
    const bufferRef = useRef(new Map());
    const [snapshot, setSnapshot] = useState(new Map());
    const pendingRef = useRef(false);
    useEffect(() => {
        if (!state)
            return;
        const t = state.t;
        const buf = bufferRef.current;
        for (const tr of state.tracks ?? []) {
            const id = tr.track_id;
            let h = buf.get(id);
            if (!h) {
                h = { track_id: id, samples: [], lastSeen: t };
                buf.set(id, h);
            }
            const last = h.samples[h.samples.length - 1];
            if (!last || last.rollup !== tr.rollup || last.vlm_activity !== tr.vlm_activity) {
                h.samples.push({ t, rollup: tr.rollup, vlm_activity: tr.vlm_activity ?? null });
            }
            else {
                // Same state as last sample — just advance its end-of-life by
                // updating lastSeen; the segment extends visually via state.t.
            }
            h.lastSeen = t;
            const cutoff = t - WINDOW_S;
            while (h.samples.length > 1 && h.samples[1].t < cutoff) {
                h.samples.shift();
            }
        }
        for (const [id, h] of buf) {
            if (t - h.lastSeen > GONE_S) {
                buf.delete(id);
            }
        }
        if (!pendingRef.current) {
            pendingRef.current = true;
            requestAnimationFrame(() => {
                pendingRef.current = false;
                // Sorted map so the SVG row order is stable.
                const sorted = new Map([...bufferRef.current.entries()].sort((a, b) => a[0] - b[0]));
                setSnapshot(sorted);
            });
        }
    }, [state]);
    // Reset when the camera changes (state goes from a value to null between
    // mounts via useCameraState's cleanup).
    useEffect(() => {
        if (state === null) {
            bufferRef.current = new Map();
            setSnapshot(new Map());
        }
    }, [state === null]);
    return snapshot;
}
