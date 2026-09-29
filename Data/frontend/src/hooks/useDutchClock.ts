import { useEffect, useRef, useState } from "react";
import { formatDutchDateTime } from "../lib/dashboardNormalize";

export type DutchClock = {
  dateLine: string;
  timeLine: string;
};

/**
 * Live Dutch-locale clock (1s). Pass `now` to freeze or inject time in tests.
 */
export function useDutchClock(opts?: { now?: () => Date; intervalMs?: number }): DutchClock {
  const nowRef = useRef(opts?.now ?? (() => new Date()));
  nowRef.current = opts?.now ?? (() => new Date());
  const intervalMs = opts?.intervalMs ?? 1000;
  const [clock, setClock] = useState<DutchClock>(() => formatDutchDateTime(nowRef.current()));

  useEffect(() => {
    const tick = () => setClock(formatDutchDateTime(nowRef.current()));
    tick();
    const id = window.setInterval(tick, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);

  return clock;
}
