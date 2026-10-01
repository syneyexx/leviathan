import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../../api/client";
import type { TradingContextMode } from "./workspaceConfig";

export type TradingContextState = {
  mode: TradingContextMode;
  market: string;
  timeframe: string;
  datasetLabel: string;
  regime: string;
  volatility: string;
  executionLabel: string;
  liveTrading: string;
  loading: boolean;
  markets: string[];
  timeframes: string[];
  /** Sidebar status — measured when backend provides them; else defaults / UNMEASURED. */
  engineStatus: string | null;
  paperBrokerStatus: string | null;
  marketDataStatus: string | null;
  riskEngineStatus: string | null;
  strategyStoreStatus: string | null;
  activeAgentsRunning: number | null;
  activeAgentsTotal: number | null;
  setMode: (mode: TradingContextMode) => void;
  setMarket: (market: string) => void;
  setTimeframe: (tf: string) => void;
  refresh: () => Promise<void>;
};

const DEFAULT_MARKETS = ["BTCUSDT", "ETHUSDT", "AAPL", "EURUSD"];
const DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

function readStored<T extends string>(key: string, fallback: T): T {
  try {
    const v = sessionStorage.getItem(key);
    return (v as T) || fallback;
  } catch {
    return fallback;
  }
}

function writeStored(key: string, value: string) {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

/**
 * Shared Trading Center context (mode / market / TF / dataset / regime / execution).
 * Backend capabilities remain the authority for live_trading and family readiness.
 */
export function useTradingContext(): TradingContextState {
  const [mode, setModeState] = useState<TradingContextMode>(() =>
    readStored<TradingContextMode>("tc.mode", "hybrid"),
  );
  const [market, setMarketState] = useState<string>(() => readStored("tc.market", "BTCUSDT"));
  const [timeframe, setTimeframeState] = useState<string>(() =>
    readStored("tc.timeframe", "1h"),
  );
  const [datasetLabel, setDatasetLabel] = useState("Binance + Crypto Historical 2018 - 2024");
  const [regime, setRegime] = useState("UNMEASURED");
  const [volatility, setVolatility] = useState("UNMEASURED");
  const [executionLabel, setExecutionLabel] = useState("PAPER ONLY");
  const [liveTrading, setLiveTrading] = useState("BLOCKED");
  const [loading, setLoading] = useState(true);
  const [markets, setMarkets] = useState<string[]>(DEFAULT_MARKETS);
  const [engineStatus, setEngineStatus] = useState<string | null>(null);
  const [paperBrokerStatus, setPaperBrokerStatus] = useState<string | null>(null);
  const [marketDataStatus, setMarketDataStatus] = useState<string | null>(null);
  const [riskEngineStatus, setRiskEngineStatus] = useState<string | null>(null);
  const [strategyStoreStatus, setStrategyStoreStatus] = useState<string | null>(null);
  const [activeAgentsRunning, setActiveAgentsRunning] = useState<number | null>(null);
  const [activeAgentsTotal, setActiveAgentsTotal] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [caps, live, status, orchSummary] = await Promise.all([
        api.marketSimCapabilities().catch(() => null),
        api.marketSimLiveTradingStatus().catch(() => null),
        api.marketSimStatus().catch(() => null),
        api.tradeOrchestraSummary().catch(() => null),
      ]);

      const liveAvail = String(
        (live as { LIVE_TRADING_AVAILABLE?: string } | null)?.LIVE_TRADING_AVAILABLE ??
          (caps as { live_trading_default?: string } | null)?.live_trading_default ??
          "BLOCKED",
      );
      setLiveTrading(liveAvail);
      setExecutionLabel(liveAvail === "BLOCKED" ? "PAPER ONLY" : liveAvail);

      const enabled = Boolean((status as { enabled?: boolean } | null)?.enabled);
      setEngineStatus(enabled ? "Running" : status ? "Stopped" : null);
      setPaperBrokerStatus(liveAvail === "BLOCKED" ? "Ready" : "Boundary");
      setRiskEngineStatus("Ready");
      setStrategyStoreStatus(enabled ? "Ready" : null);

      const summary = orchSummary as {
        orchestras?: number;
        enabled?: boolean;
        truth?: Record<string, unknown>;
      } | null;
      if (summary && typeof summary.orchestras === "number") {
        setActiveAgentsTotal(summary.orchestras);
        // Member-level active counts are not in summary — leave running UNMEASURED
        // rather than inventing zeros from orchestra count.
        setActiveAgentsRunning(null);
      } else {
        setActiveAgentsTotal(null);
        setActiveAgentsRunning(null);
      }

      if (enabled) {
        try {
          const { sources } = await api.listMarketData();
          const symbols = Array.from(
            new Set(
              sources
                .map((s) => String(s.symbol || "").toUpperCase())
                .filter(Boolean),
            ),
          );
          if (symbols.length) {
            setMarkets((prev) => Array.from(new Set([...symbols.slice(0, 24), ...prev])));
          }
          const ready = sources.filter((s) => s.status === "READY");
          setMarketDataStatus(ready.length ? "Ready" : sources.length ? "Degraded" : "Empty");
          if (ready[0]) {
            const meta = ready[0].metadata as { provider?: string; range?: string } | undefined;
            const provider = meta?.provider || "Indexed";
            setDatasetLabel(`${provider} · ${ready[0].symbol} (${ready.length} ready)`);
          }
        } catch {
          setMarketDataStatus(null);
        }
      } else {
        setMarketDataStatus(null);
      }

      // Regime/volatility stay UNMEASURED until a real detector result is present.
      setRegime("UNMEASURED");
      setVolatility("UNMEASURED");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setMode = useCallback((next: TradingContextMode) => {
    setModeState(next);
    writeStored("tc.mode", next);
  }, []);

  const setMarket = useCallback((next: string) => {
    setMarketState(next);
    writeStored("tc.market", next);
  }, []);

  const setTimeframe = useCallback((next: string) => {
    setTimeframeState(next);
    writeStored("tc.timeframe", next);
  }, []);

  return useMemo(
    () => ({
      mode,
      market,
      timeframe,
      datasetLabel,
      regime,
      volatility,
      executionLabel,
      liveTrading,
      loading,
      markets,
      timeframes: DEFAULT_TIMEFRAMES,
      engineStatus,
      paperBrokerStatus,
      marketDataStatus,
      riskEngineStatus,
      strategyStoreStatus,
      activeAgentsRunning,
      activeAgentsTotal,
      setMode,
      setMarket,
      setTimeframe,
      refresh,
    }),
    [
      mode,
      market,
      timeframe,
      datasetLabel,
      regime,
      volatility,
      executionLabel,
      liveTrading,
      loading,
      markets,
      engineStatus,
      paperBrokerStatus,
      marketDataStatus,
      riskEngineStatus,
      strategyStoreStatus,
      activeAgentsRunning,
      activeAgentsTotal,
      setMode,
      setMarket,
      setTimeframe,
      refresh,
    ],
  );
}
