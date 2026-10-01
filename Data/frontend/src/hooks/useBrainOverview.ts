/**
 * Brain V2 overview orchestration — independent, isolated fetches.
 * Never uses Screen 1 fixture numbers as production defaults.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { loadBrainCatalog } from "../pages/brain/brain-catalog";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import { classifyRawStatus, mapMeasuredComponentStatus } from "../lib/statusTruth";
import type {
  EvidenceRecord,
  HealthResponse,
  MemoryRecord,
  WorkerFabricDashboard,
  WorkerFabricJobSummary,
} from "../types/api";
import {
  categoryForNode,
  type BrainCategoryFilter,
  type BrainSemanticCategory,
} from "../pages/brain/brain-categories";
import {
  buildClusters,
  buildTimeline,
  type ClusterRow,
  type LiveBrainEdge,
  type LiveBrainNode,
  type TimelineEvent,
} from "../pages/brain/brain-live";

const GRAPH_INTERVAL_MS = 60_000;
const QUEUE_INTERVAL_MS = 12_000;
const HEALTH_INTERVAL_MS = 20_000;
const ACTIVITY_INTERVAL_MS = 45_000;
const EVIDENCE_FETCH_LIMIT = 200;
const MEMORY_FETCH_LIMIT = 100;

export type BrainStatusTone = SidebarStatusRow["tone"];

export type BrainMetricCell = {
  value: number | null;
  sublabel: string;
  available: boolean;
  loading: boolean;
};

export type BrainReasoningJob = {
  id: string;
  title: string;
  state: string;
  stateTone: "info" | "warning" | "success" | "muted";
  progress: number | null;
  elapsed: string;
};

export type BrainActivityRow = {
  id: string;
  time: string;
  description: string;
  badge: string;
  tone: "research" | "info" | "success" | "warning" | "data" | "muted";
};

export type BrainEntityTypeRow = {
  id: string;
  label: string;
  count: number;
  pct: number;
  category: BrainSemanticCategory;
};

export type BrainHealthGauge = {
  id: string;
  label: string;
  /** Measured percent, or null when only categorical health exists. */
  value: number | null;
  statusLabel: string;
  available: boolean;
};

export type BrainOverview = {
  loading: boolean;
  refreshing: boolean;
  refresh: () => Promise<void>;
  online: boolean | null;
  sidebarStatus: SidebarStatusRow[];

  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  stats: {
    node_count: number;
    edge_count: number;
    by_type: Record<string, number>;
    by_relation: Record<string, number>;
    /** Optional — present only when backend/fixture provides a corpus-level cluster total. */
    cluster_count?: number;
    /** Optional — present only when backend/fixture provides a corpus-level evidence total. */
    evidence_count?: number;
  } | null;
  graphTruth: Record<string, boolean> | null;
  graphError: string | null;
  graphLoading: boolean;
  /** Counts in the current filtered projection (search/root). */
  visible_node_count: number;
  visible_edge_count: number;
  /** Counts from the loaded catalog before local filters. */
  catalog_node_count: number | null;
  catalog_edge_count: number | null;

  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  selected: LiveBrainNode | null;
  selectedEdges: LiveBrainEdge[];
  relatedCount: number;
  relevancePct: number;
  linkedMemories: number | null;
  linkedMemoriesAvailable: boolean;
  /** True when count comes from tag/label heuristic, not graph/meta linkage. */
  linkedMemoriesHeuristic: boolean;
  evidenceForNode: number | null;
  evidenceForNodeAvailable: boolean;
  /** True when count comes from claim/label heuristic, not graph/meta linkage. */
  evidenceForNodeHeuristic: boolean;
  selectedConfidence: number | null;
  selectedConfidenceLabel: "Confidence" | "Relevantie" | null;

  categoryFilter: BrainCategoryFilter;
  setCategoryFilter: (filter: BrainCategoryFilter) => void;
  q: string;
  setQ: (q: string) => void;
  expandNode: (nodeId: string) => Promise<void>;

  metrics: {
    activeNodes: BrainMetricCell;
    knowledgeLinks: BrainMetricCell;
    memoryClusters: BrainMetricCell;
    reasoningJobs: BrainMetricCell;
    evidenceItems: BrainMetricCell;
  };

  clusters: ClusterRow[];
  clustersAvailable: boolean;
  activity: BrainActivityRow[];
  activityAvailable: boolean;
  entityTypes: BrainEntityTypeRow[];
  reasoningQueue: BrainReasoningJob[];
  reasoningAvailable: boolean;
  healthGauges: BrainHealthGauge[];
  evidenceSources: Array<{ id: string; label: string; count: number }>;
  evidenceSourcesAvailable: boolean;

  errors: Partial<Record<string, string>>;
};

function reasonMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function isReasoningCapability(cap: string | null | undefined, pool: string | null | undefined, domain: string | null | undefined): boolean {
  const hay = `${cap ?? ""} ${pool ?? ""} ${domain ?? ""}`.toLowerCase();
  return (
    hay.includes("brain") ||
    hay.includes("cognition") ||
    hay.includes("reason") ||
    hay.includes("research") ||
    hay.includes("enrich") ||
    hay.includes("analyze") ||
    hay.includes("snapshot")
  );
}

function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("nl-NL", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function prettyTypeLabel(type: string): string {
  return type
    .split(/[._-]+/g)
    .filter(Boolean)
    .map((part) => {
      const upper = part.toUpperCase();
      if (["AI", "API", "LLM", "MCP", "RAG"].includes(upper)) return upper;
      return `${part.charAt(0).toUpperCase()}${part.slice(1)}`;
    })
    .join(" ");
}

function activityTone(type: string): BrainActivityRow["tone"] {
  const cat = categoryForNode({ type });
  if (cat === "document") return "data";
  if (cat === "agent") return "warning";
  if (cat === "concept") return "research";
  return "info";
}

function activityBadge(type: string): string {
  const cat = categoryForNode({ type });
  if (cat === "document") return "Document";
  if (cat === "agent") return "Agent";
  if (cat === "concept") return type.toLowerCase().startsWith("memory") ? "Geheugen" : "Concept";
  if (cat === "entity") return "Entiteit";
  return "Ongeclassificeerd";
}

function boundedLoadedLabel(count: number, limit: number): string {
  if (count >= limit) return `≥${count} geladen`;
  return `${count} geladen`;
}

function statusFromBool(ok: boolean | null | undefined, readyLabel: string, offlineLabel = "Offline"): {
  value: string;
  tone: BrainStatusTone;
} {
  if (ok === true) return { value: readyLabel, tone: "success" };
  if (ok === false) return { value: offlineLabel, tone: "danger" };
  return { value: "UNKNOWN", tone: "muted" };
}

function documentHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

export function useBrainOverview(opts?: { enabled?: boolean }): BrainOverview {
  const enabled = opts?.enabled !== false;
  const [nodes, setNodes] = useState<LiveBrainNode[]>([]);
  const [edges, setEdges] = useState<LiveBrainEdge[]>([]);
  const [stats, setStats] = useState<BrainOverview["stats"]>(null);
  const [graphTruth, setGraphTruth] = useState<Record<string, boolean> | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [catalogNodeCount, setCatalogNodeCount] = useState<number | null>(null);
  const [catalogEdgeCount, setCatalogEdgeCount] = useState<number | null>(null);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [workersDash, setWorkersDash] = useState<WorkerFabricDashboard | null>(null);
  const [workersError, setWorkersError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceRecord[] | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [memory, setMemory] = useState<MemoryRecord[] | null>(null);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [cognitionOk, setCognitionOk] = useState<boolean | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const initialGraphSelection = useRef(true);
  const [categoryFilter, setCategoryFilter] = useState<BrainCategoryFilter>("all");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [initialLoaded, setInitialLoaded] = useState(false);

  const refreshLock = useRef(false);
  const graphAbort = useRef<AbortController | null>(null);
  const catalogCache = useRef<Awaited<ReturnType<typeof loadBrainCatalog>> | null>(null);
  useEffect(() => () => { graphAbort.current?.abort(); }, []);
  const qRef = useRef(q);
  qRef.current = q;

  const loadGraph = useCallback(async (root?: string, useCache = false) => {
    graphAbort.current?.abort();
    const controller = new AbortController();
    graphAbort.current = controller;
    setGraphLoading(true);
    setGraphError(null);
    try {
      const catalog = useCache && catalogCache.current ? catalogCache.current : await loadBrainCatalog((cursor, signal) => api.brainCatalog(cursor, signal), controller.signal,
        (partialNodes, partialEdges, partialTruth) => {
          if (controller.signal.aborted) return;
          setNodes(partialNodes);
          setEdges(partialEdges);
          setCatalogNodeCount(partialNodes.length);
          setCatalogEdgeCount(partialEdges.length);
          // pagination_complete is client paging state; preserve backend catalog_complete / bounded_projection as-is.
          setGraphTruth({
            ...partialTruth,
            paged_catalog: true,
            pagination_complete: false,
          });
        });
      if (controller.signal.aborted) return;
      catalogCache.current = catalog;
      setCatalogNodeCount(catalog.nodes.length);
      setCatalogEdgeCount(catalog.edges.length);
      const query = qRef.current.trim().toLowerCase();
      let visibleNodes = catalog.nodes.filter(n => !query || `${n.label} ${n.id} ${n.type}`.toLowerCase().includes(query));
      if (root) {
        const neighbors = new Set([root]);
        for (const e of catalog.edges) {
          if (e.source === root) neighbors.add(e.target);
          if (e.target === root) neighbors.add(e.source);
        }
        visibleNodes = visibleNodes.filter(n => neighbors.has(n.id));
      }
      const ids = new Set(visibleNodes.map(n => n.id));
      const visibleEdges = catalog.edges.filter(e => ids.has(e.source) && ids.has(e.target));
      const byType: Record<string, number> = {}, byRelation: Record<string, number> = {};
      for (const node of visibleNodes) byType[node.type] = (byType[node.type] ?? 0) + 1;
      for (const edge of visibleEdges) byRelation[edge.relation] = (byRelation[edge.relation] ?? 0) + 1;
      const data = { nodes: visibleNodes };
      setNodes(visibleNodes);
      setEdges(visibleEdges);
      // Visible projection counts — not global Brain corpus totals.
      setStats({
        node_count: visibleNodes.length,
        edge_count: visibleEdges.length,
        by_type: byType,
        by_relation: byRelation,
      });
      setGraphTruth({
        ...catalog.truth,
        paged_catalog: true,
        pagination_complete: catalog.truth.pagination_complete !== false,
      });
      const chooseInitialSelection = initialGraphSelection.current;
      initialGraphSelection.current = false;
      setSelectedId((previous) => {
        if (previous && data.nodes.some((n) => n.id === previous)) return previous;
        if (!chooseInitialSelection) return null;
        const fixtureOn =
          typeof window !== "undefined" &&
          (window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__ === true;
        if (fixtureOn) {
          const bitcoin = data.nodes.find((n) => n.label === "Bitcoin");
          if (bitcoin) return bitcoin.id;
        }
        const preferred =
          data.nodes.find((n) => /leviathan/i.test(n.label))?.id ??
          data.nodes.find((n) => categoryForNode(n) === "agent")?.id ??
          data.nodes[0]?.id ??
          null;
        return preferred;
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      setGraphError(reasonMessage(err, "Brain graph unavailable"));
      setStats(null);
      setCatalogNodeCount(null);
      setCatalogEdgeCount(null);
      setGraphTruth({ paged_catalog: true, pagination_complete: false });
    } finally {
      if (!controller.signal.aborted) { setGraphLoading(false); graphAbort.current = null; }
    }
  }, []);

  const loadSecondary = useCallback(async () => {
    const settled = await Promise.allSettled([
      api.health(),
      api.getWorkersDashboard(),
      api.listEvidence({ limit: EVIDENCE_FETCH_LIMIT }),
      api.listMemory({ limit: MEMORY_FETCH_LIMIT, status: "ACTIVE" }),
      api.cognitionHealth(),
    ]);

    if (settled[0].status === "fulfilled") {
      setHealth(settled[0].value);
      setHealthError(null);
    } else {
      setHealth(null);
      setHealthError(reasonMessage(settled[0].reason, "Health unavailable"));
    }

    if (settled[1].status === "fulfilled") {
      setWorkersDash(settled[1].value);
      setWorkersError(null);
    } else {
      setWorkersDash(null);
      setWorkersError(reasonMessage(settled[1].reason, "Workers unavailable"));
    }

    if (settled[2].status === "fulfilled") {
      setEvidence(settled[2].value.evidence ?? []);
      setEvidenceError(null);
    } else {
      setEvidence(null);
      setEvidenceError(reasonMessage(settled[2].reason, "Evidence unavailable"));
    }

    if (settled[3].status === "fulfilled") {
      setMemory(settled[3].value.memory ?? []);
      setMemoryError(null);
    } else {
      setMemory(null);
      setMemoryError(reasonMessage(settled[3].reason, "Memory unavailable"));
    }

    if (settled[4].status === "fulfilled") {
      const cog = settled[4].value.cognition as { ok?: boolean; status?: string } | undefined;
      const classified = classifyRawStatus(cog?.status);
      if (cog?.ok === true || classified.kind === "success") {
        setCognitionOk(true);
      } else if (cog?.ok === false || classified.kind === "danger") {
        setCognitionOk(false);
      } else {
        setCognitionOk(null);
      }
    } else {
      setCognitionOk(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    if (refreshLock.current) return;
    refreshLock.current = true;
    setRefreshing(true);
    try {
      await Promise.all([loadGraph(), loadSecondary()]);
    } finally {
      refreshLock.current = false;
      setRefreshing(false);
      setLoading(false);
      setInitialLoaded(true);
    }
  }, [loadGraph, loadSecondary]);

  const expandNode = useCallback(
    async (nodeId: string) => {
      await loadGraph(nodeId);
    },
    [loadGraph],
  );

  // Debounced search → reload graph
  useEffect(() => {
    if (!enabled) return;
    const handle = window.setTimeout(() => {
      void loadGraph(undefined, true);
    }, 320);
    return () => window.clearTimeout(handle);
  }, [q, enabled, loadGraph]);

  useEffect(() => {
    if (!enabled) return;
    void (async () => {
      setLoading(true);
      await Promise.all([loadGraph(), loadSecondary()]);
      setLoading(false);
      setInitialLoaded(true);
    })();
  }, [enabled, loadGraph, loadSecondary]);

  // Bounded polling — pause while hidden
  useEffect(() => {
    if (!enabled) return;
    const graphTimer = window.setInterval(() => {
      if (documentHidden() || graphAbort.current) return;
      void loadGraph();
    }, GRAPH_INTERVAL_MS);
    const queueTimer = window.setInterval(() => {
      if (documentHidden()) return;
      void api.getWorkersDashboard().then(
        (d) => {
          setWorkersDash(d);
          setWorkersError(null);
        },
        (err) => setWorkersError(reasonMessage(err, "Workers unavailable")),
      );
    }, QUEUE_INTERVAL_MS);
    const healthTimer = window.setInterval(() => {
      if (documentHidden()) return;
      void api.health().then(
        (h) => {
          setHealth(h);
          setHealthError(null);
        },
        (err) => setHealthError(reasonMessage(err, "Health unavailable")),
      );
    }, HEALTH_INTERVAL_MS);
    const activityTimer = window.setInterval(() => {
      if (documentHidden()) return;
      void Promise.allSettled([
        api.listEvidence({ limit: 200 }),
        api.listMemory({ limit: 100, status: "ACTIVE" }),
      ]).then(([ev, mem]) => {
        if (ev.status === "fulfilled") {
          setEvidence(ev.value.evidence ?? []);
          setEvidenceError(null);
        }
        if (mem.status === "fulfilled") {
          setMemory(mem.value.memory ?? []);
          setMemoryError(null);
        }
      });
    }, ACTIVITY_INTERVAL_MS);
    return () => {
      window.clearInterval(graphTimer);
      window.clearInterval(queueTimer);
      window.clearInterval(healthTimer);
      window.clearInterval(activityTimer);
      graphAbort.current?.abort();
    };
  }, [enabled, loadGraph]);

  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selected = selectedId ? nodeMap.get(selectedId) ?? null : null;
  const selectedEdges = useMemo(
    () => (selected ? edges.filter((e) => e.source === selected.id || e.target === selected.id) : []),
    [edges, selected],
  );
  const relatedCount = (() => {
    if (!selected) return 0;
    const meta = selected.meta?.related_count;
    if (typeof meta === "number" && Number.isFinite(meta)) return meta;
    return selectedEdges.length;
  })();

  const degrees = useMemo(() => {
    const map = new Map<string, number>();
    for (const edge of edges) {
      map.set(edge.source, (map.get(edge.source) ?? 0) + 1);
      map.set(edge.target, (map.get(edge.target) ?? 0) + 1);
    }
    return map;
  }, [edges]);
  const maxDegree = useMemo(() => Math.max(1, ...degrees.values(), 1), [degrees]);
  const relevancePct = selected
    ? Math.round(((degrees.get(selected.id) ?? 0) / maxDegree) * 100)
    : 0;

  const metaConfidence =
    selected && typeof selected.meta?.confidence === "number"
      ? selected.meta.confidence
      : selected && typeof selected.meta?.confidence === "string"
        ? Number(selected.meta.confidence)
        : null;
  const selectedConfidence =
    metaConfidence != null && Number.isFinite(metaConfidence)
      ? metaConfidence <= 1
        ? Math.round(metaConfidence * 100)
        : Math.round(metaConfidence)
      : null;
  const selectedConfidenceLabel: BrainOverview["selectedConfidenceLabel"] =
    selectedConfidence != null ? "Confidence" : selected ? "Relevantie" : null;

  const linkedMemoryIds = useMemo(() => {
    if (!selected) return [];
    return selectedEdges
      .map((e) => (e.source === selected.id ? e.target : e.source))
      .filter((id) => {
        const n = nodeMap.get(id);
        return n && (n.type === "memory" || n.type.startsWith("memory."));
      });
  }, [selected, selectedEdges, nodeMap]);

  const linkedMemoriesAvailable = memory != null || linkedMemoryIds.length > 0 || typeof selected?.meta?.linked_memories === "number";
  const linkedMemories =
    typeof selected?.meta?.linked_memories === "number"
      ? selected.meta.linked_memories
      : linkedMemoryIds.length > 0
        ? linkedMemoryIds.length
        : memory != null && selected
          ? memory.filter((m) => {
              const tags = m.tags ?? [];
              return tags.some((t) => t.includes(selected.id) || t.toLowerCase().includes(selected.label.toLowerCase()));
            }).length
          : memory == null
            ? null
            : 0;

  const linkedMemoriesHeuristic =
    !(typeof selected?.meta?.linked_memories === "number") &&
    linkedMemoryIds.length === 0 &&
    memory != null &&
    selected != null &&
    (linkedMemories ?? 0) > 0;

  const evidenceNodeIds = useMemo(() => {
    if (!selected) return [];
    return selectedEdges
      .map((e) => (e.source === selected.id ? e.target : e.source))
      .filter((id) => {
        const n = nodeMap.get(id);
        return n && (n.type === "evidence" || n.type.startsWith("evidence."));
      });
  }, [selected, selectedEdges, nodeMap]);

  const evidenceForNodeAvailable = evidence != null || evidenceNodeIds.length > 0 || typeof selected?.meta?.evidence_items === "number";
  const evidenceForNode =
    typeof selected?.meta?.evidence_items === "number"
      ? selected.meta.evidence_items
      : evidenceNodeIds.length > 0
        ? evidenceNodeIds.length
        : evidence != null && selected
          ? evidence.filter((ev) => {
              const claim = (ev.claim || "").toLowerCase();
              return claim.includes(selected.label.toLowerCase()) || ev.evidence_id === selected.id.replace(/^evidence:/, "");
            }).length
          : evidence == null
            ? null
            : 0;

  const evidenceForNodeHeuristic =
    !(typeof selected?.meta?.evidence_items === "number") &&
    evidenceNodeIds.length === 0 &&
    evidence != null &&
    selected != null &&
    (evidenceForNode ?? 0) > 0;

  const clusters = useMemo(() => buildClusters(nodes, edges), [nodes, edges]);

  const reasoningJobs = useMemo(() => {
    if (!workersDash) return { active: null as number | null, queued: null as number | null, rows: [] as BrainReasoningJob[], available: false };
    const poolMatch = (poolId: string) =>
      /brain|cognition|research|reason/i.test(poolId);
    const relevantPools = workersDash.pools.filter((p) => poolMatch(p.pool_id));
    const fromPools = relevantPools.length > 0;

    const busyWorkers = workersDash.workers.filter((w) => {
      if (!/busy|running/i.test(w.state)) return false;
      if (fromPools && relevantPools.some((p) => p.pool_id === w.pool_id)) return true;
      return isReasoningCapability(w.current_capability, w.pool_id, w.current_job?.domain);
    });

    const queued = (workersDash.queued_jobs ?? []).filter((j) =>
      isReasoningCapability(j.capability_id, j.worker_pool, j.domain),
    );

    const rows: BrainReasoningJob[] = [];
    for (const w of busyWorkers.slice(0, 5)) {
      const job = w.current_job;
      rows.push({
        id: w.current_job_id || w.worker_id,
        title: job?.human_title || w.current_work || w.current_capability || "Redeneertaak",
        state: "Bezig",
        stateTone: "info",
        progress:
          w.progress_percent != null && Number.isFinite(w.progress_percent)
            ? w.progress_percent
            : job?.progress_percent != null && Number.isFinite(job.progress_percent)
              ? job.progress_percent
              : null,
        elapsed: w.elapsed_display || job?.elapsed_display || "UNMEASURED",
      });
    }
    for (const j of queued.slice(0, Math.max(0, 5 - rows.length))) {
      rows.push(mapQueuedJob(j));
    }

    const activeCount = fromPools
      ? relevantPools.reduce((s, p) => s + (p.busy ?? 0), 0)
      : busyWorkers.length;
    const queuedCount = fromPools
      ? relevantPools.reduce((s, p) => s + (p.queued ?? 0), 0) || queued.length
      : queued.length;

    return {
      active: activeCount,
      queued: queuedCount,
      rows,
      available: true,
    };
  }, [workersDash]);

  const activity = useMemo((): { rows: BrainActivityRow[]; available: boolean } => {
    const events: TimelineEvent[] = buildTimeline(nodes).slice(0, 8);
    if (events.length === 0 && evidence == null && memory == null) {
      return { rows: [], available: false };
    }
    const rows: BrainActivityRow[] = events.map((ev) => ({
      id: ev.id,
      time: formatClock(ev.at),
      description: describeActivity(ev.title, ev.type),
      badge: activityBadge(ev.type),
      tone: activityTone(ev.type),
    }));
    // Supplement from evidence/memory timestamps when graph timeline is sparse
    if (rows.length < 5 && evidence) {
      for (const ev of [...evidence].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5 - rows.length)) {
        rows.push({
          id: `ev-${ev.evidence_id}`,
          time: formatClock(ev.created_at),
          description: ev.claim ? truncate(ev.claim, 64) : "Bewijsitem bijgewerkt",
          badge: "Document",
          tone: "data",
        });
      }
    }
    if (rows.length < 5 && memory) {
      for (const m of [...memory].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 5 - rows.length)) {
        rows.push({
          id: `mem-${m.memory_id}`,
          time: formatClock(m.updated_at),
          description: truncate(m.content, 64) || "Geheugen bijgewerkt",
          badge: "Geheugen",
          tone: "research",
        });
      }
    }
    return { rows: rows.slice(0, 6), available: true };
  }, [nodes, evidence, memory]);

  const entityTypes = useMemo((): BrainEntityTypeRow[] => {
    const byType = stats?.by_type ?? {};
    const entries =
      Object.keys(byType).length > 0
        ? Object.entries(byType)
        : [...nodes.reduce((m, n) => m.set(n.type, (m.get(n.type) ?? 0) + 1), new Map<string, number>())];
    const total = entries.reduce((s, [, c]) => s + c, 0) || 1;
    return entries
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([type, count]) => ({
        id: type,
        label: prettyTypeLabel(type),
        count,
        pct: Math.round((count / total) * 100),
        category: categoryForNode({ type }),
      }));
  }, [stats, nodes]);

  const evidenceSources = useMemo(() => {
    if (!evidence) return { rows: [] as Array<{ id: string; label: string; count: number }>, available: false };
    const map = new Map<string, number>();
    for (const ev of evidence) {
      const key = ev.kind || "unknown";
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    const rows = [...map.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([kind, count]) => ({ id: kind, label: prettyTypeLabel(kind), count }));
    return { rows, available: true };
  }, [evidence]);

  const healthGauges = useMemo((): BrainHealthGauge[] => {
    const graphLoaded = graphError == null && (stats != null || nodes.length > 0);
    const brainService = health?.ok === true;
    return [
      {
        id: "knowledge-graph",
        label: "Knowledge Graph",
        value: null,
        statusLabel:
          graphLoading && !initialLoaded
            ? "…"
            : graphError
              ? "Fout"
              : graphLoaded
                ? "AVAILABLE"
                : "UNKNOWN",
        available: !graphLoading || initialLoaded,
      },
      {
        id: "vector-search",
        label: "Vector Search",
        value: null,
        statusLabel:
          health?.neuro?.associative_memory === true
            ? "CONFIGURED"
            : health?.neuro?.enabled === false
              ? "Offline"
              : health
                ? "UNMEASURED"
                : "UNKNOWN",
        available: health != null,
      },
      {
        id: "memory-store",
        label: "Memory Store",
        value: null,
        statusLabel:
          memoryError
            ? "Fout"
            : memory != null
              ? "LOADED"
              : health?.neuro?.memory_tiers === true
                ? "CONFIGURED"
                : health
                  ? "UNMEASURED"
                  : "UNKNOWN",
        available: memory != null || health != null,
      },
      {
        id: "reasoning-engine",
        label: "Reasoning Engine",
        value: null,
        statusLabel:
          // Measured unhealthy always wins over configured/enabled flags.
          cognitionOk === false
            ? "Offline"
            : cognitionOk === true
              ? "Goed"
              : health?.reasoning_enabled === true
                ? "CONFIGURED"
                : health?.reasoning_enabled === false
                  ? "Offline"
                  : health
                    ? "UNMEASURED"
                    : "UNKNOWN",
        available: health != null || cognitionOk != null,
      },
    ];
    void brainService;
  }, [graphError, stats, nodes.length, graphLoading, initialLoaded, health, memory, memoryError, cognitionOk]);

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    const brain = statusFromBool(
      health?.ok === true && graphError == null ? true : health?.ok === false ? false : graphError ? false : null,
      "Running",
    );
    // Prefer product_truth components when present
    const components = health?.product_truth?.components ?? [];
    const findComp = (pred: (id: string, name: string) => boolean) =>
      components.find((c) => pred(c.id.toLowerCase(), (c.name || "").toLowerCase()));

    const mapComp = (
      comp: (typeof components)[number] | undefined,
      fallback: { value: string; tone: BrainStatusTone },
    ): { value: string; tone: BrainStatusTone } => {
      if (!comp) return fallback;
      return mapMeasuredComponentStatus(comp.status, comp.measured);
    };

    const vector = mapComp(
      findComp((id, name) => id.includes("vector") || name.includes("vector")),
      health?.neuro?.associative_memory === true
        ? { value: "CONFIGURED", tone: "muted" }
        : health
          ? { value: "UNMEASURED", tone: "muted" }
          : { value: "UNKNOWN", tone: "muted" },
    );
    const graph = mapComp(
      findComp((id, name) => id.includes("graph") || name.includes("graph")),
      graphError
        ? { value: "Offline", tone: "danger" }
        : stats != null || nodes.length > 0
          ? { value: "LOADED", tone: "info" }
          : graphLoading
            ? { value: "…", tone: "muted" }
            : { value: "UNKNOWN", tone: "muted" },
    );
    const embed = mapComp(
      findComp((id, name) => id.includes("embed") || name.includes("embed")),
      health?.neuro?.enabled === true
        ? { value: "CONFIGURED", tone: "muted" }
        : health
          ? { value: "UNMEASURED", tone: "muted" }
          : { value: "UNKNOWN", tone: "muted" },
    );
    const inference = mapComp(
      findComp((id, name) => id.includes("infer") || id.includes("llm") || name.includes("infer") || name.includes("llm")),
      health?.llm?.available === true
        ? { value: "AVAILABLE", tone: "info" }
        : health?.llm?.available === false
          ? { value: "Offline", tone: "danger" }
          : { value: "UNKNOWN", tone: "muted" },
    );

    return [
      { id: "brain-service", label: "Brain Service", value: brain.value, tone: brain.tone },
      { id: "vector-db", label: "Vector DB", value: vector.value, tone: vector.tone },
      { id: "graph-engine", label: "Graph Engine", value: graph.value, tone: graph.tone },
      { id: "embedding", label: "Embedding Service", value: embed.value, tone: embed.tone },
      { id: "inference", label: "Inference Engine", value: inference.value, tone: inference.tone },
    ];
  }, [health, graphError, stats, nodes.length, graphLoading]);

  const metrics = useMemo((): BrainOverview["metrics"] => {
    const stillLoading = loading && !initialLoaded;
    const nodeCount = stats?.node_count ?? (graphError ? null : nodes.length);
    const edgeCount = stats?.edge_count ?? (graphError ? null : edges.length);
    const clusterCount =
      stats?.cluster_count != null
        ? stats.cluster_count
        : nodes.length > 0
          ? clusters.length
          : graphError
            ? null
            : stillLoading
              ? null
              : 0;
    const evidenceCount =
      stats?.evidence_count != null
        ? stats.evidence_count
        : evidence != null
          ? evidence.length
          : null;
    const reasoningActive = reasoningJobs.available ? reasoningJobs.active : null;
    const reasoningQueued = reasoningJobs.available ? reasoningJobs.queued : null;
    const reasoningTotal =
      reasoningActive != null && reasoningQueued != null
        ? reasoningActive + reasoningQueued
        : reasoningActive ?? reasoningQueued;

    return {
      activeNodes: {
        value: stillLoading ? null : nodeCount,
        sublabel:
          nodeCount == null
            ? graphError
              ? "UNAVAILABLE"
              : "—"
            : catalogNodeCount != null && catalogNodeCount !== nodeCount
              ? `zichtbaar · ${catalogNodeCount} geladen`
              : graphTruth?.bounded_projection || graphTruth?.stats_are_not_global_unless_corpus_fits_bound
                ? boundedLoadedLabel(nodeCount, nodeCount)
                : `${nodeCount} geladen`,
        available: nodeCount != null,
        loading: stillLoading || graphLoading,
      },
      knowledgeLinks: {
        value: stillLoading ? null : edgeCount,
        sublabel:
          edgeCount == null
            ? graphError
              ? "UNAVAILABLE"
              : "—"
            : catalogEdgeCount != null && catalogEdgeCount !== edgeCount
              ? `zichtbaar · ${catalogEdgeCount} geladen`
              : `${edgeCount} geladen`,
        available: edgeCount != null,
        loading: stillLoading || graphLoading,
      },
      memoryClusters: {
        value: stillLoading ? null : clusterCount,
        sublabel:
          clusterCount != null
            ? `${clusters.length} geladen type-clusters`
            : graphError
              ? "UNAVAILABLE"
              : "—",
        available: clusterCount != null,
        loading: stillLoading || graphLoading,
      },
      reasoningJobs: {
        value: stillLoading ? null : reasoningTotal,
        sublabel:
          reasoningJobs.available && reasoningActive != null && reasoningQueued != null
            ? `${reasoningActive} actief / ${reasoningQueued} in queue`
            : reasoningJobs.available
              ? "gemeten"
              : "UNAVAILABLE",
        available: reasoningJobs.available,
        loading: stillLoading,
      },
      evidenceItems: {
        value: stillLoading ? null : evidenceCount,
        sublabel:
          evidence != null
            ? stats?.evidence_count != null
              ? `${evidenceCount} (catalogus)`
              : boundedLoadedLabel(evidence.length, EVIDENCE_FETCH_LIMIT)
            : evidenceError
              ? "UNAVAILABLE"
              : "—",
        available: evidenceCount != null,
        loading: stillLoading,
      },
    };
  }, [
    loading,
    initialLoaded,
    stats,
    graphError,
    nodes.length,
    edges.length,
    clusters.length,
    evidence,
    reasoningJobs,
    graphTruth,
    graphLoading,
    evidenceError,
    catalogNodeCount,
    catalogEdgeCount,
  ]);

  const online: boolean | null =
    health?.ok === true ? true : health?.ok === false || Boolean(healthError) ? false : null;

  return {
    loading: loading && !initialLoaded,
    refreshing,
    refresh,
    online,
    sidebarStatus,
    nodes,
    edges,
    stats,
    graphTruth,
    graphError,
    graphLoading,
    visible_node_count: nodes.length,
    visible_edge_count: edges.length,
    catalog_node_count: catalogNodeCount,
    catalog_edge_count: catalogEdgeCount,
    selectedId,
    setSelectedId,
    selected,
    selectedEdges,
    relatedCount,
    relevancePct,
    linkedMemories: linkedMemoriesAvailable ? linkedMemories : null,
    linkedMemoriesAvailable,
    linkedMemoriesHeuristic,
    evidenceForNode: evidenceForNodeAvailable ? evidenceForNode : null,
    evidenceForNodeAvailable,
    evidenceForNodeHeuristic,
    selectedConfidence,
    selectedConfidenceLabel,
    categoryFilter,
    setCategoryFilter,
    q,
    setQ,
    expandNode,
    metrics,
    clusters,
    clustersAvailable: nodes.length > 0 || (!graphLoading && !graphError),
    activity: activity.rows,
    activityAvailable: activity.available,
    entityTypes,
    reasoningQueue: reasoningJobs.rows,
    reasoningAvailable: reasoningJobs.available,
    healthGauges,
    evidenceSources: evidenceSources.rows,
    evidenceSourcesAvailable: evidenceSources.available,
    errors: {
      graph: graphError ?? undefined,
      health: healthError ?? undefined,
      workers: workersError ?? undefined,
      evidence: evidenceError ?? undefined,
      memory: memoryError ?? undefined,
    },
  };
}

function mapQueuedJob(j: WorkerFabricJobSummary): BrainReasoningJob {
  return {
    id: j.job_id,
    title: j.human_title || j.capability_id || "Wachtrijtaak",
    state: "Wachtend",
    stateTone: "warning",
    progress: j.progress_percent != null && Number.isFinite(j.progress_percent) ? j.progress_percent : null,
    elapsed: j.elapsed_display || "—",
  };
}

function truncate(text: string, max: number): string {
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function describeActivity(title: string, type: string): string {
  const cat = categoryForNode({ type });
  if (cat === "document") return `Document: ${title}`;
  if (cat === "agent") return `Agent: ${title}`;
  if (type.toLowerCase().includes("memory")) return `Geheugen: ${title}`;
  return title;
}

export { formatDateTime, prettyTypeLabel };
