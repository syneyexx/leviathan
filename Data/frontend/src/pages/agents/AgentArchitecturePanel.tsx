import { useMemo } from "react";
import type {
  AgentDefinition,
  AgentsDashboardPool,
  SystemArchitectureEntry,
} from "../../types/api";
import { buildArchitectureTiers, statusTone, type ArchitectureNode, type TeamBucket } from "./helpers";
import { Glyph, LiveBadge, PanelHead } from "./agentsUi";

const TEAM_ICON: Record<TeamBucket, string> = {
  Research: "research",
  Development: "coding",
  Trading: "trading",
  Planning: "planner",
  Risk: "critic",
  Memory: "memory",
  Evaluation: "check",
  Vision: "media",
  Other: "default",
};

export type ArchitectureInfra = {
  capabilities: number;
  models: number;
  memoryLinked: number | null;
  knowledgeDocs: number;
  supervisorHealth: string | null;
  architecture: number;
};

function nodeTone(status: string): string {
  const s = status.toLowerCase();
  if (s === "ready" || s === "idle" || s === "online") return "ok";
  if (s === "busy") return "busy";
  if (s === "error" || s === "degraded") return "warn";
  if (s === "unknown") return "muted";
  return statusTone(status);
}

function orderPools(pools: AgentsDashboardPool[]): AgentsDashboardPool[] {
  return [...pools].sort(
    (a, b) =>
      b.ready + b.busy - (a.ready + a.busy) ||
      b.desired - a.desired ||
      a.poolId.localeCompare(b.poolId),
  );
}

export function AgentArchitecturePanel({
  agents,
  systemEntries,
  pools,
  workersAvailable,
  infra,
  selectedId,
  live,
  focused,
  onSelect,
  onOpenCore,
  onOpenPool,
  onClose,
}: {
  agents: AgentDefinition[];
  systemEntries: SystemArchitectureEntry[];
  pools: AgentsDashboardPool[];
  workersAvailable: boolean;
  infra: ArchitectureInfra;
  selectedId: string;
  live: boolean;
  focused?: boolean;
  onSelect: (id: string) => void;
  onOpenCore: () => void;
  onOpenPool: (poolId: string) => void;
  onClose?: () => void;
}) {
  const tiers = useMemo(
    () =>
      buildArchitectureTiers(agents, systemEntries, {
        maxOrchestrators: focused ? 8 : 4,
        maxSpecialists: focused ? 16 : 8,
      }),
    [agents, systemEntries, focused],
  );
  const shownPools = useMemo(() => orderPools(pools).slice(0, focused ? 16 : 8), [pools, focused]);
  const hiddenPools = Math.max(0, pools.length - shownPools.length);

  const selectedOrch = tiers.orchestrators.find((o) => o.id === selectedId);
  const linkedSpecialists = new Set(selectedOrch?.memberIds ?? []);
  const linkedOrchestrators = new Set(
    tiers.orchestrators.filter((o) => o.memberIds.includes(selectedId)).map((o) => o.id),
  );

  const coreCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of systemEntries) counts[e.status || "unknown"] = (counts[e.status || "unknown"] ?? 0) + 1;
    return counts;
  }, [systemEntries]);

  function nodeClass(node: ArchitectureNode, linked: boolean) {
    return [
      "lv-ag-arch-node",
      `is-${nodeTone(node.status)}`,
      node.source === "system" ? "is-system" : "",
      selectedId === node.id ? "is-selected" : "",
      linked ? "is-linked" : "",
    ]
      .filter(Boolean)
      .join(" ");
  }

  return (
    <section className={`lv-ag-panel lv-ag-arch${focused ? " is-focused" : ""}`}>
      <PanelHead
        title="Agent Architecture"
        subtitle="Hierarchy, worker pools & system integration"
        right={
          <>
            <LiveBadge live={live} />
            {onClose ? (
              <button type="button" className="lv-ag-btn-ghost is-xs" onClick={onClose}>
                Close
              </button>
            ) : null}
          </>
        }
      />
      <div className="lv-ag-arch-body">
        <div className="lv-ag-arch-rail" aria-hidden="true">
          <span>Core</span>
          <span>Orchestrators</span>
          <span>Specialist agents</span>
          <span>Worker pools</span>
          <span>Infrastructure</span>
        </div>
        <div className="lv-ag-arch-tree">
          <div className="lv-ag-arch-tier is-core">
            <button type="button" className="lv-ag-arch-core" onClick={onOpenCore} title="Open LEVIATHAN CORE inventory">
              <Glyph kind="core" className="lv-ag-arch-core-icon" />
              <strong>LEVIATHAN CORE</strong>
              <small>Global intelligence &amp; orchestration</small>
              <em>
                {systemEntries.length} components
                {Object.entries(coreCounts)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 3)
                  .map(([s, n]) => ` · ${n} ${s}`)
                  .join("")}
              </em>
            </button>
          </div>

          <div className="lv-ag-arch-tier is-orch">
            {tiers.orchestrators.length === 0 ? (
              <p className="lv-ag-arch-empty">No orchestrators registered</p>
            ) : (
              tiers.orchestrators.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={nodeClass(o, linkedOrchestrators.has(o.id))}
                  onClick={() => onSelect(o.id)}
                  title={`${o.label} · ${o.status}${o.memberIds.length ? ` · ${o.memberIds.length} members` : ""}`}
                >
                  <Glyph kind="planner" />
                  <span className="lv-ag-arch-node-text">
                    <strong>{o.label}</strong>
                    <small>{o.source === "system" ? `system · ${o.sublabel}` : o.sublabel}</small>
                  </span>
                  <i className="lv-ag-dot" />
                </button>
              ))
            )}
            {tiers.hiddenOrchestrators > 0 ? (
              <span className="lv-ag-arch-more">+{tiers.hiddenOrchestrators}</span>
            ) : null}
          </div>

          <div className="lv-ag-arch-tier is-spec">
            {tiers.specialists.length === 0 ? (
              <p className="lv-ag-arch-empty">No specialist agents match filters</p>
            ) : (
              tiers.specialists.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`${nodeClass(s, linkedSpecialists.has(s.id))} is-tile`}
                  onClick={() => onSelect(s.id)}
                  title={`${s.label} · ${s.team ?? ""} · ${s.status}`}
                >
                  <Glyph kind={TEAM_ICON[s.team ?? "Other"]} />
                  <strong>{s.label}</strong>
                  <i className="lv-ag-dot" />
                </button>
              ))
            )}
            {tiers.hiddenSpecialists > 0 ? (
              <span className="lv-ag-arch-more">+{tiers.hiddenSpecialists}</span>
            ) : null}
          </div>

          <div className="lv-ag-arch-tier is-pools">
            {!workersAvailable ? (
              <p className="lv-ag-arch-empty">Worker registry unavailable</p>
            ) : shownPools.length === 0 ? (
              <p className="lv-ag-arch-empty">No worker pools</p>
            ) : (
              shownPools.map((p) => {
                const live = p.ready + p.busy;
                return (
                  <button
                    key={p.poolId}
                    type="button"
                    className={`lv-ag-arch-pool${live > 0 ? " is-live" : ""}${p.degraded > 0 ? " is-warn" : ""}`}
                    onClick={() => onOpenPool(p.poolId)}
                    title={`${p.poolId}: ${p.ready} ready · ${p.busy} busy · desired ${p.desired} · max ${p.maxCount}`}
                  >
                    <span className="lv-ag-arch-pool-cells" aria-hidden="true">
                      {Array.from({ length: Math.min(8, Math.max(p.desired, live, 1)) }).map((_, i) => (
                        <i key={i} className={i < p.busy ? "is-busy" : i < live ? "is-ready" : ""} />
                      ))}
                    </span>
                    <strong>
                      {live}/{p.desired}
                    </strong>
                    <small>{p.poolId}</small>
                  </button>
                );
              })
            )}
            {hiddenPools > 0 ? <span className="lv-ag-arch-more">+{hiddenPools}</span> : null}
          </div>

          <div className="lv-ag-arch-tier is-infra">
            <div className="lv-ag-arch-infra">
              <Glyph kind="tools" />
              <span>
                <strong>Tools</strong>
                <small>{infra.capabilities} capabilities</small>
              </span>
            </div>
            <div className="lv-ag-arch-infra">
              <Glyph kind="models" />
              <span>
                <strong>Models</strong>
                <small>{infra.models} registered</small>
              </span>
            </div>
            <div className="lv-ag-arch-infra">
              <Glyph kind="memory" />
              <span>
                <strong>Memory</strong>
                <small>
                  {infra.memoryLinked ?? "—"} linked · {infra.knowledgeDocs} docs
                </small>
              </span>
            </div>
            <button type="button" className="lv-ag-arch-infra is-btn" onClick={onOpenCore}>
              <Glyph kind="runtime" />
              <span>
                <strong>Runtime</strong>
                <small>
                  {infra.architecture} components · sup {infra.supervisorHealth ?? "unknown"}
                </small>
              </span>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
