import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../../../api/client";
import type {
  AgentDefinition,
  AgentEvent,
  MarketBarsResponse,
  MarketSimCapabilities,
  MarketSimPaperDeployment,
  PaperPortfolio,
  PortfolioDashboard,
  TradeOrchestra,
} from "../../../../types/api";
import {
  DEFAULT_WATCHLIST,
  draftToSettings,
  settingsToDraft,
  type OrchestratorDraft,
} from "../utils/format";

const STORAGE_KEY = "lv.paper.trading.operator.v1";

type StoredPrefs = {
  portfolioId?: string;
  symbol?: string;
  timeframe?: string;
  watchlist?: string[];
  providerId?: string;
  indicators?: { ma20: boolean; ma50: boolean; ma200: boolean; volume: boolean };
};

export type PaperIndicators = {
  ma20: boolean;
  ma50: boolean;
  ma200: boolean;
  volume: boolean;
};

export type PaperTradingState = {
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  caps: MarketSimCapabilities | null;
  portfolios: PaperPortfolio[];
  portfolioId: string | null;
  dashboard: PortfolioDashboard | null;
  orders: Array<Record<string, unknown>>;
  bars: MarketBarsResponse | null;
  barsError: string | null;
  barsLoading: boolean;
  symbol: string;
  timeframe: string;
  providerId: string;
  watchlist: string[];
  indicators: PaperIndicators;
  showIndicatorsMenu: boolean;
  agents: AgentDefinition[];
  deployments: MarketSimPaperDeployment[];
  events: AgentEvent[];
  orchestras: TradeOrchestra[];
  draft: OrchestratorDraft;
  busyAction: string | null;
  drawingTool: string | null;
  layoutSavedAt: string | null;
};

function loadPrefs(): StoredPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as StoredPrefs;
  } catch {
    return {};
  }
}

function savePrefs(p: StoredPrefs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

export function usePaperTradingOperator() {
  const prefsRef = useRef(loadPrefs());
  const symbolRef = useRef(prefsRef.current.symbol || "BTCUSDT");
  const timeframeRef = useRef(prefsRef.current.timeframe || "1h");
  const providerRef = useRef(prefsRef.current.providerId || "binance_public");

  const [state, setState] = useState<PaperTradingState>(() => ({
    loading: true,
    refreshing: false,
    error: null,
    caps: null,
    portfolios: [],
    portfolioId: prefsRef.current.portfolioId ?? null,
    dashboard: null,
    orders: [],
    bars: null,
    barsError: null,
    barsLoading: false,
    symbol: symbolRef.current,
    timeframe: timeframeRef.current,
    providerId: providerRef.current,
    watchlist: prefsRef.current.watchlist?.length
      ? prefsRef.current.watchlist
      : [...DEFAULT_WATCHLIST],
    indicators: prefsRef.current.indicators || {
      ma20: true,
      ma50: true,
      ma200: true,
      volume: true,
    },
    showIndicatorsMenu: false,
    agents: [],
    deployments: [],
    events: [],
    orchestras: [],
    draft: settingsToDraft(undefined),
    busyAction: null,
    drawingTool: null,
    layoutSavedAt: null,
  }));

  const abortRef = useRef<AbortController | null>(null);

  const persist = useCallback((patch: Partial<StoredPrefs>) => {
    prefsRef.current = { ...prefsRef.current, ...patch };
    savePrefs(prefsRef.current);
  }, []);

  const ensurePortfolio = useCallback(async (): Promise<PaperPortfolio> => {
    const listed = await api.listPortfolios(50);
    const portfolios = listed.portfolios || [];
    const existing =
      portfolios.find((p) => p.portfolio_id === prefsRef.current.portfolioId) || portfolios[0];
    if (existing) return existing;
    const created = await api.createPortfolio({
      name: "Paper Trading Desk",
      initialEquity: 100_000,
      providerId: prefsRef.current.providerId || "binance_public",
      benchmarkSymbol: prefsRef.current.symbol || "BTCUSDT",
      brokerMode: "local_paper",
      settings: draftToSettings(settingsToDraft(undefined)),
      allowManualOnly: true,
    });
    return created.portfolio;
  }, []);

  const refreshBars = useCallback(async () => {
    const symbol = symbolRef.current;
    const timeframe = timeframeRef.current;
    const providerId = providerRef.current;
    setState((s) => ({ ...s, barsLoading: true, barsError: null }));
    try {
      const res = await api.fetchMarketBars({ symbol, timeframe, providerId, limit: 220 });
      setState((s) => ({ ...s, bars: res, barsLoading: false, barsError: null }));
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      setState((s) => ({ ...s, barsLoading: false, barsError: msg }));
    }
  }, []);

  const refreshCore = useCallback(
    async (opts?: { soft?: boolean }) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setState((s) => ({
        ...s,
        loading: opts?.soft ? s.loading : true,
        refreshing: Boolean(opts?.soft),
        error: opts?.soft ? s.error : null,
      }));
      try {
        const portfolio = await ensurePortfolio();
        const portfolioId = portfolio.portfolio_id;
        persist({ portfolioId });

        const [caps, dash, ordersRes, agentsRes, depsRes, eventsRes, orchRes] = await Promise.all([
          api.marketSimCapabilities(),
          api.portfolioDashboard(portfolioId, "YTD"),
          api.listPortfolioOrders(portfolioId, 80),
          api.listAgents({ kind: "trading", includeSystem: true }).catch(() =>
            api.listAgents({ includeSystem: true }),
          ),
          api.listPaperDeployments({ limit: 50 }),
          api.listAgentEvents({ limit: 40 }),
          api.listTradeOrchestras(false),
        ]);
        if (ac.signal.aborted) return;

        const settings = (dash.portfolio.settings || portfolio.settings || {}) as Record<
          string,
          unknown
        >;
        const watched = Array.isArray(settings.watched_symbols)
          ? (settings.watched_symbols as string[]).map((x) => String(x).toUpperCase())
          : undefined;
        const chartInd = (settings.chart_indicators || {}) as Record<string, unknown>;

        setState((s) => ({
          ...s,
          loading: false,
          refreshing: false,
          error: null,
          caps,
          portfolios: [dash.portfolio],
          portfolioId,
          dashboard: dash,
          orders: ordersRes.orders || [],
          agents: agentsRes.agents || [],
          deployments: (depsRes.deployments || []) as MarketSimPaperDeployment[],
          events: eventsRes.events || [],
          orchestras: orchRes.orchestras || [],
          draft: settingsToDraft(settings),
          watchlist: watched?.length ? watched : s.watchlist,
          providerId: dash.portfolio.provider_id || s.providerId,
          indicators: {
            ma20: chartInd.ma20 !== false,
            ma50: chartInd.ma50 !== false,
            ma200: chartInd.ma200 !== false,
            volume: chartInd.volume !== false,
          },
        }));
      } catch (e) {
        if (ac.signal.aborted) return;
        const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
        setState((s) => ({ ...s, loading: false, refreshing: false, error: msg }));
      }
    },
    [ensurePortfolio, persist],
  );

  useEffect(() => {
    void refreshCore();
    void refreshBars();
    const coreId = window.setInterval(() => void refreshCore({ soft: true }), 5000);
    const barsId = window.setInterval(() => void refreshBars(), 8000);
    return () => {
      window.clearInterval(coreId);
      window.clearInterval(barsId);
      abortRef.current?.abort();
    };
  }, [refreshCore, refreshBars]);

  const setSymbol = (symbol: string) => {
    const u = symbol.toUpperCase().trim();
    if (!u) return;
    symbolRef.current = u;
    setState((s) => ({
      ...s,
      symbol: u,
      watchlist: s.watchlist.includes(u) ? s.watchlist : [...s.watchlist, u],
    }));
    persist({
      symbol: u,
      watchlist: [...(prefsRef.current.watchlist || [...DEFAULT_WATCHLIST]), u].filter(
        (v, i, a) => a.indexOf(v) === i,
      ),
    });
    void refreshBars();
    const pid = prefsRef.current.portfolioId;
    if (pid) {
      void api
        .patchPortfolio(pid, { benchmarkSymbol: u, settings: { benchmark_symbol: u } })
        .then(() => refreshCore({ soft: true }))
        .catch(() => undefined);
    }
  };

  const setTimeframe = (timeframe: string) => {
    timeframeRef.current = timeframe;
    setState((s) => ({ ...s, timeframe }));
    persist({ timeframe });
    void refreshBars();
  };

  const addSymbol = (raw: string) => {
    setSymbol(raw);
  };

  const patchDraft = (patch: Partial<OrchestratorDraft>) => {
    setState((s) => ({ ...s, draft: { ...s.draft, ...patch } }));
  };

  const saveOrchestrator = async () => {
    const pid = state.portfolioId;
    if (!pid) return;
    setState((s) => ({ ...s, busyAction: "save" }));
    try {
      await api.patchPortfolio(pid, {
        settings: {
          ...draftToSettings(state.draft),
          watched_symbols: state.watchlist,
          chart_indicators: state.indicators,
        },
      });
      const orch = state.orchestras[0];
      if (orch) {
        const level =
          state.draft.agentMode === "autonomous"
            ? "autonomous"
            : state.draft.agentMode === "assisted"
              ? "assisted"
              : "manual";
        try {
          await api.setTradeAutonomy(orch.orchestraId, level);
        } catch {
          /* optional */
        }
      }
      await refreshCore({ soft: true });
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setState((s) => ({ ...s, busyAction: null }));
    }
  };

  const runAction = async (action: "deploy" | "pause" | "flatten") => {
    const pid = state.portfolioId;
    if (!pid) return;
    setState((s) => ({ ...s, busyAction: action, error: null }));
    try {
      if (action === "deploy") {
        await api.patchPortfolio(pid, {
          settings: {
            ...draftToSettings(state.draft),
            watched_symbols: state.watchlist,
            chart_indicators: state.indicators,
          },
        });
        try {
          await api.startPortfolio(pid);
        } catch {
          await api.resumePortfolio(pid);
        }
        await api.fleetStartAll().catch(() => undefined);
        await api.portfolioTick(pid).catch(() => undefined);
      } else if (action === "pause") {
        await api.pausePortfolio(pid);
        await api.fleetPauseAll().catch(() => undefined);
      } else if (action === "flatten") {
        await api.flattenPortfolio(pid);
      }
      await refreshCore({ soft: true });
    } catch (e) {
      setState((s) => ({
        ...s,
        error: e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setState((s) => ({ ...s, busyAction: null }));
    }
  };

  const closePosition = async (positionId: string) => {
    const pid = state.portfolioId;
    if (!pid) return;
    setState((s) => ({ ...s, busyAction: `close:${positionId}` }));
    try {
      await api.closePortfolioPosition(pid, positionId);
      await refreshCore({ soft: true });
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setState((s) => ({ ...s, busyAction: null }));
    }
  };

  const toggleAgent = async (agentId: string, enable: boolean) => {
    setState((s) => ({ ...s, busyAction: `agent:${agentId}` }));
    try {
      if (enable) await api.enableAgent(agentId);
      else await api.disableAgent(agentId);
      await refreshCore({ soft: true });
    } catch (e) {
      setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setState((s) => ({ ...s, busyAction: null }));
    }
  };

  const setIndicators = (patch: Partial<PaperIndicators>) => {
    setState((s) => {
      const indicators = { ...s.indicators, ...patch };
      persist({ indicators });
      return { ...s, indicators };
    });
  };

  const saveLayout = () => {
    persist({
      symbol: state.symbol,
      timeframe: state.timeframe,
      watchlist: state.watchlist,
      indicators: state.indicators,
      providerId: state.providerId,
      portfolioId: state.portfolioId || undefined,
    });
    setState((s) => ({ ...s, layoutSavedAt: new Date().toISOString() }));
  };

  return {
    state,
    setState,
    refreshCore,
    refreshBars,
    setSymbol,
    setTimeframe,
    addSymbol,
    patchDraft,
    saveOrchestrator,
    runAction,
    closePosition,
    toggleAgent,
    setIndicators,
    saveLayout,
  };
}
