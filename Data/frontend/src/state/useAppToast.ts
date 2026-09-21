import { useContext } from "react";
import { ToastContext } from "./toastContextValue";

export function useAppToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useAppToast must be used within ToastProvider");
  }
  return ctx.toast;
}
