import type { ReactNode } from "react";

export function PageHero({
  image,
  title,
  kicker,
  quote,
  rails,
  imageOnly = false,
}: {
  image: string;
  title: string;
  kicker?: string;
  quote?: string;
  rails?: readonly string[];
  imageOnly?: boolean;
}) {
  return (
    <section className={`lv-mr-hero${imageOnly ? " is-image-only" : ""}`} aria-label={title}>
      <div className="lv-mr-hero-media">
        <img src={image} alt="" width={1450} height={118} />
      </div>
      {imageOnly ? null : (
        <>
          <div className="lv-mr-hero-shade" />
          <div className="lv-mr-hero-content">
            <h1 className="lv-mr-hero-title">{title}</h1>
            {kicker ? <p className="lv-mr-hero-kicker">{kicker}</p> : null}
            {quote ? <p className="lv-mr-hero-quote">{quote}</p> : null}
          </div>
          {rails?.length ? (
            <aside className="lv-mr-hero-rail" aria-hidden="true">
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
    <article className={`lv-mr-panel ${className}`.trim()}>
      {title || action ? (
        <div className="lv-mr-panel-head">
          {title ? <div className="lv-mr-panel-title">{title}</div> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </article>
  );
}

export function Spark({
  points,
  color = "#22c9d6",
  width = 72,
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
    <svg className="lv-mr-spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function Pill({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "cyan" | "gold" | "green" | "red" | "blue";
}) {
  return <span className={`lv-mr-pill is-${tone}`}>{children}</span>;
}

export function PlatformGlyph({ platform }: { platform: "youtube" | "tiktok" | "instagram" | "facebook" | "linkedin" | "x" }) {
  const labels: Record<typeof platform, string> = {
    youtube: "YT",
    tiktok: "TT",
    instagram: "IG",
    facebook: "FB",
    linkedin: "IN",
    x: "X",
  };
  return (
    <span className={`lv-mr-plat is-${platform}`} title={platform}>
      {labels[platform]}
    </span>
  );
}

export function Donut({
  slices,
  center,
  size = 120,
}: {
  slices: readonly { value: number; color: string }[];
  center?: string;
  size?: number;
}) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  const r = 36;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg className="lv-mr-donut" viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
      <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="14" />
      {slices.map((slice, i) => {
        const len = (slice.value / total) * c;
        const el = (
          <circle
            key={i}
            cx="60"
            cy="60"
            r={r}
            fill="none"
            stroke={slice.color}
            strokeWidth="14"
            strokeDasharray={`${len} ${c - len}`}
            strokeDashoffset={-offset}
            transform="rotate(-90 60 60)"
          />
        );
        offset += len;
        return el;
      })}
      {center ? (
        <text x="60" y="64" textAnchor="middle" fill="#F6F1E8" fontSize="11" fontWeight="700">
          {center}
        </text>
      ) : null}
    </svg>
  );
}

export function BarRow({ label, value, max = 100, color = "#22c9d6" }: { label: string; value: number; max?: number; color?: string }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  return (
    <div className="lv-mr-barrow">
      <div className="lv-mr-barrow-meta">
        <span>{label}</span>
        <strong>{value}%</strong>
      </div>
      <div className="lv-mr-bar">
        <span style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}
