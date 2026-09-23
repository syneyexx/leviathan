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
  RD_MODELS,
  RD_TEMPLATES,
  type RdEvidenceItem,
  type RdInputTab,
  type RdInsight,
  type RdTimelineStep,
  type RdWebResult,
} from "../mocks/research-dashboard";
import { useAppToast } from "../state/useAppToast";
import type {
  ResearchClaim,
  ResearchEvidence,
  ResearchProject,
  ResearchSource,
} from "../types/api";

const ACTIVE = new Set(["queued", "researching", "synthesizing", "cancelling"]);

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

function confTone(n: number | null | undefined): "high" | "mid" | "muted" {
  if (n == null || !Number.isFinite(n)) return "muted";
  return n >= 90 ? "high" : "mid";
}

function confLabel(item: { confidence: number | null; fixture?: boolean }): string {
  if (item.fixture) return "fixture";
  if (item.confidence == null || !Number.isFinite(item.confidence)) return "unmeasured";
  return `${Math.round(item.confidence)}%`;
}

function projectProgress(project: ResearchProject | null): number {
  if (!project) return 0;
  const status = project.status;
  if (status === "completed") return 100;
  if (status === "failed" || status === "cancelled") return 0;
  if (status === "draft" || status === "planned") return 8;
  if (status === "queued") return 12;
  if (status === "cancelling") return 40;
  const rounds = Math.max(1, project.total_rounds || 1);
  const roundFrac = Math.min(1, project.current_round / rounds);
  if (status === "researching") return Math.round(18 + roundFrac * 52);
  if (status === "synthesizing") return Math.round(72 + roundFrac * 22);
  return 10;
}

function timelineFromProject(project: ResearchProject | null, _live: boolean): RdTimelineStep[] {
  if (!project) return RD_IDLE_TIMELINE;
  const status = project.status;
  const sources = project.source_count;
  const evidence = project.evidence_count;
  const claims = project.claim_count;

  const step = (
    id: string,
    label: string,
    state: RdTimelineStep["status"],
    meta?: string,
    duration?: string,
  ): RdTimelineStep => ({ id, label, status: state, meta, duration });

  if (status === "draft" || status === "planned") {
    return [
      step("understand", "Understanding your query", status === "planned" ? "done" : "active", status === "planned" ? "Plan ready" : "Planning…"),
      step("search", "Searching the web", "queued", "Queued"),
      step("analyze", "Analyzing sources", "queued", "Queued"),
      step("insights", "Extracting insights", "queued", "Queued"),
      step("report", "Building structured report", "queued", "Queued"),
    ];
  }
  if (status === "queued") {
    return [
      step("understand", "Understanding your query", "done", "Ready"),
      step("search", "Searching the web", "active", "Starting…"),
      step("analyze", "Analyzing sources", "queued", "Queued"),
      step("insights", "Extracting insights", "queued", "Queued"),
      step("report", "Building structured report", "queued", "Queued"),
    ];
  }
  if (status === "researching") {
    const mid = project.current_round > 1 || sources > 0;
    return [
      step("understand", "Understanding your query", "done"),
      step("search", "Searching the web", mid ? "done" : "active", sources ? `${sources} sources` : "In progress…"),
      step("analyze", "Analyzing sources", mid ? "active" : "pending", mid ? (evidence ? `${evidence} spans` : "In progress…") : "Queued"),
      step("insights", "Extracting insights", "queued", "Queued"),
      step("report", "Building structured report", "queued", "Queued"),
    ];
  }
  if (status === "synthesizing" || status === "cancelling") {
    return [
      step("understand", "Understanding your query", "done"),
      step("search", "Searching the web", "done", sources ? `${sources} sources` : undefined),
      step("analyze", "Analyzing sources", "done", evidence ? `${evidence} spans` : undefined),
      step("insights", "Extracting insights", status === "cancelling" ? "pending" : "active", claims ? `${claims} claims` : "In progress…"),
      step("report", "Building structured report", "queued", "Queued"),
    ];
  }
  if (status === "completed") {
    return [
      step("understand", "Understanding your query", "done"),
      step("search", "Searching the web", "done", sources ? `${sources} sources` : undefined),
      step("analyze", "Analyzing sources", "done", evidence ? `${evidence} spans` : undefined),
      step("insights", "Extracting insights", "done", claims ? `${claims} claims` : undefined),
      step("report", "Building structured report", "done", "Ready"),
    ];
  }
  // failed / cancelled / interrupted
  return [
    step("understand", "Understanding your query", "done"),
    step("search", "Searching the web", sources ? "done" : "pending", sources ? `${sources} sources` : project.error || status),
    step("analyze", "Analyzing sources", evidence ? "done" : "queued", evidence ? `${evidence} spans` : "Stopped"),
    step("insights", "Extracting insights", claims ? "done" : "queued", "Stopped"),
    step("report", "Building structured report", "queued", status),
  ];
}

function mapSourcesToEvidence(sources: ResearchSource[]): RdEvidenceItem[] {
  return sources.slice(0, 8).map((s) => {
    const domain = domainFromUri(s.canonical_uri ?? s.original_uri);
    // Round 9: do not invent confidence percentages from list index.
    return {
      id: s.source_id,
      title: s.title || domain || "Untitled source",
      domain,
      ago: relativeAgo(s.fetched_at || s.created_at),
      confidence: null,
      favicon: (domain[0] || "?").toUpperCase(),
      url: s.canonical_uri ?? s.original_uri ?? undefined,
    };
  });
}

function mapSourcesToWeb(sources: ResearchSource[], evidence: ResearchEvidence[]): RdWebResult[] {
  const webby = sources.filter((s) => (s.source_type || "").toLowerCase().includes("web") || !!s.canonical_uri);
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
  return claims.slice(0, 5).map((c, i) => {
    const support = c.supporting_evidence_ids?.length ?? 0;
    // Only emit a score when there is supporting evidence; never invent %.
    const conf = support > 0 ? Math.min(98, 60 + support * 8) : null;
    return {
      id: c.claim_id,
      title: c.proposition.slice(0, 72) + (c.proposition.length > 72 ? "…" : ""),
      body: c.raw_wording || c.proposition,
      confidence: conf,
      icon: icons[i % icons.length],
    };
  });
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
  const [model, setModel] = useState<(typeof RD_MODELS)[number]>(RD_MODELS[0]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [depth, setDepth] = useState("deep");
  const [context, setContext] = useState<Record<string, boolean>>({
    web: true,
    files: false,
    datasets: false,
    code: true,
    images: false,
  });
  const [fileCount, setFileCount] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [scopeEditing, setScopeEditing] = useState(false);

  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [evidence, setEvidence] = useState<ResearchEvidence[]>([]);
  const [claims, setClaims] = useState<ResearchClaim[]>([]);
  const [hasLiveProject, setHasLiveProject] = useState(false);

  const isLive = !!(project && ACTIVE.has(project.status));
  const progress = projectProgress(project);
  const timeline = useMemo(
    () => timelineFromProject(project, hasLiveProject),
    [project, hasLiveProject],
  );

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

  const refreshArtifacts = useCallback(async (projectId: string) => {
    const [src, ev, cl] = await Promise.all([
      api.listResearchSources(projectId).catch(() => ({ sources: [] as ResearchSource[] })),
      api.listResearchEvidence(projectId).catch(() => ({ evidence: [] as ResearchEvidence[] })),
      api.listResearchClaims(projectId).catch(() => ({ claims: [] as ResearchClaim[] })),
    ]);
    setSources(src.sources);
    setEvidence(ev.evidence);
    setClaims(cl.claims);
  }, []);

  const loadLatest = useCallback(async () => {
    setLoadError(null);
    try {
      const list = await api.listResearchProjects();
      const projects = list.projects;
      if (projects.length === 0) {
        setProject(null);
        setHasLiveProject(false);
        setSources([]);
        setEvidence([]);
        setClaims([]);
        return;
      }
      const preferred =
        projects.find((p) => ACTIVE.has(p.status)) ??
        projects.find((p) => p.status === "completed") ??
        projects[0];
      const detail = await api.getResearchProject(preferred.project_id);
      setProject(detail.project);
      setHasLiveProject(true);
      await refreshArtifacts(detail.project.project_id);
    } catch (err) {
      setLoadError(errMsg(err, "Failed to load research projects"));
    }
  }, [refreshArtifacts]);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  useEffect(() => {
    if (!project || !ACTIVE.has(project.status)) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await api.getResearchProject(project.project_id);
        if (cancelled) return;
        setProject(res.project);
        if (!ACTIVE.has(res.project.status) || res.project.source_count !== project.source_count) {
          await refreshArtifacts(res.project.project_id);
        }
      } catch {
        /* keep last known */
      }
    };
    const id = window.setInterval(() => void tick(), 2500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [project?.project_id, project?.status, project?.source_count, refreshArtifacts]);

  function toggleContext(id: string) {
    setContext((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function applyTemplate(id: string) {
    const t = RD_TEMPLATES.find((x) => x.id === id);
    if (!t) return;
    setTemplateId(id);
    setDepth(t.depth);
    if (t.prompt) {
      setQuery((q) => (q.trim() ? q : t.prompt));
    }
    toast(`${t.label} selected`);
  }

  async function onFilesSelected(files: FileList | null) {
    if (!files?.length) return;
    const list = Array.from(files);
    setBusy(true);
    let ok = 0;
    const supported = /\.(txt|md|markdown|rst|csv|json|log)$/i;
    try {
      for (const file of list) {
        if (!supported.test(file.name)) {
          toast(`Unsupported for research ingest: ${file.name} (use .txt/.md/.csv/.json)`);
          continue;
        }
        if (file.size > 100 * 1024 * 1024) {
          toast(`${file.name} exceeds 100MB`);
          continue;
        }
        const content = await file.text();
        await api.createKnowledgeDocument({
          title: file.name.replace(/\.[^.]+$/, "") || file.name,
          content,
          source: `research-upload:${file.name}`,
        });
        ok += 1;
      }
      if (ok > 0) {
        setFileCount((n) => n + ok);
        setContext((c) => ({ ...c, files: true }));
        toast(`${ok} file(s) ingested into Knowledge (local research scope)`);
      }
    } catch (err) {
      toast(errMsg(err, "File ingest failed"));
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    onFilesSelected(e.dataTransfer.files);
  }

  async function onStartResearch() {
    const topic = query.trim();
    if (!topic) {
      toast("Ask a research question first");
      return;
    }
    setBusy(true);
    try {
      const seeds = urlDraft
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
      const created = await api.createResearchProject({
        topic,
        title: topic.slice(0, 80),
        objective: topic,
        depth,
        allowWeb: !!context.web,
        localScopes: context.files || context.code || context.datasets ? ["workspace"] : [],
        seedSources: seeds,
        modelProfile: { label: model },
      });
      const started = await api.runResearchProject(created.project.project_id);
      setProject(started.project);
      setHasLiveProject(true);
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
                  onClick={() => setInputTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="lv-rd-templates-btn"
              onClick={() => {
                const next = RD_TEMPLATES[(RD_TEMPLATES.findIndex((t) => t.id === templateId) + 1) % RD_TEMPLATES.length];
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
                value={model}
                aria-label="Model"
                onChange={(e) => setModel(e.target.value as (typeof RD_MODELS)[number])}
              >
                {RD_MODELS.map((m) => (
                  <option key={m} value={m}>
                    {m}
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
              <textarea
                className="lv-rd-textarea"
                style={{ minHeight: 48 }}
                value={urlDraft}
                onChange={(e) => setUrlDraft(e.target.value)}
                placeholder="https://example.com/paper …"
                aria-label="Seed URLs"
              />
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
                {RD_CONTEXT_CHIPS.map((chip) => (
                  <button
                    key={chip.id}
                    type="button"
                    className={`lv-rd-chip${context[chip.id] ? " is-active" : ""}`}
                    onClick={() => toggleContext(chip.id)}
                  >
                    <Icon name={chip.icon} />
                    {chip.label}
                  </button>
                ))}
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
                <small>TXT, MD, CSV, JSON, LOG (max 100MB) → Knowledge ingest</small>
              </div>
              {fileCount > 0 ? <small>{fileCount} file(s) staged</small> : null}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={(e) => onFilesSelected(e.target.files)}
            />
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
                  setContext((c) => ({ ...c, datasets: true }));
                  setInputTab("Datasets");
                  toast("Datasets marked in scope");
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
                <span className="lv-rd-progress-pct">{hasLiveProject ? progress : 0}%</span>
              </div>
            </div>
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
                  {fileCount > 0
                    ? `${fileCount} ingested`
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
                  {context.datasets ? "Connected" : "Not connected"}
                </span>
              </button>
              <button
                type="button"
                className="lv-rd-scope-card"
                disabled={!scopeEditing}
                onClick={() => scopeEditing && toggleContext("code")}
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
                {evidenceRows.map((item) => (
                  <li key={item.id} className="lv-rd-evidence-item">
                    <span className="lv-rd-favicon">{item.favicon}</span>
                    <div className="lv-rd-evidence-copy">
                      <strong title={item.title}>{item.title}</strong>
                      <small>
                        {item.domain} · {item.ago}
                      </small>
                    </div>
                    <span className={`lv-rd-conf is-${confTone(item.confidence)}`}>{confLabel(item)}</span>
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
                ))}
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
                {insightRows.map((item) => (
                  <li key={item.id} className="lv-rd-insight-item">
                    <span className="lv-rd-insight-ico">
                      <Icon name={item.icon} />
                    </span>
                    <div className="lv-rd-insight-copy">
                      <strong>{item.title}</strong>
                      <p>{item.body}</p>
                    </div>
                    <span className={`lv-rd-conf is-${confTone(item.confidence)}`}>{confLabel(item)}</span>
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
