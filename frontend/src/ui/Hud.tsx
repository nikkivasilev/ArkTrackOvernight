import { ReactNode } from "react";

export type HudItem = {
  label: string;
  value: ReactNode;
  tone?: "accent" | "ok" | "warn" | "danger" | "neutral";
};

const toneClasses = {
  accent: "text-accent",
  ok: "text-accent",
  warn: "text-amber",
  danger: "text-danger",
  neutral: "text-text",
};

export function Hud({ items, className = "" }: { items: HudItem[]; className?: string }) {
  return (
    <div
      className={`
        inline-flex items-stretch glass rounded-lg
        font-mono divide-x divide-border
        ${className}
      `}
    >
      {items.map((it, i) => (
        <div key={i} className="flex flex-col px-3 py-1.5 min-w-[72px]">
          <span className="text-[9px] tracking-[0.18em] text-text-mute uppercase">
            {it.label}
          </span>
          <span className={`text-[13px] tabular-nums font-semibold ${toneClasses[it.tone ?? "neutral"]}`}>
            {it.value}
          </span>
        </div>
      ))}
    </div>
  );
}
