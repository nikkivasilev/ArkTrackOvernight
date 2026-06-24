import * as Dialog from "@radix-ui/react-dialog";
import { ReactNode, useState } from "react";
import { Button } from "./Button";

type Props = {
  trigger: ReactNode;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
  onConfirm: () => void | Promise<void>;
};

export function ConfirmDialog({
  trigger,
  title,
  body,
  confirmLabel = "CONFIRM",
  cancelLabel = "CANCEL",
  tone = "danger",
  onConfirm,
}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
      setOpen(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50" />
        <Dialog.Content
          className="
            fixed left-1/2 top-1/3 -translate-x-1/2 -translate-y-1/2 z-50
            w-[min(480px,92vw)] glass rounded-xl
            shadow-xl focus:outline-none
          "
        >
          <div className="px-4 py-3 border-b border-border">
            <Dialog.Title className="m-0 font-mono text-label-caps uppercase text-text-dim">
              {title}
            </Dialog.Title>
          </div>
          <div className="px-4 py-4 text-[13px] text-text leading-relaxed">
            {body}
          </div>
          <div className="flex items-center gap-2 px-4 py-3 border-t border-border">
            <span className="flex-1" />
            <Dialog.Close asChild>
              <Button tone="ghost" size="sm" disabled={busy}>
                {cancelLabel}
              </Button>
            </Dialog.Close>
            <Button tone={tone} size="sm" onClick={handleConfirm} disabled={busy}>
              {busy ? "…" : confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
