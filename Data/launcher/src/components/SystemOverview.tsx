import type { MetricCardModel } from "../types/backend";
import { Sparkline } from "./Sparkline";

const colors: Record<MetricCardModel["tone"], string> = {
  cyan: "#3ec6c6",
  green: "#3dbe7a",
  amber: "#e0a23a",
  violet: "#9a7adf",
  muted: "#8d887c",
};

export function SystemOverview({ metrics }: { metrics: MetricCardModel[] }) {
  return (
    <section className="panel" aria-label="System overview">
      <header>
        <h2>SYSTEM OVERVIEW</h2>
        <span className="sub">Real-time metrics and performance.</span>
      </header>
      <div className="metrics">
        {metrics.map((metric) => (
          <article className="metric" key={metric.id}>
            <div className="label">{metric.label}</div>
            <div className={`value ${metric.value === "UNMEASURED" ? "muted" : metric.tone}`}>{metric.value}{metric.unit ? ` ${metric.unit}` : ""}</div>
            {metric.detail ? <div className="metric-detail">{metric.detail}</div> : null}
            <Sparkline samples={metric.samples} color={colors[metric.tone]} chart={metric.chart} />
          </article>
        ))}
      </div>
    </section>
  );
}
