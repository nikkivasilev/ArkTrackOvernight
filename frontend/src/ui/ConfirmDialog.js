import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Button } from "./Button";
export function ConfirmDialog({ trigger, title, body, confirmLabel = "CONFIRM", cancelLabel = "CANCEL", tone = "danger", onConfirm, }) {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const handleConfirm = async () => {
        setBusy(true);
        try {
            await onConfirm();
            setOpen(false);
        }
        finally {
            setBusy(false);
        }
    };
    return (_jsxs(Dialog.Root, { open: open, onOpenChange: setOpen, children: [_jsx(Dialog.Trigger, { asChild: true, children: trigger }), _jsxs(Dialog.Portal, { children: [_jsx(Dialog.Overlay, { className: "fixed inset-0 bg-black/60 backdrop-blur-sm z-50" }), _jsxs(Dialog.Content, { className: "\r\n            fixed left-1/2 top-1/3 -translate-x-1/2 -translate-y-1/2 z-50\r\n            w-[min(480px,92vw)] glass rounded-xl\r\n            shadow-xl focus:outline-none\r\n          ", children: [_jsx("div", { className: "px-4 py-3 border-b border-border", children: _jsx(Dialog.Title, { className: "m-0 font-mono text-label-caps uppercase text-text-dim", children: title }) }), _jsx("div", { className: "px-4 py-4 text-[13px] text-text leading-relaxed", children: body }), _jsxs("div", { className: "flex items-center gap-2 px-4 py-3 border-t border-border", children: [_jsx("span", { className: "flex-1" }), _jsx(Dialog.Close, { asChild: true, children: _jsx(Button, { tone: "ghost", size: "sm", disabled: busy, children: cancelLabel }) }), _jsx(Button, { tone: tone, size: "sm", onClick: handleConfirm, disabled: busy, children: busy ? "…" : confirmLabel })] })] })] })] }));
}
