import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import { buildArchitectureTiers, type TeamBucket } from "../../pages/agents/helpers";
import { Button, EmptyState, Panel, StatusDot } from "../ui";

type Props = { ws: AgentsWorkspace };

const TEAM_LABEL: Partial<Record<TeamBucket, string>> = {
  Research: "Research",
  Development: "Coding",
  Trading: "Trading",
  Planning: "Planning",
  Risk: "Risk",
  Memory: "Memory",
  Evaluation: "Evaluation",
  Vision: "Browser",
  Other: "Other",
};

export function AgentsArchitecturePanel({ ws }: Props) {
  const {
    archFleet,
    systemEntries,
    pools,
    workersSummary,
    infra,
    selectedAgentId,
    setSelectedAgentId,
    setSpawnPoolId,
    setCoreOpen,
    setArchView,
    live,
  } = ws;

  const tiers = useMemo(
    () => buildArchitectureTiers(archFleet, systemEntries, { maxOrchestrators: 4, maxSpecialists: 10 }),
    [archFleet, systemEntries],
  );

  const shownPools = useMemo(
    () =>
      [...pools]
        .sort((a, b) => b.ready + b.busy - (a.ready + a.busy) || a.poolId.localeCompare(b.poolId))
        .slice(0, 6),
    [pools],
  );

  const selectedOrch = tiers.orchestrators.find((o) => o.id === selectedAgentId);
  const linkedSpecialists = new Set(selectedOrch?.memberIds ?? []);

  return (
    <Panel
      className="lv-v2-agents-arch"
      title="Agent Architectuur"
      meta={live ? "Live" : "Stale"}
      action={
        <Button variant="ghost" size="sm" onClick={() => setArchView(true)}>
          Volledig overzicht
        </Button>
      }
    >
      <div className="lv-v2-agents-arch__flow" aria-label="Agent ecosystem">
        <div className="lv-v2-agents-arch__tier">
          <h4>Input</h4>
          <div className="lv-v2-agents-arch__nodes">
            <span className="lv-v2-agents-arch__pill">Gebruiker</span>
            <span className="lv-v2-agents-arch__pill">Scheduler</span>
            <span className="lv-v2-agents-arch__pill">Externe triggers</span>
          </div>
        </div>

        <div className="lv-v2-agents-arch__tier is-hub">
          <h4>Orchestratie</h4>
          <button
            type="button"
            className="lv-v2-agents-arch__hub"
            onClick={() => setCoreOpen(true)}
            title="Open LEVIATHAN CORE inventory"
          >
            <strong>Agent Orchestrator</strong>
            <small>
              Mission Queue · {systemEntries.length} system components ·{" "}
              {tiers.orchestrators.length} orchestrators
            </small>
          </button>
          <div className="lv-v2-agents-arch__nodes">
            <span className="lv-v2-agents-arch__pill">Missie Queue</span>
            <span className="lv-v2-agents-arch__pill">
              Agent Memory · {infra.memoryLinked ?? "—"} linked
            </span>
            <Link className="lv-v2-agents-arch__pill is-link" to="/knowledge">
              Knowledge · {infra.knowledgeDocs}
            </Link>
          </div>
          {tiers.orchestrators.length ? (
            <div className="lv-v2-agents-arch__nodes">
              {tiers.orchestrators.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={`lv-v2-agents-arch__node${selectedAgentId === o.id ? " is-selected" : ""}`}
                  onClick={() => setSelectedAgentId(o.id)}
                >
                  <StatusDot tone={o.status === "busy" ? "warning" : "success"} />
                  {o.label}
                </button>
              ))}
            </div>
          ) : (
            <EmptyState title="Geen orchestrators" detail="Fleet of system inventory leeg." />
          )}
        </div>

        <div className="lv-v2-agents-arch__tier">
          <h4>Specialisten</h4>
          <div className="lv-v2-agents-arch__nodes is-tiles">
            {tiers.specialists.length === 0 ? (
              <span className="lv-v2-agents-muted">Geen specialisten</span>
            ) : (
              tiers.specialists.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`lv-v2-agents-arch__tile${selectedAgentId === s.id ? " is-selected" : ""}${
                    linkedSpecialists.has(s.id) ? " is-linked" : ""
                  }`}
                  onClick={() => setSelectedAgentId(s.id)}
                  title={`${s.label} · ${s.team ?? ""} · ${s.status}`}
                >
                  <strong>{s.label}</strong>
                  <small>{TEAM_LABEL[s.team ?? "Other"] || s.team}</small>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="lv-v2-agents-arch__tier">
          <h4>Tools &amp; Resources</h4>
          <div className="lv-v2-agents-arch__nodes">
            <Link className="lv-v2-agents-arch__pill is-link" to="/models">
              LM Models · {infra.models}
            </Link>
            <Link className="lv-v2-agents-arch__pill is-link" to="/datasets">
              Datasets
            </Link>
            <Link className="lv-v2-agents-arch__pill is-link" to="/tools">
              Tools · {infra.capabilities}
            </Link>
            <Link className="lv-v2-agents-arch__pill is-link" to="/mcp">
              MCP
            </Link>
            <span className="lv-v2-agents-arch__pill">
              Workers ·{" "}
              {workersSummary?.available
                ? `${workersSummary.active ?? "—"} active`
                : "UNAVAILABLE"}
            </span>
          </div>
          {workersSummary?.available && shownPools.length > 0 ? (
            <div className="lv-v2-agents-arch__nodes is-pools">
              {shownPools.map((p) => (
                <button
                  key={p.poolId}
                  type="button"
                  className="lv-v2-agents-arch__pool"
                  onClick={() => setSpawnPoolId(p.poolId)}
                  title={`${p.poolId}: ready ${p.ready} · busy ${p.busy}`}
                >
                  <strong>
                    {p.ready + p.busy}/{p.desired}
                  </strong>
                  <small>{p.poolId}</small>
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="lv-v2-agents-arch__tier">
          <h4>Externe Systemen</h4>
          <div className="lv-v2-agents-arch__nodes">
            <span className="lv-v2-agents-arch__pill">Exchange APIs</span>
            <span className="lv-v2-agents-arch__pill">Data Providers</span>
            <span className="lv-v2-agents-arch__pill">Cloud Services</span>
          </div>
        </div>
      </div>
    </Panel>
  );
}
