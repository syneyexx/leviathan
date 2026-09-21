"use client";

import { useCallback, useEffect, useState } from "react";
import { SystemHealth, hadesApi } from "@/lib/hades-api";

const HEALTH_POLL_MS = 8000;

export type ShellHealthTone = "ok" | "degraded" | "offline";

export type ShellHealthState = {
  tone: ShellHealthTone;
  /** Short status shown next to the color dot (F-08). */
  label: string;
  detail: string;
  health: SystemHealth | null;
  loading: boolean;
  refresh: () => void;
};

function classify(health: SystemHealth | null, loading: boolean, error: string | null): Omit<ShellHealthState, "refresh"> {
  if (!health) {
    return {
      tone: "offline",
      label: loading ? "Laden…" : "Offline",
      detail: error || "Backend onbereikbaar",
      health: null,
      loading,
    };
  }
  const overall = health.overall || (health.backend === "ok" ? "ok" : "error");
  if (overall === "ok" && health.lm_studio === "connected") {
    return {
      tone: "ok",
      label: "Operationeel",
      detail: health.active_model ? `Model: ${health.active_model}` : "LM Studio verbonden",
      health,
      loading: false,
    };
  }
  if (overall === "ok" || overall === "warn") {
    return {
      tone: "degraded",
      label: overall === "warn" ? "Degraded" : "Beperkt",
      detail:
        health.lm_studio === "connected"
          ? health.detail || "Waarschuwing in health-checks"
          : "LM Studio offline · lokale fallback",
      health,
      loading: false,
    };
  }
  return {
    tone: "offline",
    label: "Probleem",
    detail: health.detail || error || "Health rapporteert een fout",
    health,
    loading: false,
  };
}

/** Lightweight health poll for the FINALBETA shell status pill (F-08). */
export function useShellHealth(): ShellHealthState {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await hadesApi.health();
      setHealth(next);
      setError(null);
    } catch (err) {
      setHealth(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), HEALTH_POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  return { ...classify(health, loading, error), refresh };
}
