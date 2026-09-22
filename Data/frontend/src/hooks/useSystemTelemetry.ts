import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { SystemTelemetryResponse } from "../types/api";

const HISTORY_MAX = 60;

export type TelemetryHistoryPoint = {
  at: number;
  cpuPct: number | null;
  ramPct: number | null;
  gpuPct: number | null;
  vramPct: number | null;
};

/**
 * Live system telemetry for visible pages (~1s).
 * Pauses when document is hidden; never overlaps in-flight requests.
 */
export function useSystemTelemetry(opts?: { enabled?: boolean; intervalMs?: number }) {
  const enabled = opts?.enabled ?? true;
  const intervalMs = opts?.intervalMs ?? 1000;
  const [sample, setSample] = useState<SystemTelemetryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<TelemetryHistoryPoint[]>([]);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  const pull = useCallback(async () => {
    if (inFlight.current) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    inFlight.current = true;
    try {
      const data = await api.systemTelemetry();
      if (!mounted.current) return;
      setSample(data);
      setError(null);
      setHistory((prev) => {
        const next: TelemetryHistoryPoint = {
          at: Date.now(),
          cpuPct: data.dashboard.cpuPct,
          ramPct: data.dashboard.ramPct,
          gpuPct: data.dashboard.gpuPct,
          vramPct: data.dashboard.vramPct,
        };
        const merged = [...prev, next];
        return merged.length > HISTORY_MAX ? merged.slice(merged.length - HISTORY_MAX) : merged;
      });
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : "Telemetry unavailable");
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) return;
    void pull();
    const id = window.setInterval(() => {
      void pull();
    }, intervalMs);
    const onVis = () => {
      if (document.visibilityState === "visible") void pull();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [enabled, intervalMs, pull]);

  return { sample, error, history, refresh: pull };
}

export function sparklinePath(
  history: TelemetryHistoryPoint[],
  key: keyof Omit<TelemetryHistoryPoint, "at">,
  width = 320,
  height = 60,
): { area: string; line: string } | null {
  const values = history
    .map((p) => p[key])
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (values.length < 2) return null;
  const max = Math.max(100, ...values);
  const min = 0;
  const span = Math.max(1, max - min);
  const step = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / span) * (height - 8) - 4;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = points.join(" ");
  const area = `M${points[0]} L${points.join(" ")} L${width},${height} L0,${height} Z`;
  return { area, line };
}
