import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Badge, Button, Panel } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function DatasetIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
      <path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
    </svg>
  );
}

function sourceTone(sourceType: string): "info" | "warning" | "muted" | "data" {
  const s = sourceType.toLowerCase();
  if (s.includes("hf") || s.includes("hugging")) return "warning";
  if (s.includes("local") || s.includes("upload") || s.includes("file")) return "info";
  return "data";
}

function sourceLabel(sourceType: string): string {
  const s = sourceType.toLowerCase();
  if (s.includes("hf") || s.includes("hugging")) return "HF";
  if (s.includes("local") || s.includes("upload") || s.includes("file")) return "Lokaal";
  return sourceType || "—";
}

function formatCount(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K voorbeelden`;
  return `${n} voorbeelden`;
}

export function TrainingDatasetPanel({ ws }: Props) {
  return (
    <Panel
      title="Dataset Bronnen"
      icon={<DatasetIcon />}
      className="lv-v2-training-datasets"
      action={
        <Button variant="ghost" size="sm" onClick={() => void ws.refresh()}>
          Vernieuwen
        </Button>
      }
    >
      {ws.datasets.length === 0 ? (
        <p className="lv-v2-muted">{ws.loading ? "Datasets laden…" : "Geen datasets gevonden."}</p>
      ) : (
        <ul className="lv-v2-training-list">
          {ws.datasets.map((ds) => {
            const selected = ws.selectedDatasetId === ds.datasetId;
            const name = ds.displayName || ds.name;
            return (
              <li key={ds.datasetId}>
                <button
                  type="button"
                  className={`lv-v2-training-list__item${selected ? " is-selected" : ""}`}
                  aria-pressed={selected}
                  onClick={() => ws.selectDataset(ds.datasetId)}
                >
                  <span className="lv-v2-training-list__icon" aria-hidden="true">
                    <DatasetIcon />
                  </span>
                  <span className="lv-v2-training-list__body">
                    <span className="lv-v2-training-list__title">{name}</span>
                    <span className="lv-v2-training-list__meta">
                      {ds.detectedFormat || ds.primaryCategory || ds.sourceType || "dataset"} ·{" "}
                      {formatCount(ds.rowCount)}
                    </span>
                  </span>
                  <Badge tone={sourceTone(ds.sourceType)}>{sourceLabel(ds.sourceType)}</Badge>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {ws.selectedDatasetId && ws.datasetVersions.length > 0 ? (
        <label className="lv-v2-training-field">
          Versie
          <select
            value={ws.selectedVersionId ?? ""}
            onChange={(e) => ws.selectVersion(e.target.value || null)}
          >
            {ws.datasetVersions.map((v) => (
              <option key={v.versionId} value={v.versionId}>
                {v.versionLabel || v.versionId} ({v.status})
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </Panel>
  );
}
