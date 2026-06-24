import { jsx as _jsx } from "react/jsx-runtime";
import { forwardRef } from "react";
export const Input = forwardRef(function Input({ className = "", ...props }, ref) {
    return (_jsx("input", { ref: ref, ...props, className: `
        h-9 w-full rounded-md border border-input bg-surface-low px-3 py-1 text-sm
        placeholder:text-text-mute
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-40
        focus-visible:border-accent
        disabled:opacity-50 disabled:cursor-not-allowed
        ${className}
      ` }));
});
