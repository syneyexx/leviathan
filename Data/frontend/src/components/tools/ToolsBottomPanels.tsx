import { Button } from "../ui";
import type { ToolsOverview, ToolsRecentCall } from "../../types/api";

type Props = {
  overview: ToolsOverview | null;
  recentCalls: ToolsRecentCall[];
  mcpStale?: boolean;
  pluginsStale?: boolean;
  onAddMcp: () => void;
  onLoadPlugin: () => void;
  onReconnectMcp: (serverId: string) => void;
  onTogglePlugin: (pluginId: string, enable: boolean) => void;
  onViewAllCalls: () => void;
};

function formatMs(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function formatTime(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "—";
  }
}

function connLabel(state?: string): string {
  const s = (state || "").toLowerCase();
  if (s === "connected" || s === "ready" || s === "verbonden") return "Verbonden";
  if (s === "disconnected" || s === "stopped") return "Losgekoppeld";
  if (!s || s === "unknown") return "—";
  return state || "—";
}

function statusTone(status?: string): string {
  const s = (status || "").toUpperCase();
  if (s === "COMPLETED" || s === "SUCCES") return "is-success";
  if (s === "FAILED" || s === "FOUT" || s === "TIMEOUT") return "is-danger";
  if (s === "REJECTED" || s === "AFGEWEZEN") return "is-warn";
  if (s === "CANCELLED" || s === "GEANNULEERD") return "is-muted";
  return "";
}

export function ToolsBottomPanels({
  overview,
  recentCalls,
  mcpStale,
  pluginsStale,
  onAddMcp,
  onLoadPlugin,
  onReconnectMcp,
  onTogglePlugin,
  onViewAllCalls,
}: Props) {
  const servers = overview?.mcp_servers ?? [];
  const plugins = overview?.plugins ?? [];

  return (
    <section className="lv-v2-tools-bottom" aria-label="Tools infrastructuur">
      <article className="lv-v2-tools-bottom__panel">
        <header className="lv-v2-tools-panel__head">
          <h3>MCP Servers {mcpStale ? <span className="lv-v2-stale">STALE</span> : null}</h3>
          <Button variant="secondary" size="sm" onClick={onAddMcp}>
            + MCP Server
          </Button>
        </header>
        <div className="lv-v2-tools-table-wrap">
          <table className="lv-v2-tools-table lv-v2-tools-table--compact">
            <thead>
              <tr>
                <th>Naam</th>
                <th>Status</th>
                <th>Tools</th>
                <th>Connectie</th>
                <th>Laatst gezien</th>
                <th aria-label="Acties" />
              </tr>
            </thead>
            <tbody>
              {servers.length === 0 ? (
                <tr>
                  <td colSpan={6}>Geen MCP servers geconfigureerd.</td>
                </tr>
              ) : (
                servers.map((s) => (
                  <tr key={s.server_id}>
                    <td>{s.display_name || s.server_id}</td>
                    <td>
                      <span className={`lv-v2-tools-status ${connLabel(s.connection) === "Verbonden" ? "is-active" : "is-unavailable"}`}>
                        <i />
                        {connLabel(s.connection)}
                      </span>
                    </td>
                    <td>{s.tool_count ?? "—"}</td>
                    <td className="lv-muted">{s.url || s.command || "—"}</td>
                    <td>{formatTime(s.last_seen_at ?? undefined)}</td>
                    <td>
                      <details className="lv-v2-tools-overflow">
                        <summary aria-label={`Acties MCP ${s.server_id}`}>⋯</summary>
                        <div className="lv-v2-tools-overflow__menu">
                          <button type="button" onClick={() => onReconnectMcp(s.server_id)}>
                            Reconnect
                          </button>
                          <a href="/mcp">Open details</a>
                        </div>
                      </details>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </article>

      <article className="lv-v2-tools-bottom__panel">
        <header className="lv-v2-tools-panel__head">
          <h3>Plugins {pluginsStale ? <span className="lv-v2-stale">STALE</span> : null}</h3>
          <Button variant="secondary" size="sm" onClick={onLoadPlugin}>
            + Plugin laden
          </Button>
        </header>
        <div className="lv-v2-tools-table-wrap">
          <table className="lv-v2-tools-table lv-v2-tools-table--compact">
            <thead>
              <tr>
                <th>Naam</th>
                <th>Status</th>
                <th>Tools</th>
                <th>Versie</th>
                <th aria-label="Acties" />
              </tr>
            </thead>
            <tbody>
              {plugins.length === 0 ? (
                <tr>
                  <td colSpan={5}>Geen plugins geregistreerd.</td>
                </tr>
              ) : (
                plugins.map((p) => {
                  const enabled = (p.status || "").toUpperCase() === "ENABLED";
                  return (
                    <tr key={p.plugin_id}>
                      <td>{p.name}</td>
                      <td>
                        <span className={`lv-v2-tools-status ${enabled ? "is-active" : "is-inactive"}`}>
                          <i />
                          {p.status_label ?? p.status ?? "—"}
                        </span>
                      </td>
                      <td>{p.tool_count ?? "—"}</td>
                      <td>{p.version ?? "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="lv-v2-linkish"
                          onClick={() => onTogglePlugin(p.plugin_id, !enabled)}
                        >
                          {enabled ? "Uitschakelen" : "Inschakelen"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </article>

      <article className="lv-v2-tools-bottom__panel">
        <header className="lv-v2-tools-panel__head">
          <h3>Recente Tool Aanroepen</h3>
          <Button variant="secondary" size="sm" onClick={onViewAllCalls}>
            Alles bekijken
          </Button>
        </header>
        <div className="lv-v2-tools-table-wrap">
          <table className="lv-v2-tools-table lv-v2-tools-table--compact">
            <thead>
              <tr>
                <th>Tijd</th>
                <th>Tool</th>
                <th>Status</th>
                <th>Duur</th>
                <th>Agent</th>
              </tr>
            </thead>
            <tbody>
              {recentCalls.length === 0 ? (
                <tr>
                  <td colSpan={5}>Nog geen tool-aanroepen.</td>
                </tr>
              ) : (
                recentCalls.slice(0, 8).map((row, idx) => (
                  <tr key={row.receipt_id ?? `${row.capability_id}-${row.recorded_at}-${idx}`}>
                    <td>{formatTime(row.recorded_at)}</td>
                    <td>{row.tool_name || row.capability_id}</td>
                    <td>
                      <span className={`lv-v2-tools-call-status ${statusTone(row.status)}`}>
                        {row.status_label ?? row.status}
                      </span>
                    </td>
                    <td>{formatMs(row.latency_ms)}</td>
                    <td>{row.requested_by ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}
