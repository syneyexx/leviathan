/**
 * Research workbench tabs inside Kennis Netwerk — real contracts only.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button } from "../../components/ui";
import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";
import {
  compareInsights,
  evidenceViewForEdge,
  findKnowledgeGaps,
  freshnessForNode,
  impactedDependents,
  memoryScopeLabel,
  scopeFromNode,
  type KnowledgeGapView,
} from "./brain-knowledge-model";

export type WorkbenchTab =
  | "evidence"
  | "gaps"
  | "hypotheses"
  | "agents"
  | "history"
  | "memory";

export type ResearchActionState = {
  status: "idle" | "pending" | "running" | "blocked" | "unavailable" | "failed" | "cancelled" | "complete";
  jobId: string | null;
  projectId: string | null;
  message: string;
};

type Props = {
  nodes: readonly LiveBrainNode[];
  edges: readonly LiveBrainEdge[];
  selectedId: string | null;
  selectedEdgeId: string | null;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (id: string | null) => void;
  graphTruncated: boolean;
  graphMaxNodes: number | null;
  historyAvailable: boolean;
  researchAction: ResearchActionState;
  onStartResearch: (gap: KnowledgeGapView, action: "verify" | "counter" | "expand") => void;
  onMemoryAction: (
    action: "archive" | "revoke",
    memoryId: string,
  ) => Promise<{ ok: boolean; message: string }>;
};

const TABS: { id: WorkbenchTab; label: string }[] = [
  { id: "evidence", label: "Bewijs" },
  { id: "gaps", label: "Kennishiaten" },
  { id: "hypotheses", label: "Vergelijken" },
  { id: "agents", label: "Agents" },
  { id: "history", label: "Wijzigingen" },
  { id: "memory", label: "Bewaren" },
];

export function BrainNetworkWorkbench({
  nodes,
  edges,
  selectedId,
  selectedEdgeId,
  onSelectNode,
  onSelectEdge,
  graphTruncated,
  graphMaxNodes,
  historyAvailable,
  researchAction,
  onStartResearch,
  onMemoryAction,
}: Props) {
  const [tab, setTab] = useState<WorkbenchTab>("evidence");
  const [compareA, setCompareA] = useState<string>("");
  const [compareB, setCompareB] = useState<string>("");
  const [memoryMsg, setMemoryMsg] = useState<string | null>(null);
  const [memoryPending, setMemoryPending] = useState(false);

  const selected = nodes.find((n) => n.id === selectedId) ?? null;
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId) ?? null;
  const evidence = useMemo(
    () => evidenceViewForEdge(selectedEdge, nodes),
    [selectedEdge, nodes],
  );
  const gaps = useMemo(
    () => findKnowledgeGaps(nodes, edges, { truncated: graphTruncated, maxNodes: graphMaxNodes }),
    [nodes, edges, graphTruncated, graphMaxNodes],
  );
  const insights = useMemo(
    () =>
      nodes.filter((n) => {
        const t = n.type.toLowerCase();
        return (
          t.includes("hypothesis") ||
          t.includes("finding") ||
          t.includes("claim") ||
          t === "concept" ||
          t === "research.project"
        );
      }),
    [nodes],
  );

  const compare = useMemo(() => {
    const a = compareA || insights[0]?.id || "";
    const b = compareB || insights[1]?.id || insights[0]?.id || "";
    if (!a || !b) return null;
    return compareInsights(a, b, edges);
  }, [compareA, compareB, insights, edges]);

  const impact = useMemo(() => {
    if (!selectedId) return null;
    return impactedDependents(selectedId, edges);
  }, [selectedId, edges]);

  const freshness = selected ? freshnessForNode(selected, { nowMs: Date.now() }) : null;
  const scope = scopeFromNode(selected);

  const relatedEdges = useMemo(() => {
    if (!selectedId) return edges.slice(0, 12);
    return edges.filter((e) => e.source === selectedId || e.target === selectedId);
  }, [edges, selectedId]);

  return (
    <section className="lv-v2-brain-workbench" aria-label="Research workbench">
      <div className="lv-v2-brain-workbench__head">
        <span className="lv-v2-eyebrow">Research Workbench</span>
      </div>
      <div className="lv-v2-brain-workbench__tabs" role="tablist" aria-label="Onderzoekstools">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`lv-v2-brain-workbench__tab${tab === t.id ? " is-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === "gaps" && gaps.length > 0 ? (
              <span className="lv-v2-brain-workbench__count">{gaps.length}</span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="lv-v2-brain-workbench__body" aria-live="polite">
        {tab === "evidence" ? (
          <div className="lv-v2-brain-workbench__panel">
            <p className="lv-v2-muted">
              Klik een echte relatie in de visualisatie of kies er een hieronder. Passages worden
              nooit verzonnen.
            </p>
            <div className="lv-v2-brain-workbench__edge-list">
              {relatedEdges.length === 0 ? (
                <p className="lv-v2-muted">Geen edges in deze projectie.</p>
              ) : (
                relatedEdges.map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    className={`lv-v2-brain-workbench__edge${e.id === selectedEdgeId ? " is-active" : ""}`}
                    onClick={() => onSelectEdge(e.id)}
                  >
                    <span>{e.relation}</span>
                    <span className="lv-v2-muted">
                      {e.source.slice(0, 24)} → {e.target.slice(0, 24)}
                    </span>
                  </button>
                ))
              )}
            </div>
            {evidence ? (
              <dl className="lv-v2-brain-workbench__dl">
                <div>
                  <dt>Relatie</dt>
                  <dd>
                    {evidence.classification ?? evidence.relation}
                    {!evidence.isClaimEvidence ? (
                      <Badge tone="warning">associatie</Badge>
                    ) : (
                      <Badge tone="info">{evidence.classification}</Badge>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Bron</dt>
                  <dd>{evidence.sourceTitle ?? evidence.sourceId}</dd>
                </div>
                <div>
                  <dt>Locator</dt>
                  <dd>{evidence.locator ?? "Niet beschikbaar / onbekend"}</dd>
                </div>
                <div>
                  <dt>Passage</dt>
                  <dd className="lv-v2-brain-workbench__passage">
                    {evidence.passage ?? "Niet beschikbaar / onbekend"}
                  </dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>
                    {evidence.status} — {evidence.note}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="lv-v2-muted">Geen relatie geselecteerd.</p>
            )}
          </div>
        ) : null}

        {tab === "gaps" ? (
          <div className="lv-v2-brain-workbench__panel">
            {gaps.length === 0 ? (
              <p className="lv-v2-muted">Geen expliciete hiaten in deze begrensde projectie.</p>
            ) : (
              <ul className="lv-v2-brain-workbench__gaps">
                {gaps.map((g) => (
                  <li key={g.id}>
                    <div>
                      <strong>{g.label || g.kind}</strong>
                      <p>{g.reason}</p>
                      <p className="lv-v2-muted">{g.researchQuestion}</p>
                    </div>
                    <div className="lv-v2-brain-workbench__gap-actions">
                      {g.nodeId ? (
                        <Button variant="secondary" size="sm" onClick={() => onSelectNode(g.nodeId)}>
                          Selecteer
                        </Button>
                      ) : null}
                      <Button
                        variant="primary"
                        size="sm"
                        disabled={researchAction.status === "pending" || researchAction.status === "running"}
                        onClick={() => onStartResearch(g, "verify")}
                      >
                        Onderzoek starten
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {tab === "hypotheses" ? (
          <div className="lv-v2-brain-workbench__panel">
            {insights.length < 1 ? (
              <p className="lv-v2-muted">
                Geen inzicht-/hypothese-nodes in deze projectie om te vergelijken.
              </p>
            ) : (
              <>
                <div className="lv-v2-brain-workbench__compare-pick">
                  <label>
                    Inzicht A
                    <select
                      value={compareA || insights[0]?.id || ""}
                      onChange={(e) => setCompareA(e.target.value)}
                    >
                      {insights.map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Inzicht B
                    <select
                      value={compareB || insights[1]?.id || insights[0]?.id || ""}
                      onChange={(e) => setCompareB(e.target.value)}
                    >
                      {insights.map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {compare ? (
                  <dl className="lv-v2-brain-workbench__dl">
                    <div>
                      <dt>Ondersteunend A</dt>
                      <dd>{compare.supportingA.length || "0"}</dd>
                    </div>
                    <div>
                      <dt>Ondersteunend B</dt>
                      <dd>{compare.supportingB.length || "0"}</dd>
                    </div>
                    <div>
                      <dt>Tegensprekend A / B</dt>
                      <dd>
                        {compare.contradictingA.length} / {compare.contradictingB.length}
                      </dd>
                    </div>
                    <div>
                      <dt>Gedeelde bronnen</dt>
                      <dd>{compare.shared.length ? compare.shared.join(", ") : "Geen"}</dd>
                    </div>
                    <div>
                      <dt>Voorlopig (QUALIFIES/INSUFFICIENT)</dt>
                      <dd>{compare.provisional.length || "0"}</dd>
                    </div>
                    <div>
                      <dt>Toelichting</dt>
                      <dd>{compare.note}</dd>
                    </div>
                  </dl>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {tab === "agents" ? (
          <div className="lv-v2-brain-workbench__panel">
            <p>
              Status: <Badge tone="info">{researchAction.status}</Badge>
            </p>
            <p className="lv-v2-muted">{researchAction.message}</p>
            {researchAction.jobId ? (
              <p>
                Job: <code>{researchAction.jobId}</code>
              </p>
            ) : null}
            {researchAction.projectId ? (
              <p>
                <Link className="lv-v2-brain-link" to={`/research?project=${encodeURIComponent(researchAction.projectId)}`}>
                  Open researchproject
                </Link>
              </p>
            ) : null}
            <div className="lv-v2-brain-workbench__gap-actions">
              <Button
                variant="secondary"
                size="sm"
                disabled={!selected || researchAction.status === "pending" || researchAction.status === "running"}
                onClick={() =>
                  selected &&
                  onStartResearch(
                    {
                      id: `act:verify:${selected.id}`,
                      nodeId: selected.id,
                      label: selected.label,
                      kind: "missing_support",
                      reason: "Operator startte Verifieer",
                      researchQuestion: `Verifieer «${selected.label}»`,
                      severity: "medium",
                    },
                    "verify",
                  )
                }
              >
                Verifieer
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!selected || researchAction.status === "pending" || researchAction.status === "running"}
                onClick={() =>
                  selected &&
                  onStartResearch(
                    {
                      id: `act:counter:${selected.id}`,
                      nodeId: selected.id,
                      label: selected.label,
                      kind: "contradiction",
                      reason: "Operator startte Zoek tegenbewijs",
                      researchQuestion: `Zoek tegenbewijs voor «${selected.label}»`,
                      severity: "high",
                    },
                    "counter",
                  )
                }
              >
                Zoek tegenbewijs
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!selected || researchAction.status === "pending" || researchAction.status === "running"}
                onClick={() =>
                  selected &&
                  onStartResearch(
                    {
                      id: `act:expand:${selected.id}`,
                      nodeId: selected.id,
                      label: selected.label,
                      kind: "missing_support",
                      reason: "Operator startte Werk uit",
                      researchQuestion: `Werk «${selected.label}» verder uit`,
                      severity: "medium",
                    },
                    "expand",
                  )
                }
              >
                Werk uit
              </Button>
            </div>
            <p className="lv-v2-muted">
              Succes = echte job/run-id en fase uit ResearchService — geen timer-simulatie.
            </p>
          </div>
        ) : null}

        {tab === "history" ? (
          <div className="lv-v2-brain-workbench__panel">
            {historyAvailable ? (
              <p className="lv-v2-muted">Historische snapshots worden hier geladen wanneer beschikbaar.</p>
            ) : (
              <p>
                Historische graph-snapshots zijn <strong>niet beschikbaar</strong> via het huidige
                Brain-contract. Geen reconstructie uit <code>created_at</code>.
              </p>
            )}
          </div>
        ) : null}

        {tab === "memory" ? (
          <div className="lv-v2-brain-workbench__panel">
            {!selected ? (
              <p className="lv-v2-muted">Selecteer een node.</p>
            ) : (
              <>
                <dl className="lv-v2-brain-workbench__dl">
                  <div>
                    <dt>Scope</dt>
                    <dd>{memoryScopeLabel(scope)} (UI-filter ≠ autorisatiegrens)</dd>
                  </div>
                  <div>
                    <dt>Versheid</dt>
                    <dd>{freshness?.label ?? "Onbekend"}</dd>
                  </div>
                  <div>
                    <dt>created_at</dt>
                    <dd>{freshness?.createdAt ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>updated_at</dt>
                    <dd>{freshness?.updatedAt ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>last_verified_at</dt>
                    <dd>{freshness?.lastVerifiedAt ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>retrieved_at</dt>
                    <dd>{freshness?.retrievedAt ?? "—"}</dd>
                  </div>
                </dl>
                {impact ? (
                  <div>
                    <h4>Afhankelijkheden bij intrekking</h4>
                    <p className="lv-v2-muted">{impact.note}</p>
                    {impact.dependentIds.length === 0 ? (
                      <p className="lv-v2-muted">Geen dependency-semantische nakomelingen.</p>
                    ) : (
                      <ul>
                        {impact.dependentIds.map((id) => (
                          <li key={id}>
                            <button type="button" className="lv-v2-brain-link" onClick={() => onSelectNode(id)}>
                              {nodes.find((n) => n.id === id)?.label ?? id}
                            </button>{" "}
                            — markeer voor herbeoordeling (niet automatisch onwaar)
                          </li>
                        ))}
                      </ul>
                    )}
                    {impact.truncated ? <p className="lv-v2-muted">Traversale begrensd.</p> : null}
                  </div>
                ) : null}
                {selected.type === "memory" || selected.id.startsWith("memory:") ? (
                  <div className="lv-v2-brain-workbench__gap-actions">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={memoryPending}
                      onClick={() => {
                        const mid = selected.id.replace(/^memory:/, "");
                        setMemoryPending(true);
                        void onMemoryAction("archive", mid).then((r) => {
                          setMemoryMsg(r.message);
                          setMemoryPending(false);
                        });
                      }}
                    >
                      Archiveer geheugen
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={memoryPending}
                      onClick={() => {
                        const mid = selected.id.replace(/^memory:/, "");
                        setMemoryPending(true);
                        void onMemoryAction("revoke", mid).then((r) => {
                          setMemoryMsg(r.message);
                          setMemoryPending(false);
                        });
                      }}
                    >
                      Trek in (revoke)
                    </Button>
                    <Link className="lv-v2-brain-link" to="/memory">
                      Open Geheugen
                    </Link>
                  </div>
                ) : (
                  <p className="lv-v2-muted">
                    Bewaar-/scope-mutaties gelden voor Memory-nodes via de canonieke Memory-API.
                    Deze node is type «{selected.type}».
                  </p>
                )}
                {memoryMsg ? <p>{memoryMsg}</p> : null}
              </>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** Helper used by section to create research projects via real API. */
export async function startResearchFromGap(
  gap: KnowledgeGapView,
  action: "verify" | "counter" | "expand",
): Promise<ResearchActionState> {
  const topic =
    action === "counter"
      ? `Tegenbewijs: ${gap.researchQuestion}`
      : action === "expand"
        ? `Uitwerken: ${gap.researchQuestion}`
        : gap.researchQuestion;
  try {
    const created = await api.createResearchProject({
      topic,
      title: topic.slice(0, 120),
      depth: "quick",
      allowWeb: false,
    });
    const projectId = created.project?.project_id;
    if (!projectId) {
      return {
        status: "failed",
        jobId: null,
        projectId: null,
        message: "Research create gaf geen project_id terug.",
      };
    }
    try {
      const planned = await api.planResearchProject(projectId, {});
      if (planned.queued === true) {
        const plannedJob =
          typeof planned.job_id === "string"
            ? planned.job_id
            : typeof planned.job?.job_id === "string"
              ? String(planned.job.job_id)
              : typeof (planned.job as { jobId?: unknown } | undefined)?.jobId === "string"
                ? String((planned.job as { jobId?: string }).jobId)
                : null;
        if (plannedJob) {
          return {
            status: "running",
            jobId: plannedJob,
            projectId,
            message: `Plan gequeued (job ${plannedJob}).`,
          };
        }
      }
      const run = await api.runResearchProject(projectId);
      const runRecord = run as { job_id?: unknown; job?: { job_id?: unknown } };
      const runJob =
        typeof runRecord.job_id === "string"
          ? runRecord.job_id
          : typeof runRecord.job?.job_id === "string"
            ? runRecord.job.job_id
            : null;
      return {
        status: runJob ? "running" : "complete",
        jobId: runJob,
        projectId,
        message: runJob
          ? `Research run gestart (job ${runJob}).`
          : "Researchproject aangemaakt en run aangevraagd.",
      };
    } catch (err) {
      return {
        status: "failed",
        jobId: null,
        projectId,
        message: `Project ${projectId} aangemaakt; plan/run: ${err instanceof Error ? err.message : "mislukt"}`,
      };
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Research API unavailable";
    const unavailable = /404|503|not found|unavailable/i.test(msg);
    return {
      status: unavailable ? "unavailable" : "failed",
      jobId: null,
      projectId: null,
      message: msg,
    };
  }
}
