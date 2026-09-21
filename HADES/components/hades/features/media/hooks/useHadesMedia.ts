"use client";

import { useCallback } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi } from "@/lib/hades-api";

const KEY = "hades:media-overview";

export function useHadesMedia() {
  const query = useHadesQuery(
    KEY,
    async () => {
      const [overview, channels, projects, trends, jobs, setup, analytics] = await Promise.all([
        hadesApi.mediaOverview().catch((err) => ({ error: err instanceof Error ? err.message : String(err) })),
        hadesApi.mediaChannels().catch(() => null),
        hadesApi.mediaProjects().catch(() => null),
        hadesApi.mediaTrends().catch(() => null),
        hadesApi.mediaPublishJobs().catch(() => null),
        hadesApi.mediaSetup().catch(() => null),
        hadesApi.mediaAnalytics().catch(() => null),
      ]);
      return { overview, channels, projects, trends, jobs, setup, analytics };
    },
    { staleTime: 8_000, refetchInterval: 20_000 },
  );

  const refresh = useCallback(async () => {
    invalidateHadesQuery(KEY);
    return query.refetch();
  }, [query]);

  const overview = query.data?.overview && !("error" in (query.data.overview as object) && (query.data.overview as { error?: string }).error)
    ? (query.data.overview as Awaited<ReturnType<typeof hadesApi.mediaOverview>>)
    : null;
  const overviewError =
    query.data?.overview && typeof query.data.overview === "object" && "error" in query.data.overview
      ? String((query.data.overview as { error: string }).error)
      : null;

  return {
    overview,
    channels: query.data?.channels,
    projects: query.data?.projects,
    trends: query.data?.trends,
    jobs: query.data?.jobs,
    setup: query.data?.setup,
    analytics: query.data?.analytics,
    loading: query.status === "loading" && !query.data,
    error: query.error?.message || overviewError,
    refresh,
  };
}
