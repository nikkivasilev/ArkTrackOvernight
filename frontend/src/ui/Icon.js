import { jsx as _jsx } from "react/jsx-runtime";
/**
 * Thin wrapper over the Material Symbols Outlined icon font (loaded in index.html).
 * Sizes via inline font-size so it tracks the `size` prop; color inherits from
 * the surrounding text color (use text-* utilities to tint).
 */
export function Icon({ name, filled = false, size = 20, weight = 400, className = "" }) {
    return (_jsx("span", { "aria-hidden": "true", className: `material-symbols-outlined${filled ? " fill" : ""} ${className}`, style: {
            fontSize: size,
            fontVariationSettings: `'FILL' ${filled ? 1 : 0}, 'opsz' ${size}, 'wght' ${weight}, 'GRAD' 0`,
        }, children: name }));
}
