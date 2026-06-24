import { jsx as _jsx } from "react/jsx-runtime";
import { forwardRef } from "react";
const toneClasses = {
    primary: "bg-accent text-accent-bg border border-accent " +
        "hover:glow-primary hover:brightness-110 active:brightness-95",
    default: "bg-accent text-accent-bg border border-accent " +
        "hover:glow-primary hover:brightness-110 active:brightness-95",
    secondary: "bg-surface-high/40 border border-border text-text hover:bg-surface-high/70 hover:border-accent-40",
    outline: "bg-transparent border border-border text-text hover:bg-surface-high/40 hover:border-accent-40",
    ghost: "bg-transparent text-text-dim border border-transparent hover:bg-surface-high/40 hover:text-text",
    link: "bg-transparent text-accent border border-transparent underline-offset-4 hover:underline",
    danger: "bg-transparent text-danger border border-danger hover:bg-danger hover:text-white",
    destructive: "bg-danger text-white border border-danger hover:glow-danger hover:brightness-110",
};
const sizeClasses = {
    sm: "h-8 px-3 text-[12px]",
    md: "h-9 px-4 text-[13px]",
    lg: "h-11 px-6 text-sm",
    icon: "size-9",
};
export const Button = forwardRef(function Button({ tone = "secondary", size = "md", className = "", children, ...rest }, ref) {
    return (_jsx("button", { ref: ref, ...rest, className: `
        inline-flex items-center justify-center gap-1.5 rounded-md
        font-mono font-semibold uppercase tracking-[0.08em]
        transition-all duration-200 ease-out cursor-pointer
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-60
        disabled:opacity-50 disabled:cursor-not-allowed
        ${toneClasses[tone]} ${sizeClasses[size]} ${className}
      `, children: children }));
});
