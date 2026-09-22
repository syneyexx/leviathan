import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type { ModuleSnapshot } from "../../types/api";
import { Panel, Pill, type PillTone } from "./shared";

type ManagedModuleRow = NonNullable<ModuleSnapshot["modules"]>[number];

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
}

function moduleId(row: ManagedModuleRow): string {
  return row.manifest?.module_id ?? "unknown";
}

function moduleName(row: ManagedModuleRow): string {
  return row.manifest?.name?.trim() || moduleId(row);
}

function statusTone(status?: string): PillTone {
  const s = (status ?? "").toUpperCase();
  if (s === "READY") return "ok";
  if (s === "ERROR" || s === "SHUTDOWN") return "err";
  if (s === "EXECUTING" || s === "LOADED" || s === "INITIALIZED") return "gold";
  if (s === "DISCOVERED") return "cyan";
  return "muted";
}

function isReady(row: ManagedModuleRow): boolean {
  return (row.status ?? "").toUpperCase() === "READY";
}

function tryParseArgs(raw: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: true, value: {} };
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "Arguments must be a JSON object" };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: "Invalid JSON arguments" };
  }
}

export function ModulesPage() {
  const toast = useAppToast();
  const [snapshot, setSnapshot] = useState<ModuleSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [operation, setOperation] = useState("health");
  const [argsJson, setArgsJson] = useState("{}");
  const [executing, setExecuting] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const applySnapshot = useCallback((next: ModuleSnapshot) => {
    setSnapshot(next);
    const ids = (next.modules ?? []).map(moduleId);
    setSelectedId((prev) => {
      if (prev && ids.includes(prev)) return prev;
      return ids[0] ?? null;
    });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const snap = await api.listModules();
      applySnapshot(snap);
    } catch (err) {
      setLoadError(errorMessage(err));
      setSnapshot(null);
    } finally {
      setLoading(false);
    }
  }, [applySnapshot]);

  useEffect(() => {
    void load();
  }, [load]);

  const modules = snapshot?.modules ?? [];

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return modules;
    return modules.filter((row) => {
      const hay = `${moduleId(row)} ${moduleName(row)} ${row.status ?? ""} ${row.error ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [modules, query]);

  const selected = useMemo(
    () => modules.find((row) => moduleId(row) === selectedId) ?? rows[0] ?? null,
    [modules, rows, selectedId],
  );

  const readyCount = useMemo(() => modules.filter(isReady).length, [modules]);
  const errorCount = useMemo(
    () => modules.filter((row) => (row.status ?? "").toUpperCase() === "ERROR").length,
    [modules],
  );

  async function onDiscover() {
    setDiscovering(true);
    setLoadError(null);
    try {
      const res = await api.discoverModules();
      applySnapshot(res.snapshot);
      const n = Array.isArray(res.discovered) ? res.discovered.length : 0;
      toast(`Discovered ${n} module manifest(s)`);
    } catch (err) {
      const msg = errorMessage(err);
      setLoadError(msg);
      toast(msg);
    } finally {
      setDiscovering(false);
    }
  }

  async function onExecute() {
    if (!selected) return;
    if (!isReady(selected)) {
      toast(`Module not READY (status: ${selected.status ?? "unknown"})`);
      return;
    }
    const op = operation.trim();
    if (!op) {
      toast("Operation is required");
      return;
    }
    const parsed = tryParseArgs(argsJson);
    if (!parsed.ok) {
      toast(parsed.error);
      return;
    }
    setExecuting(true);
    setLastResult(null);
    try {
      const res = await api.executeModule(moduleId(selected), op, parsed.value);
      setLastResult(JSON.stringify(res.result ?? res, null, 2));
      // Refresh snapshot so last_result / status reflect backend state.
      const snap = await api.listModules().catch(() => null);
      if (snap) applySnapshot(snap);
    } catch (err) {
      const msg = errorMessage(err);
      setLastResult(msg);
      toast(msg);
    } finally {
      setExecuting(false);
    }
  }

  const managerEnabled = snapshot?.enabled !== false;

  return (
    <AppShell
      modeLabel="Plugin Mode"
      searchPlaceholder="Zoek modules, manifests..."
      systemItems={["LLM", "NEURAL", "MEMORY", "MODULES"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main">
        <section className="lv-pr-hero is-image-only" aria-label="Modules">
          <div className="lv-pr-hero-media">
            <div
              className="lv-pr-hero-fallback"
              style={{
                display: "flex",
                flexDirection: "column",
                justifyContent: "flex-end",
                minHeight: 160,
                padding: "28px 32px",
                background:
                  "linear-gradient(135deg, rgba(18,22,30,0.95) 0%, rgba(42,36,22,0.9) 55%, rgba(20,28,36,0.95) 100%)",
                borderBottom: "1px solid rgba(212,175,55,0.25)",
              }}
            >
              <h1 className="lv-pr-hero-title" style={{ margin: 0, fontSize: "1.75rem", letterSpacing: "0.08em" }}>
                MODULES
              </h1>
              <p className="lv-pr-hero-kicker" style={{ margin: "8px 0 0", opacity: 0.85 }}>
                ModuleManager control plane — discover, status, execute.
              </p>
            </div>
          </div>
        </section>

        <section className="lv-pr-kpi-row" aria-label="Module KPIs">
          <article className="lv-pr-kpi">
            <div className="lv-pr-kpi-label">Manager</div>
            <div className="lv-pr-kpi-value">{managerEnabled ? "ON" : "OFF"}</div>
            <div className="lv-pr-kpi-foot">
              <span className="lv-pr-kpi-sub">feature flag</span>
            </div>
          </article>
          <article className="lv-pr-kpi">
            <div className="lv-pr-kpi-label">Modules</div>
            <div className="lv-pr-kpi-value">{modules.length}</div>
            <div className="lv-pr-kpi-foot">
              <span className="lv-pr-kpi-sub">from public_snapshot</span>
            </div>
          </article>
          <article className="lv-pr-kpi">
            <div className="lv-pr-kpi-label">Ready</div>
            <div className="lv-pr-kpi-value">{readyCount}</div>
            <div className="lv-pr-kpi-foot">
              <span className="lv-pr-kpi-sub">executable</span>
            </div>
          </article>
          <article className={`lv-pr-kpi${errorCount ? " is-warn" : ""}`}>
            <div className="lv-pr-kpi-label">Errors</div>
            <div className="lv-pr-kpi-value">{errorCount}</div>
            <div className="lv-pr-kpi-foot">
              <span className="lv-pr-kpi-sub">status ERROR</span>
            </div>
          </article>
        </section>

        <section className="lv-pr-perf-mid" aria-label="Modules control plane">
          <Panel
            title="Managed modules"
            className="lv-pr-perf-tools"
            action={
              <div className="lv-pr-mcp-panel-actions">
                <input
                  className="lv-pr-mcp-input"
                  style={{ minWidth: 160 }}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filter modules…"
                  aria-label="Filter modules"
                />
                <button
                  type="button"
                  className="lv-pr-mcp-btn"
                  onClick={() => void load()}
                  disabled={loading || discovering}
                >
                  {loading ? "Loading…" : "Refresh"}
                </button>
                <button
                  type="button"
                  className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                  onClick={() => void onDiscover()}
                  disabled={discovering || !managerEnabled}
                  title={managerEnabled ? "POST /api/modules/discover" : "Module manager feature flag OFF"}
                >
                  {discovering ? "Discovering…" : "Discover"}
                </button>
              </div>
            }
          >
            {loadError ? (
              <p className="lv-muted" role="alert">
                {loadError}
              </p>
            ) : null}
            {!managerEnabled ? (
              <p className="lv-muted" role="status">
                Module manager feature flag is OFF. Snapshot returns an empty modules list.
              </p>
            ) : null}
            <div className="lv-pr-table-wrap">
              <table className="lv-pr-table">
                <thead>
                  <tr>
                    <th>Module</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Isolation</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && modules.length === 0 ? (
                    <tr>
                      <td colSpan={5}>Loading module snapshot…</td>
                    </tr>
                  ) : null}
                  {!loading && rows.length === 0 ? (
                    <tr>
                      <td colSpan={5}>
                        No modules in snapshot. Use Discover to scan discovery roots.
                      </td>
                    </tr>
                  ) : null}
                  {rows.map((row) => {
                    const id = moduleId(row);
                    return (
                      <tr
                        key={id}
                        className={selected && moduleId(selected) === id ? "is-selected" : undefined}
                        onClick={() => {
                          setSelectedId(id);
                          setLastResult(null);
                        }}
                        style={{ cursor: "pointer" }}
                      >
                        <td>
                          <strong>{moduleName(row)}</strong>
                          <div className="lv-muted" style={{ fontSize: "0.85em" }}>
                            {id}
                          </div>
                        </td>
                        <td>{row.manifest?.version ?? "—"}</td>
                        <td>
                          <Pill tone={statusTone(row.status)}>{row.status ?? "—"}</Pill>
                        </td>
                        <td>{row.manifest?.isolation ?? "—"}</td>
                        <td>{row.error ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Module detail" className="lv-pr-perf-detail">
            {selected ? (
              <>
                <div style={{ marginBottom: 12 }}>
                  <h2 style={{ margin: "0 0 6px", fontSize: "1.15rem" }}>{moduleName(selected)}</h2>
                  <Pill tone={statusTone(selected.status)}>{selected.status ?? "unknown"}</Pill>
                  <p className="lv-muted" style={{ marginTop: 8 }}>
                    {moduleId(selected)}
                    {selected.manifest?.source_path ? ` · ${selected.manifest.source_path}` : ""}
                  </p>
                </div>

                {selected.error ? (
                  <p className="lv-muted" role="status">
                    Error: {selected.error}
                  </p>
                ) : null}

                {selected.health ? (
                  <>
                    <div className="lv-pr-panel-title" style={{ marginTop: 12 }}>
                      Health
                    </div>
                    <pre
                      className="lv-pr-console-log"
                      style={{ whiteSpace: "pre-wrap", maxHeight: 120, overflow: "auto", fontSize: 12 }}
                    >
                      {JSON.stringify(selected.health, null, 2)}
                    </pre>
                  </>
                ) : null}

                <div className="lv-pr-panel-title" style={{ marginTop: 16 }}>
                  Execute
                </div>
                <p className="lv-muted" style={{ marginBottom: 8 }}>
                  HTTP surface is discover + execute only. Start/Stop are not exposed by ModuleManager.
                  Execute is enabled for READY modules.
                </p>
                <label className="lv-form-field" style={{ display: "block" }}>
                  <span>Operation</span>
                  <input
                    className="lv-pr-mcp-input"
                    value={operation}
                    onChange={(e) => setOperation(e.target.value)}
                    disabled={!isReady(selected) || executing}
                    placeholder="e.g. health"
                    style={{ width: "100%", marginTop: 4 }}
                  />
                </label>
                <label className="lv-form-field" style={{ marginTop: 8, display: "block" }}>
                  <span>Arguments (JSON)</span>
                  <textarea
                    className="lv-pr-mcp-input"
                    rows={5}
                    value={argsJson}
                    onChange={(e) => setArgsJson(e.target.value)}
                    spellCheck={false}
                    disabled={!isReady(selected) || executing}
                    style={{ width: "100%", marginTop: 4 }}
                  />
                </label>
                <button
                  type="button"
                  className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                  style={{ marginTop: 10 }}
                  disabled={!isReady(selected) || executing || !managerEnabled}
                  title={
                    isReady(selected)
                      ? "POST /api/modules/{id}/execute"
                      : `Requires READY (current: ${selected.status ?? "unknown"})`
                  }
                  onClick={() => void onExecute()}
                >
                  {executing ? "Executing…" : "Execute"}
                </button>

                {lastResult ? (
                  <>
                    <div className="lv-pr-panel-title" style={{ marginTop: 16 }}>
                      Last execute result
                    </div>
                    <pre
                      className="lv-pr-console-log"
                      style={{ whiteSpace: "pre-wrap", maxHeight: 220, overflow: "auto", fontSize: 12 }}
                    >
                      {lastResult}
                    </pre>
                  </>
                ) : null}

                {selected.last_result ? (
                  <>
                    <div className="lv-pr-panel-title" style={{ marginTop: 16 }}>
                      Snapshot last_result
                    </div>
                    <pre
                      className="lv-pr-console-log"
                      style={{ whiteSpace: "pre-wrap", maxHeight: 160, overflow: "auto", fontSize: 12 }}
                    >
                      {JSON.stringify(selected.last_result, null, 2)}
                    </pre>
                  </>
                ) : null}
              </>
            ) : (
              <p className="lv-muted">Select a module to inspect status and execute operations.</p>
            )}
          </Panel>
        </section>

        {snapshot?.discovery_roots?.length ? (
          <Panel title="Discovery roots">
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {snapshot.discovery_roots.map((root) => (
                <li key={root}>
                  <code>{root}</code>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {snapshot?.telemetry ? (
          <Panel title="Telemetry">
            <div className="lv-pr-kpi-row" style={{ margin: 0 }}>
              {Object.entries(snapshot.telemetry).map(([key, value]) => (
                <article key={key} className="lv-pr-kpi" style={{ minWidth: 0 }}>
                  <div className="lv-pr-kpi-label">{key}</div>
                  <div className="lv-pr-kpi-value" style={{ fontSize: "1.1rem" }}>
                    {value}
                  </div>
                </article>
              ))}
            </div>
          </Panel>
        ) : null}
      </main>
    </AppShell>
  );
}
