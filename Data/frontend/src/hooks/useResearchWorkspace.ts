/**
 * Research V2 workspace orchestration.
 * Owns project list, active project artifacts, create/start/cancel, and ingestion.
 * Never uses Screen 1 fixture numbers as production defaults.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type RefObject } from "react";
import { api, ApiError } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import {
  RD_TEMPLATES,
  type RdInputTab,
  type RdTemplateCategory,
} from "../config/research";
import { useAppToast } from "../state/useAppToast";
import type {
  DatasetJob,
  DatasetRecord,
  HealthResponse,
  ModelDescriptor,
  ResearchBudgetCatalog,
  ResearchClaim,
  ResearchConflict,
  ResearchEvidence,
  ResearchProject,
  ResearchReport,
  ResearchSource,
  ResearchWebReadiness,
  ResearchWorker,
  SourceIngestionMember,
  SourceIngestionProgress,
} from "../types/api";
import {
  ACTIVE_STATUSES,
  COMPLETED_STATUSES,
  DRAFT_STATUSES,
  INGEST_ACTIVE,
  UPLOAD_EXT,
  aggregateProjectStats,
  datasetIndexed,
  isActiveStatus,
  isDocumentSource,
  isWebSource,
  mapClaimsToInsights,
  mapSourcesToEvidence,
  mapSourcesToWeb,
  projectMatchesFilter,
  projectProgress,
  timelineFromProject,
  zeroEvidenceDiagnosis,
  type ExecutionMode,
  type ResearchComposerMode,
  type ResearchFilterTab,
  type ResearchTypePreset,
} from "../pages/research/researchHelpers";

const PROJECT_LIST_LIMIT = 40;
const RECENT_DISPLAY_MAX = 8;
const ACTIVE_POLL_MS = 2500;
const INGEST_POLL_MS = 2000;
const HEALTH_POLL_MS = 30_000;

export type ResearchMetricCell = {
  value: number | null;
  sublabel: string;
  available: boolean;
  loading: boolean;
};

export type ResearchAgentRow = {
  id: string;
  name: string;
  status: string;
  statusTone: "success" | "warning" | "danger" | "muted" | "info";
  expertise: string;
  scope: "project" | "pool";
};

export type KnowledgeStatusRow = {
  id: string;
  label: string;
  value: string;
  tone: "success" | "warning" | "danger" | "muted" | "info";
  /** Measured percent only — never invent. */
  pct: number | null;
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function visualFixtureActive(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean((window as Window & { __LV_V2_VISUAL_FIXTURE__?: boolean }).__LV_V2_VISUAL_FIXTURE__);
}

export type ResearchWorkspace = {
  loading: boolean;
  refreshing: boolean;
  refresh: () => Promise<void>;
  online: boolean | null;
  sidebarStatus: SidebarStatusRow[];
  loadError: string | null;

  projects: ResearchProject[];
  recentProjects: ResearchProject[];
  projectFilter: ResearchFilterTab;
  setProjectFilter: (f: ResearchFilterTab) => void;
  projectSearch: string;
  setProjectSearch: (q: string) => void;
  filterCounts: Record<ResearchFilterTab, number>;
  showAllRecent: boolean;
  setShowAllRecent: (v: boolean) => void;

  project: ResearchProject | null;
  selectProject: (projectId: string | null) => Promise<void>;
  clearSelection: () => void;
  workspaceMode: "overview" | "run";

  workers: ResearchWorker[];
  poolWorkers: ResearchAgentRow[];
  sources: ResearchSource[];
  evidence: ResearchEvidence[];
  claims: ResearchClaim[];
  conflicts: ResearchConflict[];
  gaps: Array<Record<string, unknown>>;
  report: ResearchReport | null;
  webReadiness: ResearchWebReadiness | null;

  metrics: {
    activeResearch: ResearchMetricCell;
    researchAgents: ResearchMetricCell;
    knowledgeSources: ResearchMetricCell;
    webSources: ResearchMetricCell;
    documents: ResearchMetricCell;
  };

  stats7d: Array<{ day: string; completed: number; active: number; failed: number }>;
  knowledgeStatus: KnowledgeStatusRow[];
  agentRows: ResearchAgentRow[];

  // Composer
  inputTab: RdInputTab;
  setInputTab: (t: RdInputTab) => void;
  query: string;
  setQuery: (q: string) => void;
  composerMode: ResearchComposerMode;
  setComposerMode: (m: ResearchComposerMode) => void;
  typePreset: ResearchTypePreset | null;
  setTypePreset: (p: ResearchTypePreset | null) => void;
  applyTypePreset: (p: ResearchTypePreset) => void;
  templateId: string | null;
  templateFilter: RdTemplateCategory | "all";
  setTemplateFilter: (c: RdTemplateCategory | "all") => void;
  applyTemplate: (id: string) => void;
  showAllTemplates: boolean;
  setShowAllTemplates: (v: boolean) => void;
  advancedOpen: boolean;
  setAdvancedOpen: (v: boolean) => void;
  depth: string;
  setDepth: (d: string) => void;
  executionMode: ExecutionMode;
  setExecutionMode: (m: ExecutionMode) => void;
  customWorkers: number;
  setCustomWorkers: (n: number) => void;
  customRounds: number;
  setCustomRounds: (n: number) => void;
  context: Record<string, boolean>;
  toggleContext: (id: string) => void;
  models: ModelDescriptor[];
  modelId: string;
  setModelId: (id: string) => void;
  budgetCatalog: ResearchBudgetCatalog | null;
  effectiveWorkers: number;
  effectiveRounds: number | null;
  urlDraft: string;
  setUrlDraft: (v: string) => void;
  datasets: DatasetRecord[];
  datasetJobs: DatasetJob[];
  selectedDatasetId: string;
  setSelectedDatasetId: (id: string) => void;
  connectedDatasetLabel: string | null;
  loadDatasetsForPicker: () => Promise<void>;
  onConnectDataset: () => Promise<void>;
  onFilesSelected: (files: FileList | null) => Promise<void>;
  onDrop: (e: DragEvent) => void;
  onAddUrlSource: () => Promise<void>;
  dragOver: boolean;
  setDragOver: (v: boolean) => void;
  busy: boolean;
  onStartResearch: () => Promise<void>;
  onCancel: () => Promise<void>;
  focusComposer: () => void;
  focusTemplates: () => void;
  composerRef: RefObject<HTMLElement | null>;
  templatesRef: RefObject<HTMLElement | null>;

  ingestionFocusId: string | null;
  ingestionProgress: SourceIngestionProgress | null;
  ingestionMembers: SourceIngestionMember[];
  ingestionTotal: number;
  webProbeBusy: boolean;
  probeWeb: () => Promise<void>;

  evidenceRows: ReturnType<typeof mapSourcesToEvidence>;
  webRows: ReturnType<typeof mapSourcesToWeb>;
  insightRows: ReturnType<typeof mapClaimsToInsights>;
  timeline: ReturnType<typeof timelineFromProject>;
  progress: number | null;
  isLive: boolean;
  diagnosis: string | null;
};

export function useResearchWorkspace(): ResearchWorkspace {
  const toast = useAppToast();
  const composerRef = useRef<HTMLElement | null>(null);
  const templatesRef = useRef<HTMLElement | null>(null);
  const refreshGate = useRef(false);
  const selectGen = useRef(0);
  const visibleRef = useRef(true);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [projectFilter, setProjectFilter] = useState<ResearchFilterTab>("all");
  const [projectSearch, setProjectSearch] = useState("");
  const [showAllRecent, setShowAllRecent] = useState(false);

  const [project, setProject] = useState<ResearchProject | null>(null);
  const [workers, setWorkers] = useState<ResearchWorker[]>([]);
  const [poolWorkers, setPoolWorkers] = useState<ResearchAgentRow[]>([]);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [evidence, setEvidence] = useState<ResearchEvidence[]>([]);
  const [claims, setClaims] = useState<ResearchClaim[]>([]);
  const [conflicts, setConflicts] = useState<ResearchConflict[]>([]);
  const [gaps, setGaps] = useState<Array<Record<string, unknown>>>([]);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [webReadiness, setWebReadiness] = useState<ResearchWebReadiness | null>(null);

  const [knowledgeDocCount, setKnowledgeDocCount] = useState<number | null>(null);
  const [knowledgeDocError, setKnowledgeDocError] = useState(false);

  const [inputTab, setInputTab] = useState<RdInputTab>("Query");
  const [query, setQuery] = useState("");
  const [composerMode, setComposerMode] = useState<ResearchComposerMode>("standaard");
  const [typePreset, setTypePreset] = useState<ResearchTypePreset | null>(null);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [templateFilter, setTemplateFilter] = useState<RdTemplateCategory | "all">("populair");
  const [showAllTemplates, setShowAllTemplates] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [depth, setDepth] = useState("standard");
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("normal");
  const [customWorkers, setCustomWorkers] = useState(2);
  const [customRounds, setCustomRounds] = useState(10);
  const [context, setContext] = useState<Record<string, boolean>>({
    web: true,
    files: false,
    datasets: false,
    code: false,
    images: false,
  });
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [modelId, setModelId] = useState("");
  const [budgetCatalog, setBudgetCatalog] = useState<ResearchBudgetCatalog | null>(null);
  const [urlDraft, setUrlDraft] = useState("");
  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [datasetJobs, setDatasetJobs] = useState<DatasetJob[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [connectedDatasetLabel, setConnectedDatasetLabel] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const [ingestionFocusId, setIngestionFocusId] = useState<string | null>(null);
  const [ingestionProgress, setIngestionProgress] = useState<SourceIngestionProgress | null>(null);
  const [ingestionMembers, setIngestionMembers] = useState<SourceIngestionMember[]>([]);
  const [ingestionTotal, setIngestionTotal] = useState(0);
  const [ingestionOffset] = useState(0);
  const [webProbeBusy, setWebProbeBusy] = useState(false);

  const selectedModel = useMemo(
    () => (modelId ? models.find((m) => m.id === modelId) ?? null : null),
    [models, modelId],
  );

  const normalMode = budgetCatalog?.execution_modes.normal;
  const effectiveWorkers =
    executionMode === "normal"
      ? (normalMode?.research_workers ?? 2)
      : executionMode === "team"
        ? (budgetCatalog?.execution_modes.team?.research_workers?.default ?? customWorkers)
        : customWorkers;
  const effectiveRounds =
    executionMode === "normal"
      ? (normalMode?.rounds ?? 10)
      : executionMode === "team"
        ? null
        : customRounds;

  const isLive = !!(project && isActiveStatus(project.status));
  const progress = projectProgress(project);
  const timeline = useMemo(() => timelineFromProject(project), [project]);
  const evidenceRows = useMemo(() => mapSourcesToEvidence(sources), [sources]);
  const webRows = useMemo(() => mapSourcesToWeb(sources, evidence), [sources, evidence]);
  const insightRows = useMemo(() => mapClaimsToInsights(claims), [claims]);
  const diagnosis = useMemo(
    () => zeroEvidenceDiagnosis(project, webReadiness, sources),
    [project, webReadiness, sources],
  );

  const hydrateFromProject = useCallback((p: ResearchProject) => {
    setProject(p);
    if (p.topic) setQuery((q) => (q.trim() ? q : p.topic));
    if (p.depth) setDepth(p.depth);
    if (typeof p.allow_web === "boolean") setContext((c) => ({ ...c, web: p.allow_web }));
    if (p.execution_mode === "normal" || p.execution_mode === "custom" || p.execution_mode === "team") {
      setExecutionMode(p.execution_mode);
    }
    if (p.budget?.research_workers) setCustomWorkers(p.budget.research_workers);
    if (p.budget?.rounds) setCustomRounds(p.budget.rounds);
    const mp = p.model_profile as { modelId?: string; id?: string } | undefined;
    const mid = mp?.modelId ?? mp?.id;
    if (mid) setModelId(mid);
    if (p.connected_datasets?.length) {
      const first = p.connected_datasets[0] as { label?: string; datasetId?: string };
      setConnectedDatasetLabel(first.label ?? first.datasetId ?? "Connected");
      setContext((c) => ({ ...c, datasets: true }));
    }
    if (p.workers?.length) setWorkers(p.workers);
  }, []);

  const refreshArtifacts = useCallback(async (projectId: string) => {
    const [src, ev, cl, gapRes, confRes, reportRes] = await Promise.all([
      api.listResearchSources(projectId).catch(() => ({ sources: [] as ResearchSource[] })),
      api.listResearchEvidence(projectId).catch(() => ({ evidence: [] as ResearchEvidence[] })),
      api.listResearchClaims(projectId).catch(() => ({ claims: [] as ResearchClaim[] })),
      api.getResearchGaps(projectId).catch(() => ({ gaps: [] as Array<Record<string, unknown>> })),
      api.listResearchConflicts(projectId).catch(() => ({ conflicts: [] as ResearchConflict[] })),
      api.getResearchReport(projectId).catch(() => ({ report: null as ResearchReport | null })),
    ]);
    setSources(src.sources);
    setEvidence(ev.evidence);
    setClaims(cl.claims);
    setGaps(gapRes.gaps ?? []);
    setConflicts(confRes.conflicts ?? []);
    setReport(reportRes.report ?? null);
    if (src.sources.length > 0) setContext((c) => ({ ...c, files: true }));
  }, []);

  const refreshWorkers = useCallback(async (projectId: string) => {
    const res = await api.listResearchWorkers(projectId).catch(() => ({ workers: [] as ResearchWorker[] }));
    setWorkers(res.workers);
  }, []);

  const loadPoolWorkers = useCallback(async () => {
    try {
      const dash = await api.getWorkersDashboard();
      const researchish = (dash.workers ?? []).filter((w) => {
        const hay = `${w.pool_id} ${w.display_name ?? ""} ${w.current_capability ?? ""} ${(w.supported_job_kinds ?? []).join(" ")}`.toLowerCase();
        return hay.includes("research") || hay.includes("knowledge") || w.pool_id.toLowerCase().includes("research");
      });
      const pool = researchish.length > 0 ? researchish : dash.workers ?? [];
      const rows: ResearchAgentRow[] = pool.slice(0, 8).map((w) => {
        const state = (w.state || "unknown").toLowerCase();
        return {
          id: w.worker_id,
          name: w.display_name || `Worker ${w.slot}`,
          status: w.state || "unknown",
          statusTone:
            state.includes("idle") || state.includes("ready")
              ? "success"
              : state.includes("busy") || state.includes("running")
                ? "info"
                : state.includes("fail") || state.includes("dead")
                  ? "danger"
                  : "muted",
          expertise: w.current_capability || w.current_work || w.pool_id || "Worker Fabric",
          scope: "pool" as const,
        };
      });
      setPoolWorkers(rows);
    } catch {
      setPoolWorkers([]);
    }
  }, []);

  const loadProjects = useCallback(async () => {
    const list = await api.listResearchProjects(PROJECT_LIST_LIMIT);
    setProjects(list.projects);
    return list.projects;
  }, []);

  const selectProject = useCallback(
    async (projectId: string | null) => {
      const gen = ++selectGen.current;
      if (!projectId) {
        setProject(null);
        setWorkers([]);
        setSources([]);
        setEvidence([]);
        setClaims([]);
        setConflicts([]);
        setGaps([]);
        setReport(null);
        return;
      }
      try {
        const detail = await api.getResearchProject(projectId);
        if (gen !== selectGen.current) return;
        hydrateFromProject(detail.project);
        await refreshArtifacts(projectId);
        if (gen !== selectGen.current) return;
        if (isActiveStatus(detail.project.status)) {
          await refreshWorkers(projectId);
        }
      } catch (err) {
        if (gen !== selectGen.current) return;
        toast(errMsg(err, "Failed to load research project"));
      }
    },
    [hydrateFromProject, refreshArtifacts, refreshWorkers, toast],
  );

  const clearSelection = useCallback(() => {
    void selectProject(null);
  }, [selectProject]);

  const bootstrap = useCallback(async () => {
    setLoadError(null);
    try {
      const [projList, , , ,] = await Promise.all([
        loadProjects(),
        loadPoolWorkers(),
        (async () => {
          try {
            const h = await api.health();
            setHealth(h);
            setHealthError(null);
          } catch (err) {
            setHealthError(errMsg(err, "health unavailable"));
            setHealth(null);
          }
        })(),
        (async () => {
          try {
            const docs = await api.listKnowledgeDocuments();
            setKnowledgeDocCount(docs.documents?.length ?? 0);
            setKnowledgeDocError(false);
          } catch {
            setKnowledgeDocCount(null);
            setKnowledgeDocError(true);
          }
        })(),
      ]);

      const preferred =
        projList.find((p) => isActiveStatus(p.status)) ??
        null;
      // Visual fixture targets Screen 1 idle/overview composition — do not auto-enter run detail.
      if (preferred && !visualFixtureActive()) {
        await selectProject(preferred.project_id);
      }
    } catch (err) {
      setLoadError(errMsg(err, "Failed to load research projects"));
    } finally {
      setLoading(false);
    }
  }, [loadProjects, loadPoolWorkers, selectProject]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [modelOutcome, budgetOutcome, webOutcome] = await Promise.allSettled([
        api.listModels(),
        api.researchBudgets(),
        api.getResearchWebReadiness(),
      ]);
      if (cancelled) return;

      if (modelOutcome.status === "fulfilled") {
        let listed = modelOutcome.value.models ?? [];
        if (listed.length === 0) {
          try {
            const refreshed = await api.refreshModels();
            if (!cancelled) listed = refreshed.models ?? [];
          } catch {
            /* Auto allowed */
          }
        }
        if (cancelled) return;
        setModels(listed);
        setModelId((prev) => prev || listed[0]?.id || "");
      }

      if (budgetOutcome.status === "fulfilled") {
        const budgetRes = budgetOutcome.value;
        setBudgetCatalog(budgetRes);
        const normal = budgetRes.execution_modes.normal;
        setCustomWorkers(normal.research_workers);
        setCustomRounds(normal.rounds);
      } else if (!cancelled) {
        toast(errMsg(budgetOutcome.reason, "Failed to load research budgets"));
      }

      if (webOutcome.status === "fulfilled") {
        setWebReadiness(webOutcome.value.readiness);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [toast]);

  useEffect(() => {
    const onVis = () => {
      visibleRef.current = document.visibilityState === "visible";
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  useEffect(() => {
    if (!project || !isActiveStatus(project.status)) return;
    const projectId = project.project_id;
    let cancelled = false;
    const tick = async () => {
      if (!visibleRef.current) return;
      try {
        const res = await api.getResearchProject(projectId);
        if (cancelled) return;
        setProject(res.project);
        setProjects((prev) =>
          prev.map((p) => (p.project_id === res.project.project_id ? res.project : p)),
        );
        if (res.project.workers?.length) setWorkers(res.project.workers);
        else await refreshWorkers(projectId);
        const countsChanged =
          res.project.source_count !== project.source_count ||
          res.project.evidence_count !== project.evidence_count ||
          res.project.claim_count !== project.claim_count;
        if (countsChanged || !isActiveStatus(res.project.status)) {
          await refreshArtifacts(projectId);
        }
      } catch {
        /* keep last known */
      }
    };
    const id = window.setInterval(() => void tick(), ACTIVE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [
    project?.project_id,
    project?.status,
    project?.source_count,
    project?.evidence_count,
    project?.claim_count,
    refreshArtifacts,
    refreshWorkers,
  ]);

  useEffect(() => {
    if (!ingestionFocusId || !project?.project_id) return;
    let cancelled = false;
    const projectId = project.project_id;
    const sourceId = ingestionFocusId;

    async function tick() {
      if (!visibleRef.current) return;
      try {
        const status = await api.getSourceIngestionStatus(projectId, sourceId);
        if (cancelled) return;
        if (status.progress) setIngestionProgress(status.progress);
        const kids = await api.listSourceIngestionChildren(projectId, sourceId, {
          offset: ingestionOffset,
          limit: 50,
        });
        if (cancelled) return;
        setIngestionMembers(kids.members);
        setIngestionTotal(kids.total);
        await refreshArtifacts(projectId);
      } catch {
        /* ignore */
      }
    }

    void tick();
    const phase = ingestionProgress?.phase || ingestionProgress?.status || "";
    if (!INGEST_ACTIVE.has(phase)) return;
    const id = window.setInterval(() => void tick(), INGEST_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [
    ingestionFocusId,
    project?.project_id,
    ingestionOffset,
    ingestionProgress?.phase,
    ingestionProgress?.status,
    refreshArtifacts,
  ]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (!visibleRef.current) return;
      void api
        .health()
        .then((h) => {
          setHealth(h);
          setHealthError(null);
        })
        .catch(() => {
          /* keep last */
        });
    }, HEALTH_POLL_MS);
    return () => window.clearInterval(id);
  }, []);

  const refresh = useCallback(async () => {
    if (refreshGate.current) return;
    refreshGate.current = true;
    setRefreshing(true);
    try {
      await Promise.all([
        loadProjects(),
        loadPoolWorkers(),
        api.getResearchWebReadiness().then((r) => setWebReadiness(r.readiness)).catch(() => undefined),
        api
          .health()
          .then((h) => {
            setHealth(h);
            setHealthError(null);
          })
          .catch((err) => setHealthError(errMsg(err, "health unavailable"))),
        api
          .listKnowledgeDocuments()
          .then((d) => {
            setKnowledgeDocCount(d.documents?.length ?? 0);
            setKnowledgeDocError(false);
          })
          .catch(() => {
            setKnowledgeDocError(true);
          }),
      ]);
      if (project?.project_id) {
        await selectProject(project.project_id);
      }
    } finally {
      setRefreshing(false);
      refreshGate.current = false;
    }
  }, [loadProjects, loadPoolWorkers, project?.project_id, selectProject]);

  const filterCounts = useMemo((): Record<ResearchFilterTab, number> => {
    return {
      all: projects.length,
      active: projects.filter((p) => isActiveStatus(p.status)).length,
      completed: projects.filter((p) => COMPLETED_STATUSES.has(p.status)).length,
      drafts: projects.filter((p) => DRAFT_STATUSES.has(p.status)).length,
    };
  }, [projects]);

  const recentProjects = useMemo(() => {
    const q = projectSearch.trim().toLowerCase();
    let list = projects.filter((p) => projectMatchesFilter(p, projectFilter));
    if (q) {
      list = list.filter(
        (p) =>
          p.title.toLowerCase().includes(q) ||
          p.topic.toLowerCase().includes(q) ||
          (p.depth || "").toLowerCase().includes(q),
      );
    }
    list = [...list].sort(
      (a, b) => Date.parse(b.updated_at || b.created_at) - Date.parse(a.updated_at || a.created_at),
    );
    return showAllRecent ? list : list.slice(0, RECENT_DISPLAY_MAX);
  }, [projects, projectFilter, projectSearch, showAllRecent]);

  const metrics = useMemo((): ResearchWorkspace["metrics"] => {
    const stillLoading = loading;
    const active = projects.filter((p) => isActiveStatus(p.status)).length;
    const completed = projects.filter((p) => COMPLETED_STATUSES.has(p.status)).length;
    const total = projects.length;
    const sourceSum = projects.reduce((s, p) => s + (p.source_count || 0), 0);
    const projectWorkerCount = workers.length;
    const poolCount = poolWorkers.length;
    const agentValue =
      poolCount > 0 ? poolCount : projectWorkerCount > 0 ? projectWorkerCount : stillLoading ? null : 0;
    const agentSublabel =
      poolCount > 0
        ? "research pool"
        : projectWorkerCount > 0
          ? "project workers"
          : stillLoading
            ? "—"
            : "geen workers gemeten";

    let webCount: number | null = null;
    let webAvailable = false;
    if (sources.length > 0) {
      webCount = sources.filter(isWebSource).length;
      webAvailable = true;
    }

    let docCount: number | null = knowledgeDocCount;
    let docAvailable = knowledgeDocCount != null && !knowledgeDocError;
    if (!docAvailable && sources.length > 0) {
      docCount = sources.filter(isDocumentSource).length;
      docAvailable = true;
    }

    return {
      activeResearch: {
        value: stillLoading ? null : total,
        sublabel: stillLoading
          ? "—"
          : `${active} actief / ${completed} afgerond`,
        available: !stillLoading,
        loading: stillLoading,
      },
      researchAgents: {
        value: stillLoading && agentValue == null ? null : agentValue,
        sublabel: agentSublabel,
        available: agentValue != null,
        loading: stillLoading,
      },
      knowledgeSources: {
        value: stillLoading ? null : sourceSum,
        sublabel: stillLoading ? "—" : "in geladen projecten",
        available: !stillLoading,
        loading: stillLoading,
      },
      webSources: {
        value: stillLoading ? null : webCount,
        sublabel: webAvailable
          ? "huidig project"
          : stillLoading
            ? "—"
            : "UNMEASURED",
        available: webAvailable,
        loading: stillLoading,
      },
      documents: {
        value: stillLoading ? null : docCount,
        sublabel: knowledgeDocCount != null && !knowledgeDocError
          ? "knowledge library"
          : docAvailable
            ? "project documenten"
            : knowledgeDocError
              ? "UNMEASURED"
              : "—",
        available: docAvailable,
        loading: stillLoading,
      },
    };
  }, [loading, projects, workers.length, poolWorkers.length, sources, knowledgeDocCount, knowledgeDocError]);

  const stats7d = useMemo(() => aggregateProjectStats(projects, 7), [projects]);

  const knowledgeStatus = useMemo((): KnowledgeStatusRow[] => {
    const localDocs =
      knowledgeDocCount != null && !knowledgeDocError
        ? {
            id: "local",
            label: "Lokale Documenten",
            value: String(knowledgeDocCount),
            tone: "success" as const,
            pct: null,
          }
        : {
            id: "local",
            label: "Lokale Documenten",
            value: knowledgeDocError ? "UNMEASURED" : loading ? "…" : "0",
            tone: "muted" as const,
            pct: null,
          };

    const web =
      webReadiness == null
        ? {
            id: "web",
            label: "Web Index",
            value: loading ? "…" : "UNKNOWN",
            tone: "muted" as const,
            pct: null,
          }
        : webReadiness.search_available
          ? {
              id: "web",
              label: "Web Index",
              value: "Ready",
              tone: "success" as const,
              pct: null,
            }
          : webReadiness.direct_fetch_available
            ? {
                id: "web",
                label: "Web Index",
                value: "Fetch only",
                tone: "warning" as const,
                pct: null,
              }
            : {
                id: "web",
                label: "Web Index",
                value: "Unavailable",
                tone: "danger" as const,
                pct: null,
              };

    const vectorComp = health?.product_truth?.components?.find((c) =>
      `${c.id} ${c.name}`.toLowerCase().includes("vector"),
    );
    const vector =
      vectorComp != null
        ? {
            id: "vector",
            label: "Vector Database",
            value:
              vectorComp.measured === false
                ? "UNMEASURED"
                : vectorComp.status || "UNKNOWN",
            tone:
              vectorComp.measured === false
                ? ("muted" as const)
                : /ready|ok|healthy/i.test(vectorComp.status || "")
                  ? ("success" as const)
                  : ("muted" as const),
            pct: null,
          }
        : health?.neuro?.associative_memory === true
          ? {
              id: "vector",
              label: "Vector Database",
              value: "Ready",
              tone: "success" as const,
              pct: null,
            }
          : {
              id: "vector",
              label: "Vector Database",
              value: health ? "UNMEASURED" : "UNKNOWN",
              tone: "muted" as const,
              pct: null,
            };

    const external =
      sources.filter((s) => isWebSource(s) || (s.source_type || "").toLowerCase() === "seed").length;
    const externalRow = {
      id: "external",
      label: "Externe Bronnen",
      value: sources.length ? String(external) : loading ? "…" : "0",
      tone: sources.length ? ("info" as const) : ("muted" as const),
      pct: null,
    };

    return [localDocs, web, vector, externalRow];
  }, [knowledgeDocCount, knowledgeDocError, webReadiness, health, sources, loading]);

  const agentRows = useMemo((): ResearchAgentRow[] => {
    if (workers.length > 0) {
      return workers.map((w) => ({
        id: w.worker_id,
        name: `Worker ${w.worker_index + 1}`,
        status: w.status,
        statusTone:
          w.status === "running" || w.status === "active"
            ? "info"
            : w.status === "completed" || w.status === "idle"
              ? "success"
              : w.status === "failed"
                ? "danger"
                : "muted",
        expertise: w.current_task || w.phase || "Research worker",
        scope: "project" as const,
      }));
    }
    return poolWorkers;
  }, [workers, poolWorkers]);

  const sidebarStatus = useMemo((): SidebarStatusRow[] => {
    const llm = health?.llm;
    const lmValue =
      llm?.available === true
        ? "Running"
        : llm?.available === false
          ? "Offline"
          : health
            ? "UNMEASURED"
            : healthError
              ? "UNKNOWN"
              : "…";
    const lmTone =
      llm?.available === true ? "success" : llm?.available === false ? "danger" : "muted";

    return [
      { id: "lm-studio", label: "LM Studio", value: lmValue, tone: lmTone },
      {
        id: "web-research",
        label: "Web Research",
        value:
          webReadiness == null
            ? "…"
            : webReadiness.search_available
              ? "Ready"
              : webReadiness.direct_fetch_available
                ? "Fetch only"
                : "Unavailable",
        tone:
          webReadiness?.search_available
            ? "success"
            : webReadiness?.direct_fetch_available
              ? "warning"
              : webReadiness
                ? "danger"
                : "muted",
      },
      {
        id: "research-pool",
        label: "Research Pool",
        value: poolWorkers.length ? `${poolWorkers.length} workers` : loading ? "…" : "UNMEASURED",
        tone: poolWorkers.length ? "info" : "muted",
      },
      {
        id: "active-runs",
        label: "Actieve runs",
        value: String(projects.filter((p) => isActiveStatus(p.status)).length),
        tone: "info",
      },
      {
        id: "brain",
        label: "Brain",
        value: health?.ok === true ? "Online" : health?.ok === false ? "Offline" : "UNKNOWN",
        tone: health?.ok === true ? "success" : health?.ok === false ? "danger" : "muted",
      },
    ];
  }, [health, healthError, webReadiness, poolWorkers.length, projects, loading]);

  const online: boolean | null =
    health?.ok === true ? true : health?.ok === false || Boolean(healthError) ? false : null;

  const workspaceMode: "overview" | "run" =
    project && (isActiveStatus(project.status) || project.status === "completed" || project.status === "failed" || project.status === "cancelled" || project.status === "interrupted" || sources.length > 0 || evidence.length > 0)
      ? "run"
      : "overview";

  const ensureDraftProject = useCallback(async (): Promise<ResearchProject> => {
    if (project && project.status === "draft") return project;
    const topic = query.trim() || "Research draft";
    const created = await api.createResearchProject({
      topic,
      title: topic.slice(0, 80),
      objective: topic,
      depth,
      allowWeb: context.web,
      executionMode,
      modelProfile: selectedModel
        ? { modelId: selectedModel.id, displayName: selectedModel.displayName }
        : undefined,
      budget: {
        research_workers: effectiveWorkers,
        ...(executionMode === "team"
          ? { rounds: null, completion_policy: "quality_contract" }
          : { rounds: effectiveRounds }),
      },
      localScopes: [],
      seedSources: [],
    });
    hydrateFromProject(created.project);
    setProjects((prev) => [created.project, ...prev.filter((p) => p.project_id !== created.project.project_id)]);
    return created.project;
  }, [
    project,
    query,
    depth,
    context.web,
    executionMode,
    selectedModel,
    effectiveWorkers,
    effectiveRounds,
    hydrateFromProject,
  ]);

  function toggleContext(id: string) {
    setContext((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function applyTemplate(id: string) {
    const t = RD_TEMPLATES.find((x) => x.id === id);
    if (!t) return;
    setTemplateId(id);
    setDepth(t.depth);
    setExecutionMode(t.executionMode);
    setContext((c) => ({ ...c, web: t.allowWeb }));
    if (t.executionMode === "custom") {
      if ("workers" in t && t.workers != null) setCustomWorkers(t.workers);
      if ("rounds" in t && t.rounds != null) setCustomRounds(t.rounds);
    }
    if (t.prompt) setQuery((q) => (q.trim() ? q : t.prompt));
    if (t.id === "deep") {
      setComposerMode("deep");
      setTypePreset("deep");
    } else if (t.id === "competitive") {
      setTypePreset("comparative");
      setComposerMode("standaard");
    } else if (!t.allowWeb) {
      setComposerMode("document");
      setTypePreset("document");
    } else {
      setComposerMode(t.depth === "deep" || t.depth === "expert" ? "deep" : "standaard");
    }
    toast(`${t.labelNl} geselecteerd`);
  }

  function applyTypePreset(p: ResearchTypePreset) {
    setTypePreset(p);
    switch (p) {
      case "deep":
        setComposerMode("deep");
        setDepth("deep");
        setContext((c) => ({ ...c, web: true }));
        setExecutionMode("normal");
        break;
      case "web":
        setComposerMode("web");
        setDepth("standard");
        setContext((c) => ({ ...c, web: true }));
        break;
      case "document":
        setComposerMode("document");
        setDepth("standard");
        setContext((c) => ({ ...c, web: false, files: true }));
        break;
      case "comparative":
        applyTemplate("competitive");
        return;
    }
  }

  function onComposerModeChange(m: ResearchComposerMode) {
    setComposerMode(m);
    if (m === "deep") {
      setDepth("deep");
      setContext((c) => ({ ...c, web: true }));
      setTypePreset("deep");
    } else if (m === "web") {
      setDepth("standard");
      setContext((c) => ({ ...c, web: true }));
      setTypePreset("web");
    } else if (m === "document") {
      setContext((c) => ({ ...c, web: false, files: true }));
      setTypePreset("document");
    } else {
      setDepth("standard");
      setTypePreset(null);
    }
  }

  function buildSeedUrls(): string[] {
    return urlDraft
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function onFilesSelected(files: FileList | null) {
    if (!files?.length) return;
    const list = Array.from(files);
    setBusy(true);
    let ok = 0;
    try {
      const draft = await ensureDraftProject();
      for (const file of list) {
        if (!UPLOAD_EXT.test(file.name)) {
          toast(`Unsupported: ${file.name}`);
          continue;
        }
        const res = await api.uploadResearchSource(draft.project_id, file);
        ok += 1;
        const progressRow = res.progress;
        const status = progressRow?.status || res.status || res.source.parse_status;
        const brain = res.source.brain_status ? ` · brain ${res.source.brain_status}` : "";
        if (res.source_type === "archive" || progressRow) {
          setIngestionFocusId(res.source_id || res.source.source_id);
          if (progressRow) setIngestionProgress(progressRow);
          toast(`${file.name}: ${status}${brain}`);
        } else {
          toast(`${file.name}: parse ${res.source.parse_status}${brain}`);
        }
      }
      if (ok > 0) {
        setContext((c) => ({ ...c, files: true }));
        await refreshArtifacts(draft.project_id);
        const detail = await api.getResearchProject(draft.project_id);
        setProject(detail.project);
      }
    } catch (err) {
      toast(errMsg(err, "File upload failed"));
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    void onFilesSelected(e.dataTransfer.files);
  }

  async function onAddUrlSource() {
    const urls = buildSeedUrls();
    if (!urls.length) {
      toast("Enter at least one URL");
      return;
    }
    setBusy(true);
    try {
      const draft = await ensureDraftProject();
      for (const url of urls) {
        await api.addResearchUrlSource(draft.project_id, url);
      }
      toast(`${urls.length} URL(s) added`);
      setUrlDraft("");
      await refreshArtifacts(draft.project_id);
      const detail = await api.getResearchProject(draft.project_id);
      setProject(detail.project);
    } catch (err) {
      toast(errMsg(err, "Failed to add URL source"));
    } finally {
      setBusy(false);
    }
  }

  async function loadDatasetsForPicker() {
    try {
      const [dsRes, jobsRes] = await Promise.all([
        api.listDatasets(200),
        api.listDatasetJobs(undefined, 200),
      ]);
      setDatasets(dsRes.datasets);
      setDatasetJobs(jobsRes.jobs);
      if (!selectedDatasetId && dsRes.datasets[0]) {
        setSelectedDatasetId(dsRes.datasets[0].datasetId);
      }
    } catch (err) {
      toast(errMsg(err, "Failed to load datasets"));
    }
  }

  async function onConnectDataset() {
    if (!selectedDatasetId) {
      toast("Select a dataset first");
      return;
    }
    const ds = datasets.find((d) => d.datasetId === selectedDatasetId);
    if (!ds) {
      toast("Dataset not found");
      return;
    }
    const indexed = datasetIndexed(ds, datasetJobs);
    if (indexed === false) {
      toast("This dataset is not indexed yet — index it in Datasets before connecting to Research.");
      return;
    }
    setBusy(true);
    try {
      const draft = await ensureDraftProject();
      const res = await api.connectResearchDataset(draft.project_id, {
        datasetId: ds.datasetId,
        indexed: indexed === true,
        label: ds.name,
      });
      hydrateFromProject(res.project);
      setConnectedDatasetLabel(ds.name);
      setContext((c) => ({ ...c, datasets: true }));
      toast(`Connected ${ds.name}`);
    } catch (err) {
      toast(errMsg(err, "Failed to connect dataset"));
    } finally {
      setBusy(false);
    }
  }

  async function onStartResearch() {
    const topic = query.trim();
    if (!topic) {
      toast("Stel eerst een onderzoeksvraag");
      return;
    }
    setBusy(true);
    try {
      const seeds = buildSeedUrls();
      const payload = {
        topic,
        title: topic.slice(0, 80),
        objective: topic,
        depth,
        allowWeb: !!context.web,
        executionMode,
        modelProfile: selectedModel
          ? { modelId: selectedModel.id, displayName: selectedModel.displayName }
          : { modelId: "auto", displayName: "Auto (default LLM)" },
        budget: {
          research_workers: effectiveWorkers,
          ...(executionMode === "team"
            ? { rounds: null, completion_policy: "quality_contract" }
            : { rounds: effectiveRounds }),
        },
        localScopes: [] as string[],
        seedSources: seeds,
      };

      let projectId: string;
      if (project?.status === "draft") {
        const updated = await api.updateResearchProject(project.project_id, payload);
        projectId = updated.project.project_id;
        setProject(updated.project);
      } else {
        const created = await api.createResearchProject(payload);
        projectId = created.project.project_id;
        setProject(created.project);
      }
      const started = await api.runResearchProject(projectId);
      setProject(started.project);
      setWorkers(started.project.workers ?? []);
      setSources([]);
      setEvidence([]);
      setClaims([]);
      setConflicts([]);
      setGaps([]);
      setReport(null);
      setProjects((prev) => [started.project, ...prev.filter((p) => p.project_id !== projectId)]);
      toast("Onderzoek gestart");
    } catch (err) {
      toast(errMsg(err, "Failed to start research"));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    if (!project || !ACTIVE_STATUSES.has(project.status)) return;
    setBusy(true);
    try {
      const res = await api.cancelResearchProject(project.project_id);
      setProject(res.project);
      toast("Annulering aangevraagd");
    } catch (err) {
      toast(errMsg(err, "Cancel failed"));
    } finally {
      setBusy(false);
    }
  }

  async function probeWeb() {
    setWebProbeBusy(true);
    try {
      const res = await api.probeResearchWeb();
      toast(res.probe?.status === "ok" ? "Web research probe OK" : res.probe?.error || "Web probe finished");
      const readiness = await api.getResearchWebReadiness();
      setWebReadiness(readiness.readiness);
    } catch (err) {
      toast(errMsg(err, "Web probe failed"));
    } finally {
      setWebProbeBusy(false);
    }
  }

  function focusComposer() {
    composerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    const ta = composerRef.current?.querySelector("textarea");
    ta?.focus();
  }

  function focusTemplates() {
    setShowAllTemplates(true);
    templatesRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return {
    loading,
    refreshing,
    refresh,
    online,
    sidebarStatus,
    loadError,
    projects,
    recentProjects,
    projectFilter,
    setProjectFilter,
    projectSearch,
    setProjectSearch,
    filterCounts,
    showAllRecent,
    setShowAllRecent,
    project,
    selectProject,
    clearSelection,
    workspaceMode,
    workers,
    poolWorkers,
    sources,
    evidence,
    claims,
    conflicts,
    gaps,
    report,
    webReadiness,
    metrics,
    stats7d,
    knowledgeStatus,
    agentRows,
    inputTab,
    setInputTab,
    query,
    setQuery,
    composerMode,
    setComposerMode: onComposerModeChange,
    typePreset,
    setTypePreset,
    applyTypePreset,
    templateId,
    templateFilter,
    setTemplateFilter,
    applyTemplate,
    showAllTemplates,
    setShowAllTemplates,
    advancedOpen,
    setAdvancedOpen,
    depth,
    setDepth,
    executionMode,
    setExecutionMode,
    customWorkers,
    setCustomWorkers,
    customRounds,
    setCustomRounds,
    context,
    toggleContext,
    models,
    modelId,
    setModelId,
    budgetCatalog,
    effectiveWorkers,
    effectiveRounds,
    urlDraft,
    setUrlDraft,
    datasets,
    datasetJobs,
    selectedDatasetId,
    setSelectedDatasetId,
    connectedDatasetLabel,
    loadDatasetsForPicker,
    onConnectDataset,
    onFilesSelected,
    onDrop,
    onAddUrlSource,
    dragOver,
    setDragOver,
    busy,
    onStartResearch,
    onCancel,
    focusComposer,
    focusTemplates,
    composerRef,
    templatesRef,
    ingestionFocusId,
    ingestionProgress,
    ingestionMembers,
    ingestionTotal,
    webProbeBusy,
    probeWeb,
    evidenceRows,
    webRows,
    insightRows,
    timeline,
    progress,
    isLive,
    diagnosis,
  };
}
