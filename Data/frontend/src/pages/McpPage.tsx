import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { SubMenu } from "../components/SubMenu";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { McpCallRecord, McpServerPublic, McpToolRecord } from "../types/api";

const TABS = ["MCP Servers", "Tools", "Call History", "Policy"] as const;
type Tab = (typeof TABS)[number];

function stateClass(state: string): string {
  const s = state.toLowerCase();
  if (s === "ready" || s === "busy") return "ok";
  if (s === "degraded" || s === "connecting") return "warn";
  if (s === "error" || s === "circuit_open" || s === "unresponsive") return "err";
  return "muted";
}

export function McpPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<Tab>("MCP Servers");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [featureEnabled, setFeatureEnabled] = useState(false);
  const [servers, setServers] = useState<McpServerPublic[]>([]);
  const [tools, setTools] = useState<McpToolRecord[]>([]);
  const [calls, setCalls] = useState<McpCallRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [callCapId, setCallCapId] = useState("");
  const [callArgs, setCallArgs] = useState("{\n  \n}");
  const [callResult, setCallResult] = useState<string | null>(null);
  const [form, setForm] = useState({
    display_name: "",
    transport: "stdio",
    command: "",
    args: "",
    url: "",
    trust: "untrusted",
  });

  const selected = useMemo(
    () => servers.find((s) => s.server_id === selectedId) ?? null,
    [servers, selectedId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [serverRes, toolRes, callRes] = await Promise.all([
        api.mcpServers(),
        api.mcpTools(),
        api.mcpCalls(100),
      ]);
      setFeatureEnabled(serverRes.feature_enabled);
      setServers(serverRes.servers);
      setTools(toolRes.tools);
      setCalls(callRes.calls);
      setSelectedId((prev) => prev ?? serverRes.servers[0]?.server_id ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load MCP state");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, okMsg: string) {
    setBusy(true);
    try {
      await action();
      toast(okMsg);
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "MCP action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="MCP Mode"
      searchPlaceholder="Search MCP servers and tools..."
      layout="wide"
    >
      <SubMenu />
      <main className="lv-main">
        <section className="lv-panel lv-card" style={{ marginBottom: "1rem" }}>
          <div className="lv-card-head">
            <div className="lv-section-label">Tools · MCP Bridge</div>
            <span className="lv-online-count">
              {featureEnabled ? `${servers.length} registered` : "Feature disabled"}
            </span>
          </div>
          <p className="lv-muted" style={{ marginTop: 0 }}>
            One universal MCP bridge. Many servers. Invokes go through ExecutionGateway.
          </p>
          <div className="lv-tabs" role="tablist" style={{ marginTop: 12 }}>
            {TABS.map((item) => (
              <button
                key={item}
                type="button"
                className={`lv-tab${tab === item ? " is-active" : ""}`}
                onClick={() => setTab(item)}
              >
                {item}
              </button>
            ))}
          </div>
          {error ? <p className="lv-muted">{error}</p> : null}
          {loading ? <p className="lv-muted">Loading…</p> : null}
        </section>

        {!featureEnabled && !loading ? (
          <section className="lv-panel lv-card">
            <p>
              MCP is off. Set <code>LEVIATHAN_FEATURE_MCP=true</code> (and child transport flags)
              then restart the backend. Non-MCP tools remain available.
            </p>
          </section>
        ) : null}

        {featureEnabled && tab === "MCP Servers" ? (
          <div className="lv-tools-split">
            <section className="lv-panel lv-card">
              <div className="lv-card-head">
                <strong>Servers</strong>
                <button type="button" className="lv-btn" disabled={busy} onClick={() => void load()}>
                  Refresh
                </button>
              </div>
              <ul className="lv-list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {servers.map((server) => (
                  <li key={server.server_id}>
                    <button
                      type="button"
                      className="lv-btn"
                      style={{
                        width: "100%",
                        textAlign: "left",
                        marginBottom: 8,
                        opacity: selectedId === server.server_id ? 1 : 0.85,
                      }}
                      onClick={() => setSelectedId(server.server_id)}
                    >
                      <div>
                        <strong>{server.display_name}</strong>
                        <span className={`lv-pill ${stateClass(server.runtime?.state ?? "")}`}>
                          {server.runtime?.state ?? "UNKNOWN"}
                        </span>
                      </div>
                      <div className="lv-muted">
                        {server.transport} · {server.source_kind}:{server.source_key} · tools{" "}
                        {server.runtime?.tool_count ?? 0}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
              <hr />
              <h4>Register server</h4>
              <label>
                Name
                <input
                  value={form.display_name}
                  onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                />
              </label>
              <label>
                Transport
                <select
                  value={form.transport}
                  onChange={(e) => setForm((f) => ({ ...f, transport: e.target.value }))}
                >
                  <option value="stdio">stdio</option>
                  <option value="http">http</option>
                </select>
              </label>
              {form.transport === "stdio" ? (
                <>
                  <label>
                    Command
                    <input
                      value={form.command}
                      onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))}
                    />
                  </label>
                  <label>
                    Args (comma-separated)
                    <input
                      value={form.args}
                      onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))}
                    />
                  </label>
                </>
              ) : (
                <label>
                  URL
                  <input
                    value={form.url}
                    onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  />
                </label>
              )}
              <button
                type="button"
                className="lv-btn lv-btn--primary"
                disabled={busy || !form.display_name}
                onClick={() =>
                  void run(
                    () =>
                      api.mcpCreateServer({
                        display_name: form.display_name,
                        transport: form.transport,
                        command: form.command || null,
                        args: form.args
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                        url: form.url || null,
                        trust: form.trust,
                        enabled: false,
                      }),
                    "Server registered",
                  )
                }
              >
                Register
              </button>
            </section>

            <section className="lv-panel lv-card">
              {selected ? (
                <>
                  <div className="lv-card-head">
                    <strong>{selected.display_name}</strong>
                    <span className="lv-muted">{selected.server_id}</span>
                  </div>
                  <dl className="lv-kv">
                    <div>
                      <dt>Enabled</dt>
                      <dd>{selected.enabled ? "yes" : "no"}</dd>
                    </div>
                    <div>
                      <dt>State</dt>
                      <dd>{selected.runtime?.state ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Requested isolation</dt>
                      <dd>{selected.requested_isolation}</dd>
                    </div>
                    <div>
                      <dt>Effective isolation</dt>
                      <dd>{selected.runtime?.effective_isolation ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Trust</dt>
                      <dd>{selected.trust}</dd>
                    </div>
                    <div>
                      <dt>Last error</dt>
                      <dd>{selected.runtime?.last_error_message ?? "—"}</dd>
                    </div>
                  </dl>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    <button
                      type="button"
                      className="lv-btn"
                      disabled={busy}
                      onClick={() => void run(() => api.mcpEnableServer(selected.server_id), "Enabled")}
                    >
                      Enable
                    </button>
                    <button
                      type="button"
                      className="lv-btn"
                      disabled={busy}
                      onClick={() =>
                        void run(() => api.mcpDisableServer(selected.server_id), "Disabled")
                      }
                    >
                      Disable
                    </button>
                    <button
                      type="button"
                      className="lv-btn"
                      disabled={busy}
                      onClick={() =>
                        void run(() => api.mcpConnectServer(selected.server_id), "Connect requested")
                      }
                    >
                      Connect
                    </button>
                    <button
                      type="button"
                      className="lv-btn"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => api.mcpDisconnectServer(selected.server_id),
                          "Disconnected",
                        )
                      }
                    >
                      Disconnect
                    </button>
                    <button
                      type="button"
                      className="lv-btn"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => api.mcpRefreshTools(selected.server_id),
                          "Tools refreshed",
                        )
                      }
                    >
                      Refresh tools
                    </button>
                    <button
                      type="button"
                      className="lv-btn"
                      disabled={busy}
                      onClick={() =>
                        void run(() => api.mcpDeleteServer(selected.server_id), "Removed")
                      }
                    >
                      Remove
                    </button>
                  </div>
                </>
              ) : (
                <p className="lv-muted">Select a server</p>
              )}
            </section>
          </div>
        ) : null}

        {featureEnabled && tab === "Tools" ? (
          <section className="lv-panel lv-card">
            <div className="lv-card-head">
              <strong>Discovered tools</strong>
              <span className="lv-muted">{tools.length}</span>
            </div>
            <table className="lv-table">
              <thead>
                <tr>
                  <th>Capability</th>
                  <th>External</th>
                  <th>Server</th>
                  <th>Availability</th>
                  <th>Effects</th>
                  <th>Schema</th>
                </tr>
              </thead>
              <tbody>
                {tools.map((tool) => (
                  <tr key={tool.capability_id}>
                    <td>
                      <button
                        type="button"
                        className="lv-btn"
                        onClick={() => {
                          setCallCapId(tool.capability_id);
                          setTab("Call History");
                        }}
                      >
                        {tool.capability_id}
                      </button>
                    </td>
                    <td>{tool.external_name}</td>
                    <td>{tool.server_id}</td>
                    <td>{tool.availability}</td>
                    <td>{tool.semantic_effects.join(", ")}</td>
                    <td>
                      <code>{tool.schema_hash.slice(0, 10)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h4>Manual invoke (via ExecutionGateway)</h4>
            <label>
              Capability ID
              <input value={callCapId} onChange={(e) => setCallCapId(e.target.value)} />
            </label>
            <label>
              Arguments JSON
              <textarea
                rows={6}
                value={callArgs}
                onChange={(e) => setCallArgs(e.target.value)}
                style={{ width: "100%", fontFamily: "monospace" }}
              />
            </label>
            <button
              type="button"
              className="lv-btn lv-btn--primary"
              disabled={busy || !callCapId}
              onClick={() =>
                void run(async () => {
                  let args: Record<string, unknown> = {};
                  try {
                    args = JSON.parse(callArgs || "{}") as Record<string, unknown>;
                  } catch {
                    throw new ApiError(400, "Invalid JSON arguments");
                  }
                  const res = await api.mcpCall({
                    capability_id: callCapId,
                    arguments: args,
                  });
                  setCallResult(JSON.stringify(res, null, 2));
                }, "Call completed")
              }
            >
              Execute via gateway
            </button>
            {callResult ? (
              <pre style={{ overflow: "auto", maxHeight: 320 }}>{callResult}</pre>
            ) : null}
          </section>
        ) : null}

        {featureEnabled && tab === "Call History" ? (
          <section className="lv-panel lv-card">
            <div className="lv-card-head">
              <strong>Call history</strong>
              <button type="button" className="lv-btn" onClick={() => void load()}>
                Refresh
              </button>
            </div>
            <table className="lv-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Capability</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => (
                  <tr key={call.call_id}>
                    <td>{call.started_at}</td>
                    <td>{call.capability_id}</td>
                    <td>{call.status}</td>
                    <td>{call.duration_ms != null ? `${Math.round(call.duration_ms)}ms` : "—"}</td>
                    <td>{call.error_message ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}

        {tab === "Policy" ? (
          <section className="lv-panel lv-card">
            <h3>Authority boundaries</h3>
            <ul>
              <li>MCP is a capability provider — not a second execution engine.</li>
              <li>Approvals remain the only authorization authority.</li>
              <li>
                Client fields like <code>approved_by_user</code> are audit metadata only.
              </li>
              <li>Requested isolation ≠ effective isolation; silent downgrade is refused.</li>
              <li>Secret refs are never returned as plaintext values.</li>
              <li>MCP outputs are observations, not evidence.</li>
            </ul>
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
