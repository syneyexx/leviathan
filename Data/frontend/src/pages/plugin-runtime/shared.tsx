import type { ReactNode } from "react";

export function PrHero({
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
    <section className={`lv-pr-hero${imageOnly ? " is-image-only" : ""}`} aria-label={title}>
      <div className="lv-pr-hero-media">
        <img src={image} alt="" width={1600} height={240} style={{ objectPosition }} />
      </div>
      {imageOnly ? null : (
        <>
          <div className="lv-pr-hero-shade" />
          <div className="lv-pr-hero-content">
            <h1 className="lv-pr-hero-title">{title}</h1>
            {kicker ? <p className="lv-pr-hero-kicker">{kicker}</p> : null}
            {quote ? <p className="lv-pr-hero-quote">{quote}</p> : null}
          </div>
          {rails?.length ? (
            <aside className="lv-pr-hero-rail" aria-hidden="true">
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
    <article className={`lv-pr-panel ${className}`.trim()}>
      {title || action ? (
        <div className="lv-pr-panel-head">
          {title ? <div className="lv-pr-panel-title">{title}</div> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </article>
  );
}

export function Spark({
  points,
  color = "#00E5FF",
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
    <svg className="lv-pr-spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export type PillTone = "ok" | "warn" | "err" | "muted" | "gold" | "cyan";

export function Pill({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: PillTone;
}) {
  return <span className={`lv-pr-pill is-${tone}`}>{children}</span>;
}

export type BarTone = "ok" | "cyan" | "gold" | "warn" | "err";

export function Bar({
  pct,
  tone = "cyan",
  className = "",
}: {
  pct: number;
  tone?: BarTone;
  className?: string;
}) {
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <div className={`lv-pr-bar is-${tone} ${className}`.trim()} aria-hidden="true">
      <span style={{ width: `${clamped}%` }} />
    </div>
  );
}

export function Toggle({
  on,
  label,
  className = "",
}: {
  on: boolean;
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={`lv-pr-toggle${on ? " is-on" : ""}${className ? ` ${className}` : ""}`}
      role="switch"
      aria-checked={on}
      aria-label={label}
    >
      <span />
    </span>
  );
}
