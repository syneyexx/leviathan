import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import {
  activeMissionsForAgent,
  agentEnvironment,
  agentMissionStats,
  assignedCapabilityCards,
  canLaunchAgent,
  formatDurationMs,
  formatPct,
  healthLabel,
  isArchitectureEntry,
  isSystemProtected,
  statusTone,
  teamBucketForAgent,
  workersForMissions,
} from "../../pages/agents/helpers";
import { Badge, Button, EmptyState, Panel, ProgressBar, StatusDot } from "../ui";

const TABS = ["Overzicht", "Capabilities", "Tools", "Configuratie"] as const;
type Tab = (typeof TABS)[number];

function Kv({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li className="lv-v2-agents-kv">
      <span>{label}</span>
      <em>{children}</em>
    </li>
  );
}

type Props = { ws: AgentsWorkspace };

export function SelectedAgentInspector({ ws }: Props) {
  const {
    selectedAgent: agent,
    liveFleet,
    missions,
    capabilities,
    knowledgeDocs,
    datasetLearning,
    workersList,
    telemetry,
    summary,
    busy,
    selectedMissionId,
    openEdit,
    onClone,
    onToggleSelected,
    onArchive,
    setLaunchOpen,
    onCancelMission,
    setSelectedAgentId,
    selectMission,
  } = ws;

  const [tab, setTab] = useState<Tab>("Overzicht");

  const agentId = agent?.agentId ?? "";
  const arch = agent ? isArchitectureEntry(agent) : false;
  const stats = useMemo(() => agentMissionStats(missions, agentId), [missions, agentId]);
  const active = useMemo(
    () => (agentId ? activeMissionsForAgent(missions, agentId) : []),
    [missions, agentId],
  );
  const caps = useMemo(() => assignedCapabilityCards(agent, capabilities), [agent, capabilities]);
  const matchedWorkers = useMemo(
    () => (workersList?.workers ? workersForMissions(workersList.workers, active) : []),
    [workersList, active],
  );
  const knowledgeById = useMemo(
    () => Object.fromEntries(knowledgeDocs.map((d) => [d.id, d])),
    [knowledgeDocs],
  );

  if (!agent) {
    return (
      <Panel className="lv-v2-agents-inspector" title="Geselecteerde Agent">
        <EmptyState title="Geen agent geselecteerd" detail="Kies een agent in de directory of architectuur." />
      </Panel>
    );
  }

  const label = healthLabel(agent);
  const gate = canLaunchAgent(agent, summary?.agentsEnabled);
  const objective = active[0];
  const dutchStatus =
    label === "Busy" ? "Bezig" : label === "Idle" || label === "Online" ? "Actief" : label;
  const protectedAgent = isSystemProtected(agent) || arch;

  // Host telemetry is system-scoped — never claim per-agent attribution.
  const cpu = telemetry?.cpu?.available ? telemetry.cpu.utilizationPct : null;
  const ramPct = telemetry?.memory?.available ? telemetry.memory.utilizationPct : null;
  const gpuDev = telemetry?.gpu?.available ? telemetry.gpu.devices[0] : undefined;
  const gpu = gpuDev?.utilizationPct ?? null;

  return (
    <Panel
      className="lv-v2-agents-inspector"
      title="Geselecteerde Agent"
      action={
        <select
          className="lv-v2-select"
          aria-label="Selecteer agent"
          value={agent.agentId}
          onChange={(e) => setSelectedAgentId(e.target.value)}
        >
          {liveFleet.map((a) => (
            <option key={a.agentId} value={a.agentId}>
              {a.name}
            </option>
          ))}
        </select>
      }
    >
      <div className="lv-v2-agents-inspector__profile">
        <div className="lv-v2-agents-inspector__id">
          <strong>{agent.name}</strong>
          <span className="lv-v2-agents-status">
            <StatusDot
              tone={
                statusTone(label) === "ok"
                  ? "success"
                  : statusTone(label) === "warn"
                    ? "warning"
                    : "muted"
              }
            />
            {dutchStatus}
          </span>
          {protectedAgent ? <Badge tone="system">SYSTEM</Badge> : null}
        </div>
        <p className="lv-v2-agents-inspector__desc">{agent.description || "Geen beschrijving."}</p>
        <div className="lv-v2-agents-inspector__actions">
          <Button
            variant="secondary"
            size="sm"
            disabled={busy || !gate.ok}
            title={gate.reason}
            onClick={() => setLaunchOpen(true)}
          >
            Missie
          </Button>
          {!arch ? (
            <Button variant="ghost" size="sm" disabled={busy || agent.archived} onClick={openEdit}>
              Bewerken
            </Button>
          ) : null}
          {!protectedAgent ? (
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => void onToggleSelected()}>
              {agent.enabled ? "Pauzeer" : "Hervat"}
            </Button>
          ) : (
            <span className="lv-v2-agents-hint">Read-only SYSTEM</span>
          )}
          <Link className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" to="/console">
            Open console
          </Link>
        </div>
      </div>

      <div className="lv-v2-segmented lv-v2-agents-tabs" role="tablist" aria-label="Agent detail">
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

      <div className="lv-v2-agents-inspector__body" role="tabpanel">
        {tab === "Overzicht" ? (
          <>
            <h4 className="lv-v2-agents-section-title">Algemene Informatie</h4>
            <ul className="lv-v2-agents-kv-list">
              <Kv label="Status">{dutchStatus}</Kv>
              <Kv label="Type">
                <Badge tone="info">{agent.kind}</Badge>
              </Kv>
              <Kv label="Rol">{agent.role || "—"}</Kv>
              <Kv label="Versie">v{agent.version ?? 1}</Kv>
              <Kv label="Model">
                {arch ? (
                  "—"
                ) : (
                  <>
                    {agent.modelRef || "inherit / unset"}{" "}
                    <Link className="lv-v2-agents-inline-link" to="/models">
                      Open Models
                    </Link>
                  </>
                )}
              </Kv>
              <Kv label="Environment">
                {agentEnvironment(agent)} · {teamBucketForAgent(agent)}
              </Kv>
              <Kv label="Last activity">{agent.lastRunAt || "—"}</Kv>
              <Kv label="Health reason">{agent.healthReason || "—"}</Kv>
              <Kv label="Success">{arch ? "—" : formatPct(stats.successRate)}</Kv>
              <Kv label="Avg duration">{arch ? "—" : formatDurationMs(stats.avgDurationMs)}</Kv>
            </ul>

            <h4 className="lv-v2-agents-section-title">Huidige Missie</h4>
            {objective ? (
              <button
                type="button"
                className="lv-v2-agents-mission-card"
                onClick={() => selectMission(objective.missionId)}
              >
                <strong title={objective.title}>{objective.title}</strong>
                <div className="lv-v2-agents-mission-card__bar">
                  <ProgressBar
                    value={
                      objective.progress != null && Number.isFinite(objective.progress)
                        ? objective.progress * 100
                        : null
                    }
                  />
                  <span>
                    {objective.progress != null && Number.isFinite(objective.progress)
                      ? `${Math.round(objective.progress * 100)}%`
                      : "UNMEASURED"}
                  </span>
                </div>
                <small>
                  {objective.status} · start {objective.startedAt || objective.createdAt || "—"}
                </small>
              </button>
            ) : (
              <p className="lv-v2-agents-muted">Geen actieve missie.</p>
            )}

            <h4 className="lv-v2-agents-section-title">Capaciteiten</h4>
            <div className="lv-v2-agents-chips">
              {caps.slice(0, 10).map((c) => (
                <span key={c.id} className="lv-v2-agents-chip" title={c.desc}>
                  {c.title}
                </span>
              ))}
              {caps.length === 0 ? <span className="lv-v2-agents-muted">Geen toegewezen</span> : null}
            </div>

            <h4 className="lv-v2-agents-section-title">Resource Gebruik</h4>
            <p className="lv-v2-agents-hint">Systeemresources (host) — niet per-agent toegeschreven.</p>
            <div className="lv-v2-agents-meters">
              <div className="lv-v2-meter-row">
                <div className="lv-v2-meter-row__head">
                  <span>CPU</span>
                  <span>{cpu != null ? `${Math.round(cpu)}%` : "UNMEASURED"}</span>
                </div>
                <ProgressBar value={cpu} />
              </div>
              <div className="lv-v2-meter-row">
                <div className="lv-v2-meter-row__head">
                  <span>RAM</span>
                  <span>{ramPct != null ? `${Math.round(ramPct)}%` : "UNMEASURED"}</span>
                </div>
                <ProgressBar value={ramPct} />
              </div>
              <div className="lv-v2-meter-row">
                <div className="lv-v2-meter-row__head">
                  <span>GPU</span>
                  <span>{gpu != null ? `${Math.round(gpu)}%` : "UNMEASURED"}</span>
                </div>
                <ProgressBar value={gpu} tone="warning" />
              </div>
              <div className="lv-v2-meter-row">
                <div className="lv-v2-meter-row__head">
                  <span>Workers (missie-gekoppeld)</span>
                  <span>
                    {workersList?.workers
                      ? `${matchedWorkers.length}`
                      : "UNAVAILABLE"}
                  </span>
                </div>
              </div>
            </div>
          </>
        ) : null}

        {tab === "Capabilities" ? (
          <ul className="lv-v2-agents-perm-list">
            {caps.length === 0 ? (
              <EmptyState title="Geen capabilities toegewezen" detail="Alleen agent.capabilities worden getoond." />
            ) : (
              caps.map((c) => (
                <li key={c.id}>
                  <div>
                    <strong>{c.title}</strong>
                    <small>{c.desc || c.id}</small>
                  </div>
                  <Badge tone={c.available === false ? "warning" : "success"}>
                    {c.available === false ? "unavailable" : "assigned"}
                  </Badge>
                </li>
              ))
            )}
          </ul>
        ) : null}

        {tab === "Tools" ? (
          <>
            <p className="lv-v2-agents-hint">
              Executable surfaces via ExecutionGateway — capability IDs zijn geen bypass.
            </p>
            <ul className="lv-v2-agents-perm-list">
              {caps.length === 0 ? (
                <EmptyState title="Geen tools" detail="Geen toegewezen capability-oppervlakken." />
              ) : (
                caps.map((c) => (
                  <li key={c.id}>
                    <div>
                      <strong>{c.title}</strong>
                      <small>{c.id}</small>
                    </div>
                    <Badge tone={c.available === false ? "danger" : "info"}>
                      {c.available === false ? "gated/unavailable" : "authorized path"}
                    </Badge>
                  </li>
                ))
              )}
            </ul>
            <div className="lv-v2-agents-inline-links">
              <Link to="/tools">Tools</Link>
              <Link to="/mcp">MCP</Link>
              <Link to="/workflows">Workflows</Link>
            </div>
          </>
        ) : null}

        {tab === "Configuratie" ? (
          <>
            {arch ? (
              <EmptyState title="Read-only architecture" detail="SYSTEM architecture entries zijn niet muteerbaar." />
            ) : (
              <ul className="lv-v2-agents-kv-list">
                <Kv label="Enabled">{agent.enabled ? "ja" : "nee"}</Kv>
                <Kv label="Autonomy">{agent.autonomy ?? "—"} (policy metadata)</Kv>
                <Kv label="Approval">{agent.approvalMode || "—"}</Kv>
                <Kv label="Memory policy">{agent.memoryPolicy || "—"}</Kv>
                <Kv label="Dataset access">{agent.datasetAccess || "—"} (policy)</Kv>
                <Kv label="Max concurrency">{agent.maxConcurrency ?? "—"}</Kv>
                <Kv label="Timeout (s)">{agent.timeoutS ?? "—"}</Kv>
                <Kv label="Max retries">{agent.maxRetries ?? "—"}</Kv>
                <Kv label="Token budget">{agent.tokenBudget ?? "UNMEASURED"}</Kv>
                <Kv label="Knowledge sources">
                  {(agent.knowledgeSources || [])
                    .map((id) => knowledgeById[id]?.title || id)
                    .join(", ") || "—"}
                </Kv>
                {agent.orchestrator ? (
                  <>
                    <Kv label="Orch strategy">{agent.orchestrator.strategy}</Kv>
                    <Kv label="Failure strategy">{agent.orchestrator.failureStrategy}</Kv>
                    <Kv label="Delegation depth">{agent.orchestrator.maxDelegationDepth}</Kv>
                    <Kv label="Members">{agent.orchestrator.memberAgentIds.length}</Kv>
                  </>
                ) : null}
              </ul>
            )}
            {!arch ? (
              <div className="lv-v2-agents-inspector__actions">
                <Button variant="secondary" size="sm" disabled={busy} onClick={openEdit}>
                  Open editor
                </Button>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => void onClone()}>
                  Clone
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy || isSystemProtected(agent)}
                  onClick={() => void onArchive()}
                >
                  Archive
                </Button>
              </div>
            ) : null}
            {datasetLearning ? (
              <p className="lv-v2-agents-hint">
                Dataset learning · actief {datasetLearning.activity?.activeCount ?? 0}
                {selectedMissionId ? ` · missie ${selectedMissionId.slice(0, 8)}` : ""}
              </p>
            ) : null}
            {active[0] ? (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void onCancelMission(active[0].missionId)}
              >
                Cancel actieve missie
              </Button>
            ) : null}
          </>
        ) : null}
      </div>
    </Panel>
  );
}
