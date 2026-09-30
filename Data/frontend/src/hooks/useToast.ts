import { useCallback, useState } from "react";
import { playToastSoundIfEnabled } from "../lib/uiPreferences";

export function useToast(durationMs = 2200) {
  const [message, setMessage] = useState<string | null>(null);

  const toast = useCallback(
    (next: string) => {
      setMessage(next);
      playToastSoundIfEnabled();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("lv:toast", { detail: next }));
      }
      window.setTimeout(() => {
        setMessage((current) => (current === next ? null : current));
      }, durationMs);
    },
    [durationMs],
  );

  const clear = useCallback(() => setMessage(null), []);

  return { message, toast, clear };
}
