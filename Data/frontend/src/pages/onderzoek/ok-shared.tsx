import type { CSSProperties, ReactNode } from "react";

export function OkHero({
  title,
  kicker,
  quote,
  image,
  rails,
}: {
  title: string;
  kicker: string;
  quote: string;
  image: string;
  rails?: readonly string[];
}) {
  return (
    <section className="lv-ok-hero" aria-label={title}>
      <div className="lv-ok-hero-media">
        <img src={image} alt="" width={1450} height={148} />
      </div>
      <div className="lv-ok-hero-shade" />
      <div className="lv-ok-hero-content">
        <h1 className="lv-ok-hero-title">{title}</h1>
        <p className="lv-ok-hero-kicker">{kicker}</p>
        <p className="lv-ok-hero-quote">{quote}</p>
      </div>
      {rails?.length ? (
        <aside className="lv-ok-hero-rail" aria-hidden="true">
          {rails.map((line) => (
            <span key={line}>{line}</span>
          ))}
        </aside>
      ) : null}
    </section>
  );
}

export function OkPanel({
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
    <section className={`lv-ok-panel ${className}`.trim()}>
      {title || action ? (
        <header className="lv-ok-panel-head">
          {title ? <h2>{title}</h2> : <span />}
          {action}
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function OkIcon({ children }: { children: ReactNode }) {
  return (
    <svg className="lv-ok-ico" viewBox="0 0 24 24" aria-hidden="true">
      {children}
    </svg>
  );
}

export function OkGauge({
  value,
  label,
  size = 92,
  color = "#22C9D6",
}: {
  value: number;
  label: string;
  size?: number;
  color?: string;
}) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.min(100, Math.max(0, value)) / 100);
  return (
    <div className="lv-ok-gauge" style={{ width: size, height: size }}>
      <svg viewBox="0 0 88 88" width={size} height={size} aria-hidden="true">
        <circle cx="44" cy="44" r={r} fill="none" stroke="rgba(34,201,214,0.15)" strokeWidth="7" />
        <circle
          cx="44"
          cy="44"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform="rotate(-90 44 44)"
        />
      </svg>
      <div className="lv-ok-gauge-copy">
        <strong>{value}%</strong>
        <small>{label}</small>
      </div>
    </div>
  );
}

export function OkSpark({
  points,
  color = "#22C9D6",
  width = 120,
  height = 36,
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
    <svg className="lv-ok-spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function OkBars({
  values,
  color = "#22C9D6",
  height = 56,
}: {
  values: readonly number[];
  color?: string;
  height?: number;
}) {
  const max = Math.max(...values, 1);
  return (
    <div className="lv-ok-bars" style={{ height } as CSSProperties}>
      {values.map((v, i) => (
        <span
          key={i}
          style={{ height: `${Math.max(8, (v / max) * 100)}%`, background: color }}
        />
      ))}
    </div>
  );
}

export function OkProgress({
  value,
  tone = "cyan",
}: {
  value: number;
  tone?: "cyan" | "gold" | "green" | "red" | "muted";
}) {
  return (
    <div className={`lv-ok-progress is-${tone}`}>
      <span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}
