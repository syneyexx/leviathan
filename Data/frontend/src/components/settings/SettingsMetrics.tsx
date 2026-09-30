import { MetricCard } from "../ui";
import type { SettingsWorkspace } from "../../hooks/useSettingsWorkspace";

type Props = {
  ws: SettingsWorkspace;
};

function MiniBars({ values, tone = "cyan" }: { values: number[]; tone?: string }) {
  if (!values.length) {
    return <div className={`lv-v2-settings-minibars lv-v2-settings-minibars--${tone} is-empty`} aria-hidden="true" />;
  }
  const max = Math.max(1, ...values);
  return (
    <div className={`lv-v2-settings-minibars lv-v2-settings-minibars--${tone}`} aria-hidden="true">
      {values.slice(-12).map((v, i) => (
        <span key={i} style={{ height: `${Math.max(8, (v / max) * 100)}%` }} />
      ))}
    </div>
  );
}

export function SettingsMetrics({ ws }: Props) {
  const { kpis, loading } = ws;
  const modelsValue =
    kpis.modelsAvailable == null || kpis.modelsRegistered == null
      ? "—"
      : `${kpis.modelsAvailable} van ${kpis.modelsRegistered} modellen`;
  const toolsValue =
    kpis.toolsActive == null || kpis.toolsRegistered == null
      ? "—"
      : `${kpis.toolsActive} van ${kpis.toolsRegistered} tools`;

  return (
    <section className="lv-v2-settings-metrics" aria-label="Settings status">
      <MetricCard
        label="Systeem Status"
        value={loading && !kpis.systemLabel ? "…" : kpis.systemLabel}
        valueTone={kpis.systemOperational ? "success" : "default"}
        sublabel={kpis.systemOperational ? "Core health aggregate" : "Niet alle kernen gezond"}
        variant="system"
        loading={loading && !kpis.systemLabel}
        chart={
          kpis.memoryHistory.length >= 2 ? (
            <MiniBars values={kpis.memoryHistory} tone="success" />
          ) : undefined
        }
      />
      <MetricCard
        label="Beschikbare Modellen"
        value={modelsValue}
        sublabel="Beschikbaar / geregistreerd (Model Control Plane)"
        variant="agents"
        loading={loading && kpis.modelsRegistered == null}
        chart={
          kpis.memoryHistory.length >= 2 ? (
            <MiniBars values={kpis.memoryHistory} tone="cyan" />
          ) : undefined
        }
      />
      <MetricCard
        label="Geheugen Gebruik"
        value={kpis.memoryLabel}
        sublabel={kpis.memorySub}
        variant="jobs"
        loading={loading && kpis.memoryPct == null && kpis.memoryLabel === "UNMEASURED"}
        chart={
          kpis.memoryHistory.length >= 2 ? (
            <MiniBars values={kpis.memoryHistory} tone="amber" />
          ) : undefined
        }
      />
      <MetricCard
        label="Actieve Tools"
        value={toolsValue}
        sublabel="MCP tools met availability=available"
        variant="research"
        loading={loading && kpis.toolsRegistered == null}
        chart={undefined}
      />
      <MetricCard
        label="Gebruikers"
        value={kpis.usersLabel}
        sublabel={kpis.usersSub}
        variant="trading"
        chart={undefined}
      />
    </section>
  );
}
