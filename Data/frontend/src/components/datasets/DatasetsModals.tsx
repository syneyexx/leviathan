import { DatasetActivityConsole } from "../../pages/datasets/DatasetActivityConsole";
import { healthBarStyle, healthPctLabel } from "../../pages/datasets/datasetHealth";
import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";

type Props = {
  ws: DatasetsWorkspace;
};

export function DatasetsModals({ ws }: Props) {
  if (!ws.modal) return null;

  if (ws.modal === "activity") {
    return (
      <div
        className="lv-v2-ds-modal-backdrop"
        role="presentation"
        onClick={() => ws.setModal(null)}
      >
        <div
          className="lv-v2-ds-modal lv-v2-ds-modal--wide"
          role="dialog"
          aria-modal="true"
          aria-labelledby="lv-v2-ds-modal-title"
          onClick={(e) => e.stopPropagation()}
        >
          <h2 id="lv-v2-ds-modal-title">Dataset Activiteit</h2>
          <DatasetActivityConsole
            jobs={ws.jobs}
            entries={ws.activityEntries}
            preferredJobId={ws.preferredJobId}
            onPreferredJobIdChange={ws.setPreferredJobId}
            apiError={ws.jobsError}
            live={ws.live}
            busy={ws.busy}
            onCancelJob={ws.onCancelDatasetJob}
            onClearView={ws.clearActivityView}
          />
          <div className="lv-v2-ds-modal__actions">
            <button type="button" className="lv-v2-button lv-v2-button--ghost" onClick={() => ws.setModal(null)}>
              Sluiten
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (ws.modal === "health") {
    return (
      <div
        className="lv-v2-ds-modal-backdrop"
        role="presentation"
        onClick={() => ws.setModal(null)}
      >
        <div
          className="lv-v2-ds-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="lv-v2-ds-modal-title"
          onClick={(e) => e.stopPropagation()}
        >
          <h2 id="lv-v2-ds-modal-title">Dataset Health</h2>
          <p className="lv-v2-muted">
            Catalog-wide health uit overview — niet de huidige inventarispagina.
          </p>
          <ul className="lv-v2-ds-health">
            {ws.healthItems.map((item) => {
              const bar = healthBarStyle(item.pct);
              return (
                <li key={item.id}>
                  <span className="lv-v2-ds-health__label">{item.label}</span>
                  <span className={`lv-v2-ds-health__pct is-${item.tone}`}>
                    {healthPctLabel(item.pct)}
                  </span>
                  {item.hint ? <span className="lv-v2-ds-health__hint">{item.hint}</span> : null}
                  <div className={`lv-v2-ds-health__bar is-${item.tone} ${bar.className}`.trim()}>
                    <i style={bar.style} />
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="lv-v2-ds-modal__actions">
            <button type="button" className="lv-v2-button lv-v2-button--ghost" onClick={() => ws.setModal(null)}>
              Sluiten
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (ws.modal === "delete") {
    return (
      <div
        className="lv-v2-ds-modal-backdrop"
        role="presentation"
        onClick={() => !ws.busy && ws.closeModal()}
      >
        <div
          className="lv-v2-ds-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="lv-v2-ds-modal-title"
          onClick={(e) => e.stopPropagation()}
        >
          <h2 id="lv-v2-ds-modal-title">Dataset verwijderen</h2>
          <p>
            Weet je zeker dat je{" "}
            <strong>{ws.activeRow?.name || ws.activeId}</strong> wilt verwijderen? Dit kan niet
            ongedaan worden gemaakt.
          </p>
          <div className="lv-v2-ds-modal__actions">
            <button
              type="button"
              className="lv-v2-button lv-v2-button--ghost"
              disabled={ws.busy}
              onClick={() => ws.closeModal()}
            >
              Annuleren
            </button>
            <button
              type="button"
              className="lv-v2-button lv-v2-button--danger"
              disabled={ws.busy || !ws.activeId}
              onClick={() => ws.activeId && void ws.onDelete(ws.activeId)}
            >
              Verwijderen
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="lv-v2-ds-modal-backdrop"
      role="presentation"
      onClick={() => !ws.busy && ws.closeModal()}
    >
      <div
        className="lv-v2-ds-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="lv-v2-ds-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        {ws.modal === "create" ? (
          <>
            <h2 id="lv-v2-ds-modal-title">Nieuwe dataset</h2>
            <p>Registreer een lege dataset shell in LEVIATHAN.</p>
            <div className="lv-v2-ds-form">
              <label>
                Naam
                <input
                  value={ws.createName}
                  onChange={(e) => ws.setCreateName(e.target.value)}
                  placeholder="my-corpus"
                  autoFocus
                />
              </label>
              <label>
                Beschrijving
                <textarea value={ws.createDesc} onChange={(e) => ws.setCreateDesc(e.target.value)} />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost"
                  disabled={ws.busy}
                  onClick={() => ws.closeModal()}
                >
                  Annuleren
                </button>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy}
                  onClick={() => void ws.onCreate()}
                >
                  Aanmaken
                </button>
              </div>
            </div>
          </>
        ) : null}

        {ws.modal === "import" ? (
          <>
            <h2 id="lv-v2-ds-modal-title">Importeren</h2>
            <p>Upload een bestand of importeer vanaf een lokaal absoluut pad (Windows first-class).</p>
            <div className="lv-v2-ds-form">
              <label>
                Upload bestand
                <input
                  type="file"
                  onChange={(e) => ws.setUploadFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <label>
                Optionele naam
                <input
                  value={ws.uploadForm.name}
                  onChange={(e) => ws.setUploadForm((f) => ({ ...f, name: e.target.value }))}
                />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy || !ws.uploadFile}
                  onClick={() => void ws.onUpload()}
                >
                  Uploaden
                </button>
              </div>
              <hr />
              <label>
                Lokaal absoluut pad
                <input
                  value={ws.localPath}
                  onChange={(e) => ws.setLocalPath(e.target.value)}
                  placeholder="C:\\data\\corpus or /data/corpus"
                />
              </label>
              <label>
                Optionele naam
                <input value={ws.localName} onChange={(e) => ws.setLocalName(e.target.value)} />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost"
                  disabled={ws.busy}
                  onClick={() => ws.closeModal()}
                >
                  Annuleren
                </button>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy}
                  onClick={() => void ws.onImportLocal()}
                >
                  Pad importeren
                </button>
              </div>
            </div>
          </>
        ) : null}

        {ws.modal === "hf" ? (
          <>
            <h2 id="lv-v2-ds-modal-title">Externe bron — Hugging Face</h2>
            <p>Queue een Hugging Face repository import via DatasetService. Token wordt nooit gelogd of opgeslagen.</p>
            <div className="lv-v2-ds-form">
              <label>
                Repository id
                <input
                  value={ws.hfRepo}
                  onChange={(e) => ws.setHfRepo(e.target.value)}
                  placeholder="org/dataset"
                  autoFocus
                />
              </label>
              <label>
                Revision
                <input value={ws.hfRevision} onChange={(e) => ws.setHfRevision(e.target.value)} />
              </label>
              <label>
                Access token (optioneel)
                <input
                  type="password"
                  autoComplete="off"
                  value={ws.hfToken}
                  onChange={(e) => ws.setHfToken(e.target.value)}
                />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost"
                  disabled={ws.busy}
                  onClick={() => ws.closeModal()}
                >
                  Annuleren
                </button>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy}
                  onClick={() => void ws.onImportHf()}
                >
                  Importeren
                </button>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
