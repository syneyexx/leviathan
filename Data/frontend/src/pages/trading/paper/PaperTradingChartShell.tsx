import type { MarketBarsResponse } from "../../../types/api";
import { TradingCandleChart } from "./PaperTradingChartPanel";
import { fmtMoney, fmtSigned, num, toneClass } from "./utils/format";

const TOOLS = [
  { id: "crosshair", label: "+" },
  { id: "trend", label: "/" },
  { id: "fib", label: "ƒ" },
  { id: "text", label: "T" },
  { id: "brush", label: "~" },
] as const;

export function PaperTradingChartShell({
  symbol,
  bars,
  barsError,
  barsLoading,
  indicators,
  drawingTool,
  onSelectTool,
}: {
  symbol: string;
  bars: MarketBarsResponse | null;
  barsError: string | null;
  barsLoading: boolean;
  indicators: { ma20: boolean; ma50: boolean; ma200: boolean; volume: boolean };
  drawingTool: string | null;
  onSelectTool: (tool: string | null) => void;
}) {
  const series = bars?.bars || [];
  const last = series[series.length - 1];
  const prev = series[series.length - 2];
  const quotePx = bars?.quote?.price != null ? num(bars.quote.price) : null;
  const lastClose = last ? last.close : quotePx;
  const delta = last && prev ? last.close - prev.close : null;
  const deltaPct = last && prev && prev.close ? (delta! / prev.close) * 100 : null;
  const ohlc = bars?.ohlc;

  return (
    <article className="lv-paper-panel lv-paper-chart">
      <header className="lv-paper-chart-head">
        <div className="lv-paper-chart-title">
          <strong>{symbol}</strong>
          <span className="lv-paper-price">{lastClose != null ? fmtMoney(lastClose) : "—"}</span>
          {delta != null ? (
            <span className={toneClass(delta)}>
              {fmtSigned(delta)} ({deltaPct != null ? `${deltaPct >= 0 ? "+" : ""}${deltaPct.toFixed(2)}%` : "—"})
            </span>
          ) : null}
        </div>
        <div className="lv-paper-ohlc">
          <span>O {ohlc?.open != null ? fmtMoney(ohlc.open) : "—"}</span>
          <span>H {ohlc?.high != null ? fmtMoney(ohlc.high) : "—"}</span>
          <span>L {ohlc?.low != null ? fmtMoney(ohlc.low) : "—"}</span>
          <span>C {ohlc?.close != null ? fmtMoney(ohlc.close) : "—"}</span>
          <span>Vol {ohlc?.volume != null ? fmtMoney(ohlc.volume, 0) : "—"}</span>
        </div>
      </header>
      <div className="lv-paper-chart-body">
        <aside className="lv-paper-chart-rail" aria-label="Chart tools">
          {TOOLS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={drawingTool === t.id ? "is-active" : ""}
              title={t.id}
              onClick={() => onSelectTool(drawingTool === t.id ? null : t.id)}
            >
              {t.label}
            </button>
          ))}
        </aside>
        <div className="lv-paper-chart-canvas">
          {barsError ? <div className="lv-paper-banner is-bad">{barsError}</div> : null}
          {barsLoading && series.length === 0 ? (
            <p className="lv-paper-state">Loading market stream…</p>
          ) : series.length === 0 ? (
            <p className="lv-paper-state">No market stream connected — awaiting bars from provider.</p>
          ) : (
            <TradingCandleChart bars={series} indicators={indicators} height={340} width={920} />
          )}
        </div>
      </div>
    </article>
  );
}
