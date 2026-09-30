/**
 * Pure knowledge-workbench helpers over live Brain graph contracts.
 * Never invents passages, scores, or history from timestamps alone.
 */

import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";
import { isClaimEvidenceRelation } from "./brain-helix-engine";

export type Availability = "available" | "unavailable" | "unknown" | "partial";

export type EvidenceEdgeView = {
  edgeId: string;
  sourceId: string;
  targetId: string;
  relation: string;
  classification: string | null;
  isClaimEvidence: boolean;
  passage: string | null;
  locator: string | null;
  sourceTitle: string | null;
  status: Availability;
  note: string;
};

export type KnowledgeGapView = {
  id: string;
  nodeId: string;
  label: string;
  kind: "missing_support" | "contradiction" | "withdrawn_source" | "stale_review" | "truncated";
  reason: string;
  researchQuestion: string;
  severity: "low" | "medium" | "high";
};

export type FreshnessView = {
  nodeId: string;
  createdAt: string | null;
  updatedAt: string | null;
  lastVerifiedAt: string | null;
  retrievedAt: string | null;
  state: "current" | "stale" | "unknown" | "derived";
  label: string;
  days: number | null;
};

export type DependencyImpact = {
  sourceId: string;
  dependentIds: string[];
  truncated: boolean;
  note: string;
};

export type CompareInsightView = {
  aId: string;
  bId: string;
  supportingA: string[];
  supportingB: string[];
  contradictingA: string[];
  contradictingB: string[];
  shared: string[];
  provisional: string[];
  note: string;
};

const DEPENDENCY_RELATIONS = new Set([
  "SUPPORTS",
  "supports",
  "evidenced_by",
  "QUALIFIES",
  "qualifies",
  "depends_on",
  "derived_from",
  "from_run",
  "from_dataset",
]);

function metaString(meta: Record<string, unknown> | undefined, key: string): string | null {
  if (!meta) return null;
  const v = meta[key];
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function nodeMap(nodes: readonly LiveBrainNode[]): Map<string, LiveBrainNode> {
  return new Map(nodes.map((n) => [n.id, n]));
}

/** Edge evidence panel — never fabricates a quote. */
export function evidenceViewForEdge(
  edge: LiveBrainEdge | null,
  nodes: readonly LiveBrainNode[],
): EvidenceEdgeView | null {
  if (!edge) return null;
  const map = nodeMap(nodes);
  const source = map.get(edge.source);
  const claimEvidence = isClaimEvidenceRelation(edge.relation);
  const passage = metaString(source?.meta, "passage") ?? metaString(source?.meta, "excerpt");
  const locator =
    metaString(source?.meta, "locator") ??
    metaString(source?.meta, "uri") ??
    metaString(source?.meta, "source");

  if (!claimEvidence) {
    return {
      edgeId: edge.id,
      sourceId: edge.source,
      targetId: edge.target,
      relation: edge.relation,
      classification: null,
      isClaimEvidence: false,
      passage: null,
      locator,
      sourceTitle: source?.label ?? null,
      status: "available",
      note: `Associatie «${edge.relation}» — geen claim-evidence classificatie. Geen gegenereerde bronpassage.`,
    };
  }

  const hasPassage = Boolean(passage);
  return {
    edgeId: edge.id,
    sourceId: edge.source,
    targetId: edge.target,
    relation: edge.relation,
    classification: edge.relation.toUpperCase(),
    isClaimEvidence: true,
    passage: passage,
    locator,
    sourceTitle: source?.label ?? null,
    status: hasPassage ? "available" : "unknown",
    note: hasPassage
      ? "Bronpassage uit store-metadata."
      : "Passage / herkomst niet beschikbaar in deze projectie.",
  };
}

export function freshnessForNode(
  node: LiveBrainNode,
  opts: { nowMs: number; reviewEveryDays?: number | null },
): FreshnessView {
  const nowMs = opts.nowMs;
  const reviewEveryDays = opts.reviewEveryDays ?? null;
  const createdAt = node.created_at ?? metaString(node.meta, "created_at");
  const updatedAt = metaString(node.meta, "updated_at");
  const lastVerifiedAt =
    metaString(node.meta, "last_verified_at") ?? metaString(node.meta, "reviewed_at");
  const retrievedAt = metaString(node.meta, "retrieved_at");

  const t = node.type.toLowerCase();
  const derived =
    t.includes("hypothesis") ||
    t.includes("finding") ||
    t.includes("insight") ||
    t === "concept";

  if (derived && !lastVerifiedAt) {
    return {
      nodeId: node.id,
      createdAt,
      updatedAt,
      lastVerifiedAt,
      retrievedAt,
      state: "derived",
      label: "Afgeleid inzicht — verificatiedatum onbekend",
      days: null,
    };
  }

  if (!lastVerifiedAt) {
    return {
      nodeId: node.id,
      createdAt,
      updatedAt,
      lastVerifiedAt: null,
      retrievedAt,
      state: "unknown",
      label: "Controledatum onbekend (niet leeftijd 0)",
      days: null,
    };
  }

  const verifiedMs = Date.parse(lastVerifiedAt);
  if (!Number.isFinite(verifiedMs)) {
    return {
      nodeId: node.id,
      createdAt,
      updatedAt,
      lastVerifiedAt,
      retrievedAt,
      state: "unknown",
      label: "Controledatum onleesbaar",
      days: null,
    };
  }

  const days = Math.max(0, Math.floor((nowMs - verifiedMs) / 86_400_000));
  const limit = reviewEveryDays;
  if (limit == null) {
    return {
      nodeId: node.id,
      createdAt,
      updatedAt,
      lastVerifiedAt,
      retrievedAt,
      state: "unknown",
      label: `Laatst gecontroleerd · ${days} dagen geleden (termijn niet geconfigureerd)`,
      days,
    };
  }
  if (days > limit) {
    return {
      nodeId: node.id,
      createdAt,
      updatedAt,
      lastVerifiedAt,
      retrievedAt,
      state: "stale",
      label: `Hercontrole nodig · ${days} dagen (limiet ${limit})`,
      days,
    };
  }
  return {
    nodeId: node.id,
    createdAt,
    updatedAt,
    lastVerifiedAt,
    retrievedAt,
    state: "current",
    label: `Gecontroleerd · ${days} dagen geleden`,
    days,
  };
}

export function findKnowledgeGaps(
  nodes: readonly LiveBrainNode[],
  edges: readonly LiveBrainEdge[],
  opts?: { truncated?: boolean; maxNodes?: number | null },
): KnowledgeGapView[] {
  const map = nodeMap(nodes);
  const gaps: KnowledgeGapView[] = [];
  const truncated = Boolean(opts?.truncated);

  for (const node of nodes) {
    const role = node.type.toLowerCase();
    const looksInsight =
      role.includes("hypothesis") ||
      role.includes("finding") ||
      role.includes("claim") ||
      role === "concept" ||
      role === "research.project";
    if (!looksInsight) continue;

    const inbound = edges.filter((e) => e.target === node.id);
    const support = inbound.filter((e) => {
      const rel = e.relation.toUpperCase();
      return rel === "SUPPORTS" || rel === "EVIDENCED_BY" || e.relation === "evidenced_by";
    });
    const contradict = inbound.filter((e) => e.relation.toUpperCase() === "CONTRADICTS");
    const withdrawn = inbound.filter((e) => {
      const src = map.get(e.source);
      const status = metaString(src?.meta, "status")?.toLowerCase();
      return status === "withdrawn" || status === "revoked" || status === "retracted";
    });

    if (support.length === 0) {
      gaps.push({
        id: `gap:missing:${node.id}`,
        nodeId: node.id,
        label: node.label,
        kind: "missing_support",
        reason: truncated
          ? "Geen ondersteunende claim-evidence-edge in deze begrensde projectie (niet bewezen: bestaat nergens)."
          : "Geen SUPPORTS/evidenced_by-relatie naar deze node in de huidige graf.",
        researchQuestion: `Welke primaire bronnen ondersteunen «${node.label}»?`,
        severity: "high",
      });
    }
    if (contradict.length > 0) {
      gaps.push({
        id: `gap:conflict:${node.id}`,
        nodeId: node.id,
        label: node.label,
        kind: "contradiction",
        reason: `${contradict.length} CONTRADICTS-relatie(s) aanwezig — controle vereist.`,
        researchQuestion: `Wat verklaart het tegenbewijs tegen «${node.label}»?`,
        severity: "high",
      });
    }
    if (withdrawn.length > 0) {
      gaps.push({
        id: `gap:withdrawn:${node.id}`,
        nodeId: node.id,
        label: node.label,
        kind: "withdrawn_source",
        reason: "Afhankelijke bronstatus is withdrawn/revoked — herbeoordeling nodig (niet automatisch onwaar).",
        researchQuestion: `Herbeoordeel «${node.label}» na bronintrekking.`,
        severity: "medium",
      });
    }

    const fresh = freshnessForNode(node, { nowMs: Date.now() });
    if (fresh.state === "stale") {
      gaps.push({
        id: `gap:stale:${node.id}`,
        nodeId: node.id,
        label: node.label,
        kind: "stale_review",
        reason: fresh.label,
        researchQuestion: `Hercontroleer versheid van «${node.label}».`,
        severity: "medium",
      });
    }
  }

  if (truncated) {
    gaps.push({
      id: "gap:truncation",
      nodeId: "",
      label: "Begrensde projectie",
      kind: "truncated",
      reason: `Graph is begrensd${opts?.maxNodes != null ? ` (max ${opts.maxNodes} nodes)` : ""}. Ontbreken ≠ niet-bestaand.`,
      researchQuestion: "Vergroot of filter de Brain-projectie voor vollediger dekking.",
      severity: "low",
    });
  }

  return gaps;
}

/**
 * Traverse dependency-semantic edges only. Cycles bounded. Associations ignored.
 */
export function impactedDependents(
  sourceId: string,
  edges: readonly LiveBrainEdge[],
  opts?: { maxDepth?: number; maxNodes?: number },
): DependencyImpact {
  const maxDepth = opts?.maxDepth ?? 4;
  const maxNodes = opts?.maxNodes ?? 40;
  const seen = new Set<string>([sourceId]);
  const out: string[] = [];
  let queue: Array<{ id: string; depth: number }> = [{ id: sourceId, depth: 0 }];
  let truncated = false;

  while (queue.length) {
    const { id, depth } = queue.shift()!;
    if (depth >= maxDepth) {
      truncated = true;
      continue;
    }
    for (const e of edges) {
      if (e.source !== id) continue;
      if (!DEPENDENCY_RELATIONS.has(e.relation) && !DEPENDENCY_RELATIONS.has(e.relation.toUpperCase())) {
        continue;
      }
      if (seen.has(e.target)) continue;
      seen.add(e.target);
      out.push(e.target);
      if (out.length >= maxNodes) {
        truncated = true;
        return {
          sourceId,
          dependentIds: out,
          truncated: true,
          note: "Afhankelijkheden begrensd — association-edges zijn genegeerd.",
        };
      }
      queue.push({ id: e.target, depth: depth + 1 });
    }
  }

  return {
    sourceId,
    dependentIds: out,
    truncated,
    note: truncated
      ? "Traversale diepte begrensd; cycli overgeslagen."
      : "Alleen dependency-semantische relaties getraverseerd.",
  };
}

export function compareInsights(
  aId: string,
  bId: string,
  edges: readonly LiveBrainEdge[],
): CompareInsightView {
  const sourcesFor = (target: string, rel: string) =>
    edges
      .filter((e) => e.target === target && e.relation.toUpperCase() === rel.toUpperCase())
      .map((e) => e.source);

  const supportingA = sourcesFor(aId, "SUPPORTS");
  const supportingB = sourcesFor(bId, "SUPPORTS");
  const contradictingA = sourcesFor(aId, "CONTRADICTS");
  const contradictingB = sourcesFor(bId, "CONTRADICTS");
  const provisionalA = sourcesFor(aId, "INSUFFICIENT").concat(sourcesFor(aId, "QUALIFIES"));
  const provisionalB = sourcesFor(bId, "INSUFFICIENT").concat(sourcesFor(bId, "QUALIFIES"));
  const setA = new Set(supportingA);
  const shared = supportingB.filter((id) => setA.has(id));

  return {
    aId,
    bId,
    supportingA,
    supportingB,
    contradictingA,
    contradictingB,
    shared,
    provisional: [...new Set([...provisionalA, ...provisionalB])],
    note: "Edge-aantallen zijn geen waarheidsscore. Alleen gemeten classificaties getoond.",
  };
}

export function memoryScopeLabel(scope: string | null | undefined): string {
  if (!scope) return "Onbekend";
  const s = scope.toUpperCase();
  switch (s) {
    case "CONVERSATION":
      return "Gesprek";
    case "PROJECT":
      return "Project";
    case "USER":
      return "Persoonlijk / gebruiker";
    case "GLOBAL":
      return "Globaal";
    case "WORKSPACE":
      return "Werkruimte";
    case "ORCHESTRATOR_SHARED":
      return "Gedeeld (orchestrator)";
    case "AGENT_PRIVATE":
      return "Agent-privé";
    default:
      return scope;
  }
}

export function scopeFromNode(node: LiveBrainNode | null): string | null {
  if (!node) return null;
  return metaString(node.meta, "scope");
}
