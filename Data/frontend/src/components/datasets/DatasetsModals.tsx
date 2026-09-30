import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";

type Props = {
  ws: DatasetsWorkspace;
};

export function DatasetsModals({ ws }: Props) {
  if (!ws.modal) return null;

  return (
    <div
      className="lv-v2-ds-modal-backdrop"
      role="presentation"
      onClick={() => !ws.busy && ws.setModal(null)}
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
            <h2 id="lv-v2-ds-modal-title">Create Dataset</h2>
            <p>Register an empty dataset shell in LEVIATHAN.</p>
            <div className="lv-v2-ds-form">
              <label>
                Name
                <input
                  value={ws.createName}
                  onChange={(e) => ws.setCreateName(e.target.value)}
                  placeholder="my-corpus"
                  autoFocus
                />
              </label>
              <label>
                Description
                <textarea value={ws.createDesc} onChange={(e) => ws.setCreateDesc(e.target.value)} />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button type="button" className="lv-v2-button lv-v2-button--ghost" disabled={ws.busy} onClick={() => ws.setModal(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy}
                  onClick={() => void ws.onCreate()}
                >
                  Create
                </button>
              </div>
            </div>
          </>
        ) : null}

        {ws.modal === "import" ? (
          <>
            <h2 id="lv-v2-ds-modal-title">Import Dataset</h2>
            <p>Upload a file or import from a local absolute path (Windows first-class).</p>
            <div className="lv-v2-ds-form">
              <label>
                Upload file
                <input
                  type="file"
                  onChange={(e) => ws.setUploadFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <label>
                Optional name
                <input value={ws.createName} onChange={(e) => ws.setCreateName(e.target.value)} />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy || !ws.uploadFile}
                  onClick={() => void ws.onUpload()}
                >
                  Upload
                </button>
              </div>
              <hr />
              <label>
                Local absolute path
                <input
                  value={ws.localPath}
                  onChange={(e) => ws.setLocalPath(e.target.value)}
                  placeholder="C:\\data\\corpus or /data/corpus"
                />
              </label>
              <label>
                Optional name
                <input value={ws.localName} onChange={(e) => ws.setLocalName(e.target.value)} />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button type="button" className="lv-v2-button lv-v2-button--ghost" disabled={ws.busy} onClick={() => ws.setModal(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy}
                  onClick={() => void ws.onImportLocal()}
                >
                  Import path
                </button>
              </div>
            </div>
          </>
        ) : null}

        {ws.modal === "hf" ? (
          <>
            <h2 id="lv-v2-ds-modal-title">Connect Hugging Face</h2>
            <p>Queue a Hugging Face repository import through DatasetService. Token is never logged.</p>
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
                Access token (optional)
                <input
                  type="password"
                  autoComplete="off"
                  value={ws.hfToken}
                  onChange={(e) => ws.setHfToken(e.target.value)}
                />
              </label>
              <div className="lv-v2-ds-modal__actions">
                <button type="button" className="lv-v2-button lv-v2-button--ghost" disabled={ws.busy} onClick={() => ws.setModal(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--primary"
                  disabled={ws.busy}
                  onClick={() => void ws.onImportHf()}
                >
                  Import
                </button>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
