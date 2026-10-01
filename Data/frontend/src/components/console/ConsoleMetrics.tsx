import { MetricCard, Sparkline } from "../ui";
import type { ConsoleOverviewResponse } from "../../types/api";
import { formatCompactCount, formatRate } from "../../pages/console/consoleFormat";

type Props = {
  overview: ConsoleOverviewResponse | null;
  loading?: boolean;
  unmeasured?: boolean;
};

function MiniBars({ values, tone }: { values?: number[]; tone: string }) {
  if (!values?.length) {
    return <div className="lv-v2-metric-card__chart lv-v2-metric-card__chart--empty" aria-hidden="true" />;
  }
  const max = Math.max(1, ...values);
  return (
    <div className={`lv-v2-metric-card__chart lv-v2-metric-card__chart--${tone}`} aria-hidden="true">
      <div className="lv-v2-console-mini-bars">
        {values.slice(-16).map((v, i) => (
          <i key={i} style={{ height: `${Math.max(12, Math.round((v / max) * 100))}%` }} />
        ))}
      </div>
    </div>
  );
}

export function ConsoleMetrics({ overview, loading, unmeasured }: Props) {
  const m = overview?.metrics;
  const spark = m?.sparklines ?? {};

  const totalValue =
    unmeasured || m?.total_logs_24h == null ? "UNMEASURED" : formatCompactCount(m.total_logs_24h);
  const servicesValue =
    m == null
      ? "—"
      : `${m.active_services} / ${m.total_services}`;
  const warnValue =
    unmeasured || m?.warnings_24h == null ? "UNMEASURED" : formatCompactCount(m.warnings_24h);
  const errValue =
    unmeasured || m?.errors_24h == null ? "UNMEASURED" : formatCompactCount(m.errors_24h);
  const rateValue =
    unmeasured || m?.log_rate_per_min == null ? "UNMEASURED" : `${formatRate(m.log_rate_per_min)} / min`;

  return (
    <section className="lv-v2-metrics lv-v2-metrics--console" aria-label="Console metrics">
      <MetricCard
        className="lv-v2-console-metric"
        label="Totale Logs (24u)"
        value={totalValue}
        sublabel="EventStore venster"
        loading={loading}
        chart={<MiniBars values={spark.total} tone="agents" />}
      />
      <MetricCard
        className="lv-v2-console-metric"
        label="Actieve Services"
        value={servicesValue}
        sublabel="operational + measured"
        loading={loading}
        valueTone={m && m.active_services > 0 ? "success" : "default"}
        chart={
          <Sparkline
            className="lv-v2-console-sparkline"
            values={spark.success ?? []}
            width={72}
            height={28}
            stroke="#34d399"
          />
        }
      />
      <MetricCard
        className="lv-v2-console-metric"
        label="Waarschuwingen"
        value={warnValue}
        sublabel="Laatste 24 uur"
        loading={loading}
        chart={<MiniBars values={spark.warning} tone="amber" />}
      />
      <MetricCard
        className="lv-v2-console-metric"
        label="Fouten"
        value={errValue}
        sublabel="Laatste 24 uur"
        loading={loading}
        chart={<MiniBars values={spark.error} tone="danger" />}
      />
      <MetricCard
        className="lv-v2-console-metric"
        label="Gem. Log Rate"
        value={rateValue}
        sublabel="Trailing 5 min"
        loading={loading}
        chart={
          <Sparkline
            className="lv-v2-console-sparkline"
            values={spark.rate ?? spark.total ?? []}
            width={72}
            height={28}
            stroke="#38bdf8"
          />
        }
      />
    </section>
  );
}
