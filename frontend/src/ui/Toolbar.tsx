import { ReactNode } from "react";

type Props = {
  title?: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  className?: string;
};

/**
 * Page header — large display title + subtitle, with right-aligned actions.
 * No box; sits directly on the page background per the Midnight Obsidian design.
 */
export function Toolbar({ title, subtitle, children, className = "" }: Props) {
  return (
    <div className={`flex flex-wrap items-end gap-x-4 gap-y-3 mb-6 ${className}`}>
      <div className="min-w-0">
        {title && (
          <h1 className="m-0 font-display text-headline-md md:text-headline-lg font-semibold tracking-tight text-text">
            {title}
          </h1>
        )}
        {subtitle && (
          <div className="mt-1 font-sans text-[14px] text-text-dim">{subtitle}</div>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </div>
  );
}
