import { useState } from "react";
import { Link } from "react-router-dom";
import { PxIcon } from "../../pages/pixel/pixel-shared";
import { DM_ADVANCED_ACTIONS, DM_CATEGORY_FILTERS } from "../../pages/dataset-management/constants";
import {
  categoryForDataset,
  dash,
  displayNameForDataset,
  mapSourceLabel,
  mapTypeLabel,
  qualityLabel,
  qualityTone,
  recoveryLabel,
} from "../../pages/dataset-management/viewModels";
import type { DatasetManagementWorkspace } from "../../pages/dataset-management/useDatasetManagementWorkspace";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetMgmtDetails({ ws }: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const selected = ws.selected;

  if (ws.detailError) {
    return (
      <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-details" aria-label="Details">
        <h3 className="lv-v2-panel__title">Details</h3>
        <p className="lv-v2-dm-muted">{ws.detailError}</p>
      </section>
    );
  }

  if (!selected) {
    return (
      <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-details" aria-label="Details">
        <h3 className="lv-v2-panel__title">Details</h3>
        <p className="lv-v2-dm-muted">Selecteer een dataset</p>
      </section>
    );
  }

  const displayName = displayNameForDataset(selected);
  const learnedLabel =
    selected.learningState?.canonicalState === "LEARNED" || selected.learned
      ? "Geleerd"
      : ws.recovery?.reindexRequired || ws.recovery?.recoveryState === "REINDEX_REQUIRED"
        ? "Herindexeren vereist (≠ geleerd)"
        : dash(selected.learningState?.label ?? selected.brainStatus ?? "niet geleerd");

  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-details" aria-label="Details">
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">Details</h3>
        <span className={`lv-v2-dm-pill is-${qualityTone(selected.quality)}`}>{qualityLabel(selected.quality)}</span>
      </div>
      <p className="lv-v2-dm-detail-name">{displayName}</p>
      {displayName !== selected.name ? (
        <p className="lv-v2-dm-muted">Interne naam: {selected.name}</p>
      ) : null}
      <p className="lv-v2-dm-muted">{selected.description || "Geen beschrijving"}</p>
      {ws.versions.length === 0 ? (
        <p className="lv-v2-dm-muted">Lege dataset — nog geen versies of rijen.</p>
      ) : null}

      <dl className="lv-v2-dm-meta-grid">
        <dt>Categorie</dt>
        <dd>{dash(categoryForDataset(selected) || null)}</dd>
        <dt>Bron</dt>
        <dd>{mapSourceLabel(selected.sourceType)}</dd>
        <dt>Type</dt>
        <dd>{mapTypeLabel(selected)}</dd>
        <dt>Locatie</dt>
        <dd className="lv-v2-dm-mono">{dash(selected.rawPath ?? selected.originalUri)}</dd>
        <dt>Versie</dt>
        <dd>
          {ws.versions.length > 1 ? (
            <select
              className="lv-v2-select"
              value={ws.selectedVersionId ?? ""}
              onChange={(e) => ws.setSelectedVersionId(e.target.value || null)}
            >
              {ws.versions.map((v) => (
                <option key={v.versionId} value={v.versionId}>
                  {v.versionLabel} ({v.kind})
                </option>
              ))}
            </select>
          ) : (
            dash(ws.selectedVersion?.versionLabel)
          )}
        </dd>
        <dt>Brain status</dt>
        <dd>{learnedLabel}</dd>
        <dt>Recovery</dt>
        <dd>{recoveryLabel(ws.recovery?.recoveryState ?? selected.recoveryState)}</dd>
        <dt>Licentie</dt>
        <dd>{dash(selected.license)}</dd>
      </dl>

      {ws.semanticEditing ? (
        <div className="lv-v2-dm-edit-form">
          <label className="lv-v2-dm-field">
            Weergavenaam
            <input
              className="lv-v2-input"
              value={ws.editDisplayName}
              onChange={(e) => ws.setEditDisplayName(e.target.value)}
            />
          </label>
          <label className="lv-v2-dm-field">
            Categorie
            <select
              className="lv-v2-select"
              value={ws.editCategory}
              onChange={(e) => ws.setEditCategory(e.target.value)}
            >
              {DM_CATEGORY_FILTERS.filter((c) => c !== DM_CATEGORY_FILTERS[0]).map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="lv-v2-dm-field">
            Tags (komma-gescheiden)
            <input
              className="lv-v2-input"
              value={ws.editTags}
              onChange={(e) => ws.setEditTags(e.target.value)}
            />
          </label>
          <div className="lv-v2-dm-edit-actions">
            <button
              type="button"
              className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
              disabled={ws.busy || !ws.selectedId}
              onClick={() => void ws.onSaveSemantic()}
            >
              Opslaan
            </button>
            <button
              type="button"
              className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm"
              onClick={() => ws.setSemanticEditing(false)}
            >
              Annuleren
            </button>
          </div>
        </div>
      ) : null}

      <div className="lv-v2-dm-action-list lv-v2-dm-detail-actions">
        <button
          type="button"
          className="lv-v2-dm-action-btn"
          disabled={ws.busy || !ws.selectedId}
          onClick={() => ws.setSemanticEditing((v) => !v)}
        >
          <PxIcon name="sliders" />
          <span>Metagegevens bewerken</span>
        </button>
        <button
          type="button"
          className="lv-v2-dm-action-btn"
          disabled={ws.busy || !ws.selectedId || !ws.selectedVersionId}
          onClick={() => void ws.onAnalyzeSemantic()}
        >
          <PxIcon name="refresh" />
          <span>Opnieuw analyseren</span>
        </button>
        <button
          type="button"
          className="lv-v2-dm-action-btn"
          disabled={!ws.selectedVersionId}
          onClick={() => ws.setSampleTab("JSON")}
        >
          <PxIcon name="file" />
          <span>Voorbeeld bekijken</span>
        </button>
        <Link
          to={
            ws.selectedId
              ? `/training?datasetId=${encodeURIComponent(ws.selectedId)}${
                  ws.selectedVersionId ? `&datasetVersionId=${encodeURIComponent(ws.selectedVersionId)}` : ""
                }`
              : "/training"
          }
          className="lv-v2-dm-action-link"
        >
          <PxIcon name="play" />
          <span>Gebruik in training</span>
        </Link>
        <Link to="/offline-datasets" className="lv-v2-dm-action-link">
          <PxIcon name="database" />
          <span>Geleerd in Brain</span>
        </Link>
      </div>

      <details
        className="lv-v2-dm-advanced"
        open={advancedOpen}
        onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary>Geavanceerde bewerkingen</summary>
        <div className="lv-v2-dm-advanced-grid">
          {DM_ADVANCED_ACTIONS.map((action) => {
            const needsVersion = action.id !== "materialize";
            const disabled =
              ws.busy ||
              !ws.selectedId ||
              (needsVersion && !ws.selectedVersionId);
            return (
              <button
                key={action.id}
                type="button"
                className="lv-v2-dm-action-btn"
                disabled={disabled}
                title={
                  disabled
                    ? needsVersion && !ws.selectedVersionId
                      ? "Selecteer eerst een datasetversie"
                      : "Selecteer eerst een dataset"
                    : undefined
                }
                onClick={() => void ws.onAdvancedAction(action.id)}
              >
                <PxIcon name={action.icon} />
                <span>{action.label}</span>
              </button>
            );
          })}
        </div>
        <p className="lv-v2-dm-muted">
          Geavanceerde jobs draaien via DatasetService → JobRuntime → dataset worker.
          Enqueue ≠ voltooid. Deduplicatie/transform creëert nieuwe versies (niet stil destructief).
        </p>
      </details>
    </section>
  );
}
