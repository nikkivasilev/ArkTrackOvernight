import type { Camera } from "../../api/client";

type Status = Camera["status"];

// Status semantics (Midnight Obsidian): running → primary blue (active/optimal),
// completed → indigo, cancelled → amber (warning), failed → red (offline/error).
const palette: Record<Status, string> = {
  queued:    "border-border       bg-surface-high/50 text-text-dim",
  running:   "border-accent-30    bg-accent-15    text-accent",
  completed: "border-accent-2-35  bg-accent-2-15  text-tertiary",
  failed:    "border-danger-35    bg-danger-15    text-danger",
  cancelled: "border-amber-35     bg-amber-15     text-amber",
};

export function CameraStatusBadge({ status }: { status: Status }) {
  const classes = palette[status] ?? palette.queued;
  return (
    <span
      className={`
        inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5
        font-mono text-[10px] font-semibold uppercase tracking-wider
        ${classes}
      `}
    >
      {status === "running" && (
        <span className="relative flex size-1.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex size-1.5 rounded-full bg-accent" />
        </span>
      )}
      {status}
    </span>
  );
}
