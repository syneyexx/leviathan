import { useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ModelProvider } from "../../types/api";

export function ProviderManager({
  providers,
  onChanged,
}: {
  providers: ModelProvider[];
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    type: "lm_studio",
    endpoint: "http://127.0.0.1:1234/v1",
    apiKey: "",
  });

  async function test(id: string) {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.testModelProvider(id);
      setMessage(
        result.connected
          ? `Connected to ${result.provider}: ${result.modelsFound} models · ${result.latencyMs != null ? Math.round(result.latencyMs) : "—"} ms`
          : `Failed: ${result.error ?? result.health}`,
      );
      await onChanged();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Test failed");
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    setMessage(null);
    try {
      await api.createModelProvider({
        name: form.name,
        type: form.type,
        endpoint: form.endpoint,
        apiKey: form.apiKey || null,
      });
      setForm({ name: "", type: "lm_studio", endpoint: "http://127.0.0.1:1234/v1", apiKey: "" });
      await onChanged();
      setMessage("Provider created");
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm(`Delete provider ${id}?`)) return;
    setBusy(true);
    try {
      await api.deleteModelProvider(id);
      await onChanged();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="lv-panel lv-card lv-models-providers">
      <div className="lv-section-label">Provider management</div>
      {message ? <p className="lv-muted">{message}</p> : null}
      <table className="lv-models-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Endpoint</th>
            <th>Health</th>
            <th>Auth</th>
            <th>Last OK</th>
            <th>Error</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((p) => (
            <tr key={p.id}>
              <td>{p.name}</td>
              <td>{p.type}</td>
              <td>{p.endpoint}</td>
              <td>
                <span className={`lv-health lv-health--${p.health}`}>{p.health}</span>
              </td>
              <td>{p.apiKeyConfigured ? "configured" : "—"}</td>
              <td>{p.lastSuccessfulAt ?? "—"}</td>
              <td>{p.lastError ?? "—"}</td>
              <td>
                <div className="lv-row-actions">
                  <button className="lv-btn" type="button" disabled={busy} onClick={() => void test(p.id)}>
                    Test connection
                  </button>
                  <button className="lv-btn lv-btn-danger" type="button" disabled={busy} onClick={() => void remove(p.id)}>
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="lv-section-label">Add provider</div>
      <div className="lv-models-provider-form">
        <input
          className="lv-input"
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select
          className="lv-select"
          value={form.type}
          onChange={(e) => setForm({ ...form, type: e.target.value })}
        >
          <option value="lm_studio">LM Studio</option>
          <option value="ollama">Ollama</option>
          <option value="openai_compatible">OpenAI-compatible</option>
          <option value="llama_cpp">llama.cpp (boundary)</option>
        </select>
        <input
          className="lv-input"
          placeholder="Endpoint"
          value={form.endpoint}
          onChange={(e) => setForm({ ...form, endpoint: e.target.value })}
        />
        <input
          className="lv-input"
          placeholder="API key (stored backend-side)"
          type="password"
          value={form.apiKey}
          onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
          autoComplete="off"
        />
        <button className="lv-btn lv-btn-gold" type="button" disabled={busy || !form.name} onClick={() => void create()}>
          Add provider
        </button>
      </div>
      <p className="lv-muted">API keys never appear in GET responses — only configured: true/false.</p>
    </article>
  );
}
