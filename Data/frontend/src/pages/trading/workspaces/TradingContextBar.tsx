import type { TradingContextState } from "./useTradingContext";
import type { TradingContextMode } from "./workspaceConfig";

const MODES: { id: TradingContextMode; label: string }[] = [
  { id: "offline", label: "Offline" },
  { id: "live", label: "Live" },
  { id: "hybrid", label: "Hybrid" },
];

export function TradingContextBar({ ctx }: { ctx: TradingContextState }) {
  return (
    <section className="lv-tc-context" aria-label="Trading context">
      <div className="lv-tc-context__group">
        <span className="lv-tc-context__label">Mode</span>
        <div className="lv-tc-context__modes" role="group" aria-label="Data mode">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`lv-tc-context__mode${ctx.mode === m.id ? " is-active" : ""}`}
              onClick={() => ctx.setMode(m.id)}
              title={
                m.id === "live"
                  ? "Live market data (not live money)"
                  : m.id === "offline"
                    ? "Historical / offline datasets"
                    : "Hybrid offline + live data"
              }
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <label className="lv-tc-context__group">
        <span className="lv-tc-context__label">Market</span>
        <select
          className="lv-tc-context__select"
          value={ctx.market}
          onChange={(e) => ctx.setMarket(e.target.value)}
        >
          {ctx.markets.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>

      <label className="lv-tc-context__group">
        <span className="lv-tc-context__label">Timeframe</span>
        <select
          className="lv-tc-context__select"
          value={ctx.timeframe}
          onChange={(e) => ctx.setTimeframe(e.target.value)}
        >
          {ctx.timeframes.map((tf) => (
            <option key={tf} value={tf}>
              {tf}
            </option>
          ))}
        </select>
      </label>

      <div className="lv-tc-context__group lv-tc-context__group--wide">
        <span className="lv-tc-context__label">Dataset / Feed</span>
        <span className="lv-tc-context__value" title={ctx.datasetLabel}>
          {ctx.loading ? "Loading…" : ctx.datasetLabel}
        </span>
      </div>

      <div className="lv-tc-context__badges">
        <span className="lv-tc-badge lv-tc-badge--regime" title="Deterministic regime; HMM not claimed">
          Regime · {ctx.regime}
        </span>
        <span className="lv-tc-badge lv-tc-badge--vol" title="Volatility measurement">
          Vol · {ctx.volatility}
        </span>
        <span
          className="lv-tc-badge lv-tc-badge--exec"
          title={`LIVE_TRADING_AVAILABLE=${ctx.liveTrading}`}
        >
          {ctx.executionLabel}
        </span>
      </div>
    </section>
  );
}
