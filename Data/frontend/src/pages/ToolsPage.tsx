import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { CapabilityListItem, McpToolRecord } from "../types/api";

type ProviderFilter = "all" | "builtin" | "mcp" | "module" | "function" | "other";

const PROVIDER_TABS: Array<{ id: ProviderFilter; label: string }> = [
  { id: "all", label: "All Tools" },
  { id: "builtin", label: "Built-in" },
  { id: "function", label: "Functions" },
  { id: "mcp", label: "MCP" },
  { id: "module", label: "Module" },
  { id: "other", label: "Other" },
];

function normalizeProvider(kind?: string | null): string {
  return (kind ?? "unknown").trim().toLowerCase();
}

function providerBucket(kind?: string | null): Exclude<ProviderFilter, "all"> {
  const k = normalizeProvider(kind);
  if (k === "builtin" || k === "native" || k === "internal") return "builtin";
  if (k === "function") return "function";
  if (k === "mcp") return "mcp";
  if (k === "module") return "module";
  return "other";
}

function unavailableReason(cap: CapabilityListItem): string | null {
  if (cap.available !== false && cap.enabled !== false) return null;
  const reason =
    (typeof cap.unavailable_reason === "string" && cap.unavailable_reason.trim()) ||
    (typeof cap.availability_reason === "string" && cap.availability_reason.trim()) ||
    null;
  if (reason) return reason;
  if (cap.available === false) return "Unavailable";
  if (cap.enabled === false) return "Disabled";
  return null;
}

function isInvokable(cap: CapabilityListItem): boolean {
  return cap.available !== false && cap.enabled !== false;
}

function statusLabel(cap: CapabilityListItem): string {
  if (cap.available === false) return "Unavailable";
  if (cap.enabled === false) return "Disabled";
  return "Available";
}

function statusDot(cap: CapabilityListItem): string {
  if (cap.available === false) return "failed";
  if (cap.enabled === false) return "running";
  return "ready";
}

function displayName(cap: CapabilityListItem): string {
  return (cap.name && String(cap.name).trim()) || cap.id;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
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

export function ToolsPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<ProviderFilter>("all");
  const [query, setQuery] = useState("");
  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [mcpTools, setMcpTools] = useState<McpToolRecord[]>([]);
  const [functionCount, setFunctionCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [argsJson, setArgsJson] = useState("{}");
  const [invoking, setInvoking] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [capsRes, mcpRes, fnRes] = await Promise.all([
        api.listCapabilities({ limit: 500 }),
        api.mcpTools().catch(() => null),
        api.listFunctions().catch(() => null),
      ]);
      setCapabilities(capsRes.capabilities ?? []);
      setMcpTools(mcpRes?.tools ?? []);
      setFunctionCount(Array.isArray(fnRes?.functions) ? fnRes.functions.length : null);
      setSelectedId((prev) => {
        const ids = (capsRes.capabilities ?? []).map((c) => c.id);
        if (prev && ids.includes(prev)) return prev;
        return ids[0] ?? null;
      });
    } catch (err) {
      setLoadError(errorMessage(err));
      setCapabilities([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return capabilities.filter((cap) => {
      if (tab !== "all" && providerBucket(cap.provider_kind) !== tab) return false;
      if (!q) return true;
      const hay = `${cap.id} ${cap.name ?? ""} ${cap.description ?? ""} ${cap.provider_kind ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [capabilities, query, tab]);

  const selected = useMemo(
    () => capabilities.find((c) => c.id === selectedId) ?? rows[0] ?? null,
    [capabilities, rows, selectedId],
  );

  const selectedReason = selected ? unavailableReason(selected) : null;
  const selectedInvokable = selected ? isInvokable(selected) : false;

  const counts = useMemo(() => {
    const base: Record<ProviderFilter, number> = {
      all: capabilities.length,
      builtin: 0,
      function: 0,
      mcp: 0,
      module: 0,
      other: 0,
    };
    for (const cap of capabilities) {
      base[providerBucket(cap.provider_kind)] += 1;
    }
    return base;
  }, [capabilities]);

  const availableCount = useMemo(
    () => capabilities.filter((c) => isInvokable(c)).length,
    [capabilities],
  );

  async function invokeSelected() {
    if (!selected) return;
    if (!selectedInvokable) {
      toast(selectedReason ?? "Capability unavailable");
      return;
    }
    const parsed = tryParseArgs(argsJson);
    if (!parsed.ok) {
      toast(parsed.error);
      return;
    }
    setInvoking(true);
    setLastResult(null);
    try {
      const res = await api.executeCapability(selected.id, parsed.value);
      setLastResult(JSON.stringify(res.result ?? res, null, 2));
    } catch (err) {
      setLastResult(errorMessage(err));
      toast(errorMessage(err));
    } finally {
      setInvoking(false);
    }
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Tools Mode"
      searchPlaceholder="Search capabilities, MCP tools, functions..."
      systemItems={["LLM", "Neural", "Memory", "Tools"]}
      layout="wide"
      pageClass="lv-app--tools"
    >
      <main className="lv-main lv-tools-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src="/assets/hero-tools.jpg" alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <h1 className="lv-hero-title">Tools</h1>
            <p className="lv-hero-kicker" style={{ marginTop: 6 }}>
              Capability catalog. Provenance. Live invoke.
            </p>
            <p className="lv-page-quote">“Tools turn thought into action.” — LEVIATHAN</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Discover</span>
            <span>Provenance</span>
            <span>Invoke</span>
            <span>Observe</span>
          </div>
        </section>

        <div className="lv-tools-toolbar">
          <div className="lv-tabs" role="tablist">
            {PROVIDER_TABS.map((item) => (
              <button
                key={item.id}
                className={`lv-tab${tab === item.id ? " is-active" : ""}`}
                type="button"
                onClick={() => setTab(item.id)}
              >
                {item.label}
                <span className="lv-muted" style={{ marginLeft: 6 }}>
                  {counts[item.id]}
                </span>
              </button>
            ))}
          </div>
          <div className="lv-toolbar" style={{ marginLeft: "auto" }}>
            <input
              className="lv-input"
              style={{ minWidth: 180 }}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search capabilities..."
              aria-label="Search capabilities"
            />
            <button className="lv-btn" type="button" onClick={() => void load()} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>

        {loadError ? (
          <p className="lv-muted" role="alert" style={{ padding: "0 4px 12px" }}>
            Failed to load capabilities: {loadError}
          </p>
        ) : null}

        <div className="lv-tools-split">
          <div className="lv-models-table-wrap">
            <table className="lv-models-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Provider</th>
                  <th>Availability</th>
                  <th>Description</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {loading && capabilities.length === 0 ? (
                  <tr>
                    <td colSpan={5}>Loading capabilities…</td>
                  </tr>
                ) : null}
                {!loading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={5}>No capabilities match this filter.</td>
                  </tr>
                ) : null}
                {rows.map((cap) => {
                  const reason = unavailableReason(cap);
                  return (
                    <tr
                      key={cap.id}
                      className={selected?.id === cap.id ? "is-selected" : undefined}
                      onClick={() => {
                        setSelectedId(cap.id);
                        setLastResult(null);
                      }}
                    >
                      <td>
                        <div className="lv-tool-name-cell">
                          <strong>{displayName(cap)}</strong>
                          <small className="lv-muted">{cap.id}</small>
                        </div>
                      </td>
                      <td>
                        <span className="lv-tag gold">{normalizeProvider(cap.provider_kind)}</span>
                      </td>
                      <td>
                        <span className="lv-model-status">
                          <span className={`lv-status-dot ${statusDot(cap)}`} />
                          {statusLabel(cap)}
                        </span>
                      </td>
                      <td>{cap.description || "—"}</td>
                      <td>{reason ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <article className="lv-panel lv-panel-premium lv-tool-detail">
            {selected ? (
              <>
                <div className="lv-tool-detail-head">
                  <div>
                    <div className="lv-tool-detail-title">
                      <div>
                        <h2>{displayName(selected)}</h2>
                        <span className="lv-model-status">
                          <span className={`lv-status-dot ${statusDot(selected)}`} />
                          {statusLabel(selected)}
                        </span>
                      </div>
                    </div>
                    <p className="lv-node-desc">{selected.description || "No description provided."}</p>
                    <p className="lv-muted" style={{ marginTop: 6 }}>
                      id: {selected.id}
                    </p>
                  </div>
                </div>

                <div className="lv-toolbar">
                  <span className="lv-tag gold">{normalizeProvider(selected.provider_kind)}</span>
                  {selected.provider_ref ? (
                    <span className="lv-tag">ref: {String(selected.provider_ref)}</span>
                  ) : null}
                  {(selected.side_effects ?? []).map((effect) => (
                    <span key={effect} className="lv-tag">
                      {effect}
                    </span>
                  ))}
                </div>

                {selectedReason ? (
                  <p className="lv-muted" role="status" style={{ marginTop: 8 }}>
                    Unavailable: {selectedReason}
                  </p>
                ) : null}

                <div className="lv-section-label">Invoke</div>
                <label className="lv-form-field full">
                  <span>Arguments (JSON object)</span>
                  <textarea
                    className="lv-input"
                    rows={6}
                    value={argsJson}
                    onChange={(event) => setArgsJson(event.target.value)}
                    spellCheck={false}
                    disabled={!selectedInvokable || invoking}
                  />
                </label>

                <div className="lv-detail-actions" style={{ gridTemplateColumns: "1fr" }}>
                  <button
                    className="lv-btn lv-btn-gold"
                    type="button"
                    disabled={!selectedInvokable || invoking}
                    title={selectedReason ?? undefined}
                    onClick={() => void invokeSelected()}
                  >
                    {invoking ? "Invoking…" : "Invoke Capability"}
                  </button>
                </div>

                {lastResult ? (
                  <>
                    <div className="lv-section-label">Last result</div>
                    <pre className="lv-code-block" style={{ whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>
                      {lastResult}
                    </pre>
                  </>
                ) : null}
              </>
            ) : (
              <p className="lv-muted">Select a capability to inspect provenance and invoke.</p>
            )}
          </article>
        </div>

        <div className="lv-tools-bottom">
          <article className="lv-panel lv-card">
            <div className="lv-section-label">Catalog summary</div>
            <div className="lv-job-metrics">
              <div className="lv-metric">
                <span>Capabilities</span>
                <strong>{capabilities.length}</strong>
              </div>
              <div className="lv-metric">
                <span>Available</span>
                <strong>{availableCount}</strong>
              </div>
              <div className="lv-metric">
                <span>MCP tools</span>
                <strong>{mcpTools.length}</strong>
              </div>
              <div className="lv-metric">
                <span>Functions</span>
                <strong>{functionCount ?? "—"}</strong>
              </div>
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">MCP tool surface</div>
            <div className="lv-server-list">
              {mcpTools.length === 0 ? (
                <p className="lv-muted">No MCP tools reported (bridge may be empty or offline).</p>
              ) : (
                mcpTools.slice(0, 8).map((tool) => (
                  <div key={`${tool.server_id}:${tool.capability_id}`} className="lv-server-row">
                    <span
                      className={`lv-status-dot ${
                        tool.availability === "AVAILABLE" || tool.availability === "available"
                          ? "ready"
                          : "failed"
                      }`}
                    />
                    <div>
                      <strong>{tool.external_name}</strong>
                      <small>
                        {tool.server_id} · {tool.availability}
                        {tool.provider_kind ? ` · ${tool.provider_kind}` : ""}
                      </small>
                    </div>
                  </div>
                ))
              )}
            </div>
          </article>

          <article className="lv-panel lv-card">
            <div className="lv-section-label">Provenance</div>
            <p className="lv-muted">
              Each row is a live CapabilityCatalog entry. Provider kind is the authority surface
              (builtin / function / mcp / module). Availability is independent of registration —
              invoke is blocked when unavailable or disabled, with the backend reason shown.
            </p>
          </article>
        </div>

        <p className="lv-footer-quote">“Tools turn thought into action.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
