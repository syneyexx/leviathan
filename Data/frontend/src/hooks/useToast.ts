import { useCallback, useState } from "react";

export function useToast(durationMs = 2200) {
  const [message, setMessage] = useState<string | null>(null);

  const toast = useCallback(
    (next: string) => {
      setMessage(next);
      window.setTimeout(() => {
        setMessage((current) => (current === next ? null : current));
      }, durationMs);
    },
    [durationMs],
  );

  const clear = useCallback(() => setMessage(null), []);

  return { message, toast, clear };
}
