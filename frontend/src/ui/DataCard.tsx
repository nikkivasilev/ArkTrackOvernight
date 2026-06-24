import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon } from "./Icon";

type Props = {
  to?: string;
  thumb: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  badge?: ReactNode;
  accentSide?: "ok" | "warn" | "danger" | "info" | "neutral";
  /** Small mono id shown bottom-left over the feed, e.g. "CAM-042". */
  feedId?: ReactNode;
  /** Show the pulsing LIVE chip top-left. */
  live?: boolean;
  className?: string;
};

export function DataCard({
  to,
  thumb,
  title,
  meta,
  badge,
  accentSide = "neutral",
  feedId,
  live = false,
  className = "",
}: Props) {
  // Cancelled / warning cameras get an amber flag: a soft orange glow on the
  // card + an orange border on the info container below the feed. Every other
  // card just deepens its shadow on hover.
  const isWarn = accentSide === "warn";

  const inner = (
    <>
      <div className="relative bg-black aspect-video flex items-center justify-center overflow-hidden">
        <div className="absolute inset-0 [&>img]:w-full [&>img]:h-full [&>img]:object-cover [&>img]:opacity-80 flex items-center justify-center">
          {thumb}
        </div>
        {live && (
          <div className="absolute top-2 left-2 flex items-center gap-1.5 glass px-2 py-0.5 rounded-md font-mono text-[10px] uppercase tracking-wider text-accent">
            <span className="relative flex size-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-70" />
              <span className="relative inline-flex size-1.5 rounded-full bg-danger" />
            </span>
            Live
          </div>
        )}
        {badge && <div className="absolute top-2 right-2">{badge}</div>}
        {feedId && (
          <div className="absolute bottom-2 left-2 font-mono text-[10px] tracking-wider text-text-dim glass px-1.5 py-0.5 rounded-md">
            {feedId}
          </div>
        )}
        <div className="absolute bottom-2 right-2 size-7 grid place-items-center rounded-md glass text-text-dim opacity-0 group-hover:opacity-100 transition-opacity">
          <Icon name="fullscreen" size={16} />
        </div>
      </div>
      <div className={`px-3 py-2.5 border-t glass ${isWarn ? "border-t-warn-muted" : "border-border"}`}>
        <div className="font-display text-[14px] text-text font-semibold truncate">{title}</div>
        {meta && (
          <div className="font-mono text-[11px] text-text-dim truncate mt-0.5">{meta}</div>
        )}
      </div>
    </>
  );

  const base = `
    group block rounded-xl overflow-hidden
    transition-all duration-300 ease-in-out
    no-underline text-text cam-card
     ${className}
  `;

  if (to) {
    return (
      <Link to={to} className={base}>
        {inner}
      </Link>
    );
  }
  return <div className={base}>{inner}</div>;
}
