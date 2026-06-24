import { ReactNode } from "react";

type Tone = "accent" | "ok" | "warn" | "danger" | "neutral";

type Props = {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  tone?: Tone;
  size?: "sm" | "md" | "lg";
  className?: string;
};

const toneClasses: Record<Tone, string> = {
  accent:  "text-accent text-glow-primary",
  ok:      "text-accent text-glow-primary",
  warn:    "text-amber text-glow-secondary",
  danger:  "text-danger",
  neutral: "text-text",
};

export function StatReadout({
  label,
  value,
  unit,
  tone = "neutral",
  size = "md",
  className = "",
}: Props) {
  const numSize =
    size === "lg" ? "font-display text-stats" :
    size === "sm" ? "text-[20px] leading-none" :
                    "text-[30px] leading-none";
  const unitSize = size === "lg" ? "text-[16px]" : "text-[12px]";
  return (
    <div className={`glass rounded-xl flex flex-col gap-1.5 px-4 py-3 ${className}`}>
      <div className="font-mono text-label-caps uppercase text-text-dim">{label}</div>
      <div className={`font-display tabular-nums font-semibold ${numSize} ${toneClasses[tone]}`}>
        {value}
        {unit && <span className={`ml-1 text-text-dim font-normal ${unitSize}`}>{unit}</span>}
      </div>
    </div>
  );
}
