/**
 * Trading Desk (WAVE 5/6) — single composition hook for the native page.
 *
 * Absorbs Paper Trading + Portefeuille + Broker boundary + Wallets + Orchestra
 * fleet behind one hook. Every value is derived from real backend responses;
 * anything the backend does not measure renders literally as "UNMEASURED"
 * (never invented client-side). Live trading stays BLOCKED everywhere.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../../../api/client";
import type {
  MarketBar,
  MarketSimCapabilities,
  MarketSimPaperDeployment,
  PaperPortfolio,
  PortfolioDashboard,
  PortfolioRecommendation,
  TradeOrchestra,
  TradingDecision,
} from "../../../../types/api";
import { UNMEASURED, asNumber, asRec } from "../commandHub/hubFormat";

function asStr(v: unknown, fallback = UNMEASURED): string {
  if (typeof v === "string" && v.trim()) return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return fallback;
}

export type WalletRow = {
  id: string;
  name: string;
  status: string;
  mode: string;
  brokerMode: string;
  baseCurrency: string;
  equity: number | null;
  cash: number | null;
  unrealizedPnl: number | null;
  realizedPnl: number | null;
  killSwitch: boolean;
  orchestraId: string | null;
  createdAt: string;
};

export type OrderRow = {
  id: string;
  symbol: string;
  side: string;
  qty: string;
  status: string;
  createdAt: string;
  raw: Record<string, unknown>;
};

export type ActivityRow = {
  id: string;
  time: string;
  agent: string;
  role: string;
  stage: string;
  summary: string;
};

function emptyCapabilities(): MarketSimCapabilities {
  return {
    feature_enabled: false,
    live_trading_default: "BLOCKED",
    live_credentials_separated: true,
    alpaca_paper_secrets_present: false,
    binance_public_reachable: false,
    force_live_blocked: true,
    markets: [],
    execution_granularity: [],
    truth: {
      capability_from_adapters: false,
      not_from_ui_presence: false,
      profitable_backtest_is_not_proof: true,
    },
  } as unknown as MarketSimCapabilities;
}

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn();
  } catch {
    return fallback;
  }
}

export function useTradingDeskData(market: string, timeframe: string) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [portfolios, setPortfolios] = useState<PaperPortfolio[]>([]);
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string>("");
  const [dashboard, setDashboard] = useState<PortfolioDashboard | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [orchestras, setOrchestras] = useState<TradeOrchestra[]>([]);
  const [deployments, setDeployments] = useState<MarketSimPaperDeployment[]>([]);
  const [decisions, setDecisions] = useState<TradingDecision[]>([]);
  const [capabilities, setCapabilities] = useState<MarketSimCapabilities>(emptyCapabilities());
  const [liveTrading, setLiveTrading] = useState("BLOCKED");
  const [bars, setBars] = useState<MarketBar[]>([]);
  const [barsLoading, setBarsLoading] = useState(false);
  const [selectedPositions, setSelectedPositions] = useState<string[]>([]);

  const marketRef = useRef(market);
  const timeframeRef = useRef(timeframe);
  marketRef.current = market;
  timeframeRef.current = timeframe;

  const notify = useCallback((msg: string) => {
    setNotice(msg);
    window.setTimeout(() => setNotice((prev) => (prev === msg ? null : prev)), 6000);
  }, []);

  /* ------------------------------------------------------------- list load */

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [portsResp, orchResp, depResp, caps, live] = await Promise.all([
        safe(() => api.listPortfolios(50), { portfolios: [] as PaperPortfolio[] }),
        safe(() => api.listTradeOrchestras(false), { orchestras: [] as TradeOrchestra[] }),
        safe(
          () => api.listPaperDeployments({ limit: 50 }),
          { deployments: [] as MarketSimPaperDeployment[], truth: {} },
        ),
        safe(() => api.marketSimCapabilities(), emptyCapabilities()),
        safe(() => api.marketSimLiveTradingStatus(), { LIVE_TRADING_AVAILABLE: "BLOCKED" } as Record<string, unknown>),
      ]);
      setPortfolios(portsResp.portfolios || []);
      setOrchestras(orchResp.orchestras || []);
      setDeployments(depResp.deployments || []);
      setCapabilities(caps);
      const liveAvail = String(
        (live as { LIVE_TRADING_AVAILABLE?: string }).LIVE_TRADING_AVAILABLE ?? caps.live_trading_default ?? "BLOCKED",
      );
      setLiveTrading(liveAvail);
      setSelectedPortfolioId((prev) => prev || (portsResp.portfolios || [])[0]?.portfolio_id || "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Failed to load Trading Desk");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  /* ------------------------------------------------------------ dashboard */

  const refreshDashboard = useCallback(async (portfolioId?: string) => {
    const pid = portfolioId ?? selectedPortfolioId;
    if (!pid) {
      setDashboard(null);
      setOrders([]);
      return;
    }
    setDashboardLoading(true);
    try {
      const [dash, ordersResp] = await Promise.all([
        api.portfolioDashboard(pid, "YTD"),
        safe(() => api.listPortfolioOrders(pid, 50), { orders: [] as Array<Record<string, unknown>> }),
      ]);
      setDashboard(dash);
      setOrders(
        (ordersResp.orders || []).map((o) => ({
          id: String(o.order_id ?? o.client_order_id ?? o.id ?? Math.random()),
          symbol: String(o.symbol ?? "—"),
          side: String(o.side ?? "—"),
          qty: String(o.qty ?? o.quantity ?? "—"),
          status: String(o.status ?? "—"),
          createdAt: String(o.created_at ?? o.timestamp ?? "—"),
          raw: o,
        })),
      );
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Dashboard refresh failed");
    } finally {
      setDashboardLoading(false);
    }
  }, [selectedPortfolioId]);

  useEffect(() => {
    void refreshDashboard(selectedPortfolioId);
    setSelectedPositions([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPortfolioId]);

  /* --------------------------------------------------------------- chart */

  const refreshBars = useCallback(async () => {
    setBarsLoading(true);
    try {
      const res = await api.fetchMarketBars({
        symbol: marketRef.current,
        timeframe: timeframeRef.current,
        limit: 120,
      });
      setBars(res.bars || []);
    } catch {
      setBars([]);
    } finally {
      setBarsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshBars();
  }, [refreshBars, market, timeframe]);

  /* ------------------------------------------------------------ activity */

  const refreshActivity = useCallback(async () => {
    try {
      const res = await api.listTradingDecisions({ limit: 40 });
      setDecisions(res.decisions || []);
    } catch {
      setDecisions([]);
    }
  }, []);

  useEffect(() => {
    void refreshActivity();
  }, [refreshActivity]);

  const refresh = useCallback(async () => {
    await Promise.all([loadList(), refreshDashboard(selectedPortfolioId), refreshBars(), refreshActivity()]);
  }, [loadList, refreshDashboard, refreshBars, refreshActivity, selectedPortfolioId]);

  /* -------------------------------------------------------------- derived */

  const wallets: WalletRow[] = useMemo(
    () =>
      portfolios.map((p) => ({
        id: p.portfolio_id,
        name: p.name || p.portfolio_id,
        status: p.status,
        mode: p.mode,
        brokerMode: p.broker_mode,
        baseCurrency: p.base_currency,
        equity: asNumber(p.equity),
        cash: asNumber(p.cash),
        unrealizedPnl: asNumber(p.unrealized_pnl),
        realizedPnl: asNumber(p.realized_pnl),
        killSwitch: Boolean(p.kill_switch),
        orchestraId: p.orchestra_id,
        createdAt: p.created_at,
      })),
    [portfolios],
  );

  const selectedWallet = useMemo(
    () => wallets.find((w) => w.id === selectedPortfolioId) ?? null,
    [wallets, selectedPortfolioId],
  );

  const totalEquity = useMemo(
    () => wallets.reduce((sum, w) => sum + (w.equity ?? 0), 0),
    [wallets],
  );

  const activity: ActivityRow[] = useMemo(
    () =>
      decisions.slice(0, 30).map((d) => {
        const payload = asRec(d.payload) || {};
        return {
          id: d.decisionId,
          time: asStr(d.asOf, "—"),
          agent: asStr(d.role, d.agentId || "Agent"),
          role: d.role,
          stage: d.stage,
          summary:
            (typeof payload.summary === "string" && payload.summary) ||
            (typeof payload.finding === "string" && payload.finding) ||
            (typeof payload.hypothesis === "string" && payload.hypothesis) ||
            d.stage,
        };
      }),
    [decisions],
  );

  const positions = dashboard?.positions ?? [];

  /* ---------------------------------------------------------------- KPIs */

  const kpis = useMemo(() => {
    const kp = dashboard?.kpis;
    return {
      equity: kp ? asNumber(kp.total_equity) : totalEquity || null,
      cash: kp ? asNumber(kp.cash_balance) : null,
      openPositions: positions.length,
      dayPnl: kp ? asNumber(kp.daily_pnl) : null,
      dayPnlPct: kp ? kp.daily_pnl_pct : null,
      riskStatus: dashboard?.risk.health.label ?? UNMEASURED,
      riskScore: dashboard?.risk.health.score ?? null,
      liveTrading,
    };
  }, [dashboard, totalEquity, positions.length, liveTrading]);

  /* ------------------------------------------------------------- actions */

  async function run<T>(name: string, fn: () => Promise<T>): Promise<T | null> {
    setBusy(name);
    try {
      const res = await fn();
      return res;
    } catch (err) {
      notify(err instanceof ApiError ? err.message : err instanceof Error ? err.message : `${name} failed`);
      return null;
    } finally {
      setBusy(null);
    }
  }

  const createPortfolio = useCallback(
    async (payload: {
      name: string;
      initialEquity: number;
      orchestraId: string | null;
      shortingEnabled: boolean;
      brokerMode?: string;
    }) => {
      const res = await run("create-portfolio", () =>
        api.createPortfolio({
          name: payload.name,
          initialEquity: payload.initialEquity,
          orchestraId: payload.orchestraId,
          shortingEnabled: payload.shortingEnabled,
          brokerMode: payload.brokerMode,
          allowManualOnly: true,
          settings: {
            allow_manual_only: true,
            fee_bps: 5,
            slippage_bps: 2,
            shorting_enabled: payload.shortingEnabled,
          },
        }),
      );
      if (res) {
        notify(`Created wallet ${res.portfolio.name}`);
        setSelectedPortfolioId(res.portfolio.portfolio_id);
        await loadList();
      }
      return res;
    },
    [loadList, notify],
  );

  const lifecycle = useCallback(
    async (action: "start" | "pause" | "resume" | "stop", portfolioId?: string) => {
      const pid = portfolioId ?? selectedPortfolioId;
      if (!pid) return;
      const fn =
        action === "start"
          ? api.startPortfolio
          : action === "pause"
            ? api.pausePortfolio
            : action === "resume"
              ? api.resumePortfolio
              : api.stopPortfolio;
      const res = await run(`lifecycle-${action}`, () => fn(pid));
      if (res) {
        notify(`Wallet ${action}`);
        await Promise.all([loadList(), refreshDashboard(pid)]);
      }
    },
    [selectedPortfolioId, loadList, refreshDashboard, notify],
  );

  const closePosition = useCallback(
    async (positionId: string) => {
      if (!selectedPortfolioId) return;
      const res = await run("close-position", () => api.closePortfolioPosition(selectedPortfolioId, positionId));
      if (res) {
        notify("Close order submitted");
        await refreshDashboard(selectedPortfolioId);
      }
    },
    [selectedPortfolioId, refreshDashboard, notify],
  );

  const closeSelectedPositions = useCallback(async () => {
    if (!selectedPortfolioId || !selectedPositions.length) return;
    const res = await run("close-selected", () =>
      api.closeSelectedPortfolioPositions(selectedPortfolioId, selectedPositions),
    );
    if (res) {
      notify(`Closed ${selectedPositions.length} position(s)`);
      setSelectedPositions([]);
      await refreshDashboard(selectedPortfolioId);
    }
  }, [selectedPortfolioId, selectedPositions, refreshDashboard, notify]);

  const flatten = useCallback(async () => {
    if (!selectedPortfolioId) return;
    const res = await run("flatten", () => api.flattenPortfolio(selectedPortfolioId));
    if (res) {
      notify("Flatten submitted — all paper positions closing");
      await refreshDashboard(selectedPortfolioId);
    }
  }, [selectedPortfolioId, refreshDashboard, notify]);

  const killSwitch = useCallback(
    async (armed: boolean) => {
      if (!selectedPortfolioId) return;
      const res = await run("kill-switch", () => api.portfolioKillSwitch(selectedPortfolioId, armed));
      if (res) {
        notify(`Kill switch ${armed ? "ARMED" : "disarmed"}`);
        await Promise.all([loadList(), refreshDashboard(selectedPortfolioId)]);
      }
    },
    [selectedPortfolioId, loadList, refreshDashboard, notify],
  );

  const placeOrder = useCallback(
    async (payload: { symbol: string; side: string; qty: number }) => {
      if (!selectedPortfolioId) return null;
      const res = await run("place-order", () => api.placePortfolioOrder(selectedPortfolioId, payload));
      if (res) {
        notify(`Order submitted: ${payload.side} ${payload.qty} ${payload.symbol}`);
        await refreshDashboard(selectedPortfolioId);
      }
      return res;
    },
    [selectedPortfolioId, refreshDashboard, notify],
  );

  const rebalancePreview = useCallback(
    async (orders_?: Array<Record<string, unknown>>) => {
      if (!selectedPortfolioId) return null;
      return run("rebalance-preview", () => api.portfolioRebalancePreview(selectedPortfolioId, orders_));
    },
    [selectedPortfolioId],
  );

  const rebalanceExecute = useCallback(
    async (orders_?: Array<Record<string, unknown>>) => {
      if (!selectedPortfolioId) return null;
      const res = await run("rebalance-execute", () => api.portfolioRebalanceExecute(selectedPortfolioId, orders_));
      if (res) {
        notify("Rebalance executed (paper)");
        await refreshDashboard(selectedPortfolioId);
      }
      return res;
    },
    [selectedPortfolioId, refreshDashboard, notify],
  );

  const runRecommendation = useCallback(
    async (rec: PortfolioRecommendation) => {
      if (!rec.estimated_orders?.length) {
        notify("No executable paper orders for this recommendation");
        return;
      }
      await rebalanceExecute(rec.estimated_orders);
    },
    [rebalanceExecute, notify],
  );

  const saveAllocations = useCallback(async () => {
    if (!selectedPortfolioId || !dashboard) return;
    const allocations = (dashboard.strategy_allocation || []).map((s) => ({
      kind: "strategy",
      target_id: s.strategy_id,
      target_allocation_pct: s.allocation_pct,
      strategy_version: s.strategy_version,
      agent_id: s.agent_id,
      active: s.status === "ACTIVE",
    }));
    const res = await run("save-allocations", () => api.savePortfolioAllocations(selectedPortfolioId, allocations));
    if (res) {
      notify("Allocations saved");
      await refreshDashboard(selectedPortfolioId);
    }
  }, [selectedPortfolioId, dashboard, refreshDashboard, notify]);

  const exportPortfolio = useCallback(
    async (format: "json" | "csv") => {
      if (!selectedPortfolioId) return;
      try {
        const res = await api.exportPortfolio(selectedPortfolioId, format);
        const content = res.content;
        const blob =
          format === "csv"
            ? new Blob([String(content)], { type: "text/csv" })
            : new Blob([JSON.stringify(content, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = String(res.filename || `trading-desk.${format}`);
        a.click();
        URL.revokeObjectURL(url);
        notify(`Exported ${format.toUpperCase()}`);
      } catch (err) {
        notify(err instanceof ApiError ? err.message : "Export failed");
      }
    },
    [selectedPortfolioId, notify],
  );

  /* -------------------------------------------------------- paper deployments */

  const createPaperDeployment = useCallback(
    async (payload: Parameters<typeof api.createPaperDeployment>[0]) => {
      const res = await run("create-deployment", () => api.createPaperDeployment(payload));
      if (res) {
        notify("Paper deployment created");
        await loadList();
      }
      return res;
    },
    [loadList, notify],
  );

  const shadowObserve = useCallback(
    async (deploymentId: string) => {
      const res = await run(`shadow-${deploymentId}`, () => api.shadowObserveDeployment(deploymentId, {}));
      if (res) {
        notify("Shadow observe recorded");
        await loadList();
      }
      return res;
    },
    [loadList, notify],
  );

  const promoteDeployment = useCallback(
    async (deploymentId: string, targetLevel: string) => {
      const res = await run(`promote-${deploymentId}`, () =>
        api.promotePaperDeployment(deploymentId, { targetLevel }),
      );
      if (res) {
        notify(`Promote → ${targetLevel} requested (paper track only)`);
        await loadList();
      }
      return res;
    },
    [loadList, notify],
  );

  const deploymentKillSwitch = useCallback(
    async (deploymentId: string, armed: boolean) => {
      const res = await run(`deploy-kill-${deploymentId}`, () =>
        api.paperDeploymentKillSwitch(deploymentId, armed, armed ? "Manual kill-switch (Trading Desk)" : ""),
      );
      if (res) {
        notify(`Deployment kill switch ${armed ? "ARMED" : "disarmed"}`);
        await loadList();
      }
      return res;
    },
    [loadList, notify],
  );

  const getExecutionCalibration = useCallback(async (deploymentId: string) => {
    try {
      return await api.getPaperExecutionCalibration(deploymentId);
    } catch {
      return null;
    }
  }, []);

  /* ---------------------------------------------------------------- orchestras */

  const setAutonomy = useCallback(
    async (orchestraId: string, level: string) => {
      const res = await run(`autonomy-${orchestraId}`, () => api.setTradeAutonomy(orchestraId, level));
      if (res) {
        notify(`Autonomy set to ${level} (mandate cannot enable live)`);
        await loadList();
      }
      return res;
    },
    [loadList, notify],
  );

  const launchMission = useCallback(
    async (orchestraId: string, kind: string) => {
      const res = await run(`mission-${orchestraId}`, () => api.launchTradeMission(orchestraId, { kind }));
      if (res) {
        notify(`Mission launched: ${kind}`);
        await refreshActivity();
      }
      return res;
    },
    [refreshActivity, notify],
  );

  return {
    loading,
    error,
    busy,
    notice,
    dismissNotice: () => setNotice(null),

    portfolios,
    wallets,
    selectedPortfolioId,
    setSelectedPortfolioId,
    selectedWallet,
    dashboard,
    dashboardLoading,
    orders,
    positions,
    selectedPositions,
    setSelectedPositions,

    orchestras,
    deployments,
    decisions,
    activity,
    capabilities,
    liveTrading,

    bars,
    barsLoading,
    market,
    timeframe,

    kpis,
    totalEquity,

    refresh,
    refreshDashboard,
    refreshBars,
    refreshActivity,

    createPortfolio,
    lifecycle,
    closePosition,
    closeSelectedPositions,
    flatten,
    killSwitch,
    placeOrder,
    rebalancePreview,
    rebalanceExecute,
    runRecommendation,
    saveAllocations,
    exportPortfolio,

    createPaperDeployment,
    shadowObserve,
    promoteDeployment,
    deploymentKillSwitch,
    getExecutionCalibration,

    setAutonomy,
    launchMission,
  };
}

export type TradingDeskData = ReturnType<typeof useTradingDeskData>;
