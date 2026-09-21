import type { CSSProperties, ReactNode } from "react";

type Tone = "green" | "red" | "gold" | "teal";

export function StatusDot({ tone = "green", className = "" }: { tone?: Tone; className?: string }) {
  return <span className={`mp-status-dot ${className}`.trim()} data-tone={tone} aria-hidden="true" />;
}

export function VerifiedBadge({ className = "" }: { className?: string }) {
  return (
    <span className={`mp-verified ${className}`.trim()} aria-label="Verified" title="Verified">
      <svg viewBox="0 0 24 24">
        <path d="M5 12.5l4.2 4.2L19 7.5" />
      </svg>
    </span>
  );
}

export function GrowthDelta({
  absolute,
  percent,
  direction = "up",
}: {
  absolute?: string;
  percent?: string;
  direction?: "up" | "down" | "flat";
}) {
  return (
    <span className={`mp-growth is-${direction}`}>
      {absolute ? <span>{absolute}</span> : null}
      {percent ? <span>{percent}</span> : null}
    </span>
  );
}

export function Sparkline({
  values,
  stroke = "#e53935",
  fill = "rgba(229, 57, 53, 0.12)",
  className = "",
}: {
  values: number[];
  stroke?: string;
  fill?: string;
  className?: string;
}) {
  const width = 120;
  const height = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => {
    const x = (index / Math.max(values.length - 1, 1)) * width;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  });
  const line = points.join(" ");
  const area = `0,${height} ${line} ${width},${height}`;

  return (
    <svg className={`mp-sparkline ${className}`.trim()} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <polyline points={area} fill={fill} stroke="none" />
      <polyline points={line} fill="none" stroke={stroke} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function MetricCard({
  label,
  value,
  absolute,
  percent,
  direction = "up",
  icon,
  sparkline,
  sparkStroke,
}: {
  label: string;
  value: string;
  absolute?: string;
  percent?: string;
  direction?: "up" | "down" | "flat";
  icon?: ReactNode;
  sparkline?: number[];
  sparkStroke?: string;
}) {
  return (
    <article className="mp-metric-card">
      <div className="mp-metric-head">
        <div className="mp-metric-label">{label}</div>
        {icon ? <div className="mp-metric-icon">{icon}</div> : null}
      </div>
      <div className="mp-metric-value">{value}</div>
      <GrowthDelta absolute={absolute} percent={percent} direction={direction} />
      {sparkline ? <Sparkline values={sparkline} stroke={sparkStroke} /> : null}
    </article>
  );
}

export function Panel({
  title,
  children,
  action,
  className = "",
  bodyClassName = "",
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`mp-panel ${className}`.trim()}>
      <div className="mp-panel-title">
        <span>{title}</span>
        {action}
      </div>
      <div className={`mp-panel-body ${bodyClassName}`.trim()}>{children}</div>
    </section>
  );
}

export type PlatformKind = "youtube" | "tiktok" | "instagram" | "facebook";

export function PlatformIcon({ platform, className = "" }: { platform: PlatformKind; className?: string }) {
  const wrap = (node: ReactNode) => (
    <span className={`mp-platform-icon ${className}`.trim()} aria-hidden="true">
      {node}
    </span>
  );

  if (platform === "youtube") {
    return wrap(
      <svg viewBox="0 0 24 24">
        <rect x="2.5" y="6" width="19" height="12" rx="3.5" fill="#FF0000" />
        <path d="M10 9.5v5l5-2.5-5-2.5z" fill="#fff" />
      </svg>,
    );
  }

  if (platform === "tiktok") {
    return wrap(
      <svg viewBox="0 0 24 24">
        <path d="M14.5 4v9.2a3.3 3.3 0 11-2.4-3.2V7.2c.7.2 1.5.4 2.4.5V4h0z" fill="#25F4EE" />
        <path
          d="M15.2 4.4c.7 1.7 2.1 3 3.8 3.5V10c-1.4-.2-2.7-.8-3.8-1.7v5.5a4.6 4.6 0 11-4.6-4.6c.3 0 .5 0 .8.1v2.3a2.3 2.3 0 102 2.3V4.4h1.8z"
          fill="#FE2C55"
        />
        <path d="M14.5 4v9.2a3.3 3.3 0 11-2.4-3.2V7.3c.7.15 1.5.35 2.4.45V4z" fill="#fff" opacity="0.92" />
      </svg>,
    );
  }

  if (platform === "instagram") {
    return wrap(
      <svg viewBox="0 0 24 24">
        <defs>
          <linearGradient id="mp-ig" x1="4" y1="20" x2="20" y2="4">
            <stop stopColor="#f58529" />
            <stop offset="0.4" stopColor="#dd2a7b" />
            <stop offset="0.7" stopColor="#8134af" />
            <stop offset="1" stopColor="#515bd4" />
          </linearGradient>
        </defs>
        <rect x="3" y="3" width="18" height="18" rx="5" fill="url(#mp-ig)" />
        <circle cx="12" cy="12" r="4.2" fill="none" stroke="#fff" strokeWidth="1.6" />
        <circle cx="17.2" cy="6.8" r="1.1" fill="#fff" />
      </svg>,
    );
  }

  return wrap(
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" fill="#1877F2" />
      <path
        d="M13.2 19v-6.2h2.1l.3-2.4h-2.4V8.9c0-.7.2-1.2 1.2-1.2h1.3V5.6c-.2 0-1-.1-1.9-.1-1.9 0-3.2 1.2-3.2 3.3v1.8H9.2v2.4h2.1V19h1.9z"
        fill="#fff"
      />
    </svg>,
  );
}

export type ChartSeries = {
  id: string;
  color: string;
  values: number[];
  fill?: string;
};

export function LineChart({
  series,
  labels,
  height = 180,
  className = "",
  marker,
}: {
  series: ChartSeries[];
  labels?: string[];
  height?: number;
  className?: string;
  marker?: { index: number; label: string };
}) {
  const width = 640;
  const pad = { top: 12, right: 12, bottom: 24, left: 36 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const all = series.flatMap((s) => s.values);
  const min = Math.min(...all, 0);
  const max = Math.max(...all, 1);
  const range = max - min || 1;
  const len = Math.max(...series.map((s) => s.values.length), 2);

  const toPoint = (value: number, index: number) => {
    const x = pad.left + (index / Math.max(len - 1, 1)) * innerW;
    const y = pad.top + innerH - ((value - min) / range) * innerH;
    return { x, y };
  };

  const gridLines = 4;

  return (
    <svg className={`mp-line-chart ${className}`.trim()} viewBox={`0 0 ${width} ${height}`} role="img">
      {Array.from({ length: gridLines + 1 }, (_, i) => {
        const y = pad.top + (innerH / gridLines) * i;
        return (
          <line
            key={`g-${i}`}
            x1={pad.left}
            x2={width - pad.right}
            y1={y}
            y2={y}
            stroke="rgba(214,169,87,0.12)"
            strokeWidth="1"
          />
        );
      })}
      {series.map((s) => {
        const points = s.values.map((value, index) => toPoint(value, index));
        const line = points.map((p, index) => `${index === 0 ? "M" : "L"}${p.x} ${p.y}`).join(" ");
        const area =
          points.length > 0
            ? `${line} L${points[points.length - 1].x} ${pad.top + innerH} L${points[0].x} ${pad.top + innerH} Z`
            : "";
        return (
          <g key={s.id}>
            {s.fill && area ? <path d={area} fill={s.fill} stroke="none" /> : null}
            <path d={line} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
          </g>
        );
      })}
      {marker && series[0] ? (() => {
        const value = series[0].values[marker.index];
        if (value == null) return null;
        const { x, y } = toPoint(value, marker.index);
        return (
          <g>
            <circle cx={x} cy={y} r="4" fill={series[0].color} stroke="#111" strokeWidth="1.5" />
            <rect x={x - 42} y={y - 28} width="84" height="18" rx="4" fill="rgba(8,8,8,0.92)" stroke="rgba(214,169,87,0.35)" />
            <text x={x} y={y - 15} textAnchor="middle" fill="#e8e4dc" fontSize="9">
              {marker.label}
            </text>
          </g>
        );
      })() : null}
      {labels?.map((label, index) => {
        const x = pad.left + (index / Math.max(labels.length - 1, 1)) * innerW;
        return (
          <text key={label} x={x} y={height - 6} textAnchor="middle" fill="rgba(138,134,128,0.9)" fontSize="10">
            {label}
          </text>
        );
      })}
    </svg>
  );
}

export function ProgressBar({
  value,
  label,
  tone = "gold",
  showValue = true,
}: {
  value: number;
  label?: string;
  tone?: "gold" | "red" | "teal" | "green";
  showValue?: boolean;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="mp-progress" data-tone={tone}>
      {(label || showValue) && (
        <div className="mp-progress-meta">
          <span>{label}</span>
          {showValue ? <span>{Math.round(clamped)}%</span> : null}
        </div>
      )}
      <div className="mp-progress-track" role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100}>
        <div className="mp-progress-fill" style={{ width: `${clamped}%` } as CSSProperties} />
      </div>
    </div>
  );
}

export function DonutChart({
  value,
  size = 72,
  stroke = 8,
  color = "#d6a957",
  track = "rgba(255,255,255,0.08)",
  label,
}: {
  value: number;
  size?: number;
  stroke?: number;
  color?: string;
  track?: string;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;

  return (
    <svg className="mp-donut" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label ?? `${clamped}%`}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={track} strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="50%" dominantBaseline="middle" textAnchor="middle" fill="#e8e4dc" fontSize={size * 0.22} fontWeight="600">
        {label ?? `${Math.round(clamped)}%`}
      </text>
    </svg>
  );
}
