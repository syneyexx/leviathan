/**
 * LLM / Statistieken V2 workspace orchestration.
 *
 * Authorities:
 * - Dashboard aggregates: GET /api/analytics/dashboard
 * - Live resources: GET /api/system/telemetry (merged when dashboard resources incomplete)
 *
 * Visual fixture is TEST-ONLY behind window.__LV_V2_VISUAL_FIXTURE__ === 'analytics'.
 * Production never falls back to fixture numbers on API failure.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import {
  ANALYTICS_V2_VISUAL_FIXTURE,
  isAnalyticsVisualFixtureActive,
} from "../../mocks/analyticsV2VisualFixture";
import type { AnalyticsDashboard, SystemTelemetryResponse } from "../../types/api";

export type ChartRange = "7d" | "30d" | "90d";
export type RankingRange = "7d" | "30d";

export type AnalyticsPanelId =
  | "kennis"
  | "datasets"
  | "documenten"
  | "research"
  | "verwerking"
  | "systeem"
  | "kennis-groei"
  | "dataset-groei"
  | "onderzoek-activiteit"
  | "item-types"
  | "dataset-types"
  | "bronnen"
  | "top-agents"
  | "top-bronnen"
  | "tags"
  | "resources"
  | "verwerkingstijden"
  | "activiteit";

const SEARCH_INDEX: Array<{ q: string[]; panel: AnalyticsPanelId }> = [
  { q: ["kennis", "knowledge", "items"], panel: "kennis" },
  { q: ["dataset", "datasets"], panel: "datasets" },
  { q: ["document", "documenten"], panel: "documenten" },
  { q: ["research", "onderzoek", "opdracht"], panel: "research" },
  { q: ["verwerking", "processing", "tijd"], panel: "verwerking" },
  { q: ["systeem", "gebruik", "usage", "pressure"], panel: "systeem" },
  { q: ["groei", "growth"], panel: "kennis-groei" },
  { q: ["activiteit", "activity"], panel: "onderzoek-activiteit" },
  { q: ["type", "verdeling", "donut", "item"], panel: "item-types" },
  { q: ["bron", "bronnen", "source", "provenance"], panel: "bronnen" },
  { q: ["agent", "agents"], panel: "top-agents" },
  { q: ["tag", "tags"], panel: "tags" },
  { q: ["cpu", "ram", "gpu", "disk", "resource", "telemetry"], panel: "resources" },
  { q: ["log", "event"], panel: "activiteit" },
];

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function mergeTelemetryResources(
  dash: AnalyticsDashboard,
  telemetry: SystemTelemetryResponse | null,
): AnalyticsDashboard {
  if (!telemetry) return dash;
  const d = telemetry.dashboard;
  return {
    ...dash,
    resources: {
      collectedAt: telemetry.collectedAt,
      cpu: {
        pct: d.cpuPct,
        status: d.cpuPct != null || telemetry.cpu.available ? "OK" : "UNMEASURED",
      },
      ram: {
        pct: d.ramPct,
        usedBytes: telemetry.memory.usedBytes,
        totalBytes: telemetry.memory.totalBytes,
        status: d.ramPct != null || telemetry.memory.available ? "OK" : "UNMEASURED",
      },
      gpu: {
        pct: d.gpuPct,
        status: d.gpuPct != null ? "OK" : "UNMEASURED",
        devices: telemetry.gpu.devices as unknown as Array<Record<string, unknown>>,
        aggregate: "dashboard_gpuPct_or_max_device",
      },
      disk: {
        pct: d.diskPct ?? telemetry.disk?.utilizationPct ?? null,
        usedBytes: telemetry.disk?.usedBytes ?? null,
        totalBytes: telemetry.disk?.totalBytes ?? null,
        status:
          d.diskPct != null || telemetry.disk?.available ? "OK" : "UNMEASURED",
        metric: telemetry.disk?.metric ?? null,
      },
      truth: telemetry.truth,
    },
  };
}

export function useAnalyticsWorkspace() {
  const [dashboard, setDashboard] = useState<AnalyticsDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [chartRange, setChartRange] = useState<ChartRange>("30d");
  const [rankingRange, setRankingRange] = useState<RankingRange>("7d");
  const [search, setSearch] = useState("");
  const [focusPanel, setFocusPanel] = useState<AnalyticsPanelId | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const lastGoodRef = useRef<AnalyticsDashboard | null>(null);

  const load = useCallback(
    async (opts?: { soft?: boolean }) => {
      if (isAnalyticsVisualFixtureActive()) {
        setDashboard(ANALYTICS_V2_VISUAL_FIXTURE);
        setLoading(false);
        setRefreshing(false);
        setError(null);
        setStale(false);
        setOnline(true);
        lastGoodRef.current = ANALYTICS_V2_VISUAL_FIXTURE;
        return;
      }
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      if (opts?.soft) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const [dashRes, telemetry] = await Promise.all([
          api.analyticsDashboard({ chartRange, rankingRange, activityLimit: 10 }),
          api.systemTelemetry().catch(() => null),
        ]);
        if (ac.signal.aborted) return;
        let next = dashRes.dashboard;
        // Prefer live telemetry for resource meters when available.
        if (telemetry) {
          next = mergeTelemetryResources(next, telemetry);
          // If dashboard system usage unmeasured but telemetry exists, keep dashboard truth
          // (pressure is server-side). Resources still update from telemetry.
        }
        setDashboard(next);
        lastGoodRef.current = next;
        setStale(Boolean(next.partial));
        setOnline(true);
      } catch (err) {
        if (ac.signal.aborted) return;
        setOnline(false);
        if (lastGoodRef.current) {
          setDashboard(lastGoodRef.current);
          setStale(true);
          setError(errMsg(err, "Analytics refresh mislukt — stale data behouden"));
        } else {
          setDashboard(null);
          setError(errMsg(err, "Analytics dashboard unavailable"));
        }
      } finally {
        inFlightRef.current = false;
        setLoading(false);
        setRefreshing(false);
      }
    },
    [chartRange, rankingRange],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (isAnalyticsVisualFixtureActive()) return;
    const onVis = () => {
      if (document.visibilityState === "visible") void load({ soft: true });
    };
    document.addEventListener("visibilitychange", onVis);
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void load({ soft: true });
    }, 60_000);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.clearInterval(id);
      abortRef.current?.abort();
    };
  }, [load]);

  const refresh = useCallback(() => load({ soft: true }), [load]);

  const runSearch = useCallback((query: string) => {
    setSearch(query);
    const q = query.trim().toLowerCase();
    if (!q) {
      setFocusPanel(null);
      return;
    }
    const hit = SEARCH_INDEX.find((row) => row.q.some((t) => q.includes(t) || t.includes(q)));
    if (hit) {
      setFocusPanel(hit.panel);
      const el = document.getElementById(`lv-an-panel-${hit.panel}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      el?.classList.add("is-focus");
      window.setTimeout(() => el?.classList.remove("is-focus"), 1600);
    }
  }, []);

  const kpiCards = useMemo(() => {
    const k = dashboard?.kpis;
    return [
      { id: "kennis" as const, label: "Totaal Kennis Items", metric: k?.knowledgeItems, accent: "cyan", format: "count" as const },
      { id: "datasets" as const, label: "Totaal Datasets", metric: k?.datasets, accent: "blue", format: "count" as const },
      { id: "documenten" as const, label: "Totaal Documenten", metric: k?.documents, accent: "magenta", format: "count" as const },
      { id: "research" as const, label: "Onderzoek Opdrachten", metric: k?.researchJobs, accent: "yellow", format: "count" as const },
      { id: "verwerking" as const, label: "Gem. Verwerkingstijd", metric: k?.avgProcessingSeconds, accent: "cyan", format: "seconds" as const },
      { id: "systeem" as const, label: "Systeem Gebruik", metric: k?.systemUsagePercent, accent: "red", format: "percent" as const },
    ];
  }, [dashboard]);

  return {
    dashboard,
    loading,
    refreshing,
    error,
    stale,
    online,
    chartRange,
    setChartRange,
    rankingRange,
    setRankingRange,
    search,
    setSearch,
    runSearch,
    focusPanel,
    refresh,
    kpiCards,
  };
}

export type AnalyticsWorkspace = ReturnType<typeof useAnalyticsWorkspace>;
