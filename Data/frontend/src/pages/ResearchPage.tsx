import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { mediaPageHeroes } from "../assets/mediaPagesAssets";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import {
  RD_CONTEXT_CHIPS,
  RD_HERO,
  RD_IDLE_TIMELINE,
  RD_INPUT_TABS,
  RD_TEMPLATES,
  type RdEvidenceItem,
  type RdInputTab,
  type RdInsight,
  type RdTimelineStep,
  type RdTimelineStepStatus,
  type RdWebResult,
} from "../config/research";
import { useAppToast } from "../state/useAppToast";
import type {
  DatasetJob,
  DatasetRecord,
  ModelDescriptor,
  ResearchBudgetCatalog,
  ResearchClaim,
  ResearchEvidence,
  ResearchProject,
  ResearchSource,
  ResearchWorker,
  SourceIngestionMember,
  SourceIngestionProgress,
} from "../types/api";

const ACTIVE = new Set(["queued", "researching", "synthesizing", "cancelling"]);

const UPLOAD_EXT =
  /\.(pdf|txt|md|markdown|csv|json|jsonl|ndjson|log|rst|ya?ml|toml|docx|xlsx|pptx|py|ts|tsx|js|jsx|zip|tar|tgz|gz)$/i;

const INGEST_ACTIVE = new Set([
  "queued",
  "inspecting",
  "expanding",
  "classifying",
  "parsing",
  "normalizing",
  "brain_pending",
  "brain_syncing",
  "uploading",
  "stored",
]);

const UPLOAD_ACCEPT =
  ".pdf,.txt,.md,.markdown,.csv,.json,.jsonl,.ndjson,.log,.rst,.yaml,.yml,.toml,.docx,.xlsx,.pptx,.py,.ts,.tsx,.js,.jsx,.zip,.tar,.tgz,.gz";


const PHASE_STEP_INDEX: Record<string, number> = {
  idle: 0,
  planning: 0,
  source_ingestion: 1,
  source_fetch: 1,
  source_parse: 1,
  local_retrieval: 2,
  web_search: 2,
  evidence_extraction: 3,
  claim_analysis: 4,
  conflict_analysis: 5,
  query_adaptation: 6,
  synthesis: 6,
  report_generation: 7,
  brain_sync: 8,
  completed: 9,
  failed: -2,
  cancelled: -2,
};

type ExecutionMode = "normal" | "custom" | "team";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function domainFromUri(uri: string | null | undefined): string {
  if (!uri) return "source";
  try {
    return new URL(uri).hostname.replace(/^www\./, "");
  } catch {
    return uri.slice(0, 28);
  }
}

function relativeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}h ago`;
  const days = Math.round(hr / 24);
  return `${days}d ago`;
}

function confTone(label: string): "high" | "mid" | "muted" {
  if (label.toLowerCase().startsWith("supported")) return "high";
  if (label.toLowerCase() === "unmeasured") return "muted";
  return "mid";
}

function claimSupportLabel(claim: ResearchClaim): string {
  const n = claim.supporting_evidence_ids?.length ?? 0;
  if (n > 0) return `Supported by ${n} evidence span${n === 1 ? "" : "s"}`;
  return "Unmeasured";
}

function projectProgress(project: ResearchProject | null): number {
  if (!project) return 0;
  const status = project.status;
  if (status === "failed" || status === "cancelled" || status === "interrupted") {
    const pct = project.progress_pct;
    if (pct != null && Number.isFinite(pct)) return Math.min(99, Math.round(pct));
    return 0;
  }
  if (status === "completed") {
    const pct = project.progress_pct;
    return pct != null && Number.isFinite(pct) ? Math.round(pct) : 100;
  }
  const pct = project.progress_pct;
  if (pct != null && Number.isFinite(pct)) return Math.round(pct);
  return 0;
}

function stepMeta(id: string, project: ResearchProject): string | undefined {
  switch (id) {
    case "ingestion":
      return project.source_count > 0 ? `${project.source_count} sources` : undefined;
    case "evidence":
      return project.evidence_count > 0 ? `${project.evidence_count} spans` : undefined;
    case "claims":
      return project.claim_count > 0 ? `${project.claim_count} claims` : undefined;
    case "conflicts":
      return project.conflict_count > 0 ? `${project.conflict_count} conflicts` : undefined;
    case "complete":
      return project.status === "completed" ? "Done" : undefined;
    default:
      return undefined;
  }
}

function timelineFromProject(project: ResearchProject | null): RdTimelineStep[] {
  if (!project) return RD_IDLE_TIMELINE;

  const status = project.status;
  const phaseKey = (project.phase || "idle").toLowerCase();
  const failed =
    status === "failed" ||
    status === "cancelled" ||
    status === "interrupted" ||
    phaseKey === "failed" ||
    phaseKey === "cancelled";
  const completed = status === "completed" || phaseKey === "completed";

  let activeIdx = PHASE_STEP_INDEX[phaseKey] ?? 0;
  if (status === "draft") activeIdx = -1;
  if (completed) activeIdx = RD_IDLE_TIMELINE.length;

  return RD_IDLE_TIMELINE.map((base, i) => {
    let stepStatus: RdTimelineStepStatus = "queued";
    let meta = base.meta;

    if (completed) {
      stepStatus = "done";
      meta = stepMeta(base.id, project) ?? base.meta;
    } else if (failed) {
      const failAt = activeIdx >= 0 ? activeIdx : 0;
      if (i < failAt) stepStatus = "done";
      else if (i === failAt) {
        stepStatus = "failed";
        meta = project.error || status;
      } else stepStatus = "queued";
    } else if (status === "draft") {
      stepStatus = "queued";
      meta = "Waiting";
    } else {
      if (i < activeIdx) {
        stepStatus = "done";
        meta = stepMeta(base.id, project) ?? base.meta;
      } else if (i === activeIdx) {
        stepStatus = "active";
        meta = stepMeta(base.id, project) ?? (project.phase?.replace(/_/g, " ") || "In progress…");
      } else {
        stepStatus = "queued";
        meta = "Waiting";
      }
    }

    return { ...base, status: stepStatus, meta };
  });
}

function mapSourcesToEvidence(sources: ResearchSource[]): RdEvidenceItem[] {
  return sources.slice(0, 8).map((s) => {
    const domain = domainFromUri(s.canonical_uri ?? s.original_uri);
    const parseNote = `parse ${s.parse_status}`;
    const brainNote = s.brain_status ? ` · brain ${s.brain_status}` : "";
    return {
      id: s.source_id,
      title: s.title || domain || "Untitled source",
      domain,
      ago: relativeAgo(s.fetched_at || s.created_at),
      confidence: null,
      supportLabel: `${parseNote}${brainNote}`,
      favicon: (domain[0] || "?").toUpperCase(),
      url: s.canonical_uri ?? s.original_uri ?? undefined,
    };
  });
}

function mapSourcesToWeb(sources: ResearchSource[], evidence: ResearchEvidence[]): RdWebResult[] {
  const webby = sources.filter(
    (s) => (s.source_type || "").toLowerCase().includes("web") || !!s.canonical_uri,
  );
  const pool = (webby.length ? webby : sources).slice(0, 3);
  return pool.map((s, i) => {
    const domain = domainFromUri(s.canonical_uri ?? s.original_uri);
    const span = evidence.find((e) => e.source_id === s.source_id)?.span_text;
    return {
      id: s.source_id,
      rank: i + 1,
      title: s.title || domain || "Web result",
      domain,
      snippet: span
        ? span.slice(0, 160) + (span.length > 160 ? "…" : "")
        : `${s.source_type || "source"} · parse ${s.parse_status}`,
    };
  });
}

function mapClaimsToInsights(claims: ResearchClaim[]): RdInsight[] {
  const icons: RdInsight["icon"][] = ["bot", "brain", "bulb"];
  return claims.slice(0, 5).map((c, i) => ({
    id: c.claim_id,
    title: c.proposition.slice(0, 72) + (c.proposition.length > 72 ? "…" : ""),
    body: c.raw_wording || c.proposition,
    confidence: null,
    supportLabel: claimSupportLabel(c),
    icon: icons[i % icons.length],
  }));
}

function datasetIndexed(ds: DatasetRecord, jobs: DatasetJob[]): boolean | null {
  const related = jobs.filter((j) => j.datasetId === ds.datasetId);
  const indexing = related.some((j) => {
    const t = j.jobType.toLowerCase();
    const s = j.status.toLowerCase();
    return t.includes("index") && (s === "running" || s === "queued" || s === "pending");
  });
  if (indexing) return false;
  const done = related.some((j) => {
    const t = j.jobType.toLowerCase();
    const s = j.status.toLowerCase();
    return t.includes("index") && (s === "completed" || s === "succeeded" || s === "done");
  });
  if (done) return true;
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const emb = String(meta?.embeddings ?? meta?.indexStatus ?? "").toLowerCase();
  if (emb.includes("index") && !emb.includes("not")) return true;
  if (ds.status.toLowerCase() === "ready") return false;
  return null;
}

function Icon({ name }: { name: string }) {
  const common = { viewBox: "0 0 24 24", "aria-hidden": true as const };
  switch (name) {
    case "globe":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
      );
    case "file":
      return (
        <svg {...common}>
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z" />
          <path d="M14 3v6h6" />
        </svg>
      );
    case "database":
      return (
        <svg {...common}>
          <ellipse cx="12" cy="5" rx="7" ry="3" />
          <path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
        </svg>
      );
    case "code":
      return (
        <svg {...common}>
          <path d="M8 8 4 12l4 4M16 8l4 4-4 4M13 5l-2 14" />
        </svg>
      );
    case "image":
      return (
        <svg {...common}>
          <rect x="4" y="5" width="16" height="14" rx="2" />
          <circle cx="9" cy="10" r="1.5" />
          <path d="m7 17 4-4 3 3 3-4 3 5" />
        </svg>
      );
    case "chevron":
      return (
        <svg {...common}>
          <path d="m7 10 5 5 5-5" />
        </svg>
      );
    case "upload":
      return (
        <svg {...common}>
          <path d="M12 16V6M8 9l4-4 4 4M5 18h14" />
        </svg>
      );
    case "link":
      return (
        <svg {...common}>
          <path d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.1 1" />
          <path d="M14 11a5 5 0 0 0-7.1 0l-2 2a5 5 0 0 0 7.1 7.1l1.1-1" />
        </svg>
      );
    case "ingest":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
        </svg>
      );
    case "network":
      return (
        <svg {...common}>
          <circle cx="6" cy="7" r="2" />
          <circle cx="18" cy="7" r="2" />
          <circle cx="12" cy="17" r="2" />
          <path d="M8 7h8M7.5 8.5 11 15M16.5 8.5 13 15" />
        </svg>
      );
    case "target":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8" />
          <circle cx="12" cy="12" r="4" />
          <circle cx="12" cy="12" r="1" />
        </svg>
      );
    case "check":
      return (
        <svg {...common}>
          <path d="m6 12 4 4 8-8" />
        </svg>
      );
    case "ext":
      return (
        <svg {...common}>
          <path d="M14 5h5v5M19 5l-9 9M10 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4" />
        </svg>
      );
    case "bot":
      return (
        <svg {...common}>
          <rect x="6" y="8" width="12" height="10" rx="2" />
          <path d="M12 4v4M9 12h.01M15 12h.01M9 16h6" />
        </svg>
      );
    case "brain":
      return (
        <svg {...common}>
          <path d="M9 5a3 3 0 0 0-3 3v1a3 3 0 0 0 0 6v1a3 3 0 0 0 3 3M15 5a3 3 0 0 1 3 3v1a3 3 0 0 1 0 6v1a3 3 0 0 1-3 3M12 5v14" />
        </svg>
      );
    case "bulb":
      return (
        <svg {...common}>
          <path d="M9 18h6M10 21h4M8 14a5 5 0 1 1 8 0c-.8.9-1.5 1.6-1.5 3h-5c0-1.4-.7-2.1-1.5-3z" />
        </svg>
      );
    default:
      return null;
  }
}

export function ResearchPage() {
  const toast = useAppToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [inputTab, setInputTab] = useState<RdInputTab>("Query");
  const [query, setQuery] = useState("");
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [modelId, setModelId] = useState("");
  const [budgetCatalog, setBudgetCatalog] = useState<ResearchBudgetCatalog | null>(null);
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("normal");
  const [customWorkers, setCustomWorkers] = useState(2);
  const [customRounds, setCustomRounds] = useState(10);

  const [templateId, setTemplateId] = useState<string | null>(null);
  const [depth, setDepth] = useState("deep");
  const [context, setContext] = useState<Record<string, boolean>>({
    web: true,
    files: false,
    datasets: false,
    code: false,
    images: false,
  });
  const [dragOver, setDragOver] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [scopeEditing, setScopeEditing] = useState(false);

  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [datasetJobs, setDatasetJobs] = useState<DatasetJob[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [connectedDatasetLabel, setConnectedDatasetLabel] = useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [workers, setWorkers] = useState<ResearchWorker[]>([]);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [ingestionFocusId, setIngestionFocusId] = useState<string | null>(null);
  const [ingestionProgress, setIngestionProgress] = useState<SourceIngestionProgress | null>(null);
  const [ingestionMembers, setIngestionMembers] = useState<SourceIngestionMember[]>([]);
  const [ingestionTotal, setIngestionTotal] = useState(0);
  const [ingestionOffset, setIngestionOffset] = useState(0);
  const [evidence, setEvidence] = useState<ResearchEvidence[]>([]);
  const [claims, setClaims] = useState<ResearchClaim[]>([]);
  const [gaps, setGaps] = useState<Array<Record<string, unknown>>>([]);
  const [hasLiveProject, setHasLiveProject] = useState(false);

  const selectedModel = useMemo(
    () => (modelId ? models.find((m) => m.id === modelId) ?? null : null),
    [models, modelId],
  );

  const normalMode = budgetCatalog?.execution_modes.normal;
  const customLimits = budgetCatalog?.execution_modes.custom.limits;

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

  const fileSourceCount = useMemo(
    () =>
      sources.filter((s) => {
        const t = (s.source_type || "").toLowerCase();
        return t.includes("file") || t.includes("local") || t === "seed";
      }).length,
    [sources],
  );

  const isLive = !!(project && ACTIVE.has(project.status));
  const progress = projectProgress(project);
  const timeline = useMemo(() => timelineFromProject(project), [project]);

  const evidenceRows = useMemo(() => {
    if (sources.length > 0) return mapSourcesToEvidence(sources);
    return [] as RdEvidenceItem[];
  }, [sources]);

  const webRows = useMemo(() => {
    if (sources.length > 0) return mapSourcesToWeb(sources, evidence);
    return [] as RdWebResult[];
  }, [sources, evidence]);

  const insightRows = useMemo(() => {
    if (claims.length > 0) return mapClaimsToInsights(claims);
    return [] as RdInsight[];
  }, [claims]);

  const showGenerating = isLive || (!!project && project.status === "synthesizing");
  const evidenceCountLabel =
    sources.length > 0 ? `${sources.length} sources` : hasLiveProject ? "0 sources" : "no project yet";

  const hydrateFromProject = useCallback((p: ResearchProject) => {
    setProject(p);
    setHasLiveProject(true);
    if (p.topic && !query.trim()) setQuery(p.topic);
    if (p.depth) setDepth(p.depth);
    if (typeof p.allow_web === "boolean") setContext((c) => ({ ...c, web: p.allow_web }));
    if (p.execution_mode === "normal" || p.execution_mode === "custom") {
      setExecutionMode(
        p.execution_mode === "team" || p.execution_mode === "custom" || p.execution_mode === "normal"
          ? p.execution_mode
          : "normal",
      );
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
  }, [query]);

  const refreshArtifacts = useCallback(async (projectId: string) => {
    const [src, ev, cl, gapRes] = await Promise.all([
      api.listResearchSources(projectId).catch(() => ({ sources: [] as ResearchSource[] })),
      api.listResearchEvidence(projectId).catch(() => ({ evidence: [] as ResearchEvidence[] })),
      api.listResearchClaims(projectId).catch(() => ({ claims: [] as ResearchClaim[] })),
      api.getResearchGaps(projectId).catch(() => ({ gaps: [] as Array<Record<string, unknown>> })),
    ]);
    setSources(src.sources);
    setEvidence(ev.evidence);
    setClaims(cl.claims);
    setGaps(gapRes.gaps ?? []);
    if (src.sources.length > 0) {
      setContext((c) => ({ ...c, files: true }));
    }
  }, []);

  const refreshWorkers = useCallback(async (projectId: string) => {
    const res = await api.listResearchWorkers(projectId).catch(() => ({ workers: [] as ResearchWorker[] }));
    setWorkers(res.workers);
  }, []);

  const loadLatest = useCallback(async () => {
    setLoadError(null);
    try {
      const list = await api.listResearchProjects();
      const projects = list.projects;
      if (projects.length === 0) {
        setProject(null);
        setHasLiveProject(false);
        setWorkers([]);
        setSources([]);
        setEvidence([]);
        setClaims([]);
        setGaps([]);
        return;
      }
      const preferred =
        projects.find((p) => ACTIVE.has(p.status)) ??
        projects.find((p) => p.status === "completed") ??
        projects[0];
      const detail = await api.getResearchProject(preferred.project_id);
      hydrateFromProject(detail.project);
      await refreshArtifacts(detail.project.project_id);
      if (ACTIVE.has(detail.project.status)) {
        await refreshWorkers(detail.project.project_id);
      }
    } catch (err) {
      setLoadError(errMsg(err, "Failed to load research projects"));
    }
  }, [hydrateFromProject, refreshArtifacts, refreshWorkers]);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  useEffect(() => {
    if (!ingestionFocusId || !project?.project_id) return;
    let cancelled = false;
    const projectId = project.project_id;
    const sourceId = ingestionFocusId;

    async function tick() {
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
        /* ignore transient poll errors */
      }
    }

    void tick();
    const phase = ingestionProgress?.phase || ingestionProgress?.status || "";
    if (!INGEST_ACTIVE.has(phase)) return;
    const id = window.setInterval(() => void tick(), 1500);
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
    let cancelled = false;
    (async () => {
      // Load independently — a budget failure must not leave Start Research stuck
      // behind an empty model gate.
      const [modelOutcome, budgetOutcome] = await Promise.allSettled([
        api.listModels(),
        api.researchBudgets(),
      ]);
      if (cancelled) return;

      if (modelOutcome.status === "fulfilled") {
        let listed = modelOutcome.value.models ?? [];
        if (listed.length === 0) {
          try {
            const refreshed = await api.refreshModels();
            if (!cancelled) listed = refreshed.models ?? [];
          } catch {
            /* empty registry is allowed — research can start on Auto */
          }
        }
        if (cancelled) return;
        setModels(listed);
        setModelId((prev) => prev || listed[0]?.id || "");
      } else if (!cancelled) {
        toast(errMsg(modelOutcome.reason, "Failed to load models"));
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
    })();
    return () => {
      cancelled = true;
    };
  }, [toast]);

  useEffect(() => {
    if (!project || !ACTIVE.has(project.status)) return;
    const projectId = project.project_id;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await api.getResearchProject(projectId);
        if (cancelled) return;
        setProject(res.project);
        if (res.project.workers?.length) setWorkers(res.project.workers);
        else await refreshWorkers(projectId);
        const countsChanged =
          res.project.source_count !== project.source_count ||
          res.project.evidence_count !== project.evidence_count ||
          res.project.claim_count !== project.claim_count;
        if (countsChanged || !ACTIVE.has(res.project.status)) {
          await refreshArtifacts(projectId);
        }
      } catch {
        /* keep last known */
      }
    };
    const id = window.setInterval(() => void tick(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [project?.project_id, project?.status, project?.source_count, project?.evidence_count, project?.claim_count, refreshArtifacts, refreshWorkers]);

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
    if (t.prompt) {
      setQuery((q) => (q.trim() ? q : t.prompt));
    }
    toast(`${t.label} selected`);
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
        // Client accept is convenience only — backend is authoritative. No hard 100MB ceiling.
        const res = await api.uploadResearchSource(draft.project_id, file);
        ok += 1;
        const progress = res.progress;
        const status = progress?.status || res.status || res.source.parse_status;
        const brain = res.source.brain_status ? ` · brain ${res.source.brain_status}` : "";
        if (res.source_type === "archive" || progress) {
          setIngestionFocusId(res.source_id || res.source.source_id);
          if (progress) setIngestionProgress(progress);
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
      toast("Ask a research question first");
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
        // Model is optional — backend falls back to wired model_caller / deterministic analysis.
        modelProfile: selectedModel
          ? {
              modelId: selectedModel.id,
              displayName: selectedModel.displayName,
            }
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
      setHasLiveProject(true);
      const started = await api.runResearchProject(projectId);
      setProject(started.project);
      setWorkers(started.project.workers ?? []);
      setSources([]);
      setEvidence([]);
      setClaims([]);
      toast("Research started");
    } catch (err) {
      toast(errMsg(err, "Failed to start research"));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    if (!project || !ACTIVE.has(project.status)) return;
    setBusy(true);
    try {
      const res = await api.cancelResearchProject(project.project_id);
      setProject(res.project);
      toast("Cancel requested");
    } catch (err) {
      toast(errMsg(err, "Cancel failed"));
    } finally {
      setBusy(false);
    }
  }

  const heroSrc = mediaPageHeroes.research || "/assets/hero-research.jpg";
  const workerRows =
    workers.length > 0 ? workers : (project?.workers?.length ? project.workers : []);

  const phaseLabel = project?.phase?.replace(/_/g, " ") ?? (project ? project.status : "idle");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Search research…"
      pageClass="lv-app--research-dash"
      layout="wide"
    >
      <main className="lv-main lv-rd-main">
        <section className="lv-rd-hero" aria-label="Research">
          <span className="lv-rd-hero-ornament is-tl" />
          <span className="lv-rd-hero-ornament is-tr" />
          <span className="lv-rd-hero-ornament is-bl" />
          <span className="lv-rd-hero-ornament is-br" />
          <div className="lv-rd-hero-media">
            <img src={heroSrc} alt="" width={1600} height={440} />
          </div>
          <div className="lv-rd-hero-shade" />
          <div className="lv-rd-hero-content">
            <div className="lv-rd-hero-copy">
              <h1 className="lv-rd-hero-title">{RD_HERO.title}</h1>
              <p className="lv-rd-hero-tagline">{RD_HERO.tagline}</p>
              <p className="lv-rd-hero-desc">{RD_HERO.description}</p>
            </div>
            <blockquote className="lv-rd-hero-quote">{RD_HERO.quote}</blockquote>
          </div>
        </section>

        {loadError ? (
          <p className="lv-rd-error" role="alert">
            {loadError}
          </p>
        ) : null}

        <section className="lv-rd-query" aria-label="Research query">
          <div className="lv-rd-query-top">
            <div className="lv-rd-tabs" role="tablist">
              {RD_INPUT_TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={inputTab === tab}
                  className={`lv-rd-tab${inputTab === tab ? " is-active" : ""}`}
                  onClick={() => {
                    setInputTab(tab);
                    if (tab === "Datasets") void loadDatasetsForPicker();
                  }}
                >
                  {tab}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="lv-rd-templates-btn"
              onClick={() => {
                const next =
                  RD_TEMPLATES[
                    (RD_TEMPLATES.findIndex((t) => t.id === templateId) + 1) % RD_TEMPLATES.length
                  ];
                applyTemplate(next.id);
              }}
            >
              Research Templates
              <Icon name="chevron" />
            </button>
          </div>

          <div className="lv-rd-composer">
            <div className="lv-rd-composer-top">
              <select
                className="lv-rd-model"
                value={modelId}
                aria-label="Model"
                onChange={(e) => setModelId(e.target.value)}
              >
                <option value="">Auto (default LLM)</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.displayName}
                  </option>
                ))}
              </select>
            </div>
            <textarea
              className="lv-rd-textarea"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={
                inputTab === "Query"
                  ? "Ask a research question..."
                  : inputTab === "URLs"
                    ? "Paste URLs to investigate…"
                    : `Describe ${inputTab.toLowerCase()} context…`
              }
              aria-label="Research question"
            />
            {inputTab === "URLs" ? (
              <>
                <textarea
                  className="lv-rd-textarea"
                  style={{ minHeight: 48 }}
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  placeholder="https://example.com/paper …"
                  aria-label="Seed URLs"
                />
                <div className="lv-rd-composer-foot">
                  <button
                    type="button"
                    className="lv-rd-ghost-btn"
                    disabled={busy || !urlDraft.trim()}
                    onClick={() => void onAddUrlSource()}
                  >
                    Add URLs to project
                  </button>
                </div>
              </>
            ) : null}
            {inputTab === "Datasets" ? (
              <div className="lv-rd-composer-foot" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <select
                  className="lv-rd-model"
                  value={selectedDatasetId}
                  aria-label="Dataset"
                  onChange={(e) => setSelectedDatasetId(e.target.value)}
                >
                  {datasets.length === 0 ? (
                    <option value="">No datasets</option>
                  ) : (
                    datasets.map((d) => (
                      <option key={d.datasetId} value={d.datasetId}>
                        {d.name}
                      </option>
                    ))
                  )}
                </select>
                <button
                  type="button"
                  className="lv-rd-ghost-btn"
                  disabled={busy || !selectedDatasetId}
                  onClick={() => void onConnectDataset()}
                >
                  Connect selected dataset
                </button>
              </div>
            ) : null}
            <div className="lv-rd-composer-foot">
              <div className="lv-rd-chips">
                <button
                  type="button"
                  className="lv-rd-chip is-add"
                  onClick={() => fileInputRef.current?.click()}
                >
                  + Add context
                </button>
                {RD_CONTEXT_CHIPS.map((chip) => {
                  const unavailable = "unavailable" in chip ? chip.unavailable : undefined;
                  return (
                    <button
                      key={chip.id}
                      type="button"
                      className={`lv-rd-chip${context[chip.id] ? " is-active" : ""}`}
                      disabled={!!unavailable}
                      title={unavailable ?? undefined}
                      onClick={() => {
                        if (unavailable) {
                          toast(unavailable);
                          return;
                        }
                        toggleContext(chip.id);
                      }}
                    >
                      <Icon name={chip.icon} />
                      {chip.label}
                    </button>
                  );
                })}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {isLive ? (
                  <button type="button" className="lv-rd-ghost-btn" disabled={busy} onClick={() => void onCancel()}>
                    Cancel
                  </button>
                ) : null}
                <button
                  type="button"
                  className="lv-rd-start"
                  disabled={busy || !query.trim()}
                  onClick={() => void onStartResearch()}
                  title={
                    !query.trim()
                      ? "Enter a research question first"
                      : selectedModel
                        ? `Start with ${selectedModel.displayName}`
                        : "Start with Auto (default LLM)"
                  }
                >
                  {busy ? "Starting…" : "Start Research →"}
                </button>
              </div>
            </div>
          </div>

          <div className="lv-rd-pills" aria-label="Research templates">
            {RD_TEMPLATES.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`lv-rd-pill${templateId === t.id ? " is-active" : ""}`}
                onClick={() => applyTemplate(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </section>

        <section className="lv-rd-row" aria-label="Research operations">
          <article className="lv-rd-panel">
            <div className="lv-rd-panel-head">
              <h2 className="lv-rd-panel-title">
                <Icon name="ingest" />
                Source Ingestion
              </h2>
            </div>
            <div
              className={`lv-rd-dropzone${dragOver ? " is-drag" : ""}`}
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
            >
              <Icon name="upload" />
              <div>
                <strong>Drop files here or click to upload</strong>
                <small>
                  PDF, text, code, Office, ZIP/TAR archives → durable Source Ingestion (backend-enforced limits)
                </small>
              </div>
              {fileSourceCount > 0 ? <small>{fileSourceCount} file source(s) on project</small> : null}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={UPLOAD_ACCEPT}
              hidden
              onChange={(e) => void onFilesSelected(e.target.files)}
            />
            {ingestionProgress ? (
              <div className="lv-rd-ingest-status" aria-live="polite">
                <div className="lv-rd-panel-head">
                  <h3 className="lv-rd-panel-title">Source Ingestion</h3>
                  <span className="lv-rd-badge is-count">
                    {ingestionProgress.filename || "upload"} · {ingestionProgress.status}
                  </span>
                </div>
                <p className="lv-rd-ingest-summary">
                  {ingestionProgress.archive_type ? `${ingestionProgress.archive_type} · ` : ""}
                  {ingestionProgress.progress_pct != null
                    ? `${ingestionProgress.progress_pct}% · `
                    : "working · "}
                  ingested {ingestionProgress.files_ingested}/{ingestionProgress.files_discovered}
                  {" · "}skipped {ingestionProgress.files_skipped}
                  {" · "}failed {ingestionProgress.files_failed}
                  {" · "}brain {ingestionProgress.brain_synced}
                  {ingestionProgress.files_quarantined
                    ? ` · quarantined ${ingestionProgress.files_quarantined}`
                    : ""}
                  {ingestionProgress.files_routed ? ` · routed ${ingestionProgress.files_routed}` : ""}
                </p>
                <div className="lv-rd-ingest-actions">
                  {INGEST_ACTIVE.has(ingestionProgress.status) ? (
                    <button
                      type="button"
                      className="lv-rd-ghost-btn"
                      disabled={busy || !project}
                      onClick={() => {
                        if (!project || !ingestionFocusId) return;
                        void api
                          .cancelSourceIngestion(project.project_id, ingestionFocusId)
                          .then((r) => setIngestionProgress(r.progress))
                          .catch((err) => toast(errMsg(err, "Cancel failed")));
                      }}
                    >
                      Cancel
                    </button>
                  ) : null}
                  {ingestionProgress.files_failed > 0 ? (
                    <button
                      type="button"
                      className="lv-rd-ghost-btn"
                      disabled={busy || !project}
                      onClick={() => {
                        if (!project || !ingestionFocusId) return;
                        void api
                          .retrySourceIngestion(project.project_id, ingestionFocusId, true)
                          .then((r) => {
                            if (r.progress) setIngestionProgress(r.progress);
                            toast("Retry queued");
                          })
                          .catch((err) => toast(errMsg(err, "Retry failed")));
                      }}
                    >
                      Retry failed
                    </button>
                  ) : null}
                  {ingestionProgress.brain_failed > 0 ? (
                    <button
                      type="button"
                      className="lv-rd-ghost-btn"
                      disabled={busy || !project}
                      onClick={() => {
                        if (!project || !ingestionFocusId) return;
                        void api
                          .retrySourceIngestionBrain(project.project_id, ingestionFocusId)
                          .then(() => toast("Brain retry started"))
                          .catch((err) => toast(errMsg(err, "Brain retry failed")));
                      }}
                    >
                      Retry Brain sync
                    </button>
                  ) : null}
                </div>
                {ingestionMembers.length > 0 ? (
                  <ul className="lv-rd-ingest-members">
                    {ingestionMembers
                      .filter((m) => !m.is_directory)
                      .map((m) => (
                        <li key={m.member_id}>
                          <span className={`lv-rd-ingest-mark is-${m.outcome}`}>
                            {m.outcome === "success"
                              ? "✓"
                              : m.outcome === "failed"
                                ? "✕"
                                : m.outcome === "quarantined"
                                  ? "!"
                                  : m.outcome === "routed"
                                    ? "↷"
                                    : "–"}
                          </span>
                          <code>{m.relative_path}</code>
                          <small>
                            {m.outcome}
                            {m.brain_status && m.brain_status !== "not_applicable"
                              ? ` · brain ${m.brain_status}`
                              : ""}
                            {m.skip_reason ? ` · ${m.skip_reason}` : ""}
                          </small>
                        </li>
                      ))}
                  </ul>
                ) : null}
                {ingestionTotal > ingestionMembers.length ? (
                  <div className="lv-rd-ingest-actions">
                    <button
                      type="button"
                      className="lv-rd-ghost-btn"
                      disabled={ingestionOffset <= 0}
                      onClick={() => setIngestionOffset((o) => Math.max(0, o - 50))}
                    >
                      Prev
                    </button>
                    <small>
                      {ingestionOffset + 1}–{Math.min(ingestionOffset + 50, ingestionTotal)} of{" "}
                      {ingestionTotal}
                    </small>
                    <button
                      type="button"
                      className="lv-rd-ghost-btn"
                      disabled={ingestionOffset + 50 >= ingestionTotal}
                      onClick={() => setIngestionOffset((o) => o + 50)}
                    >
                      Next
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="lv-rd-ingest-actions">
              <button
                type="button"
                className="lv-rd-ghost-btn"
                onClick={() => {
                  setInputTab("URLs");
                  toast("Paste URLs in the query panel");
                }}
              >
                <Icon name="link" />
                Add from URL
              </button>
              <button
                type="button"
                className="lv-rd-ghost-btn"
                onClick={() => {
                  setInputTab("Datasets");
                  void loadDatasetsForPicker();
                }}
              >
                <Icon name="database" />
                Connect Dataset
              </button>
            </div>
          </article>

          <article className="lv-rd-panel">
            <div className="lv-rd-panel-head">
              <h2 className="lv-rd-panel-title">
                <Icon name="network" />
                Active Research
              </h2>
              <div className="lv-rd-panel-meta">
                {isLive ? (
                  <span className="lv-rd-badge is-live">Live</span>
                ) : project ? (
                  <span className="lv-rd-badge is-count">{project.status}</span>
                ) : (
                  <span className="lv-rd-badge is-count">idle</span>
                )}
                <span className="lv-rd-badge is-count">{phaseLabel}</span>
                <span className="lv-rd-progress-pct">{hasLiveProject ? progress : 0}%</span>
              </div>
            </div>
            {project?.error && (project.status === "failed" || project.status === "cancelled") ? (
              <p className="lv-rd-error" role="alert">{project.error}</p>
            ) : null}
            <ol className="lv-rd-timeline">
              {timeline.map((step) => (
                <li key={step.id} className={`lv-rd-step is-${step.status}`}>
                  <span className="lv-rd-step-ico" aria-hidden="true">
                    {step.status === "done" ? <Icon name="check" /> : null}
                  </span>
                  <div className="lv-rd-step-copy">
                    <strong>{step.label}</strong>
                    {step.meta ? <small>{step.meta}</small> : null}
                  </div>
                  {step.duration ? <span className="lv-rd-step-time">{step.duration}</span> : <span />}
                </li>
              ))}
            </ol>
            {workerRows.length > 0 ? (
              <ul className="lv-rd-insight-list" aria-label="Research workers">
                {workerRows.map((w) => (
                  <li key={w.worker_id} className="lv-rd-insight-item">
                    <span className="lv-rd-insight-ico">
                      <Icon name="bot" />
                    </span>
                    <div className="lv-rd-insight-copy">
                      <strong>
                        Worker {w.worker_index + 1} · Round {w.current_round}/{w.total_rounds}
                      </strong>
                      <p>
                        {w.phase.replace(/_/g, " ")} · {w.current_query || w.current_task || "—"}
                      </p>
                      <small>
                        Sources {w.sources_added} · Evidence {w.evidence_added}
                        {w.last_error ? ` · Error: ${w.last_error}` : ""}
                      </small>
                    </div>
                    <span className="lv-rd-badge is-count">{w.status}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="lv-rd-empty-note">
                {isLive ? "Workers starting…" : "Worker details appear during an active run."}
              </p>
            )}
          </article>

          <article className="lv-rd-panel">
            <div className="lv-rd-panel-head">
              <h2 className="lv-rd-panel-title">
                <Icon name="target" />
                Research Scope
              </h2>
              <button type="button" className="lv-rd-edit" onClick={() => setScopeEditing((v) => !v)}>
                {scopeEditing ? "Done" : "Edit"}
              </button>
            </div>
            <div className="lv-rd-scope-grid" style={{ marginBottom: 10 }}>
              <button
                type="button"
                className={`lv-rd-pill${executionMode === "normal" ? " is-active" : ""}`}
                disabled={!scopeEditing && executionMode !== "normal"}
                onClick={() => scopeEditing && setExecutionMode("normal")}
              >
                Normal
              </button>
              <button
                type="button"
                className={`lv-rd-pill${executionMode === "custom" ? " is-active" : ""}`}
                disabled={!scopeEditing && executionMode !== "custom"}
                onClick={() => scopeEditing && setExecutionMode("custom")}
              >
                Custom
              </button>
              <button
                type="button"
                className={`lv-rd-pill${executionMode === "team" ? " is-active" : ""}`}
                disabled={!scopeEditing && executionMode !== "team"}
                onClick={() => scopeEditing && setExecutionMode("team")}
                title="Continues until the quality criteria are met, or shows exactly what prevents completion."
              >
                TEAM
              </button>
            </div>
            <p className="lv-rd-empty-note" style={{ margin: "0 0 10px", textAlign: "left" }}>
              {executionMode === "normal"
                ? (normalMode?.description ??
                  `Locked: ${effectiveWorkers} workers, ${effectiveRounds} rounds/worker`)
                : executionMode === "team"
                  ? (budgetCatalog?.execution_modes.team?.description ??
                    "Continues until the quality criteria are met, or shows exactly what prevents completion.")
                  : (budgetCatalog?.execution_modes.custom.description ??
                    "Set workers and rounds within backend limits.")}
            </p>
            {executionMode === "custom" && scopeEditing ? (
              <div className="lv-rd-scope-grid" style={{ marginBottom: 10 }}>
                <label className="lv-rd-scope-card">
                  <strong>Workers</strong>
                  <input
                    type="number"
                    min={customLimits?.research_workers.min ?? 1}
                    max={customLimits?.research_workers.max ?? 16}
                    value={customWorkers}
                    onChange={(e) => setCustomWorkers(Number(e.target.value))}
                  />
                </label>
                <label className="lv-rd-scope-card">
                  <strong>Rounds / worker</strong>
                  <input
                    type="number"
                    min={customLimits?.rounds.min ?? 1}
                    max={customLimits?.rounds.max ?? 100}
                    value={customRounds}
                    onChange={(e) => setCustomRounds(Number(e.target.value))}
                  />
                </label>
              </div>
            ) : executionMode === "team" ? (
              <p className="lv-rd-empty-note" style={{ margin: "0 0 10px", textAlign: "left" }}>
                {effectiveWorkers} workers · open-ended iterations (no fixed round total)
              </p>
            ) : (
              <p className="lv-rd-empty-note" style={{ margin: "0 0 10px", textAlign: "left" }}>
                {effectiveWorkers} workers · {effectiveRounds} rounds/worker
              </p>
            )}
            <div className="lv-rd-scope-grid">
              <button
                type="button"
                className="lv-rd-scope-card"
                disabled={!scopeEditing}
                onClick={() => scopeEditing && toggleContext("web")}
              >
                <Icon name="globe" />
                <strong>Web Search</strong>
                <span className={context.web ? "is-on" : undefined}>{context.web ? "Enabled" : "Disabled"}</span>
              </button>
              <button
                type="button"
                className="lv-rd-scope-card"
                disabled={!scopeEditing}
                onClick={() => {
                  if (!scopeEditing) return;
                  if (!context.files) fileInputRef.current?.click();
                  else toggleContext("files");
                }}
              >
                <Icon name="file" />
                <strong>Your Files</strong>
                <span>
                  {fileSourceCount > 0
                    ? `${fileSourceCount} uploaded`
                    : context.files
                      ? "Enabled"
                      : "None"}
                </span>
              </button>
              <button
                type="button"
                className="lv-rd-scope-card"
                disabled={!scopeEditing}
                onClick={() => scopeEditing && toggleContext("datasets")}
              >
                <Icon name="database" />
                <strong>Datasets</strong>
                <span className={context.datasets ? "is-on" : undefined}>
                  {connectedDatasetLabel ?? (context.datasets ? "Connected" : "Not connected")}
                </span>
              </button>
              <button
                type="button"
                className="lv-rd-scope-card"
                disabled={!scopeEditing}
                onClick={() => {
                  if (!scopeEditing) return;
                  const chip = RD_CONTEXT_CHIPS.find((c) => c.id === "code");
                  if (chip && "unavailable" in chip && chip.unavailable) toast(chip.unavailable);
                  else toggleContext("code");
                }}
              >
                <Icon name="code" />
                <strong>Code Analysis</strong>
                <span className={context.code ? "is-on" : undefined}>{context.code ? "Enabled" : "Disabled"}</span>
              </button>
            </div>
          </article>
        </section>

        <section className="lv-rd-row" aria-label="Research outputs">
          <article className="lv-rd-panel">
            <div className="lv-rd-panel-head">
              <h2 className="lv-rd-panel-title">Collected Evidence</h2>
              <div className="lv-rd-panel-meta">
                <span className="lv-rd-badge is-count">{evidenceCountLabel}</span>
                <Link className="lv-rd-link" to="/evidence">
                  View all →
                </Link>
              </div>
            </div>
            {evidenceRows.length === 0 ? (
              <p className="lv-rd-empty-note">No evidence yet — start a research run to collect sources.</p>
            ) : (
              <ul className="lv-rd-evidence-list">
                {evidenceRows.map((item) => {
                  const label = item.supportLabel ?? "Unmeasured";
                  return (
                    <li key={item.id} className="lv-rd-evidence-item">
                      <span className="lv-rd-favicon">{item.favicon}</span>
                      <div className="lv-rd-evidence-copy">
                        <strong title={item.title}>{item.title}</strong>
                        <small>
                          {item.domain} · {item.ago}
                        </small>
                      </div>
                      <span className={`lv-rd-conf is-${confTone(label)}`}>{label}</span>
                      <button
                        type="button"
                        className="lv-rd-ext"
                        aria-label="Open source"
                        onClick={() => {
                          if (item.url) window.open(item.url, "_blank", "noopener,noreferrer");
                          else toast(item.title);
                        }}
                      >
                        <Icon name="ext" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </article>

          <article className="lv-rd-panel">
            <div className="lv-rd-panel-head">
              <h2 className="lv-rd-panel-title">Web Results</h2>
              <div className="lv-rd-panel-meta">
                <span>Top results</span>
                <button
                  type="button"
                  className="lv-rd-link"
                  onClick={() => {
                    const el = document.querySelector(".lv-rd-web-list");
                    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                  }}
                >
                  View all →
                </button>
              </div>
            </div>
            {webRows.length === 0 ? (
              <p className="lv-rd-empty-note">
                {context.web ? "Web results appear after retrieval." : "Enable Web in context to search the open web."}
              </p>
            ) : (
              <ul className="lv-rd-web-list">
                {webRows.map((item) => (
                  <li key={item.id} className="lv-rd-web-item">
                    <span className="lv-rd-web-rank">{item.rank}</span>
                    <div className="lv-rd-web-copy">
                      <strong>{item.title}</strong>
                      <em>{item.domain}</em>
                      <p>{item.snippet}</p>
                    </div>
                    <div className="lv-rd-web-thumb" aria-hidden="true" />
                  </li>
                ))}
              </ul>
            )}
          </article>

          <article className="lv-rd-panel">
            <div className="lv-rd-panel-head">
              <h2 className="lv-rd-panel-title">Insights &amp; Summary</h2>
              <span className="lv-rd-badge is-draft">Draft</span>
            </div>
            <div className="lv-rd-insights-head">
              <h3>Key Findings</h3>
              {showGenerating ? (
                <span className="lv-rd-generating">
                  <span className="lv-rd-spinner" />
                  Generating...
                </span>
              ) : null}
            </div>
            {insightRows.length === 0 ? (
              <p className="lv-rd-empty-note">Insights appear once claims are synthesized.</p>
            ) : (
              <ul className="lv-rd-insight-list">
                {insightRows.map((item) => {
                  const label = item.supportLabel ?? "Unmeasured";
                  return (
                    <li key={item.id} className="lv-rd-insight-item">
                      <span className="lv-rd-insight-ico">
                        <Icon name={item.icon} />
                      </span>
                      <div className="lv-rd-insight-copy">
                        <strong>{item.title}</strong>
                        <p>{item.body}</p>
                      </div>
                      <span className={`lv-rd-conf is-${confTone(label)}`}>{label}</span>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="lv-rd-insights-head" style={{ marginTop: "1rem" }}>
              <h3>Open Gaps</h3>
              <span className="lv-rd-badge">{gaps.length}</span>
            </div>
            {gaps.length === 0 ? (
              <p className="lv-rd-empty-note">No open research gaps recorded yet.</p>
            ) : (
              <ul className="lv-rd-insight-list">
                {gaps.slice(0, 8).map((gap) => (
                  <li
                    key={String(gap.gap_id ?? gap.reason)}
                    className="lv-rd-insight-item"
                  >
                    <div className="lv-rd-insight-copy">
                      <strong>
                        {String(gap.gap_type ?? "GAP")} · {String(gap.severity ?? "")}
                      </strong>
                      <p>{String(gap.reason ?? gap.target_question ?? "")}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </article>
        </section>
      </main>
    </AppShell>
  );
}
