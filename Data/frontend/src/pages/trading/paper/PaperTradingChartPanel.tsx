import type { MarketBar } from "../../../types/api";
import { sma } from "./utils/format";

type Indicators = { ma20: boolean; ma50: boolean; ma200: boolean; volume: boolean };

export function TradingCandleChart({
  bars,
  width = 900,
  height = 360,
  indicators,
}: {
  bars: MarketBar[];
  width?: number;
  height?: number;
  indicators: Indicators;
}) {
  if (bars.length < 2) {
    return (
      <div className="lv-paper-chart-empty" style={{ minHeight: height }}>
        Awaiting market bars…
      </div>
    );
  }

  const volH = indicators.volume ? Math.round(height * 0.18) : 0;
  const chartH = height - volH;
  const padL = 8;
  const padR = 8;
  const padT = 8;
  const padB = 4;
  const highs = bars.map((b) => b.high);
  const lows = bars.map((b) => b.low);
  const closes = bars.map((b) => b.close);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const span = max - min || 1;
  const innerW = width - padL - padR;
  const gap = innerW / bars.length;
  const bodyW = Math.max(2.2, gap * 0.55);

  const y = (v: number) => padT + (chartH - padT - padB) * (1 - (v - min) / span);
  const volumes = bars.map((b) => b.volume);
  const vmax = Math.max(...volumes, 1);

  const ma20 = indicators.ma20 ? sma(closes, 20) : [];
  const ma50 = indicators.ma50 ? sma(closes, 50) : [];
  const ma200 = indicators.ma200 ? sma(closes, 200) : [];

  const pathFor = (series: Array<number | null>) => {
    let d = "";
    for (let i = 0; i < series.length; i++) {
      const v = series[i];
      if (v == null) continue;
      const x = padL + i * gap + gap / 2;
      d += `${d ? " L" : "M"}${x.toFixed(1)},${y(v).toFixed(1)}`;
    }
    return d;
  };

  return (
    <svg
      className="lv-paper-candles"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Candlestick chart"
    >
      {[0.25, 0.5, 0.75].map((t) => (
        <line
          key={t}
          x1={padL}
          x2={width - padR}
          y1={padT + (chartH - padT - padB) * t}
          y2={padT + (chartH - padT - padB) * t}
          stroke="rgba(214,169,87,0.08)"
          strokeWidth="1"
        />
      ))}
      {bars.map((b, i) => {
        const x = padL + i * gap + gap / 2;
        const up = b.close >= b.open;
        const color = up ? "#34d399" : "#c45c5c";
        const top = y(Math.max(b.open, b.close));
        const bot = y(Math.min(b.open, b.close));
        const volBar = indicators.volume ? (b.volume / vmax) * (volH - 4) : 0;
        return (
          <g key={`${b.ts}-${i}`}>
            <line x1={x} x2={x} y1={y(b.high)} y2={y(b.low)} stroke={color} strokeWidth="1.15" />
            <rect
              x={x - bodyW / 2}
              y={top}
              width={bodyW}
              height={Math.max(1.5, bot - top)}
              fill={color}
              rx="0.4"
            />
            {indicators.volume ? (
              <rect
                x={x - bodyW / 2}
                y={height - volBar}
                width={bodyW}
                height={volBar}
                fill={color}
                opacity="0.38"
              />
            ) : null}
          </g>
        );
      })}
      {indicators.ma20 && ma20.length ? (
        <path d={pathFor(ma20)} fill="none" stroke="#22c9d6" strokeWidth="1.4" />
      ) : null}
      {indicators.ma50 && ma50.length ? (
        <path d={pathFor(ma50)} fill="none" stroke="#d4af37" strokeWidth="1.4" />
      ) : null}
      {indicators.ma200 && ma200.length ? (
        <path d={pathFor(ma200)} fill="none" stroke="#b45353" strokeWidth="1.4" />
      ) : null}
      {volH > 0 ? (
        <line
          x1={padL}
          x2={width - padR}
          y1={chartH}
          y2={chartH}
          stroke="rgba(214,169,87,0.18)"
          strokeWidth="1"
        />
      ) : null}
    </svg>
  );
}
