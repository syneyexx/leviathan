"use client";

import { useCallback } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi } from "@/lib/hades-api";

const KEY = "hades:trading-overview";

export function useHadesTrading() {
  const query = useHadesQuery(
    KEY,
    async () => {
      const [dashboard, lab, instruments, datasets] = await Promise.all([
        hadesApi.tradingDashboard().catch((err) => ({
          error: err instanceof Error ? err.message : String(err),
        })),
        hadesApi.labOverview().catch(() => null),
        hadesApi.labInstruments().catch(() => null),
        hadesApi.labDatasets({ limit: 50 }).catch(() => null),
      ]);
      return { dashboard, lab, instruments, datasets };
    },
    { staleTime: 5_000, refetchInterval: 15_000 },
  );

  const refresh = useCallback(async () => {
    invalidateHadesQuery(KEY);
    return query.refetch();
  }, [query]);

  const dashRaw = query.data?.dashboard;
  const dashboard =
    dashRaw && typeof dashRaw === "object" && "paper" in dashRaw
      ? (dashRaw as Awaited<ReturnType<typeof hadesApi.tradingDashboard>>)
      : null;
  const error =
    query.error?.message ||
    (dashRaw && typeof dashRaw === "object" && "error" in dashRaw
      ? String((dashRaw as { error: string }).error)
      : null);

  return {
    dashboard,
    lab: query.data?.lab,
    paper: dashboard?.paper ?? null,
    strategies: dashboard?.strategies ?? [],
    runs: dashboard?.runs ?? [],
    symbols: dashboard?.symbols ?? [],
    bars: dashboard?.bars ?? [],
    instruments: query.data?.instruments?.instruments ?? [],
    datasets: query.data?.datasets?.datasets ?? [],
    loading: query.status === "loading" && !query.data,
    error,
    refresh,
    setEnabled: async (enabled: boolean) => {
      await hadesApi.setPaperTrading(enabled);
      await refresh();
    },
    setKillSwitch: async (armed: boolean) => {
      await hadesApi.setTradingKillSwitch(armed);
      await refresh();
    },
  };
}
