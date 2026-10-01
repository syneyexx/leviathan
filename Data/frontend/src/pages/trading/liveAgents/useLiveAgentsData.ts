/**
 * Live Agents data — realtime / offline paper execution console.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../../../api/client";
import type {
  MarketDataSource,
  MarketSimPaperDeployment,
  PaperPortfolio,
  TradeOrchestra,
  TradeOrchestraMember,
  TradingDecision,
} from "../../../types/api";
import { UNMEASURED, asNumber, fmtInt, fmtUsd } from "../workspaces/commandHub/hubFormat";

export type DataMode = "realtime" | "offline";

export type LiveAgentCard = {
  id: string;
  name: string;
  role: string;
  strategy: string;
  status: string;
  statusTone: "green" | "gold" | "red" | "purple" | "muted";
  dataMode: DataMode;
  executionMode: "PAPER";
  wallet: number | null;
  sessionPnl: number | null;
  openPositions: string;
  queueDepth: string;
  latestAction: string;
  latency: string;
  spark: number[];
};

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn();
  } catch {
    return fallback;
  }
}

function tone(status: string): LiveAgentCard["statusTone"] {
  const s = status.toUpperCase();
  if (["ACTIVE", "RUNNING", "READY", "LIVE", "WARM"].includes(s)) return "green";
  if (["PAUSE", "PAUSED", "SHADOW"].includes(s)) return "gold";
  if (["SIMULATION", "REPLAY", "OFFLINE"].includes(s)) return "purple";
  if (["KILLED", "ERROR", "FAILED", "STOPPED"].includes(s)) return "red";
  return "muted";
}

export function useLiveAgentsData(market: string) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [dataMode, setDataMode] = useState<DataMode>("realtime");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [agents, setAgents] = useState<LiveAgentCard[]>([]);
  const [portfolios, setPortfolios] = useState<PaperPortfolio[]>([]);
  const [deployments, setDeployments] = useState<MarketSimPaperDeployment[]>([]);
  const [orchestras, setOrchestras] = useState<TradeOrchestra[]>([]);
  const [orders, setOrders] = useState<Array<Record<string, unknown>>>([]);
  const [decisions, setDecisions] = useState<TradingDecision[]>([]);
  const [sources, setSources] = useState<MarketDataSource[]>([]);
  const [providers, setProviders] = useState<Array<Record<string, unknown>>>([]);
  const [presets, setPresets] = useState<Array<{ id: string }>>([]);
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);
  const [liveTrading, setLiveTrading] = useState("BLOCKED");
  const [selectedPortfolioId, setSelectedPortfolioId] = useState("");
  const [replaySpeed, setReplaySpeed] = useState(1);
  const [scenarioPreset, setScenarioPreset] = useState("crash_recovery");
  const [maxPositions, setMaxPositions] = useState("5");
  const [maxPosSize, setMaxPosSize] = useState("20");
  const [riskGuards, setRiskGuards] = useState(true);
  const [paperOnly, setPaperOnly] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ports, orch, deps, live, src, decisionsResp, runsResp, presetsResp, prov] =
        await Promise.all([
          safe(() => api.listPortfolios(50), { portfolios: [] as PaperPortfolio[] }),
          safe(() => api.listTradeOrchestras(false), { orchestras: [] as TradeOrchestra[] }),
          safe(() => api.listPaperDeployments({ limit: 50 }), {
            deployments: [] as MarketSimPaperDeployment[],
            truth: {},
          }),
          safe(() => api.marketSimLiveTradingStatus(), { LIVE_TRADING_AVAILABLE: "BLOCKED" }),
          safe(() => api.listMarketData(100), { sources: [] as MarketDataSource[] }),
          safe(() => api.listTradingDecisions({ limit: 40 }), { decisions: [] as TradingDecision[] }),
          safe(() => api.listMarketSimRuns(30), { runs: [] as Array<Record<string, unknown>> }),
          safe(() => api.listOfflineScenarioPresets(), {
            presets: [] as Array<{ id: string; segments: Array<Record<string, unknown>> }>,
            truth: {},
          }),
          safe(
            () =>
              (api as { listMarketProviders?: () => Promise<{ providers: Array<Record<string, unknown>> }> })
                .listMarketProviders?.() ?? Promise.resolve({ providers: [] }),
            { providers: [] as Array<Record<string, unknown>> },
          ),
        ]);

      setPortfolios(ports.portfolios || []);
      setOrchestras(orch.orchestras || []);
      setDeployments(deps.deployments || []);
      setLiveTrading(String((live as { LIVE_TRADING_AVAILABLE?: string }).LIVE_TRADING_AVAILABLE || "BLOCKED"));
      setSources(src.sources || []);
      setDecisions(decisionsResp.decisions || []);
      setRuns((runsResp.runs || []) as Array<Record<string, unknown>>);
      setPresets((presetsResp.presets || []).map((p) => ({ id: p.id })));
      setProviders(prov.providers || []);
      setSelectedPortfolioId((prev) => prev || ports.portfolios?.[0]?.portfolio_id || "");

      const details = await Promise.all(
        (orch.orchestras || [])
          .filter((o) => o.enabled)
          .slice(0, 8)
          .map((o) => safe(() => api.getTradeOrchestra(o.orchestraId), null)),
      );

      const cards: LiveAgentCard[] = [];
      for (const d of details) {
        const full = d?.orchestra;
        if (!full) continue;
        const members: TradeOrchestraMember[] = full.members || [];
        const linked = (ports.portfolios || []).find((p) => p.orchestra_id === full.orchestraId);
        for (const m of members) {
          const health = String(m.health || "unknown");
          cards.push({
            id: m.agentId || `${full.orchestraId}-${m.name}`,
            name: m.name || m.agentId || "Agent",
            role: m.role || m.canonicalRole || UNMEASURED,
            strategy: UNMEASURED,
            status: m.enabled ? health : "Pauze",
            statusTone: tone(m.enabled ? health : "PAUSED"),
            dataMode,
            executionMode: "PAPER",
            wallet: linked ? asNumber(linked.equity) : null,
            sessionPnl: linked ? asNumber(linked.realized_pnl) : null,
            openPositions: UNMEASURED,
            queueDepth: UNMEASURED,
            latestAction: UNMEASURED,
            latency: UNMEASURED,
            spark: linked ? [asNumber(linked.equity) ?? 0] : [],
          });
        }
      }
      if (!cards.length) {
        for (const o of orch.orchestras || []) {
          cards.push({
            id: o.orchestraId,
            name: o.name,
            role: o.role || "orchestra",
            strategy: UNMEASURED,
            status: String(o.health || (o.enabled ? "Ready" : "Pauze")),
            statusTone: tone(String(o.health || (o.enabled ? "READY" : "PAUSED"))),
            dataMode,
            executionMode: "PAPER",
            wallet: null,
            sessionPnl: null,
            openPositions: UNMEASURED,
            queueDepth: UNMEASURED,
            latestAction: UNMEASURED,
            latency: UNMEASURED,
            spark: [],
          });
        }
      }
      setAgents(cards);
      setSelectedId((prev) => prev || cards[0]?.id || null);
      setStale(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStale(true);
    } finally {
      setLoading(false);
    }
  }, [dataMode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedPortfolioId) {
      setOrders([]);
      return;
    }
    void safe(() => api.listPortfolioOrders(selectedPortfolioId, 40), { orders: [] }).then((res) => {
      setOrders(res.orders || []);
    });
  }, [selectedPortfolioId]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter((a) => a.name.toLowerCase().includes(q) || a.role.toLowerCase().includes(q));
  }, [agents, search]);

  const selected = useMemo(
    () => agents.find((a) => a.id === selectedId) ?? filtered[0] ?? null,
    [agents, filtered, selectedId],
  );

  const kpis = useMemo(() => {
    const liveSessions = deployments.filter((d) =>
      ["ACTIVE", "RUNNING", "SHADOW"].some((t) => String(d.status || "").toUpperCase().includes(t)),
    ).length;
    const offline = runs.filter((r) => {
      const st = String(r.status || r.state || "").toUpperCase();
      return ["RUNNING", "PAUSED", "ACTIVE"].some((t) => st.includes(t));
    }).length;
    const nav = portfolios.reduce((acc, p) => acc + (asNumber(p.equity) ?? 0), 0);
    return [
      {
        id: "live",
        label: "Live sessies",
        value: `${liveSessions} / ${Math.max(agents.length, liveSessions)}`,
        delta: UNMEASURED,
        spark: [liveSessions],
      },
      {
        id: "offline",
        label: "Offline replays",
        value: fmtInt(offline),
        delta: UNMEASURED,
        spark: [offline],
      },
      {
        id: "nav",
        label: "Paper NAV",
        value: portfolios.length ? fmtUsd(nav) : UNMEASURED,
        delta: UNMEASURED,
        spark: portfolios.slice(0, 8).map((p) => asNumber(p.equity) ?? 0),
      },
      {
        id: "orders",
        label: "Orders/min",
        value: UNMEASURED,
        delta: UNMEASURED,
        spark: [],
      },
      {
        id: "latency",
        label: "Gem. latency",
        value: UNMEASURED,
        delta: UNMEASURED,
        spark: [],
      },
    ];
  }, [deployments, runs, portfolios, agents.length]);

  const marketSnapshot = useMemo(() => {
    return sources.slice(0, 8).map((s) => ({
      symbol: s.symbol,
      timeframe: s.timeframe,
      status: s.status,
      path: s.path,
      price: UNMEASURED,
      change: UNMEASURED,
      volatility: UNMEASURED,
    }));
  }, [sources]);

  const brokerHealth = useMemo(
    () => [
      { id: "fill", label: "Fill rate", value: UNMEASURED },
      { id: "reject", label: "Afgewezen orders", value: UNMEASURED },
      { id: "queue", label: "Orders in queue", value: orders.length ? String(orders.length) : UNMEASURED },
      { id: "cancel", label: "Pending cancels", value: UNMEASURED },
      {
        id: "workers",
        label: "Execution workers",
        value: UNMEASURED,
      },
    ],
    [orders.length],
  );

  async function generateScenario() {
    setBusy("scenario");
    setNotice(null);
    try {
      const res = await api.createOfflineScenario({
        preset: scenarioPreset,
        symbol: market || "BTCUSDT",
        timeframe: "1h",
        seed: Date.now() % 1_000_000,
        narrative: `AI-structured offline scenario preset=${scenarioPreset}`,
        prompt: `Generate structured regime constraints for ${scenarioPreset}`,
      });
      setNotice(
        `Scenario gegenereerd: ${String(res.scenario.scenarioId || "")} · bars=${String(res.scenario.barCount || "")} (PAPER REPLAY ONLY)`,
      );
      await refresh();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function startReplay() {
    setBusy("replay");
    setNotice(null);
    try {
      const ready = sources.find((s) => s.status === "READY") || sources[0];
      if (!ready) {
        setNotice("Geen dataset/scenario beschikbaar — genereer of indexeer eerst data.");
        return;
      }
      const strategies = await api.listMarketStrategies(20).catch(() => ({ strategies: [] }));
      const strategyId = strategies.strategies?.[0]?.strategy_id;
      if (!strategyId) {
        setNotice("Geen strategie beschikbaar voor offline replay.");
        return;
      }
      const created = await api.createMarketSimRun({
        strategyId,
        sourceId: ready.source_id,
        initialCash: 100000,
        speed: replaySpeed,
      });
      const runObj = (created as { run?: { run_id?: string }; run_id?: string }).run;
      const runId = String(runObj?.run_id || (created as { run_id?: string }).run_id || "");
      if (runId) {
        await api.startMarketSimRun(runId);
        setNotice(`Offline replay gestart (PAPER): ${runId}`);
      } else {
        setNotice("Replay aangemaakt — start-id UNMEASURED in response.");
      }
      await refresh();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function killAll() {
    setBusy("kill");
    try {
      for (const d of deployments.slice(0, 20)) {
        if (d.kill_switch) continue;
        await safe(() => api.paperDeploymentKillSwitch(d.deployment_id, true), null);
      }
      for (const p of portfolios.slice(0, 20)) {
        if (p.kill_switch) continue;
        await safe(() => api.portfolioKillSwitch(p.portfolio_id, true), null);
      }
      setNotice("Kill switch geactiveerd op deployments/portfolios (PAPER).");
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  return {
    loading,
    error,
    stale,
    liveTrading,
    dataMode,
    setDataMode,
    agents: filtered,
    selected,
    setSelectedId,
    search,
    setSearch,
    kpis,
    orders,
    decisions,
    marketSnapshot,
    brokerHealth,
    providers,
    sources,
    presets,
    runs,
    deployments,
    portfolios,
    orchestras,
    selectedPortfolioId,
    setSelectedPortfolioId,
    replaySpeed,
    setReplaySpeed,
    scenarioPreset,
    setScenarioPreset,
    maxPositions,
    setMaxPositions,
    maxPosSize,
    setMaxPosSize,
    riskGuards,
    setRiskGuards,
    paperOnly,
    setPaperOnly,
    busy,
    notice,
    generateScenario,
    startReplay,
    killAll,
    refresh,
  };
}

export type LiveAgentsData = ReturnType<typeof useLiveAgentsData>;
