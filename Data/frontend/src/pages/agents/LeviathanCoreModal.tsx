import { useMemo, useState } from "react";
import type {
  AgentDefinition,
  AgentFleetSummary,
  AgentsDashboard,
  SystemArchitectureEntry,
} from "../../types/api";
import {
  agentOrigin,
  formatDurationMs,
  formatPct,
  groupSystemEntriesByRuntime,
  networkEdgesFromAgents,
} from "./helpers";
import { Modal } from "./agentsUi";

const TABS = [
  "Architecture",
  "Components",
  "Data Flow",
  "Operations",
  "Performance",
  "Security",
  "Configuration",
] as const;
type Tab = (typeof TABS)[number];

function statusClass(status: string): string {
  const s = (status || "unknown").toLowerCase();
  if (s === "ready" || s === "idle") return "ok";
  if (s === "busy") return "busy";
  if (s === "degraded" || s === "error" || s === "offline") return "warn";
  if (s === "disabled") return "off";
  return "muted";
}

function countBy<T>(items: T[], key: (t: T) => string): Array<[string, number]> {
  const m = new Map<string, number>();
  for (const it of items) m.set(key(it), (m.get(key(it)) ?? 0) + 1);
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function LeviathanCoreModal({
  systemEntries,
  agents,
  summary,
  dashboard,
  failureWindowHours,
  modelsCount,
  capabilitiesCount,
  onSelectEntry,
  onClose,
}: {
  systemEntries: SystemArchitectureEntry[];
  agents: AgentDefinition[];
  summary: AgentFleetSummary | null;
  dashboard: AgentsDashboard | null;
  failureWindowHours: number;
  modelsCount: number;
  capabilitiesCount: number;
  onSelectEntry: (id: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("Architecture");
  const groups = useMemo(() => groupSystemEntriesByRuntime(systemEntries), [systemEntries]);
  const byId = useMemo(() => Object.fromEntries(systemEntries.map((e) => [e.id, e])), [systemEntries]);
  const statusCounts = useMemo(() => countBy(systemEntries, (e) => e.status || "unknown"), [systemEntries]);
  const liveAgents = useMemo(() => agents.filter((a) => !a.archived), [agents]);
  const fleetEdges = useMemo(() => networkEdgesFromAgents(liveAgents), [liveAgents]);
  const agentNames = useMemo(() => Object.fromEntries(liveAgents.map((a) => [a.agentId, a.name])), [liveAgents]);
  const gateway = systemEntries.find((e) => e.systemKey === "execution_gateway");

  return (
    <Modal
      wide
      className="lv-ag-core-modal"
      title={
        <>
          LEVIATHAN CORE <small>Global intelligence &amp; orchestration · SystemInventory</small>
        </>
      }
      onClose={onClose}
    >
      <div className="lv-ag-tabs is-underline">
        {TABS.map((t) => (
          <button key={t} type="button" className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <p className="lv-ag-field-hint">
        Statuses come from runtime probes. Components without a registered probe stay “unknown” — never
        assumed healthy.
      </p>

      {systemEntries.length === 0 ? <p className="lv-ag-empty">SystemInventory returned no components.</p> : null}

      {tab === "Architecture" ? (
        <div className="lv-ag-core-groups">
          {groups.map((g) => (
            <div key={g.runtimeKind} className="lv-ag-core-group">
              <h4>{g.runtimeKind}</h4>
              <ul>
                {g.entries.map((e) => (
                  <li key={e.id}>
                    <button type="button" className="lv-ag-linkish" onClick={() => onSelectEntry(e.id)}>
                      {e.name}
                    </button>
                    <span className={`lv-ag-chip is-${statusClass(e.status)}`}>{e.status || "unknown"}</span>
                    <small>{e.entityType}</small>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}

      {tab === "Components" ? (
        <div className="lv-ag-table-wrap is-tall">
          <table className="lv-ag-table is-dense">
            <thead>
              <tr>
                <th>Component</th>
                <th>Type</th>
                <th>Runtime</th>
                <th>Status</th>
                <th>Enabled</th>
                <th>Exec</th>
                <th>Module</th>
              </tr>
            </thead>
            <tbody>
              {systemEntries.map((e) => (
                <tr key={e.id} onClick={() => onSelectEntry(e.id)} title={e.description}>
                  <td>{e.name}</td>
                  <td className="is-muted">{e.entityType}</td>
                  <td className="is-muted">{e.runtimeKind || "—"}</td>
                  <td>
                    <span className={`lv-ag-chip is-${statusClass(e.status)}`}>{e.status || "unknown"}</span>
                  </td>
                  <td className="is-muted">{e.enabled == null ? "unknown" : e.enabled ? "yes" : "no"}</td>
                  <td className="is-muted">{e.executable ? "yes" : "no"}</td>
                  <td className="is-model">{e.sourceModule || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "Data Flow" ? (
        <div className="lv-ag-core-cols">
          <div>
            <h4 className="lv-ag-subhead">Declared system relationships</h4>
            <ul className="lv-ag-member-list">
              {systemEntries.flatMap((e) =>
                (e.relationships || []).map((r) => (
                  <li key={`${e.id}-${r.relation}-${r.targetId}`}>
                    <span>{e.name}</span>
                    <span>
                      {r.relation} → {byId[r.targetId]?.name ?? r.targetSystemKey ?? r.targetId}
                    </span>
                  </li>
                )),
              )}
            </ul>
          </div>
          <div>
            <h4 className="lv-ag-subhead">Fleet delegation (orchestrator members)</h4>
            {fleetEdges.length === 0 ? (
              <p className="lv-ag-muted">No orchestrator memberships defined.</p>
            ) : (
              <ul className="lv-ag-member-list">
                {fleetEdges.map((e) => (
                  <li key={`${e.from}-${e.to}`}>
                    <span>{agentNames[e.from] ?? e.from}</span>
                    <span>
                      delegates → {agentNames[e.to] ?? e.to}
                      {e.active ? " · busy" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : null}

      {tab === "Operations" ? (
        <div className="lv-ag-core-cols">
          <ul className="lv-ag-kv">
            {statusCounts.map(([s, n]) => (
              <li key={s}>
                <span>Components {s}</span>
                <em>{n}</em>
              </li>
            ))}
            <li>
              <span>Agents feature</span>
              <em>{summary?.agentsEnabled ?? dashboard?.agentsEnabled ? "enabled" : "disabled"}</em>
            </li>
          </ul>
          <ul className="lv-ag-kv">
            <li>
              <span>Active missions</span>
              <em>{dashboard?.missions.active ?? summary?.activeMissions ?? "—"}</em>
            </li>
            <li>
              <span>Queued / starting / running</span>
              <em>
                {dashboard
                  ? `${dashboard.missions.queued} / ${dashboard.missions.starting} / ${dashboard.missions.running}`
                  : "—"}
              </em>
            </li>
            <li>
              <span>Worker supervisor</span>
              <em>{dashboard?.workers.available ? dashboard.workers.supervisorHealth ?? "unknown" : "unavailable"}</em>
            </li>
            <li>
              <span>Active / registered workers</span>
              <em>
                {dashboard?.workers.available
                  ? `${dashboard.workers.active ?? "—"} / ${dashboard.workers.instances ?? "—"}`
                  : "—"}
              </em>
            </li>
          </ul>
        </div>
      ) : null}

      {tab === "Performance" ? (
        dashboard ? (
          <ul className="lv-ag-kv">
            <li>
              <span>Window</span>
              <em>{dashboard.windowHours}h</em>
            </li>
            <li>
              <span>Success rate</span>
              <em>{formatPct(dashboard.performance.successRate)}</em>
            </li>
            <li>
              <span>Eligible terminal missions</span>
              <em>{dashboard.performance.eligibleTerminal}</em>
            </li>
            <li>
              <span>Avg / p50 / p95 duration</span>
              <em>
                {formatDurationMs(dashboard.performance.avgDurationMs)} /{" "}
                {formatDurationMs(dashboard.performance.p50DurationMs)} /{" "}
                {formatDurationMs(dashboard.performance.p95DurationMs)}
              </em>
            </li>
            <li>
              <span>Completed / failed / cancelled</span>
              <em>
                {dashboard.missions.completedInWindow} / {dashboard.missions.failedInWindow} /{" "}
                {dashboard.missions.cancelledInWindow}
              </em>
            </li>
            <li>
              <span>Failure window ({failureWindowHours}h) success / retry / failed</span>
              <em>
                {dashboard.failureRetry.success} / {dashboard.failureRetry.retry} / {dashboard.failureRetry.failed}
              </em>
            </li>
          </ul>
        ) : (
          <p className="lv-ag-empty">Dashboard not loaded.</p>
        )
      ) : null}

      {tab === "Security" ? (
        <div className="lv-ag-core-cols">
          <ul className="lv-ag-kv">
            <li>
              <span>Execution Gateway</span>
              <em>{gateway ? gateway.status || "unknown" : "not in inventory"}</em>
            </li>
            <li>
              <span>SYSTEM (protected) agents</span>
              <em>{liveAgents.filter((a) => agentOrigin(a) === "system").length}</em>
            </li>
            <li>
              <span>USER (mutable) agents</span>
              <em>{liveAgents.filter((a) => agentOrigin(a) === "user").length}</em>
            </li>
            <li>
              <span>Architecture descriptors (read-only)</span>
              <em>{systemEntries.length}</em>
            </li>
          </ul>
          <ul className="lv-ag-kv">
            {countBy(liveAgents, (a) => a.approvalMode || "inherit").map(([mode, n]) => (
              <li key={mode}>
                <span>Approval mode: {mode}</span>
                <em>{n}</em>
              </li>
            ))}
            {countBy(liveAgents, (a) => a.datasetAccess || "none").map(([mode, n]) => (
              <li key={`d-${mode}`}>
                <span>Dataset access: {mode}</span>
                <em>{n}</em>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {tab === "Configuration" ? (
        <div className="lv-ag-core-cols">
          <ul className="lv-ag-kv">
            <li>
              <span>LEVIATHAN_FEATURE_AGENTS</span>
              <em>{summary?.agentsEnabled ?? dashboard?.agentsEnabled ? "on" : "off"}</em>
            </li>
            <li>
              <span>Dashboard window</span>
              <em>{dashboard?.windowHours ?? "—"}h</em>
            </li>
            <li>
              <span>Failure window</span>
              <em>{failureWindowHours}h</em>
            </li>
            <li>
              <span>Registered models</span>
              <em>{modelsCount}</em>
            </li>
            <li>
              <span>Capability registry</span>
              <em>{capabilitiesCount}</em>
            </li>
            <li>
              <span>Worker pools</span>
              <em>{dashboard?.workers.available ? dashboard.workers.pools.length : "—"}</em>
            </li>
          </ul>
          <ul className="lv-ag-member-list">
            {systemEntries
              .filter((e) => typeof e.metadata?.detail === "string")
              .map((e) => (
                <li key={e.id}>
                  <span>{e.name}</span>
                  <span>{String(e.metadata?.detail)}</span>
                </li>
              ))}
          </ul>
        </div>
      ) : null}
    </Modal>
  );
}
