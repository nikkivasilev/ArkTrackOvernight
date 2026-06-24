import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Page header — large display title + subtitle, with right-aligned actions.
 * No box; sits directly on the page background per the Midnight Obsidian design.
 */
export function Toolbar({ title, subtitle, children, className = "" }) {
    return (_jsxs("div", { className: `flex flex-wrap items-end gap-x-4 gap-y-3 mb-6 ${className}`, children: [_jsxs("div", { className: "min-w-0", children: [title && (_jsx("h1", { className: "m-0 font-display text-headline-md md:text-headline-lg font-semibold tracking-tight text-text", children: title })), subtitle && (_jsx("div", { className: "mt-1 font-sans text-[14px] text-text-dim", children: subtitle }))] }), _jsx("div", { className: "ml-auto flex items-center gap-2", children: children })] }));
}
