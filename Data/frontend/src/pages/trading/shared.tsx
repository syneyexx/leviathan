import type { ReactNode } from "react";

export function TradingHero({
  title,
  kicker,
  quote,
  image,
  rails,
  objectPosition = "center 40%",
  /** When true, show the mockup crop as-is (titles already baked into the image). */
  imageOnly = true,
}: {
  title: string;
  kicker?: string;
  quote?: string;
  image: string;
  rails?: readonly string[];
  objectPosition?: string;
  imageOnly?: boolean;
}) {
  return (
    <section className={`lv-tp-hero${imageOnly ? " is-image-only" : ""}`} aria-label={title}>
      <div className="lv-tp-hero-media">
        <img src={image} alt="" width={1600} height={240} style={{ objectPosition }} />
      </div>
      {imageOnly ? null : (
        <>
          <div className="lv-tp-hero-shade" />
          <div className="lv-tp-hero-content">
            <h1 className="lv-tp-hero-title">{title}</h1>
            {kicker ? <p className="lv-tp-hero-kicker">{kicker}</p> : null}
            {quote ? <p className="lv-tp-hero-quote">{quote}</p> : null}
          </div>
          {rails?.length ? (
            <aside className="lv-tp-hero-rail" aria-hidden="true">
              {rails.map((line) => (
                <span key={line}>{line}</span>
              ))}
            </aside>
          ) : null}
        </>
      )}
    </section>
  );
}

export function Spark({
  points,
  color = "#34d399",
  width = 64,
  height = 22,
}: {
  points: readonly number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const path = points
    .map((v, i) => {
      const x = (i / Math.max(points.length - 1, 1)) * width;
      const y = height - 3 - ((v - min) / span) * (height - 6);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="lv-tp-spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function CandleChart({
  candles,
  width = 640,
  height = 220,
  volumeHeight = 42,
  markers = [],
}: {
  candles: readonly [number, number, number, number][];
  width?: number;
  height?: number;
  volumeHeight?: number;
  markers?: readonly { index: number; side: "B" | "S" }[];
}) {
  const chartH = height - volumeHeight;
  const highs = candles.map((c) => c[1]);
  const lows = candles.map((c) => c[2]);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const span = max - min || 1;
  const gap = width / candles.length;
  const bodyW = Math.max(3, gap * 0.55);

  const y = (v: number) => chartH - ((v - min) / span) * (chartH - 8) - 4;
  const volumes = candles.map((c) => Math.abs(c[3] - c[0]));
  const vmax = Math.max(...volumes, 1);

  return (
    <svg className="lv-tp-candles" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      {[0.25, 0.5, 0.75].map((t) => (
        <line
          key={t}
          x1="0"
          x2={width}
          y1={chartH * t}
          y2={chartH * t}
          stroke="rgba(214,169,87,0.08)"
          strokeWidth="1"
        />
      ))}
      {candles.map(([o, h, l, c], i) => {
        const x = i * gap + gap / 2;
        const up = c >= o;
        const color = up ? "#34d399" : "#f87171";
        const top = y(Math.max(o, c));
        const bot = y(Math.min(o, c));
        const volH = (volumes[i] / vmax) * (volumeHeight - 6);
        return (
          <g key={i}>
            <line x1={x} x2={x} y1={y(h)} y2={y(l)} stroke={color} strokeWidth="1.2" />
            <rect x={x - bodyW / 2} y={top} width={bodyW} height={Math.max(2, bot - top)} fill={color} rx="0.5" />
            <rect
              x={x - bodyW / 2}
              y={height - volH}
              width={bodyW}
              height={volH}
              fill={color}
              opacity="0.35"
            />
          </g>
        );
      })}
      {markers.map((m) => {
        const x = m.index * gap + gap / 2;
        const candle = candles[m.index];
        if (!candle) return null;
        const cy = y(candle[3]) - (m.side === "B" ? -10 : 10);
        const fill = m.side === "B" ? "#34d399" : "#f87171";
        return (
          <g key={`${m.index}-${m.side}`}>
            <circle cx={x} cy={cy} r="7" fill={fill} />
            <text x={x} y={cy + 3} textAnchor="middle" fontSize="8" fill="#04110a" fontWeight="700">
              {m.side}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function LineSeries({
  series,
  width = 520,
  height = 160,
}: {
  series: readonly { values: readonly number[]; color: string }[];
  width?: number;
  height?: number;
}) {
  const all = series.flatMap((s) => s.values);
  const max = Math.max(...all);
  const min = Math.min(...all);
  const span = max - min || 1;
  const pathFor = (values: readonly number[]) =>
    values
      .map((v, i) => {
        const x = (i / Math.max(values.length - 1, 1)) * width;
        const y = height - 6 - ((v - min) / span) * (height - 12);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

  return (
    <svg className="lv-tp-linechart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      {[0.25, 0.5, 0.75].map((t) => (
        <line
          key={t}
          x1="0"
          x2={width}
          y1={height * t}
          y2={height * t}
          stroke="rgba(214,169,87,0.08)"
          strokeWidth="1"
        />
      ))}
      {series.map((s, i) => (
        <path key={i} d={pathFor(s.values)} fill="none" stroke={s.color} strokeWidth="1.8" />
      ))}
    </svg>
  );
}

export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <article className={`lv-tp-panel ${className}`.trim()}>
      {title || action ? (
        <div className="lv-tp-panel-head">
          {title ? <div className="lv-tp-panel-title">{title}</div> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </article>
  );
}

export function Tone({ value, children }: { value: number | boolean; children: ReactNode }) {
  const up = typeof value === "boolean" ? value : value >= 0;
  return <span className={up ? "is-good" : "is-bad"}>{children}</span>;
}

export function AreaSpark({
  points,
  color = "#22c9d6",
  width = 160,
  height = 44,
}: {
  points: readonly number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const coords = points.map((v, i) => {
    const x = (i / Math.max(points.length - 1, 1)) * width;
    const y = height - 4 - ((v - min) / span) * (height - 8);
    return [x, y] as const;
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  return (
    <svg className="lv-tp-area" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <path d={area} fill={color} opacity="0.18" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

export function RingGauge({
  value,
  label,
  display,
  color = "#34d399",
}: {
  value: number;
  label: string;
  display?: string;
  color?: string;
}) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const len = (Math.min(100, Math.max(0, value)) / 100) * c;
  return (
    <div className="lv-tp-ring">
      <svg viewBox="0 0 56 56" aria-hidden="true">
        <circle cx="28" cy="28" r={r} fill="none" stroke="rgba(52,211,153,0.15)" strokeWidth="4" />
        <circle
          cx="28"
          cy="28"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeDasharray={`${len} ${c - len}`}
          strokeLinecap="round"
          transform="rotate(-90 28 28)"
        />
        <text x="28" y="31" textAnchor="middle" className="lv-tp-ring-val">
          {display ?? `${value}%`}
        </text>
      </svg>
      <span>{label}</span>
    </div>
  );
}

export function Donut({
  slices,
  center,
  size = 140,
}: {
  slices: readonly { value: number; color: string }[];
  center?: string;
  size?: number;
}) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  const r = 42;
  const c = 2 * Math.PI * r;
  const arcs = slices.reduce<Array<{ color: string; len: number; dashOffset: number }>>((acc, slice) => {
    const len = (slice.value / total) * c;
    const dashOffset = -acc.reduce((sum, item) => sum + item.len, 0);
    acc.push({ color: slice.color, len, dashOffset });
    return acc;
  }, []);
  return (
    <svg className="lv-tp-donut" viewBox="0 0 140 140" width={size} height={size} aria-hidden="true">
      <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="16" />
      {arcs.map((arc, i) => (
        <circle
          key={i}
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke={arc.color}
          strokeWidth="16"
          strokeDasharray={`${arc.len} ${c - arc.len}`}
          strokeDashoffset={arc.dashOffset}
          transform="rotate(-90 70 70)"
        />
      ))}
      {center ? (
        <text x="70" y="74" textAnchor="middle" fill="#F6F1E8" fontSize="11" fontWeight="700">
          {center}
        </text>
      ) : null}
    </svg>
  );
}

export const MOCK_CANDLES: [number, number, number, number][] = [
  [40, 55, 36, 52],
  [52, 62, 48, 58],
  [58, 64, 50, 53],
  [53, 70, 51, 68],
  [68, 74, 60, 63],
  [63, 72, 58, 70],
  [70, 82, 66, 79],
  [79, 88, 74, 84],
  [84, 90, 78, 81],
  [81, 92, 76, 90],
  [90, 96, 84, 88],
  [88, 98, 82, 95],
  [95, 102, 90, 99],
  [99, 108, 94, 104],
  [104, 110, 98, 100],
  [100, 112, 96, 108],
  [108, 118, 104, 114],
  [114, 120, 108, 111],
  [111, 124, 106, 120],
  [120, 128, 114, 122],
  [122, 130, 116, 126],
  [126, 132, 118, 121],
  [121, 136, 115, 132],
  [132, 140, 126, 137],
];
