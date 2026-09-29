import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import {
  clampPct,
  domainBadgeTone,
  formatDuration,
  type BadgeTone,
  type StatusTone,
} from "../lib/dashboardNormalize";
import { isActiveJobStatus, normalizeJobStatus } from "../lib/jobStatus";
import type { HealthResponse, JobRecord } from "../types/api";
import { brainLegendCategory, type BrainLegendCategory } from "../pages/brain/brainV2Colors";
import {
  buildClusters,
  type LiveBrainEdge,
  type LiveBrainNode,
} from "../pages/brain/brain-live";
import type { BrainView } from "../pages/brain/brain-mock";

export type BrainTypeFilterTab = "Alles" | "Entiteiten" | "Concepten" | "Documenten" | "Agents";

export type BrainMetricCell = {
  value: number | null;
  available: boolean;
  sublabel: string;
};

export type BrainOverviewMetrics = {
  nodes: BrainMetricCell;
  links: BrainMetricCell;
  clusters: BrainMetricCell;
  reasoningJobs: { active: number | null; queued: number | null; available: boolean };
  evidence: BrainMetricCell;
};

export type BrainHealthRow = {
  id: string;
  label: string;
  value: string;
  tone: StatusTone;
  pct: number | null;
};

export type BrainOverview = {
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  stats: {
    node_count?: number;
    edge_count?: number;
    by_type?: Record<string, number>;
    by_relation?: Record<string, number>;
  } | null;
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  selectedNode: LiveBrainNode | null;
  selectedEdges: LiveBrainEdge[];
  view: BrainView;
  setView: (view: BrainView) => void;
  typeFilterTab: BrainTypeFilterTab;
  setTypeFilterTab: (tab: BrainTypeFilterTab) => void;
  filteredNodes: LiveBrainNode[];
  filteredEdges: LiveBrainEdge[];
  metrics: BrainOverviewMetrics;
  clusters: Array<{ id: string; label: string; count: number; max: number }>;
  recentActivity: Array<{
    id: string;
    time: string;
    description: string;
    domain: string;
    tone: BadgeTone;
  }>;
  entityTypes: Array<{ type: string; label: string; count: number; pct: number }>;
  reasoningQueue: Array<{
    id: string;
    title: string;
    state: string;
    progress: number | null;
    duration: string;
    tone: BadgeTone;
  }>;
  health: BrainHealthRow[];
  sidebarStatus: SidebarStatusRow[];
  q: string;
  setQ: (q: string) => void;
  loadRoot: (root?: string) => Promise<void>;
};

const REASONING_RE = /brain|reason|cognit|research/i;
const EVIDENCE_LIST_LIMIT = 250;
const MEMORY_LIST_LIMIT = 50;
const ACTIVITY_LIMIT = 8;
const QUEUE_LIMIT = 6;

const TAB_TO_CATEGORY: Record<Exclude<BrainTypeFilterTab, "Alles">, BrainLegendCategory> = {
  Entiteiten: "entity",
  Concepten: "concept",
  Documenten: "document",
  Agents: "agent",
};

function reasonMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function isReasoningJob(job: JobRecord): boolean {
  const capability = String(job.capabilityId ?? job.capability_id ?? "");
  const state = String(job.state ?? job.status ?? "");
  const title = String(job.human_title ?? job.title ?? "");
  return REASONING_RE.test(capability) || REASONING_RE.test(state) || REASONING_RE.test(title);
}

function jobId(job: JobRecord, index: number): string {
  return String(job.jobId ?? job.job_id ?? job.id ?? `job-${index}`);
}

function jobTitle(job: JobRecord, id: string): string {
  const title = job.human_title ?? job.title ?? job.capabilityId ?? job.capability_id;
  return typeof title === "string" && title.trim() ? title : id;
}

function jobState(job: JobRecord): string {
  return String(job.state ?? job.status ?? "unknown");
}

function jobProgress(job: JobRecord): number | null {
  const raw = job.progress_percent ?? job.progress;
  if (typeof raw === "number") return clampPct(raw <= 1 && raw > 0 ? raw * 100 : raw);
  if (raw && typeof raw === "object" && "percent" in raw) {
    const pct = (raw as { percent?: unknown }).percent;
    return typeof pct === "number" ? clampPct(pct) : null;
  }
  return null;
}

function jobDuration(job: JobRecord): string {
  if (typeof job.elapsed_display === "string" && job.elapsed_display.trim()) {
    return job.elapsed_display;
  }
  if (typeof job.elapsed_seconds === "number") {
    return formatDuration(job.elapsed_seconds);
  }
  return "UNMEASURED";
}

function jobTone(state: string): BadgeTone {
  const s = normalizeJobStatus(state);
  if (s === "completed" || s === "succeeded" || s === "ready") return "success";
  if (s === "failed" || s === "error" || s === "interrupted") return "danger";
  if (isActiveJobStatus(state)) return "info";
  if (s === "queued" || s === "pending") return "warning";
  return "muted";
}

function formatActivityTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const d = new Date(t);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
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

function categoryMatchesTab(type: string, tab: BrainTypeFilterTab): boolean {
  if (tab === "Alles") return true;
  return brainLegendCategory(type) === TAB_TO_CATEGORY[tab];
}

/**
 * Composes Brain V2 dashboard data from live APIs.
 * Never invents trends, totals, or healthy gauges without evidence.
 */
export function useBrainOverview(): BrainOverview {
  const [nodes, setNodes] = useState<LiveBrainNode[]>([]);
  const [edges, setEdges] = useState<LiveBrainEdge[]>([]);
  const [stats, setStats] = useState<BrainOverview["stats"]>(null);
  const [jobs, setJobs] = useState<JobRecord[] | null>(null);
  const [evidenceCount, setEvidenceCount] = useState<number | null>(null);
  const [evidenceAvailable, setEvidenceAvailable] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [memoryAvailable, setMemoryAvailable] = useState(false);
  const [healthRes, setHealthRes] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<BrainView>("Graph");
  const [typeFilterTab, setTypeFilterTab] = useState<BrainTypeFilterTab>("Alles");
  const [q, setQ] = useState("");
  const [loadRootArg, setLoadRootArg] = useState<string | undefined>(undefined);

  const mounted = useRef(true);
  const inFlight = useRef(false);
  const initialDone = useRef(false);

  const pull = useCallback(async (root?: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    if (initialDone.current) setRefreshing(true);
    else setLoading(true);

    try {
      const [graphRes, jobsRes, evidenceRes, memoryRes, healthSettled] = await Promise.allSettled([
        api.brainGraph({
          limit: 250,
          q: q.trim() || undefined,
          root: root ?? loadRootArg,
        }),
        api.listJobs(),
        api.listEvidence({ limit: EVIDENCE_LIST_LIMIT }),
        api.listMemory({ limit: MEMORY_LIST_LIMIT }),
        api.health(),
      ]);

      if (!mounted.current) return;

      const errors: string[] = [];

      if (graphRes.status === "fulfilled") {
        const data = graphRes.value;
        setNodes(data.nodes);
        setEdges(data.edges);
        setStats(data.stats);
        setSelectedId((previous) => {
          if (previous && data.nodes.some((node) => node.id === previous)) return previous;
          return data.nodes[0]?.id ?? null;
        });
      } else {
        setNodes([]);
        setEdges([]);
        setStats(null);
        setSelectedId(null);
        errors.push(reasonMessage(graphRes.reason, "Brain graph unavailable"));
      }

      if (jobsRes.status === "fulfilled") {
        setJobs(jobsRes.value.jobs ?? []);
      } else {
        setJobs(null);
      }

      if (evidenceRes.status === "fulfilled") {
        const list = evidenceRes.value.evidence ?? [];
        setEvidenceCount(list.length);
        setEvidenceAvailable(true);
      } else {
        setEvidenceCount(null);
        setEvidenceAvailable(false);
      }

      if (memoryRes.status === "fulfilled") {
        const list = memoryRes.value.memory ?? [];
        setMemoryCount(list.length);
        setMemoryAvailable(true);
      } else {
        setMemoryCount(null);
        setMemoryAvailable(false);
      }

      if (healthSettled.status === "fulfilled") {
        setHealthRes(healthSettled.value);
      } else {
        setHealthRes(null);
      }

      setError(errors[0] ?? null);
    } finally {
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
        initialDone.current = true;
      }
      inFlight.current = false;
    }
  }, [q, loadRootArg]);

  useEffect(() => {
    mounted.current = true;
    void pull();
    return () => {
      mounted.current = false;
    };
  }, [pull]);

  const refresh = useCallback(async () => {
    await pull(loadRootArg);
  }, [pull, loadRootArg]);

  const loadRoot = useCallback(async (root?: string) => {
    setLoadRootArg(root);
    await pull(root);
  }, [pull]);

  const filteredNodes = useMemo(
    () => nodes.filter((node) => categoryMatchesTab(node.type, typeFilterTab)),
    [nodes, typeFilterTab],
  );
  const filteredIds = useMemo(() => new Set(filteredNodes.map((node) => node.id)), [filteredNodes]);
  const filteredEdges = useMemo(
    () => edges.filter((edge) => filteredIds.has(edge.source) && filteredIds.has(edge.target)),
    [edges, filteredIds],
  );

  const selectedNode = useMemo(
    () => (selectedId ? nodes.find((node) => node.id === selectedId) ?? null : null),
    [nodes, selectedId],
  );
  const selectedEdges = useMemo(
    () =>
      selectedNode
        ? edges.filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
        : [],
    [edges, selectedNode],
  );

  const clusterRows = useMemo(() => {
    if (!nodes.length) return [];
    const built = buildClusters(nodes, edges);
    const max = built[0]?.nodes ?? 0;
    return built.slice(0, 5).map((row) => ({
      id: row.id,
      label: prettyTypeLabel(row.label),
      count: row.nodes,
      max: Math.max(max, 1),
    }));
  }, [nodes, edges]);

  const reasoningJobs = useMemo(() => {
    if (!jobs) return [];
    return jobs.filter(isReasoningJob);
  }, [jobs]);

  const metrics = useMemo<BrainOverviewMetrics>(() => {
    const nodeStat = typeof stats?.node_count === "number" ? stats.node_count : null;
    const edgeStat = typeof stats?.edge_count === "number" ? stats.edge_count : null;
    const nodeValue = nodeStat ?? (nodes.length > 0 ? nodes.length : null);
    const linkValue = edgeStat ?? (edges.length > 0 ? edges.length : null);
    const usingProjection = nodeStat == null || edgeStat == null || nodes.length > 0;

    return {
      nodes: {
        value: nodeValue,
        available: nodeValue != null,
        sublabel: nodeValue == null ? "unavailable" : usingProjection ? "in huidige projectie" : "graph stats",
      },
      links: {
        value: linkValue,
        available: linkValue != null,
        sublabel: linkValue == null ? "unavailable" : usingProjection ? "in huidige projectie" : "graph stats",
      },
      clusters: {
        value: nodes.length > 0 ? clusterRows.length : null,
        available: nodes.length > 0,
        sublabel: nodes.length > 0 ? "in huidige projectie" : "unavailable",
      },
      reasoningJobs: {
        active: jobs
          ? reasoningJobs.filter((job) => isActiveJobStatus(jobState(job))).length
          : null,
        queued: jobs
          ? reasoningJobs.filter((job) => {
              const s = normalizeJobStatus(jobState(job));
              return s === "queued" || s === "pending";
            }).length
          : null,
        available: jobs != null,
      },
      evidence: {
        value: evidenceAvailable ? evidenceCount : null,
        available: evidenceAvailable,
        sublabel: evidenceAvailable ? `bounded ≤${EVIDENCE_LIST_LIMIT}` : "unavailable",
      },
    };
  }, [
    stats,
    nodes.length,
    edges.length,
    clusterRows.length,
    jobs,
    reasoningJobs,
    evidenceAvailable,
    evidenceCount,
  ]);

  const recentActivity = useMemo(() => {
    return nodes
      .filter((node) => node.created_at)
      .slice()
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
      .slice(0, ACTIVITY_LIMIT)
      .map((node) => ({
        id: node.id,
        time: formatActivityTime(node.created_at),
        description: node.label,
        domain: prettyTypeLabel(node.type.split(".")[0] || node.type),
        tone: domainBadgeTone(node.type),
      }));
  }, [nodes]);

  const entityTypes = useMemo(() => {
    const byType =
      stats?.by_type && Object.keys(stats.by_type).length > 0
        ? Object.entries(stats.by_type)
        : [
            ...nodes
              .reduce((map, node) => map.set(node.type, (map.get(node.type) ?? 0) + 1), new Map<string, number>())
              .entries(),
          ];
    const total = byType.reduce((sum, [, count]) => sum + count, 0) || 1;
    return byType
      .slice()
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([type, count]) => ({
        type,
        label: prettyTypeLabel(type),
        count,
        pct: Math.round((count / total) * 100),
      }));
  }, [stats, nodes]);

  const reasoningQueue = useMemo(() => {
    return reasoningJobs.slice(0, QUEUE_LIMIT).map((job, index) => {
      const id = jobId(job, index);
      const state = jobState(job);
      return {
        id,
        title: jobTitle(job, id),
        state,
        progress: jobProgress(job),
        duration: jobDuration(job),
        tone: jobTone(state),
      };
    });
  }, [reasoningJobs]);

  const graphLoaded = nodes.length > 0 || (typeof stats?.node_count === "number" && stats.node_count >= 0 && error == null && !loading);
  const graphHealthy = Boolean(healthRes?.ok && (nodes.length > 0 || typeof stats?.node_count === "number"));

  const health = useMemo<BrainHealthRow[]>(() => {
    const graph: BrainHealthRow = graphHealthy
      ? { id: "knowledge-graph", label: "Knowledge Graph", value: "HEALTHY", tone: "success", pct: 100 }
      : healthRes == null && error
        ? { id: "knowledge-graph", label: "Knowledge Graph", value: "UNAVAILABLE", tone: "danger", pct: null }
        : {
            id: "knowledge-graph",
            label: "Knowledge Graph",
            value: "UNKNOWN",
            tone: "muted",
            pct: null,
          };

    // Vector search is never claimed healthy from health.ok alone.
    const vector: BrainHealthRow = {
      id: "vector-search",
      label: "Vector Search",
      value: "UNKNOWN",
      tone: "muted",
      pct: null,
    };

    const memory: BrainHealthRow = memoryAvailable
      ? {
          id: "memory-store",
          label: "Memory Store",
          value: memoryCount != null && memoryCount >= 0 ? "REACHABLE" : "UNKNOWN",
          tone: memoryCount != null ? "info" : "muted",
          pct: null,
        }
      : {
          id: "memory-store",
          label: "Memory Store",
          value: "UNKNOWN",
          tone: "muted",
          pct: null,
        };

    const reasoningProven =
      healthRes?.reasoning_enabled === true || (jobs != null && reasoningJobs.length > 0);
    const reasoning: BrainHealthRow = reasoningProven
      ? {
          id: "reasoning-engine",
          label: "Reasoning Engine",
          value: healthRes?.reasoning_enabled === false ? "DISABLED" : "REACHABLE",
          tone: healthRes?.reasoning_enabled === false ? "warning" : "info",
          pct: null,
        }
      : {
          id: "reasoning-engine",
          label: "Reasoning Engine",
          value: "UNKNOWN",
          tone: "muted",
          pct: null,
        };

    return [graph, vector, memory, reasoning];
  }, [
    graphHealthy,
    healthRes,
    error,
    memoryAvailable,
    memoryCount,
    jobs,
    reasoningJobs.length,
  ]);

  const sidebarStatus = useMemo<SidebarStatusRow[]>(() => {
    const rows: SidebarStatusRow[] = [
      {
        id: "brain-graph",
        label: "Brain Graph",
        value: graphHealthy ? "Healthy" : graphLoaded ? "Loaded" : error ? "Error" : "Unknown",
        tone: graphHealthy ? "success" : error ? "danger" : "muted",
      },
      {
        id: "reasoning",
        label: "Reasoning",
        value:
          jobs == null
            ? "Unknown"
            : `${reasoningJobs.filter((job) => isActiveJobStatus(jobState(job))).length} active`,
        tone: jobs == null ? "muted" : "info",
      },
      {
        id: "evidence",
        label: "Evidence",
        value: evidenceAvailable && evidenceCount != null ? String(evidenceCount) : "Unknown",
        tone: evidenceAvailable ? "info" : "muted",
      },
      {
        id: "memory",
        label: "Memory",
        value: memoryAvailable && memoryCount != null ? String(memoryCount) : "Unknown",
        tone: memoryAvailable ? "info" : "muted",
      },
    ];
    return rows;
  }, [
    graphHealthy,
    graphLoaded,
    error,
    jobs,
    reasoningJobs,
    evidenceAvailable,
    evidenceCount,
    memoryAvailable,
    memoryCount,
  ]);

  return {
    loading,
    refreshing,
    error,
    refresh,
    nodes,
    edges,
    stats,
    selectedId,
    setSelectedId,
    selectedNode,
    selectedEdges,
    view,
    setView,
    typeFilterTab,
    setTypeFilterTab,
    filteredNodes,
    filteredEdges,
    metrics,
    clusters: clusterRows,
    recentActivity,
    entityTypes,
    reasoningQueue,
    health,
    sidebarStatus,
    q,
    setQ,
    loadRoot,
  };
}
