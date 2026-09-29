import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "./Button";

export type DialogProps = {
  open: boolean;
  title: string;
  description?: string;
  children?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmVariant?: "primary" | "secondary" | "ghost";
  danger?: boolean;
  busy?: boolean;
  onConfirm?: () => void;
  onClose: () => void;
};

/**
 * Generic V2 modal dialog — reusable across Chat rename/delete and future pages.
 */
export function Dialog({
  open,
  title,
  description,
  children,
  confirmLabel = "Bevestigen",
  cancelLabel = "Annuleren",
  confirmVariant = "primary",
  danger = false,
  busy = false,
  onConfirm,
  onClose,
}: DialogProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.activeElement as HTMLElement | null;
    panelRef.current?.querySelector<HTMLElement>("input,textarea,button")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="lv-v2-dialog-root" role="presentation">
      <button
        type="button"
        className="lv-v2-dialog-backdrop"
        aria-label="Sluiten"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        className={`lv-v2-dialog${danger ? " lv-v2-dialog--danger" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h2 id={titleId} className="lv-v2-dialog__title">
          {title}
        </h2>
        {description ? <p className="lv-v2-dialog__desc">{description}</p> : null}
        {children ? <div className="lv-v2-dialog__body">{children}</div> : null}
        <div className="lv-v2-dialog__actions">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </Button>
          {onConfirm ? (
            <Button
              variant={confirmVariant}
              size="sm"
              loading={busy}
              onClick={onConfirm}
              className={danger ? "lv-v2-button--danger" : undefined}
            >
              {confirmLabel}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
