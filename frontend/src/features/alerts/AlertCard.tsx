import { Alert, api } from "../../api/client";
import { Pill, PillTone } from "../../ui/Pill";
import { Button } from "../../ui/Button";

type Props = {
  alert: Alert;
  onAck?: (a: Alert) => void;
};

const severityTone: Record<Alert["severity"], PillTone> = {
  info: "info",
  warn: "warn",
  critical: "danger",
};

export default function AlertCard({ alert, onAck }: Props) {
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
    } catch (e) {
      console.error(e);
    }
  };
  const box = alert.detection_box;

  return (
    <div
      className={`
        group glass rounded-xl overflow-hidden flex flex-col
        transition-all duration-300 ease-in-out cam-card
        ${alert.acknowledged ? "opacity-55" : ""}
      `}
    >
      <div className="relative bg-black h-44 md:h-48 overflow-hidden">
        {alert.has_clip ? (
          // Resting-worker event clip — the video shows the subject, so no
          // static bbox overlay (it would be wrong as the clip plays).
          <video
            controls
            preload="metadata"
            poster={api.alertThumbnailUrl(alert.id)}
            src={api.alertClipUrl(alert.id)}
            className="block w-full h-full object-contain"
          />
        ) : (
          <>
            <img
              src={api.alertThumbnailUrl(alert.id)}
              alt="alert thumbnail"
              className="block w-full h-full object-contain"
            />
            {box && (
              <div
                className="absolute pointer-events-none border-2 border-dashed border-accent bg-accent-10"
                style={{
                  left: `${box.x1 * 100}%`,
                  top: `${box.y1 * 100}%`,
                  width: `${(box.x2 - box.x1) * 100}%`,
                  height: `${(box.y2 - box.y1) * 100}%`,
                }}
              />
            )}
          </>
        )}
        <div className="absolute top-2 left-2">
          <Pill tone={severityTone[alert.severity]} dot>{alert.severity}</Pill>
        </div>
      </div>
      <div className={`px-3 py-2 border-t ${isWarn ? "border-t-warn-muted" : "border-border"} text-[11px] text-text-dim font-mono leading-relaxed`}>
        <div>
          t=<span className="tabular-nums">{alert.start_timestamp_in_video.toFixed(2)}</span>s
          {alert.end_timestamp_in_video != null && (
            <> → <span className="tabular-nums">{alert.end_timestamp_in_video.toFixed(2)}</span>s</>
          )}
        </div>
        <div>
          {alert.confidence != null
            ? <>conf <span className="tabular-nums">{(alert.confidence * 100).toFixed(0)}</span>%</>
            : "no conf"}
        </div>
        <div>{new Date(alert.created_at).toLocaleTimeString()}</div>
        <div className="mt-1.5 flex items-center gap-2">
          {alert.acknowledged ? (
            <span className="text-text-dim text-[10px] tracking-[0.16em] uppercase">
              acked
            </span>
          ) : (
            <Button tone="primary" size="sm" onClick={ack}>ACK</Button>
          )}
          <span className="flex-1" />
          <Button tone="danger" size="sm" onClick={del}>DELETE</Button>
        </div>
      </div>
    </div>
  );
}
