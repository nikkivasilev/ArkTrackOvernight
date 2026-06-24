import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { api } from "../../api/client";
import { Pill } from "../../ui/Pill";
import { Button } from "../../ui/Button";
const severityTone = {
    info: "info",
    warn: "warn",
    critical: "danger",
};
export default function AlertCard({ alert, onAck }) {
    // Same treatment as the dashboard camera cards: glass + dim hover-lift; a
    // warning severity gets the soft amber glow + off-orange footer top border.
    const isWarn = alert.severity === "warn";
    const ack = async () => {
        const next = await api.ackAlert(alert.id);
        onAck?.(next);
    };
    const del = async () => {
        // The row + its clip/thumbnail files are removed server-side; the
        // alert.deleted WS event drops it from the list (AppContext).
        try {
            await api.deleteAlert(alert.id);
        }
        catch (e) {
            console.error(e);
        }
    };
    const box = alert.detection_box;
    return (_jsxs("div", { className: `
        group glass rounded-xl overflow-hidden flex flex-col
        transition-all duration-300 ease-in-out cam-card
        ${alert.acknowledged ? "opacity-55" : ""}
      `, children: [_jsxs("div", { className: "relative bg-black h-44 md:h-48 overflow-hidden", children: [alert.has_clip ? (
                    // Resting-worker event clip — the video shows the subject, so no
                    // static bbox overlay (it would be wrong as the clip plays).
                    _jsx("video", { controls: true, preload: "metadata", poster: api.alertThumbnailUrl(alert.id), src: api.alertClipUrl(alert.id), className: "block w-full h-full object-contain" })) : (_jsxs(_Fragment, { children: [_jsx("img", { src: api.alertThumbnailUrl(alert.id), alt: "alert thumbnail", className: "block w-full h-full object-contain" }), box && (_jsx("div", { className: "absolute pointer-events-none border-2 border-dashed border-accent bg-accent-10", style: {
                                    left: `${box.x1 * 100}%`,
                                    top: `${box.y1 * 100}%`,
                                    width: `${(box.x2 - box.x1) * 100}%`,
                                    height: `${(box.y2 - box.y1) * 100}%`,
                                } }))] })), _jsx("div", { className: "absolute top-2 left-2", children: _jsx(Pill, { tone: severityTone[alert.severity], dot: true, children: alert.severity }) })] }), _jsxs("div", { className: `px-3 py-2 border-t ${isWarn ? "border-t-warn-muted" : "border-border"} text-[11px] text-text-dim font-mono leading-relaxed`, children: [_jsxs("div", { children: ["t=", _jsx("span", { className: "tabular-nums", children: alert.start_timestamp_in_video.toFixed(2) }), "s", alert.end_timestamp_in_video != null && (_jsxs(_Fragment, { children: [" \u2192 ", _jsx("span", { className: "tabular-nums", children: alert.end_timestamp_in_video.toFixed(2) }), "s"] }))] }), _jsx("div", { children: alert.confidence != null
                            ? _jsxs(_Fragment, { children: ["conf ", _jsx("span", { className: "tabular-nums", children: (alert.confidence * 100).toFixed(0) }), "%"] })
                            : "no conf" }), _jsx("div", { children: new Date(alert.created_at).toLocaleTimeString() }), _jsxs("div", { className: "mt-1.5 flex items-center gap-2", children: [alert.acknowledged ? (_jsx("span", { className: "text-text-dim text-[10px] tracking-[0.16em] uppercase", children: "acked" })) : (_jsx(Button, { tone: "primary", size: "sm", onClick: ack, children: "ACK" })), _jsx("span", { className: "flex-1" }), _jsx(Button, { tone: "danger", size: "sm", onClick: del, children: "DELETE" })] })] })] }));
}
