import { Link } from "react-router-dom";
import {
  DM_CATEGORY_FILTERS,
  DM_SAMPLE_TABS,
} from "../../pages/datasets/datasetManagementConstants";
import {
  categoryForDataset,
  dash,
  displayNameForDataset,
  mapSourceLabel,
  mapTypeLabel,
  recoveryLabel,
  tagsForDataset,
} from "../../pages/datasets/datasetManagementFormat";
import { mapDatasetStatus, toneForDatasetStatus } from "../../pages/pixel/datasetStatus";
import type { DatasetManagementWorkspace } from "../../hooks/useDatasetManagementWorkspace";
import { DmIcon } from "./DatasetManagementIcons";

type Props = {
  ws: DatasetManagementWorkspace;
};

function brainActionLabel(ws: DatasetManagementWorkspace): {
  label: string;
  mode: "learn" | "rebuild" | "open";
} {
  const selected = ws.selected;
  const brain = selected?.brainStatus ?? selected?.brain?.brainStatus;
  const canonical =
    selected?.canonicalState ??
    selected?.learningState?.canonicalState ??
    selected?.brain?.canonicalState;
  const learned =
    Boolean(selected?.learned) ||
    brain === "learned" ||
    canonical === "LEARNED";
  if (learned) return { label: "Open in Brain", mode: "open" };
  if (brain === "indexing" || brain === "queued" || canonical === "INDEXING") {
    return { label: "Indexeren…", mode: "learn" };
  }
  if (brain === "failed" || canonical === "FAILED") {
    return { label: "Opnieuw leren", mode: "rebuild" };
  }
  if (ws.recovery?.reindexRequired || ws.recovery?.recoveryState === "REINDEX_REQUIRED") {
    return { label: "Herindexeren", mode: "rebuild" };
  }
  return { label: "Kennis leren", mode: "learn" };
}

function brainStatusText(ws: DatasetManagementWorkspace): string {
  const selected = ws.selected;
  if (!selected) return "—";
  const brain = selected.brainStatus ?? selected.brain?.brainStatus;
  const canonical =
    selected.canonicalState ??
    selected.learningState?.canonicalState ??
    selected.brain?.canonicalState;
  if (selected.learned || brain === "learned" || canonical === "LEARNED") return "Geleerd";
  if (brain === "indexing" || brain === "queued" || canonical === "INDEXING") return "Indexeren";
  if (brain === "failed" || canonical === "FAILED") return "Mislukt";
  if (ws.recovery?.reindexRequired || ws.recovery?.recoveryState === "REINDEX_REQUIRED") {
    return "Verouderd — herindexeren";
  }
  return selected.learningState?.label ?? "Niet geleerd";
}

function previewTable(ws: DatasetManagementWorkspace) {
  const rows = ws.preview.slice(0, 8);
  if (rows.length === 0) return null;
  const cols = new Set<string>();
  for (const row of rows) {
    Object.keys(row as object).forEach((k) => cols.add(k));
  }
  const headers = [...cols].slice(0, 8);
  return (
    <div className="lv-v2-dm-preview-table-wrap">
      <table className="lv-v2-dm-preview-table">
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => {
            const r = row as Record<string, unknown>;
            return (
              <tr key={idx}>
                {headers.map((h) => {
                  const v = r[h];
                  const text =
                    v == null
                      ? "—"
                      : typeof v === "string" || typeof v === "number" || typeof v === "boolean"
                        ? String(v).slice(0, 120)
                        : JSON.stringify(v).slice(0, 120);
                  return <td key={h}>{text}</td>;
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function DatasetManagementDetail({ ws }: Props) {
  const selected = ws.selected;
  const statusNl = selected
    ? mapDatasetStatus(
        selected.status,
        selected.brainStatus ?? selected.brain?.brainStatus,
        selected.canonicalState ??
          selected.learningState?.canonicalState ??
          selected.brain?.canonicalState,
      )
    : null;
  const brainAction = brainActionLabel(ws);
  const trainBlocked = ws.actionDisabledReason("train");

  return (
    <div className="lv-v2-dm-detail-stack">
      <section className="lv-v2-panel lv-v2-dm-detail" aria-label="Dataset details">
        <div className="lv-v2-panel__head">
          <h3 className="lv-v2-panel__title">Details</h3>
          {statusNl ? (
            <span className={`lv-v2-dm-pill is-${toneForDatasetStatus(statusNl)}`}>{statusNl}</span>
          ) : null}
        </div>
        <div className="lv-v2-panel__body">
          {ws.detailError ? (
            <p className="lv-v2-dm-empty">{ws.detailError}</p>
          ) : selected ? (
            <>
              <p className="lv-v2-dm-detail__name">{displayNameForDataset(selected)}</p>
              {displayNameForDataset(selected) !== selected.name ? (
                <p className="lv-v2-dm-detail__internal">Intern: {selected.name}</p>
              ) : null}
              <p className="lv-v2-dm-detail__desc">{selected.description || "Geen beschrijving"}</p>
              {ws.versions.length === 0 ? (
                <p className="lv-v2-dm-empty">Lege dataset — nog geen versies of rijen.</p>
              ) : null}
              <dl className="lv-v2-dm-meta">
                <div>
                  <dt>Categorie</dt>
                  <dd>{dash(categoryForDataset(selected) || "Ongecategoriseerd")}</dd>
                </div>
                <div>
                  <dt>Bron</dt>
                  <dd>{mapSourceLabel(selected.sourceType)}</dd>
                </div>
                <div>
                  <dt>Type</dt>
                  <dd>{mapTypeLabel(selected)}</dd>
                </div>
                <div>
                  <dt>Locatie</dt>
                  <dd title={selected.rawPath ?? selected.originalUri ?? undefined}>
                    {dash(
                      (selected.rawPath ?? selected.originalUri)
                        ? String(selected.rawPath ?? selected.originalUri).replace(
                            /^.*[/\\]([^/\\]+)$/,
                            "…/$1",
                          )
                        : null,
                    )}
                  </dd>
                </div>
                <div>
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
                </div>
                <div>
                  <dt>Brain</dt>
                  <dd>{brainStatusText(ws)}</dd>
                </div>
                <div>
                  <dt>Recovery</dt>
                  <dd>
                    {recoveryLabel(ws.recovery?.recoveryState ?? selected.recoveryState)}
                  </dd>
                </div>
                <div>
                  <dt>Licentie</dt>
                  <dd>{dash(selected.license)}</dd>
                </div>
              </dl>

              {selected.semanticProfile?.summary ? (
                <div className="lv-v2-dm-summary">
                  <h4>Semantische samenvatting</h4>
                  <p>{String(selected.semanticProfile.summary).slice(0, 420)}</p>
                </div>
              ) : null}

              {ws.semanticEditing ? (
                <div className="lv-v2-dm-edit">
                  <label>
                    Weergavenaam
                    <input
                      className="lv-v2-input"
                      value={ws.editDisplayName}
                      onChange={(e) => ws.setEditDisplayName(e.target.value)}
                    />
                  </label>
                  <label>
                    Categorie
                    <select
                      className="lv-v2-select"
                      value={ws.editCategory}
                      onChange={(e) => ws.setEditCategory(e.target.value)}
                    >
                      {DM_CATEGORY_FILTERS.filter((c) => c !== "Alle categorieën").map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Tags (komma-gescheiden)
                    <input
                      className="lv-v2-input"
                      value={ws.editTags}
                      onChange={(e) => ws.setEditTags(e.target.value)}
                    />
                  </label>
                  <div className="lv-v2-dm-edit__actions">
                    <button
                      type="button"
                      className="lv-v2-button lv-v2-button--primary"
                      disabled={ws.busy}
                      onClick={() => void ws.onSaveMetadata()}
                    >
                      Opslaan
                    </button>
                    <button
                      type="button"
                      className="lv-v2-button"
                      onClick={() => ws.setSemanticEditing(false)}
                    >
                      Annuleren
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="lv-v2-dm-quick">
                <button
                  type="button"
                  disabled={ws.busy || !ws.selectedId}
                  onClick={() => {
                    if (!ws.semanticEditing && selected) {
                      ws.setEditDisplayName(displayNameForDataset(selected));
                      ws.setEditCategory(categoryForDataset(selected));
                      ws.setEditTags(tagsForDataset(selected).join(", "));
                    }
                    ws.setSemanticEditing((v) => !v);
                  }}
                >
                  <DmIcon name="sliders" />
                  <span>Metadata bewerken</span>
                </button>
                <button
                  type="button"
                  disabled={ws.busy || !ws.selectedId || !ws.selectedVersionId}
                  onClick={() => void ws.onAnalyzeSemantic()}
                >
                  <DmIcon name="refresh" />
                  <span>Opnieuw analyseren</span>
                </button>
                <button
                  type="button"
                  disabled={!ws.selectedVersionId}
                  onClick={() => {
                    ws.setSampleTab("JSON");
                    document
                      .querySelector(".lv-v2-dm-preview")
                      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                  }}
                >
                  <DmIcon name="file" />
                  <span>Voorbeeld bekijken</span>
                </button>
                {trainBlocked ? (
                  <button type="button" disabled title={trainBlocked}>
                    <DmIcon name="play" />
                    <span>Gebruik in training</span>
                  </button>
                ) : (
                  <Link to={ws.trainingDeepLink} className="lv-v2-dm-quick__link">
                    <DmIcon name="play" />
                    <span>Gebruik in training</span>
                  </Link>
                )}
                {brainAction.mode === "open" ? (
                  <Link to="/offline-datasets" className="lv-v2-dm-quick__link is-brain">
                    <DmIcon name="database" />
                    <span>{brainAction.label}</span>
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="lv-v2-dm-quick__link is-brain"
                    disabled={ws.busy || Boolean(ws.actionDisabledReason(brainAction.mode === "rebuild" ? "index" : "learn"))}
                    onClick={() =>
                      void ws.onSidebarAction(brainAction.mode === "rebuild" ? "index" : "learn")
                    }
                  >
                    <DmIcon name="database" />
                    <span>{brainAction.label}</span>
                  </button>
                )}
              </div>
            </>
          ) : (
            <p className="lv-v2-dm-empty">Selecteer een dataset</p>
          )}
        </div>
      </section>

      <section className="lv-v2-panel lv-v2-dm-preview" aria-label="Voorbeeld data">
        <div className="lv-v2-panel__head">
          <h3 className="lv-v2-panel__title">Voorbeeld data</h3>
          <div className="lv-v2-dm-tabs">
            {DM_SAMPLE_TABS.map((t) => (
              <button
                key={t}
                type="button"
                className={`lv-v2-dm-tab${ws.sampleTab === t ? " is-active" : ""}`}
                onClick={() => ws.setSampleTab(t)}
              >
                {t}
              </button>
            ))}
            <button
              type="button"
              className="lv-v2-dm-tab"
              disabled={!ws.samplePreview}
              onClick={() => {
                void navigator.clipboard?.writeText(ws.samplePreview || "").then(
                  () => undefined,
                  () => undefined,
                );
              }}
            >
              Kopieer
            </button>
          </div>
        </div>
        <div className="lv-v2-panel__body">
          {ws.sampleTab === "Tabel" && ws.preview.length > 0 && !ws.previewError
            ? previewTable(ws)
            : (
              <pre className="lv-v2-dm-code">{ws.samplePreview}</pre>
            )}
        </div>
      </section>
    </div>
  );
}
