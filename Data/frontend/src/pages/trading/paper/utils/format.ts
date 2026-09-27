/** Paper Trading display helpers — formatting only; never invents PnL. */

export function num(v: string | number | null | undefined): number {
  if (v == null || v === "") return 0;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

export function fmtMoney(v: string | number | null | undefined, digits = 2): string {
  const n = num(v);
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

export function fmtSigned(v: string | number | null | undefined, digits = 2): string {
  const n = num(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${fmtMoney(n, digits)}`;
}

export function toneClass(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v) || v === 0) return "";
  return v > 0 ? "is-good" : "is-bad";
}

/** Simple moving average for chart overlays (display-only from backend bars). */
export function sma(closes: number[], period: number): Array<number | null> {
  const out: Array<number | null> = [];
  let sum = 0;
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i];
    if (i >= period) sum -= closes[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

export const DEFAULT_WATCHLIST = [
  "BTCUSDT",
  "ETHUSDT",
  "AAPL",
  "TSLA",
  "NVDA",
  "EURUSD",
  "GBPUSD",
  "XAUUSD",
] as const;

export const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;

export type PaperAgentMode = "autonomous" | "assisted" | "manual";

export type OrchestratorDraft = {
  agentMode: PaperAgentMode;
  capitalAllocation: number;
  positionSizingPct: number;
  maxOpenPositions: number;
  maxDrawdownPct: number;
  dailyLossLimitPct: number;
  defaultStopLossPct: number;
  defaultTakeProfitPct: number;
  allowNewPositions: boolean;
  autoRebalance: boolean;
  newsFilter: boolean;
  useTrailingStops: boolean;
  hedgeMode: boolean;
  multiAgentCoordination: boolean;
};

function settingNum(v: unknown, fallback: number): number {
  if (typeof v === "number" || typeof v === "string") return num(v);
  return fallback;
}

export function settingsToDraft(settings: Record<string, unknown> | undefined): OrchestratorDraft {
  const s = settings || {};
  const modeRaw = String(s.agent_mode || "autonomous").toLowerCase();
  const agentMode: PaperAgentMode =
    modeRaw === "assisted" || modeRaw === "manual" ? modeRaw : "autonomous";
  return {
    agentMode,
    capitalAllocation: settingNum(s.capital_allocation, 100_000),
    positionSizingPct: settingNum(s.position_sizing_pct ?? s.per_trade_risk_pct, 2),
    maxOpenPositions: Math.round(settingNum(s.max_concurrent_positions, 10)),
    maxDrawdownPct: settingNum(s.max_drawdown_pct, 10),
    dailyLossLimitPct: settingNum(s.daily_loss_limit_pct, 5),
    defaultStopLossPct: settingNum(s.default_stop_loss_pct, 1.5),
    defaultTakeProfitPct: settingNum(s.default_take_profit_pct, 3),
    allowNewPositions: s.allow_new_positions !== false,
    autoRebalance: Boolean(s.auto_rebalance),
    newsFilter: Boolean(s.news_filter),
    useTrailingStops: Boolean(s.use_trailing_stops),
    hedgeMode: Boolean(s.hedge_mode),
    multiAgentCoordination: s.multi_agent_coordination !== false,
  };
}

export function draftToSettings(draft: OrchestratorDraft): Record<string, unknown> {
  return {
    agent_mode: draft.agentMode,
    capital_allocation: draft.capitalAllocation,
    position_sizing_pct: draft.positionSizingPct,
    per_trade_risk_pct: draft.positionSizingPct,
    max_concurrent_positions: draft.maxOpenPositions,
    max_drawdown_pct: draft.maxDrawdownPct,
    daily_loss_limit_pct: draft.dailyLossLimitPct,
    default_stop_loss_pct: draft.defaultStopLossPct,
    default_take_profit_pct: draft.defaultTakeProfitPct,
    allow_new_positions: draft.allowNewPositions,
    auto_rebalance: draft.autoRebalance,
    news_filter: draft.newsFilter,
    use_trailing_stops: draft.useTrailingStops,
    hedge_mode: draft.hedgeMode,
    multi_agent_coordination: draft.multiAgentCoordination,
    shorting_enabled: draft.hedgeMode,
  };
}
