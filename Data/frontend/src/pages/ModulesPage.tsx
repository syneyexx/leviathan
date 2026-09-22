import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { ModuleSnapshot } from "../types/api";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

type Managed = NonNullable<ModuleSnapshot["modules"]>[number];

export function ModulesPage() {
  const toast = useAppToast();
  const [snap, setSnap] = useState<ModuleSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [operation, setOperation] = useState("health");
  const [argsJson, setArgsJson] = useState("{}");
  const [lastResult, setLastResult] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listModules();
      setSnap(data);
      const first = data.modules?.[0]?.manifest?.module_id;
      if (first && !selectedId) setSelectedId(first);
    } catch (err) {
      setError(errMsg(err, "Failed to load modules"));
      setSnap(null);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  const modules = snap?.modules ?? [];
  const selected: Managed | undefined = modules.find((m) => m.manifest?.module_id === selectedId);

  async function onDiscover() {
    setBusy(true);
    try {
      const res = await api.discoverModules();
      setSnap(res.snapshot);
      toast(`Discovered ${(res.discovered ?? []).length} manifests`);
    } catch (err) {
      toast(errMsg(err, "Discover failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onExecute() {
    if (!selectedId) return;
    let args: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(argsJson || "{}") as unknown;
      if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
        toast("Arguments must be a JSON object");
        return;
      }
      args = parsed as Record<string, unknown>;
    } catch {
      toast("Invalid JSON arguments");
      return;
    }
    setBusy(true);
    try {
      const res = await api.executeModule(selectedId, operation.trim() || "health", args);
      setLastResult(res.result);
      toast("Execute completed");
      await load();
    } catch (err) {
      toast(errMsg(err, "Execute failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Modules Mode"
      searchPlaceholder="Search modules…"
      systemItems={["LLM", "Neural", "Memory", "Runtime"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main" style={{ padding: "1.25rem", display: "grid", gap: "1rem" }}>
        <header className="lv-pr-console-head" style={{ marginBottom: 0 }}>
          <div>
            <h1 className="lv-pr-console-title" style={{ margin: 0 }}>
              <span className="lv-pr-console-title-muted">Plugin &amp; Runtime</span>
              <span className="lv-pr-console-title-sep">›</span>
              <span>Modules</span>
            </h1>
            <p className="lv-pr-console-sub">
              ModuleManager control plane — discoverable ≠ authorized. Lifecycle via backend authority.
            </p>
          </div>
          <button type="button" className="lv-pr-console-tool is-gold" disabled={busy} onClick={() => void onDiscover()}>
            Discover
          </button>
        </header>

        {error ? <div role="alert">{error}</div> : null}
        {snap?.enabled === false ? <div role="status">Module manager feature disabled</div> : null}

        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "1rem" }}>
          <section>
            <h2>Modules ({modules.length})</h2>
            {loading ? <p>Loading…</p> : null}
            {!loading && modules.length === 0 ? <p>No modules discovered.</p> : null}
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Isolation</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {modules.map((m) => {
                    const id = m.manifest?.module_id ?? "unknown";
                    return (
                      <tr
                        key={id}
                        onClick={() => setSelectedId(id)}
                        style={{ cursor: "pointer", outline: selectedId === id ? "1px solid #c9a227" : undefined }}
                      >
                        <td>{id}</td>
                        <td>{m.manifest?.name ?? "—"}</td>
                        <td>{m.manifest?.version ?? "—"}</td>
                        <td>{m.status ?? "—"}</td>
                        <td>{m.manifest?.isolation ?? "—"}</td>
                        <td>{m.error ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {snap?.telemetry ? (
              <pre style={{ fontSize: "0.8rem", opacity: 0.8 }}>{JSON.stringify(snap.telemetry, null, 2)}</pre>
            ) : null}
          </section>

          <section>
            <h2>Execute</h2>
            {!selected ? (
              <p>Select a module</p>
            ) : (
              <div style={{ display: "grid", gap: "0.6rem" }}>
                <div>
                  <strong>{selected.manifest?.name}</strong> · {selected.status}
                </div>
                <div style={{ fontSize: "0.85rem", opacity: 0.75 }}>
                  capabilities: {(selected.manifest?.capabilities ?? []).length}
                  {selected.manifest?.source_path ? ` · ${selected.manifest.source_path}` : ""}
                </div>
                <label>
                  Operation
                  <input value={operation} onChange={(e) => setOperation(e.target.value)} style={{ width: "100%" }} />
                </label>
                <label>
                  Arguments (JSON)
                  <textarea value={argsJson} onChange={(e) => setArgsJson(e.target.value)} rows={6} style={{ width: "100%" }} />
                </label>
                <button
                  type="button"
                  disabled={busy || !["READY", "INITIALIZED"].includes(String(selected.status))}
                  onClick={() => void onExecute()}
                  title={
                    !["READY", "INITIALIZED"].includes(String(selected.status))
                      ? `Module not ready (${selected.status})`
                      : "Execute via ModuleManager"
                  }
                >
                  Execute
                </button>
                {lastResult != null ? (
                  <pre style={{ maxHeight: 240, overflow: "auto", background: "rgba(0,0,0,0.25)", padding: "0.75rem" }}>
                    {JSON.stringify(lastResult, null, 2)}
                  </pre>
                ) : null}
              </div>
            )}
          </section>
        </div>
      </main>
    </AppShell>
  );
}
