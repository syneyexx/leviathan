import { createContext } from "react";

export type ToastContextValue = {
  toast: (message: string) => void;
};

export const ToastContext = createContext<ToastContextValue | null>(null);
