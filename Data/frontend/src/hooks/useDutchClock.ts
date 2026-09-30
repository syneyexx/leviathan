import { useEffect, useRef, useState } from "react";
import { formatDutchDateTime } from "../lib/dashboardNormalize";
import { formatClockInTimezone, readUiPrefsCache } from "../lib/uiPreferences";

export type DutchClock = {
  dateLine: string;
  timeLine: string;
};

/**
 * Live clock (1s). Pass `now` to freeze or inject time in tests.
 * Uses Settings Control Plane timezone/locale from the UI prefs cache when present.
 */
export function useDutchClock(opts?: { now?: () => Date; intervalMs?: number }): DutchClock {
  const nowRef = useRef(opts?.now ?? (() => new Date()));
  nowRef.current = opts?.now ?? (() => new Date());
  const intervalMs = opts?.intervalMs ?? 1000;

  const tick = (): DutchClock => {
    const date = nowRef.current();
    const prefs = readUiPrefsCache();
    try {
      return formatClockInTimezone(date, prefs.timezone, prefs.locale);
    } catch {
      return formatDutchDateTime(date);
    }
  };

  const [clock, setClock] = useState<DutchClock>(() => tick());

  useEffect(() => {
    const run = () => setClock(tick());
    run();
    const id = window.setInterval(run, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);

  return clock;
}
