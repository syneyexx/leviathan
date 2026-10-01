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

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [caps, live, status] = await Promise.all([
        api.marketSimCapabilities().catch(() => null),
        api.marketSimLiveTradingStatus().catch(() => null),
        api.marketSimStatus().catch(() => null),
      ]);

      const liveAvail = String(
        (live as { LIVE_TRADING_AVAILABLE?: string } | null)?.LIVE_TRADING_AVAILABLE ??
          (caps as { live_trading_default?: string } | null)?.live_trading_default ??
          "BLOCKED",
      );
      setLiveTrading(liveAvail);
      setExecutionLabel(liveAvail === "BLOCKED" ? "PAPER ONLY" : liveAvail);

      const enabled = Boolean((status as { enabled?: boolean } | null)?.enabled);
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
          if (ready[0]) {
            const meta = ready[0].metadata as { provider?: string; range?: string } | undefined;
            const provider = meta?.provider || "Indexed";
            setDatasetLabel(`${provider} · ${ready[0].symbol} (${ready.length} ready)`);
          }
        } catch {
          /* keep defaults */
        }
      }

      // Regime/volatility stay UNMEASURED until a real detector result is present.
      // Do not invent Bullish/High from UI chrome.
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
      setMode,
      setMarket,
      setTimeframe,
      refresh,
    ],
  );
}
