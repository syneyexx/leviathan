import { useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ModelProvider } from "../../types/api";

export function ModelImportDialog({
  providers,
  onClose,
  onDone,
}: {
  providers: ModelProvider[];
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [source, setSource] = useState<"local_file" | "huggingface" | "ollama">("local_file");
  const [path, setPath] = useState("");
  const [repo, setRepo] = useState("");
  const [revision, setRevision] = useState("main");
  const [filename, setFilename] = useState("");
  const [providerId, setProviderId] = useState(
    providers.find((p) => p.type === "ollama")?.id ?? providers[0]?.id ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (source === "local_file") {
        await api.importModel({ source: "local_file", path });
      } else if (source === "huggingface") {
        await api.downloadModel({
          source: "huggingface",
          repositoryId: repo,
          revision,
          filename: filename || null,
        });
      } else {
        await api.downloadModel({
          source: "ollama",
          repositoryId: repo,
          revision: revision || null,
          providerId,
        });
      }
      await onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lv-models-modal" role="dialog" aria-modal="true" aria-label="Import or download model">
      <div className="lv-models-modal-card">
        <div className="lv-card-head">
          <div className="lv-section-label">Import / Download</div>
          <button className="lv-link" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        {error ? <p className="lv-muted">{error}</p> : null}
        <label className="lv-models-field">
          Source
          <select
            className="lv-select"
            value={source}
            onChange={(e) => setSource(e.target.value as typeof source)}
          >
            <option value="local_file">Local File</option>
            <option value="huggingface">Hugging Face repository</option>
            <option value="ollama">Ollama pull</option>
          </select>
        </label>
        {source === "local_file" ? (
          <label className="lv-models-field">
            Absolute server path (.gguf / .safetensors)
            <input className="lv-input" value={path} onChange={(e) => setPath(e.target.value)} />
          </label>
        ) : (
          <>
            <label className="lv-models-field">
              Repository id
              <input className="lv-input" value={repo} onChange={(e) => setRepo(e.target.value)} />
            </label>
            <label className="lv-models-field">
              Revision
              <input className="lv-input" value={revision} onChange={(e) => setRevision(e.target.value)} />
            </label>
            {source === "huggingface" ? (
              <label className="lv-models-field">
                Filename (optional — first gguf/safetensors if empty)
                <input className="lv-input" value={filename} onChange={(e) => setFilename(e.target.value)} />
              </label>
            ) : (
              <label className="lv-models-field">
                Ollama provider
                <select
                  className="lv-select"
                  value={providerId}
                  onChange={(e) => setProviderId(e.target.value)}
                >
                  {providers
                    .filter((p) => p.type === "ollama")
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </select>
              </label>
            )}
          </>
        )}
        <div className="lv-row-actions">
          <button className="lv-btn lv-btn-gold" type="button" disabled={busy} onClick={() => void submit()}>
            Start
          </button>
          <button className="lv-btn" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
        <p className="lv-muted">
          Hugging Face downloads require outbound network enabled. Paths are validated server-side.
        </p>
      </div>
    </div>
  );
}
