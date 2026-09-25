import { useMemo, useState, type ReactNode } from "react";
import { formatElapsed } from "../../lib/jobStatus";
import type {
  AgentDefinition,
  AgentEvent,
  AgentMission,
  CapabilityListItem,
  DatasetLearningStatus,
  DatasetRecord,
  KnowledgeDocument,
  SystemTelemetryResponse,
  WorkerRegistration,
} from "../../types/api";
import {
  activeMissionsForAgent,
  agentEnvironment,
  agentIconKind,
  agentMissionStats,
  assignedCapabilityCards,
  canLaunchAgent,
  filterEvents,
  formatDurationMs,
  formatPct,
  healthLabel,
  isArchitectureEntry,
  isSystemProtected,
  orchestratorsForMember,
  statusTone,
  teamBucketForAgent,
  workersForMissions,
  type LogFilter,
} from "./helpers";
import { AgentIcon, Bar, PanelHead } from "./agentsUi";
import { DatasetLearningSection } from "./DatasetLearningSection";

const TABS = ["Overview", "Tools", "Memory", "Workers", "Logs"] as const;
type Tab = (typeof TABS)[number];
const LOG_FILTERS: LogFilter[] = ["All", "System", "Agents", "Tasks", "Warnings", "Errors"];

function Kv({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li>
      <span>{label}</span>
      <em>{children}</em>
    </li>
  );
}

export function SelectedAgentPanel({
  agent,
  agents,
  missions,
  events,
  capabilities,
  knowledgeDocs,
  datasets,
  datasetLearning,
  workers,
  telemetry,
  agentsEnabled,
  busy,
  selectedMissionId,
  onEdit,
  onClone,
  onToggle,
  onArchive,
  onLaunch,
  onCancelMission,
  onSelectAgent,
  onSelectMission,
  onDatasetCancel,
  onDatasetRetry,
  onDatasetReindex,
}: {
  agent: AgentDefinition | undefined;
  agents: AgentDefinition[];
  missions: AgentMission[];
  events: AgentEvent[];
  capabilities: CapabilityListItem[];
  knowledgeDocs: KnowledgeDocument[];
  datasets: DatasetRecord[];
  datasetLearning: DatasetLearningStatus | null;
  workers: WorkerRegistration[] | null;
  telemetry: SystemTelemetryResponse | null;
  agentsEnabled: boolean | undefined;
  busy: boolean;
  selectedMissionId: string;
  onEdit: () => void;
  onClone: () => void;
  onToggle: () => void;
  onArchive: () => void;
  onLaunch: () => void;
  onCancelMission: (missionId: string) => void;
  onSelectAgent: (id: string) => void;
  onSelectMission: (id: string) => void;
  onDatasetCancel: (jobId: string) => void;
  onDatasetRetry: (jobId: string) => void;
  onDatasetReindex: (datasetId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("Overview");
  const [logFilter, setLogFilter] = useState<LogFilter>("All");
  const [logScopeMission, setLogScopeMission] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const agentId = agent?.agentId ?? "";
  const arch = agent ? isArchitectureEntry(agent) : false;
  const agentById = useMemo(() => Object.fromEntries(agents.map((a) => [a.agentId, a])), [agents]);
  const stats = useMemo(() => agentMissionStats(missions, agentId), [missions, agentId]);
  const active = useMemo(
    () => (agentId ? activeMissionsForAgent(missions, agentId) : []),
    [missions, agentId],
  );
  const parents = useMemo(() => orchestratorsForMember(agents, agentId), [agents, agentId]);
  const caps = useMemo(() => assignedCapabilityCards(agent, capabilities), [agent, capabilities]);
  const agentEvents = useMemo(
    () =>
      filterEvents(events, logFilter, {
        agentId: agentId || undefined,
        missionId: logScopeMission ? selectedMissionId || undefined : undefined,
      }),
    [events, logFilter, agentId, logScopeMission, selectedMissionId],
  );
  const recentDecisions = useMemo(
    () => events.filter((e) => e.agentId === agentId).slice(0, 4),
    [events, agentId],
  );
  const matchedWorkers = useMemo(
    () => (workers ? workersForMissions(workers, active) : []),
    [workers, active],
  );
  const knowledgeById = useMemo(
    () => Object.fromEntries(knowledgeDocs.map((d) => [d.id, d])),
    [knowledgeDocs],
  );

  if (!agent) {
    return (
      <section className="lv-ag-panel lv-ag-selected">
        <PanelHead title="Selected Agent" />
        <p className="lv-ag-empty">Select an agent from the table or architecture.</p>
      </section>
    );
  }

  const label = healthLabel(agent);
  const relationships = Array.isArray(agent.metadata?.relationships)
    ? (agent.metadata.relationships as Array<{ relation: string; targetId: string; targetSystemKey?: string }>)
    : [];
  const gate = canLaunchAgent(agent, agentsEnabled);
  const objective = active[0];
  const cpu = telemetry?.cpu?.available ? telemetry.cpu.utilizationPct : null;
  const gpuDev = telemetry?.gpu?.available ? telemetry.gpu.devices[0] : undefined;
  const gpu = gpuDev?.utilizationPct ?? null;
  const concurrency = Math.max(1, agent.maxConcurrency || 1);

  function menuAction(fn: () => void) {
    setMenuOpen(false);
    fn();
  }

  return (
    <section className="lv-ag-panel lv-ag-selected">
      <PanelHead
        title="Selected Agent"
        right={
          <div className="lv-ag-menu">
            <button
              type="button"
              className="lv-ag-btn-ghost is-xs"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
            >
              Actions ▾
            </button>
            {menuOpen ? (
              <div className="lv-ag-menu-list" role="menu">
                <button type="button" role="menuitem" disabled={busy || !gate.ok} title={gate.reason} onClick={() => menuAction(onLaunch)}>
                  Launch mission…
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={busy || active.length === 0}
                  onClick={() => menuAction(() => onCancelMission(active[0].missionId))}
                >
                  Cancel active mission
                </button>
                {!arch ? (
                  <>
                    <button type="button" role="menuitem" disabled={busy || agent.archived} onClick={() => menuAction(onEdit)}>
                      Edit
                    </button>
                    <button type="button" role="menuitem" disabled={busy} onClick={() => menuAction(onClone)}>
                      Clone
                    </button>
                    <button type="button" role="menuitem" disabled={busy || agent.archived} onClick={() => menuAction(onToggle)}>
                      {agent.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      className="is-danger"
                      disabled={busy || agent.archived || isSystemProtected(agent)}
                      title={isSystemProtected(agent) ? "SYSTEM agents cannot be archived" : undefined}
                      onClick={() => menuAction(onArchive)}
                    >
                      Archive
                    </button>
                  </>
                ) : (
                  <span className="lv-ag-menu-note">Architecture entries are read-only</span>
                )}
              </div>
            ) : null}
          </div>
        }
      />

      <div className="lv-ag-sel-id">
        <span className="lv-ag-sel-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <AgentIcon kind={agentIconKind(agent)} />
          </svg>
        </span>
        <div className="lv-ag-sel-meta">
          <div className="lv-ag-sel-name">
            <strong>{agent.name}</strong>
            <span className={`lv-ag-chip is-${statusTone(label)}`}>{label}</span>
          </div>
          <small>{agent.role || String(agent.kind)}</small>
          <p title={agent.description}>{agent.description || "No description."}</p>
        </div>
      </div>

      <div className="lv-ag-tabs is-underline" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "is-active" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="lv-ag-sel-body">
        {tab === "Overview" ? (
          <>
            <ul className="lv-ag-kv is-dense">
              <Kv label="Orchestrator">
                {parents.length === 0 ? (
                  "—"
                ) : (
                  <button type="button" className="lv-ag-linkish" onClick={() => onSelectAgent(parents[0].agentId)}>
                    {parents[0].name}
                    {parents.length > 1 ? ` +${parents.length - 1}` : ""}
                  </button>
                )}
              </Kv>
              <Kv label="Model">{arch ? "—" : agent.modelRef || "inherit / unset"}</Kv>
              <Kv label="Environment">
                {agentEnvironment(agent)} · {teamBucketForAgent(agent)}
              </Kv>
              <Kv label="Last run">{agent.lastRunAt ? formatElapsed(agent.lastRunAt) : "—"}</Kv>
              <Kv label="Total tasks">{arch ? "—" : stats.total}</Kv>
              <Kv label="Success rate">{arch ? "—" : formatPct(stats.successRate)}</Kv>
              <Kv label="Avg response">{arch ? "—" : formatDurationMs(stats.avgDurationMs)}</Kv>
            </ul>

            <div className="lv-ag-sel-block">
              <h4>Current objective</h4>
              {objective ? (
                <button type="button" className="lv-ag-objective" onClick={() => onSelectMission(objective.missionId)}>
                  <span title={objective.title}>{objective.title}</span>
                  <span className="lv-ag-objective-bar">
                    <Bar ratio={objective.progress || 0} />
                    <em>{Math.round((objective.progress || 0) * 100)}%</em>
                  </span>
                </button>
              ) : (
                <p className="lv-ag-muted">No active mission.</p>
              )}
            </div>

            <div className="lv-ag-sel-block">
              <h4>
                Active workers ({matchedWorkers.length}/{concurrency})
              </h4>
              <div className="lv-ag-res-row">
                <span>
                  CPU {cpu != null ? `${cpu.toFixed(0)}%` : "—"}
                  <Bar ratio={cpu != null ? cpu / 100 : null} tone="gold" />
                </span>
                <span>
                  GPU {gpu != null ? `${gpu.toFixed(0)}%` : "—"}
                  <Bar ratio={gpu != null ? gpu / 100 : null} tone="gold" />
                </span>
              </div>
              <p className="lv-ag-field-hint">Host telemetry — not per-agent attribution.</p>
            </div>

            <div className="lv-ag-sel-block">
              <h4>Recent decisions</h4>
              {recentDecisions.length === 0 ? (
                <p className="lv-ag-muted">No events recorded for this agent.</p>
              ) : (
                <ul className="lv-ag-decisions">
                  {recentDecisions.map((e) => (
                    <li key={e.eventId}>
                      <time>{e.createdAt.slice(11, 16)}</time>
                      <span title={e.message}>{e.message}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="lv-ag-sel-block">
              <h4>Capabilities &amp; tags</h4>
              <div className="lv-ag-chips">
                {caps.slice(0, 8).map((c) => (
                  <span key={c.id} className="lv-ag-tag" title={c.desc}>
                    {c.title}
                  </span>
                ))}
                {agent.tags.slice(0, 6).map((t) => (
                  <span key={`t-${t}`} className="lv-ag-tag is-gold">
                    {t}
                  </span>
                ))}
                {caps.length === 0 && agent.tags.length === 0 ? (
                  <span className="lv-ag-muted">None assigned</span>
                ) : null}
              </div>
            </div>

            {agent.kind === "orchestrator" && agent.orchestrator ? (
              <div className="lv-ag-sel-block">
                <h4>
                  Orchestrator · {agent.orchestrator.strategy} · depth {agent.orchestrator.maxDelegationDepth} ·{" "}
                  {agent.orchestrator.failureStrategy}
                </h4>
                <ul className="lv-ag-member-list">
                  {agent.orchestrator.memberAgentIds.map((mid) => {
                    const m = agentById[mid];
                    return (
                      <li key={mid}>
                        <button type="button" className="lv-ag-linkish" onClick={() => onSelectAgent(mid)}>
                          {m?.name ?? mid.slice(0, 12)}
                        </button>
                        <span>{m ? `${m.kind} · ${healthLabel(m)}${!m.enabled ? " · disabled" : ""}` : "missing"}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}

            {arch && relationships.length > 0 ? (
              <div className="lv-ag-sel-block">
                <h4>Relationships</h4>
                <ul className="lv-ag-kv is-dense">
                  {relationships.map((rel) => (
                    <Kv key={`${rel.relation}-${rel.targetId}`} label={rel.relation}>
                      {rel.targetSystemKey || rel.targetId}
                    </Kv>
                  ))}
                </ul>
                {typeof agent.metadata?.sourceModule === "string" ? (
                  <p className="lv-ag-field-hint">module: {agent.metadata.sourceModule}</p>
                ) : null}
              </div>
            ) : null}
            {!gate.ok ? <p className="lv-ag-field-hint">{gate.reason}</p> : null}
          </>
        ) : null}

        {tab === "Tools" ? (
          <div className="lv-ag-cap-list">
            {caps.length === 0 ? (
              <p className="lv-ag-empty">
                No capabilities assigned.
                {capabilities.length > 0 ? ` Registry has ${capabilities.length} — assign via Edit.` : ""}
              </p>
            ) : (
              caps.map((cap) => {
                const reg = capabilities.find((c) => c.id === cap.id);
                return (
                  <div key={cap.id} className="lv-ag-cap-row">
                    <strong>{cap.title}</strong>
                    <small>{cap.desc}</small>
                    <em>
                      {reg?.provider_kind ? `provider: ${String(reg.provider_kind)}` : "capability ID only"}
                      {reg?.available === false ? " · unavailable" : ""}
                    </em>
                  </div>
                );
              })
            )}
          </div>
        ) : null}

        {tab === "Memory" ? (
          <>
            <ul className="lv-ag-kv is-dense">
              <Kv label="Memory policy">{agent.memoryPolicy}</Kv>
              <Kv label="Dataset access">{agent.datasetAccess}</Kv>
              <Kv label="Token budget">{agent.tokenBudget ?? "unset"}</Kv>
              <Kv label="Knowledge sources">{agent.knowledgeSources.length}</Kv>
            </ul>
            {agent.knowledgeSources.length > 0 ? (
              <ul className="lv-ag-member-list">
                {agent.knowledgeSources.map((id) => (
                  <li key={id}>
                    <span>{knowledgeById[id]?.title || id}</span>
                    <span>{knowledgeById[id]?.source || ""}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            <DatasetLearningSection
              agent={agent}
              datasetLearning={datasetLearning}
              datasets={datasets}
              busy={busy}
              onCancelJob={onDatasetCancel}
              onRetryJob={onDatasetRetry}
              onReindex={onDatasetReindex}
            />
          </>
        ) : null}

        {tab === "Workers" ? (
          <>
            <ul className="lv-ag-kv is-dense">
              <Kv label="Concurrency">
                {active.length} / {agent.maxConcurrency}
              </Kv>
              <Kv label="Timeout / retries">
                {agent.timeoutS ?? "—"}s / {agent.maxRetries}
              </Kv>
              <Kv label="Registry workers on these jobs">{workers ? matchedWorkers.length : "registry unavailable"}</Kv>
            </ul>
            {active.length === 0 ? (
              <p className="lv-ag-empty">No active missions for this agent.</p>
            ) : (
              <ul className="lv-ag-member-list">
                {active.map((m) => (
                  <li key={m.missionId}>
                    <button type="button" className="lv-ag-linkish" onClick={() => onSelectMission(m.missionId)}>
                      {m.title}
                    </button>
                    <span className="lv-ag-inline-actions">
                      {m.status} · {m.jobIds.length} job(s)
                      <button
                        type="button"
                        className="lv-ag-btn-stop is-xs"
                        disabled={busy}
                        onClick={() => onCancelMission(m.missionId)}
                      >
                        Cancel
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {matchedWorkers.length > 0 ? (
              <ul className="lv-ag-member-list">
                {matchedWorkers.map((w) => (
                  <li key={w.worker_id}>
                    <span>
                      {w.pool_id} · {w.worker_id.slice(0, 14)}
                    </span>
                    <span>
                      {w.state} · job {String(w.current_job_id).slice(0, 10)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}

        {tab === "Logs" ? (
          <>
            <div className="lv-ag-tabs is-xs">
              {LOG_FILTERS.map((f) => (
                <button key={f} type="button" className={logFilter === f ? "is-active" : ""} onClick={() => setLogFilter(f)}>
                  {f}
                </button>
              ))}
              <label className="lv-ag-check is-inline">
                <input type="checkbox" checked={logScopeMission} onChange={(e) => setLogScopeMission(e.target.checked)} />
                <span>Selected mission</span>
              </label>
            </div>
            <ul className="lv-ag-logs">
              {agentEvents.length === 0 ? (
                <li className="lv-ag-empty">No events for current filters.</li>
              ) : (
                agentEvents.slice(0, 60).map((log) => (
                  <li key={log.eventId}>
                    <time>{log.createdAt.slice(11, 19)}</time>
                    <span className="lv-ag-log-src">[{log.category}]</span>
                    <span className="lv-ag-log-text" title={log.message}>
                      {log.message}
                    </span>
                    <em>{log.level}</em>
                  </li>
                ))
              )}
            </ul>
          </>
        ) : null}
      </div>

      <div className="lv-ag-sel-actions">
        <button type="button" className="lv-ag-act" disabled={busy || !gate.ok} title={gate.reason} onClick={onLaunch}>
          ▸ Open Console
        </button>
        <button type="button" className="lv-ag-act" onClick={() => setTab("Memory")}>
          ◎ Inspect Memory
        </button>
        <button type="button" className="lv-ag-act" onClick={() => setTab("Workers")}>
          ▦ View Workers
        </button>
        <button
          type="button"
          className={`lv-ag-act ${agent.enabled ? "is-danger" : "is-ok"}`}
          disabled={busy || arch || agent.archived}
          onClick={onToggle}
        >
          {agent.enabled ? "❚❚ Pause Agent" : "▶ Resume Agent"}
        </button>
      </div>
    </section>
  );
}
