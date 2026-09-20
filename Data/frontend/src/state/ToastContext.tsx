import { type ReactNode } from "react";
import { Toast } from "../components/Toast";
import { useToast } from "../hooks/useToast";
import { ToastContext } from "./toastContextValue";

export function ToastProvider({ children }: { children: ReactNode }) {
  const { message, toast } = useToast();
  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <Toast message={message} />
    </ToastContext.Provider>
  );
}
