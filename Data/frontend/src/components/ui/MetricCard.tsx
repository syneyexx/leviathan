import type { ReactNode } from "react";

type MetricVariant = "system" | "agents" | "jobs" | "research" | "trading";
type ValueTone = "success" | "default";

export type MetricCardProps = {
  label: string;
  value: ReactNode;
  sublabel?: ReactNode;
  delta?: ReactNode;
  variant?: MetricVariant;
  chart?: ReactNode;
  valueTone?: ValueTone;
  loading?: boolean;
  className?: string;
};

export function MetricCard({
  label,
  value,
  sublabel,
  delta,
  variant,
  chart,
  valueTone = "default",
  loading = false,
  className = "",
}: MetricCardProps) {
  const classes = [
    "lv-v2-metric-card",
    variant ? `lv-v2-metric-card--${variant}` : "",
    loading ? "is-loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const valueClass = [
    "lv-v2-metric-card__value",
    valueTone === "success" ? "lv-v2-metric-card__value--success" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article className={classes} aria-busy={loading || undefined}>
      <div className="lv-v2-metric-card__main">
        <div className="lv-v2-metric-card__label">{label}</div>
        {loading ? (
          <div className={`${valueClass} lv-v2-skeleton`} aria-hidden="true">
            &nbsp;
          </div>
        ) : (
          <div className={valueClass}>
            {value}
            {delta ? <span className="lv-v2-metric-card__delta">{delta}</span> : null}
          </div>
        )}
        {sublabel && !loading ? <div className="lv-v2-metric-card__sub">{sublabel}</div> : null}
      </div>
      {chart ? <div className="lv-v2-metric-card__chart">{chart}</div> : null}
    </article>
  );
}
