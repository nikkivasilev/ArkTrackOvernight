import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
/**
 * Absolutely-positioned SVG overlay drawn over the LiveTab MJPEG. Renders
 * each zone's polygon and name. Excluded ("not monitored") zones get a red
 * dashed outline so the operator can see at a glance which areas the
 * worker won't be counted in.
 *
 * Polygons are stored normalized (0..1), so the SVG uses viewBox 0..1 with
 * preserveAspectRatio="none" — the MJPEG's `width:100%; height:auto` shape
 * forces the same aspect ratio, so the overlay tracks the image cleanly.
 * Strokes use vectorEffect="non-scaling-stroke" to stay 2px under that
 * stretched viewBox.
 */
export default function LiveZonesOverlay({ cameraId }) {
    const [zones, setZones] = useState([]);
    useEffect(() => {
        let alive = true;
        const pull = () => {
            api
                .listZones(cameraId)
                .then((z) => alive && setZones(z))
                .catch(() => {
                /* transient; keep last list */
            });
        };
        pull();
        // Repoll so toggles on the Zones tab show up on Live without a remount.
        const t = setInterval(pull, 5000);
        return () => {
            alive = false;
            clearInterval(t);
        };
    }, [cameraId]);
    if (zones.length === 0)
        return null;
    return (_jsx("svg", { className: "live-zones", viewBox: "0 0 1 1", preserveAspectRatio: "none", style: {
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            pointerEvents: "none",
        }, children: zones.map((z) => {
            const d = z.polygon
                .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`)
                .join(" ") + " Z";
            const stroke = z.excluded ? "#ff6b6b" : "#4ea1ff";
            const fill = z.excluded ? "rgba(255, 107, 107, 0.15)" : "rgba(78, 161, 255, 0.10)";
            const [lx, ly] = z.polygon[0] ?? [0, 0];
            return (_jsxs("g", { children: [_jsx("path", { d: d, fill: fill, stroke: stroke, strokeWidth: 2, strokeDasharray: z.excluded ? "6 4" : undefined, vectorEffect: "non-scaling-stroke" }), _jsxs("text", { x: lx, y: ly, dx: 4, dy: -4, fill: stroke, style: { fontSize: "11px", fontFamily: "system-ui, sans-serif" }, paintOrder: "stroke", stroke: "rgba(0,0,0,0.6)", strokeWidth: 2, vectorEffect: "non-scaling-stroke", children: [z.name, z.excluded ? " · not monitored" : ""] })] }, z.id));
        }) }));
}
