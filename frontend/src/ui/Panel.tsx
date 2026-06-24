import { HTMLAttributes, ReactNode } from "react";

type Props = HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "flush";
  title?: ReactNode;
  right?: ReactNode;
  /** Optional inner-glow for active / high-priority panels. */
  glow?: "primary" | "secondary";
};

export function Panel({
  variant = "default",
  title,
  right,
  glow,
  className = "",
  children,
  ...rest
}: Props) {
  const pad = variant === "flush" ? "" : "p-4";
  const glowClass = glow === "primary" ? "glow-primary" : glow === "secondary" ? "glow-secondary" : "";
  return (
    <section
      {...rest}
      className={`glass rounded-xl ${glowClass} ${pad} ${className}`}
    >
      {(title || right) && (
        <header className="flex items-center gap-3 mb-3">
          {title && (
            <h2 className="m-0 font-mono text-label-caps uppercase text-text-dim">
              {typeof title === "string" ? title.toUpperCase() : title}
            </h2>
          )}
          <div className="ml-auto flex items-center gap-2">{right}</div>
        </header>
      )}
      {children}
    </section>
  );
}
