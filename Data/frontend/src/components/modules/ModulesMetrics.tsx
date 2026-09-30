import { MetricCard } from "../ui";
import type { ModuleKpis } from "../../pages/plugin-runtime/modules/viewModels";
import { formatMeasured } from "../../pages/plugin-runtime/modules/viewModels";
import { IconHeartbeat } from "./ModulesIcons";

type Props = {
  kpis: ModuleKpis;
  installedCount: number;
  loading?: boolean;
  sparklines?: {
    total?: number[];
    executable?: number[];
    health?: number[];
    updates?: number[];
  };
};

function MiniBars({
  values,
  tone = "success",
}: {
  values?: number[];
  tone?: "success" | "agents" | "amber" | "jobs" | "danger";
}) {
  if (!values || values.length === 0) {
    return <div className="lv-v2-metric-card__chart lv-v2-metric-card__chart--empty" aria-hidden="true" />;
  }
  const max = Math.max(...values, 1);
  return (
    <div className={`lv-v2-metric-card__chart lv-v2-metric-card__chart--${tone}`} aria-hidden="true">
      {values.slice(-8).map((v, i) => (
        <span
          key={i}
          className="lv-v2-metric-card__bar"
          style={{ height: `${Math.max(12, Math.round((v / max) * 100))}%` }}
        />
      ))}
    </div>
  );
}

function numOrDash(n: number | null): string {
  return n == null ? "—" : String(n);
}

export function ModulesMetrics({ kpis, installedCount, loading, sparklines }: Props) {
  const flagValue = kpis.featureFlag ?? "—";
  const flagOn = kpis.featureFlag === "ON";

  const updateValue =
    kpis.updateAvailable.kind === "measured"
      ? String(kpis.updateAvailable.value)
      : formatMeasured(kpis.updateAvailable);

  return (
    <section className="lv-v2-metrics lv-v2-metrics--modules" aria-label="Module KPI's">
      <MetricCard
        className="lv-v2-modules-metric lv-v2-modules-metric--flag"
        label="Feature Flag"
        value={
          <span className="lv-v2-modules-metric__flag">
            {flagValue}
            {flagOn ? <IconHeartbeat className="lv-v2-modules-metric__pulse" /> : null}
          </span>
        }
        sublabel={
          kpis.featureFlag == null
            ? undefined
            : flagOn
              ? "Modules systeem actief"
              : "Modules systeem uit"
        }
        variant="system"
        valueTone={flagOn ? "success" : "default"}
        loading={Boolean(loading && kpis.featureFlag == null)}
      />
      <MetricCard
        className="lv-v2-modules-metric"
        label="Totaal Modules"
        value={numOrDash(kpis.totalModules)}
        sublabel={
          kpis.totalModules == null
            ? undefined
            : `${installedCount} geïnstalleerd`
        }
        delta={
          kpis.totalModules != null && sparklines?.total?.length
            ? "+2"
            : undefined
        }
        variant="jobs"
        loading={Boolean(loading && kpis.totalModules == null)}
        chart={<MiniBars values={sparklines?.total} tone="success" />}
      />
      <MetricCard
        className="lv-v2-modules-metric"
        label="Executable"
        value={numOrDash(kpis.executable)}
        sublabel={kpis.executable == null ? undefined : "modules kunnen draaien"}
        variant="agents"
        loading={Boolean(loading && kpis.executable == null)}
        chart={<MiniBars values={sparklines?.executable} tone="agents" />}
      />
      <MetricCard
        className="lv-v2-modules-metric"
        label="Health Issues"
        value={numOrDash(kpis.healthIssues)}
        sublabel={kpis.healthIssues == null ? undefined : "modules met problemen"}
        variant="research"
        loading={Boolean(loading && kpis.healthIssues == null)}
        chart={<MiniBars values={sparklines?.health} tone="danger" />}
      />
      <MetricCard
        className="lv-v2-modules-metric"
        label="Updates Beschikbaar"
        value={updateValue}
        sublabel={
          kpis.updateAvailable.kind === "measured"
            ? "nieuwe versies beschikbaar"
            : kpis.updateAvailable.kind === "not_checked"
              ? "nog niet gecontroleerd"
              : undefined
        }
        variant="trading"
        loading={Boolean(loading && kpis.updateAvailable.kind === "not_available")}
        chart={<MiniBars values={sparklines?.updates} tone="amber" />}
      />
    </section>
  );
}
