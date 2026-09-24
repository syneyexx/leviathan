import type { ReactNode } from "react";
import { BRAIN_STATS, BRAIN_VIEWS, type BrainView } from "./brain-mock";

const tabPaths: Record<BrainView, ReactNode> = {
  Graph: <><circle cx="12" cy="12" r="2" /><circle cx="4" cy="5" r="2" /><circle cx="20" cy="5" r="2" /><circle cx="4" cy="19" r="2" /><circle cx="20" cy="19" r="2" /><path d="m6 6 4.4 4.5m3.2 0L18 6M6 18l4.4-4.5m3.2 0L18 18" /></>,
  Tree: <><path d="M12 4v15M5 8h14M5 8v5m14-5v5M7 19h10" /><circle cx="5" cy="15" r="2" /><circle cx="19" cy="15" r="2" /></>,
  Timeline: <><circle cx="12" cy="12" r="9" /><path d="M12 6v6l4 3" /></>,
  Clusters: <><circle cx="5" cy="7" r="2" /><circle cx="18" cy="5" r="2" /><circle cx="12" cy="18" r="2" /><path d="m7 8 4 8m5-9-3 9M7 7h9" /></>,
  Analytics: <><path d="M4 19h16M6 16v-5m6 5V5m6 11V9" /><circle cx="6" cy="9" r="1" /><circle cx="12" cy="3" r="1" /><circle cx="18" cy="7" r="1" /></>,
};

export function BrainHeader({
  quote,
  stats,
}: {
  quote?: string;
  stats?: readonly { label: string; value: string; icon: string }[];
}) {
  const rows = stats?.length ? stats : BRAIN_STATS;
  return (
    <header className="lv-br-header">
      <div className="lv-br-title-block">
        <h1 className="lv-br-title">Brain</h1>
        <p className="lv-br-subtitle">Dynamic Knowledge Intelligence</p>
        <p className="lv-br-quote">{quote ?? "“Everything is connected.”"}</p>
      </div>
      <div className="lv-br-stats">
        {rows.map((stat) => (
          <div key={stat.label} className="lv-br-stat">
            <span className={`lv-br-stat-icon is-${stat.icon}`} aria-hidden="true" />
            <div>
              <strong>{stat.value}</strong>
              <span>{stat.label}</span>
            </div>
          </div>
        ))}
      </div>
      <aside className="lv-br-aside">
        <p>“Knowledge is a network not an archive.”</p>
        <span>— LEVIATHAN</span>
      </aside>
    </header>
  );
}

export function BrainViewTabs({
  view,
  onChange,
  trailing,
}: {
  view: BrainView;
  onChange: (view: BrainView) => void;
  trailing?: ReactNode;
}) {
  return (
    <div className="lv-br-toolbar">
      <div className="lv-br-tabs" role="tablist" aria-label="Brain views">
        {BRAIN_VIEWS.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={view === item}
            data-brain-view={item}
            className={`lv-br-tab${view === item ? " is-active" : ""}`}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onChange(item);
            }}
          >
            <svg className="lv-br-tab-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{tabPaths[item]}</svg>
            {item === "Graph" ? "Graph View" : item}
          </button>
        ))}
      </div>
      {trailing ? <div className="lv-br-tools">{trailing}</div> : null}
    </div>
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
    <svg className="lv-br-spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function LineChart({
  series,
  labels,
  width = 420,
  height = 160,
}: {
  series: readonly { name: string; color: string; values: readonly number[]; dashed?: boolean }[];
  labels?: readonly string[];
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
        const y = height - 10 - ((v - min) / span) * (height - 20);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

  return (
    <div className="lv-br-linechart">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        {[0.25, 0.5, 0.75].map((t) => (
          <line key={t} x1="0" x2={width} y1={height * t} y2={height * t} stroke="rgba(214,169,87,0.1)" />
        ))}
        {series.map((s) => (
          <path
            key={s.name}
            d={pathFor(s.values)}
            fill="none"
            stroke={s.color}
            strokeWidth="2"
            strokeDasharray={s.dashed ? "5 4" : undefined}
          />
        ))}
      </svg>
      {labels ? (
        <div className="lv-br-linechart-labels">
          {labels.map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
      ) : null}
      <div className="lv-br-legend">
        {series.map((s) => (
          <span key={s.name}>
            <i style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Donut({
  slices,
  center,
  size = 140,
}: {
  slices: readonly { value: number; color: string; label?: string }[];
  center?: string;
  size?: number;
}) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  const r = 42;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg className="lv-br-donut" viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
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
        <text x="60" y="64" textAnchor="middle" fill="#F6F1E8" fontSize="10" fontWeight="700">
          {center}
        </text>
      ) : null}
    </svg>
  );
}

export function Heatmap({
  grid,
  rowLabels,
  colLabels,
  labelWidth = 48,
  compact = false,
}: {
  grid: readonly (readonly number[])[];
  rowLabels?: readonly string[];
  colLabels?: readonly string[];
  labelWidth?: number;
  compact?: boolean;
}) {
  const colorFor = (v: number) => {
    if (v > 0.85) return "#F0C875";
    if (v > 0.7) return "#20DC8C";
    if (v > 0.5) return "#22C9D6";
    if (v > 0.35) return "#4285E8";
    return "#1a2740";
  };
  return (
    <div className={`lv-br-heatmap${compact ? " is-compact" : ""}`}>
      {colLabels ? (
        <div className="lv-br-heatmap-cols" style={{ gridTemplateColumns: `${labelWidth}px repeat(${colLabels.length}, minmax(0, 1fr))` }}>
          <span />
          {colLabels.map((c) => (
            <span key={c}>{c}</span>
          ))}
        </div>
      ) : null}
      {grid.map((row, ri) => (
        <div key={ri} className="lv-br-heatmap-row" style={{ gridTemplateColumns: `${labelWidth}px repeat(${row.length}, minmax(0, 1fr))` }}>
          <span className="lv-br-heatmap-ylab">{rowLabels?.[ri] ?? ""}</span>
          {row.map((v, ci) => (
            <span key={ci} className="lv-br-heatmap-cell" style={{ background: colorFor(v) }} title={v.toFixed(2)} />
          ))}
        </div>
      ))}
    </div>
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
    <article className={`lv-br-panel ${className}`.trim()}>
      {title || action ? (
        <div className="lv-br-panel-head">
          {title ? <div className="lv-br-panel-title">{title}</div> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </article>
  );
}
