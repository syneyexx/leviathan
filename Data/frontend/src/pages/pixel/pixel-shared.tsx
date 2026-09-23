import type { ReactNode } from "react";
import { Spark } from "../media/mr-shared";

const ICON_GLYPH: Record<string, string> = {
  database: "◫",
  grid: "▦",
  link: "⛓",
  chart: "◧",
  upload: "↑",
  search: "⌕",
  globe: "◎",
  bolt: "⚡",
  target: "◎",
  settings: "⚙",
  brain: "◉",
  image: "▣",
  folder: "▤",
  terminal: ">_",
  checkcircle: "✓",
  more: "⋯",
  download: "↓",
  plus: "+",
  trash: "✕",
  save: "▣",
  refresh: "↻",
  copy: "⧉",
  play: "▶",
  pause: "❚❚",
  shield: "⛨",
  file: "▤",
  book: "▥",
  sliders: "≡",
  squareplus: "⊕",
  code: "{ }",
  list: "☰",
  pulse: "∿",
  meta: "∞",
  users: "👥",
  wrench: "⚒",
  line: "↗",
  chevron: "›",
  square: "□",
};

export function PxIcon({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span className={`lv-px-ico ${className}`.trim()} aria-hidden="true">
      {ICON_GLYPH[name] ?? "•"}
    </span>
  );
}

export function PxHero({
  title,
  subtitle,
  quote,
  pillars,
  extra,
}: {
  title: string;
  subtitle?: string;
  quote?: string;
  pillars?: readonly string[];
  extra?: ReactNode;
}) {
  return (
    <header className="lv-px-hero">
      <div className="lv-px-hero-grid">
        <div>
          <h1 className="lv-px-hero-title">{title}</h1>
          {subtitle ? <p className="lv-px-hero-sub">{subtitle}</p> : null}
        </div>
        {quote ? <p className="lv-px-hero-quote">“{quote}”</p> : null}
        {pillars?.length ? (
          <div className="lv-px-hero-pillars" aria-hidden="true">
            {pillars.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </div>
        ) : null}
        {extra}
      </div>
    </header>
  );
}

export function PxKpi({
  label,
  value,
  hint,
  hintTone = "muted",
  icon,
  progress,
  spark,
}: {
  label: string;
  value: string;
  hint?: string;
  hintTone?: "muted" | "cyan" | "gold" | "green" | "red";
  icon?: string;
  progress?: number;
  spark?: readonly number[];
}) {
  return (
    <article className="lv-px-kpi">
      {icon ? (
        <span className="lv-px-kpi-ico">
          <PxIcon name={icon} />
        </span>
      ) : null}
      <div className="lv-px-kpi-body">
        <div className="lv-px-kpi-label">{label}</div>
        <div className="lv-px-kpi-value">{value}</div>
        {hint ? <div className={`lv-px-kpi-hint is-${hintTone}`}>{hint}</div> : null}
        {progress != null ? (
          <div className="lv-px-progress is-thin" aria-hidden="true">
            <i style={{ width: `${progress}%` }} />
          </div>
        ) : null}
      </div>
      {spark?.length ? <Spark points={spark} color="var(--lv-cyan)" /> : null}
    </article>
  );
}

export function PxSwitch({
  on,
  onToggle,
  label,
}: {
  on: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      className={`lv-px-switch${on ? " is-on" : ""}`}
      aria-pressed={on}
      aria-label={label}
      onClick={onToggle}
    />
  );
}

export function chartPolyline(values: readonly number[], width: number, height: number): string {
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  return values
    .map((v, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * width;
      const y = height - 2 - ((v - min) / span) * (height - 4);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function donutSegments(slices: { value: number; color: string }[]) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  const c = 2 * Math.PI * 14;
  let offset = 0;
  return slices.map((slice) => {
    const len = (slice.value / total) * c;
    const seg = { dash: `${len} ${c - len}`, offset: -offset, color: slice.color };
    offset += len;
    return seg;
  });
}
