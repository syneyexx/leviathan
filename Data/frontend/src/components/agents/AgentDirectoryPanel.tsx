import { useEffect, useMemo } from "react";
import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import { healthLabel, isArchitectureEntry, statusTone, teamBucketForAgent } from "../../pages/agents/helpers";
import { Badge, EmptyState, Panel, StatusDot } from "../ui";

type Props = {
  ws: AgentsWorkspace;
};

function roleTone(agent: { kind?: string; role?: string; tags?: string[] }): "research" | "trading" | "training" | "data" | "system" | "info" | "warning" | "muted" {
  const team = teamBucketForAgent(agent as Parameters<typeof teamBucketForAgent>[0]);
  if (team === "Research") return "research";
  if (team === "Trading") return "trading";
  if (team === "Development") return "info";
  if (team === "Risk") return "warning";
  if (team === "Memory" || team === "Evaluation") return "data";
  if (team === "Planning") return "system";
  return "muted";
}

function statusDotTone(label: string): "success" | "warning" | "danger" | "muted" | "info" {
  const t = statusTone(label);
  if (t === "ok") return "success";
  if (t === "warn") return "warning";
  if (t === "muted" || t === "off") return "muted";
  return "info";
}

export function AgentDirectoryPanel({ ws }: Props) {
  const {
    tableAgents,
    selectedAgentId,
    setSelectedAgentId,
    filters,
    setFilters,
    filterOptions,
    showAll,
    setShowAll,
    liveFleet,
    rosterUniverse,
    directorySearchRef,
    directoryFocusToken,
  } = ws;

  const totalCount = showAll ? rosterUniverse.length : liveFleet.length;

  useEffect(() => {
    if (!directoryFocusToken) return;
    directorySearchRef.current?.focus();
  }, [directoryFocusToken, directorySearchRef]);

  const typeFilter = filters.role !== "All Roles" ? filters.role : "all";

  const rows = useMemo(() => tableAgents, [tableAgents]);

  return (
    <Panel
      className="lv-v2-agents-directory"
      title="Agent Directory"
      meta={`${rows.length}${rows.length !== totalCount ? ` / ${totalCount}` : ""} agents`}
      action={
        <div className="lv-v2-agents-directory__tools">
          <input
            ref={directorySearchRef}
            type="search"
            className="lv-v2-input lv-v2-agents-directory__search"
            placeholder="Zoek agent…"
            value={filters.query || ""}
            onChange={(e) => setFilters({ ...filters, query: e.target.value })}
            aria-label="Zoek agents"
          />
          <select
            className="lv-v2-select"
            aria-label="Filter op rol"
            value={typeFilter}
            onChange={(e) =>
              setFilters({
                ...filters,
                role: e.target.value === "all" ? "All Roles" : e.target.value,
              })
            }
          >
            <option value="all">Alle types</option>
            {filterOptions.roles
              .filter((r) => r !== "All Roles")
              .map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
          </select>
          <button type="button" className="lv-v2-link-btn" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Fleet only" : "Incl. arch"}
          </button>
        </div>
      }
    >
      <div className="lv-v2-agents-filters" aria-label="Extra filters">
        <select
          className="lv-v2-select is-compact"
          aria-label="Team"
          value={filters.team}
          onChange={(e) => setFilters({ ...filters, team: e.target.value })}
        >
          {filterOptions.teams.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          className="lv-v2-select is-compact"
          aria-label="Status"
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
        >
          {filterOptions.statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          className="lv-v2-select is-compact"
          aria-label="Model"
          value={filters.model}
          onChange={(e) => setFilters({ ...filters, model: e.target.value })}
        >
          {filterOptions.models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <select
          className="lv-v2-select is-compact"
          aria-label="Environment"
          value={filters.environment}
          onChange={(e) => setFilters({ ...filters, environment: e.target.value })}
        >
          {filterOptions.environments.map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>
      </div>

      <div className="lv-v2-table-wrap">
        <table className="lv-v2-table lv-v2-agents-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Status</th>
              <th>Rol</th>
              <th>Beschrijving</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4}>
                  <EmptyState
                    title={totalCount === 0 ? "Geen agents" : "Geen matches"}
                    detail={totalCount === 0 ? "Maak een agent aan om te beginnen." : "Pas filters of zoekterm aan."}
                  />
                </td>
              </tr>
            ) : (
              rows.map((agent) => {
                const label = healthLabel(agent);
                const arch = isArchitectureEntry(agent);
                const dutchStatus =
                  label === "Busy"
                    ? "Bezig"
                    : label === "Idle" || label === "Online"
                      ? "Actief"
                      : label === "Offline"
                        ? "Offline"
                        : label === "Unknown"
                          ? "Onbekend"
                          : label;
                return (
                  <tr
                    key={agent.agentId}
                    className={selectedAgentId === agent.agentId ? "is-selected" : ""}
                    onClick={() => setSelectedAgentId(agent.agentId)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedAgentId(agent.agentId);
                      }
                    }}
                    tabIndex={0}
                    aria-selected={selectedAgentId === agent.agentId}
                  >
                    <td>
                      <span className="lv-v2-agents-name">
                        <span className="lv-v2-agents-name__glyph" aria-hidden="true">
                          {(agent.name || "?").slice(0, 1).toUpperCase()}
                        </span>
                        <span className="lv-v2-agents-name__text" title={agent.name}>
                          {agent.name}
                        </span>
                        {arch || agent.origin === "system" ? (
                          <Badge tone="system">SYS</Badge>
                        ) : null}
                      </span>
                    </td>
                    <td>
                      <span className="lv-v2-agents-status">
                        <StatusDot tone={statusDotTone(label)} />
                        {dutchStatus}
                      </span>
                    </td>
                    <td>
                      <Badge tone={roleTone(agent)}>{agent.role || String(agent.kind)}</Badge>
                    </td>
                    <td className="lv-v2-agents-desc" title={agent.description || undefined}>
                      {agent.description || "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
