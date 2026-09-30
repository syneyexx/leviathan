import { MetricCard } from "../ui";
import type { DatasetOverview } from "../../types/api";
import { formatBytes, formatCompactCount } from "../../pages/dataset-management/viewModels";

type Props = {
  overview: DatasetOverview | null;
  loading: boolean;
  error: string | null;
};

export function DatasetMgmtMetrics({ overview, loading, error }: Props) {
  const storagePct =
    overview?.capacityBytes && overview.capacityBytes > 0 && overview.usedBytes != null
      ? Math.round((overview.usedBytes / overview.capacityBytes) * 100)
      : null;

  return (
    <section className="lv-v2-metrics lv-v2-dm-metrics" aria-label="Dataset Management KPI's">
      <MetricCard
        label="Totaal Datasets"
        value={loading ? "…" : formatCompactCount(overview?.totalDatasets ?? 0)}
        sublabel={error ? "Laden mislukt" : `${overview?.byStatus ? Object.keys(overview.byStatus).length : 0} statustypen`}
        variant="system"
        loading={loading}
      />
      <MetricCard
        label="Totaal Samples"
        value={loading ? "…" : formatCompactCount(overview?.totalSamples ?? 0)}
        sublabel={
          overview?.samplesUnmeasuredDatasets
            ? `${overview.samplesUnmeasuredDatasets} datasets ongemeten`
            : "Alle datasets gemeten"
        }
        variant="agents"
        loading={loading}
      />
      <MetricCard
        label="Opslag Gebruikt"
        value={loading ? "…" : formatBytes(overview?.attributableBytes ?? 0)}
        sublabel={
          storagePct != null
            ? `${storagePct}% van ${formatBytes(overview?.capacityBytes)}`
            : "Capaciteit onbekend"
        }
        variant="jobs"
        loading={loading}
      />
      <MetricCard
        label="Actieve Imports"
        value={loading ? "…" : String(overview?.activeImports ?? 0)}
        sublabel={
          overview
            ? `${overview.runningImports} bezig · ${overview.queuedImports} in wachtrij`
            : undefined
        }
        variant="research"
        loading={loading}
      />
      <MetricCard
        label="Validatie Issues"
        value={loading ? "…" : String(overview?.validationIssues ?? 0)}
        sublabel={
          overview
            ? `${overview.criticalValidationIssues} kritiek · ${overview.warningValidationIssues} waarschuwingen`
            : undefined
        }
        variant="trading"
        loading={loading}
      />
      <MetricCard
        label="Catalogus"
        value={loading ? "…" : overview?.catalogStatus.label ?? "—"}
        sublabel={
          overview?.catalogStatus.lastCatalogReconcileAt
            ? `Laatste reconcile ${new Date(overview.catalogStatus.lastCatalogReconcileAt).toLocaleString("nl-NL")}`
            : "Geen reconcile-tijdstip bekend"
        }
        variant="system"
        loading={loading}
      />
    </section>
  );
}
