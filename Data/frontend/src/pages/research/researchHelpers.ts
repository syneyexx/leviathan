/** Shared Research domain helpers — status mapping, timeline, provenance labels. */

import {
  RD_IDLE_TIMELINE,
  type RdEvidenceItem,
  type RdInsight,
  type RdTimelineStep,
  type RdTimelineStepStatus,
  type RdWebResult,
} from "../../config/research";
import type {
  DatasetJob,
  DatasetRecord,
  ResearchClaim,
  ResearchEvidence,
  ResearchProject,
  ResearchSource,
  ResearchWebReadiness,
} from "../../types/api";

export const ACTIVE_STATUSES = new Set([
  "queued",
  "researching",
  "synthesizing",
  "verifying",
  "cancelling",
]);

export const COMPLETED_STATUSES = new Set(["completed"]);

export const DRAFT_STATUSES = new Set(["draft", "planned", "waiting_for_input", "paused", "blocked"]);

export const FAILED_STATUSES = new Set(["failed", "cancelled", "interrupted"]);

export const UPLOAD_EXT =
  /\.(pdf|txt|md|markdown|csv|json|jsonl|ndjson|log|rst|ya?ml|toml|docx|xlsx|pptx|py|ts|tsx|js|jsx|zip|tar|tgz|gz)$/i;

export const INGEST_ACTIVE = new Set([
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

export const UPLOAD_ACCEPT =
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

export type ResearchFilterTab = "all" | "active" | "completed" | "drafts";

export type ExecutionMode = "normal" | "custom" | "team";

export type ResearchComposerMode = "standaard" | "deep" | "web" | "document";

export type ResearchTypePreset = "deep" | "web" | "document" | "comparative";

export function isActiveStatus(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function projectMatchesFilter(project: ResearchProject, filter: ResearchFilterTab): boolean {
  const s = project.status;
  switch (filter) {
    case "active":
      return isActiveStatus(s);
    case "completed":
      return COMPLETED_STATUSES.has(s);
    case "drafts":
      return DRAFT_STATUSES.has(s);
    default:
      return true;
  }
}

export function statusBadgeTone(
  status: string,
): "success" | "info" | "warning" | "danger" | "muted" | "research" {
  if (isActiveStatus(status)) return "success";
  if (COMPLETED_STATUSES.has(status)) return "info";
  if (status === "failed") return "danger";
  if (status === "cancelled" || status === "interrupted" || status === "cancelling") return "warning";
  if (DRAFT_STATUSES.has(status)) return "muted";
  return "research";
}

export function statusLabelNl(status: string): string {
  const map: Record<string, string> = {
    draft: "Concept",
    planned: "Gepland",
    queued: "In wachtrij",
    researching: "Actief",
    synthesizing: "Synthese",
    verifying: "Verifiëren",
    waiting_for_input: "Wacht op input",
    blocked: "Geblokkeerd",
    paused: "Gepauzeerd",
    completed: "Afgerond",
    cancelling: "Annuleren…",
    cancelled: "Geannuleerd",
    failed: "Mislukt",
    interrupted: "Onderbroken",
  };
  return map[status] ?? status;
}

export function depthLabelNl(depth: string | null | undefined): string {
  const map: Record<string, string> = {
    quick: "Snel",
    standard: "Standaard",
    deep: "Deep Research",
    expert: "Expert",
  };
  return map[depth ?? ""] ?? depth ?? "—";
}

export function domainFromUri(uri: string | null | undefined): string {
  if (!uri) return "source";
  try {
    return new URL(uri).hostname.replace(/^www\./, "");
  } catch {
    return uri.slice(0, 28);
  }
}

export function relativeAgoNl(iso: string | null | undefined, nowMs = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const sec = Math.max(0, Math.round((nowMs - t) / 1000));
  if (sec < 60) return `${sec}s geleden`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min geleden`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}u geleden`;
  const days = Math.round(hr / 24);
  return `${days}d geleden`;
}

export function confTone(label: string): "high" | "mid" | "muted" {
  if (label.toLowerCase().startsWith("supported")) return "high";
  if (label.toLowerCase() === "unmeasured") return "muted";
  return "mid";
}

export function claimSupportLabel(claim: ResearchClaim): string {
  const n = claim.supporting_evidence_ids?.length ?? 0;
  if (n > 0) return `Supported by ${n} evidence span${n === 1 ? "" : "s"}`;
  return "Unmeasured";
}

export function projectProgress(project: ResearchProject | null): number | null {
  if (!project) return null;
  const status = project.status;
  if (status === "failed" || status === "cancelled" || status === "interrupted") {
    const pct = project.progress_pct;
    if (pct != null && Number.isFinite(pct)) return Math.min(99, Math.round(pct));
    return null;
  }
  if (status === "completed") {
    const pct = project.progress_pct;
    return pct != null && Number.isFinite(pct) ? Math.round(pct) : 100;
  }
  const pct = project.progress_pct;
  if (pct != null && Number.isFinite(pct)) return Math.round(pct);
  return null;
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

export function timelineFromProject(project: ResearchProject | null): RdTimelineStep[] {
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
    } else if (i < activeIdx) {
      stepStatus = "done";
      meta = stepMeta(base.id, project) ?? base.meta;
    } else if (i === activeIdx) {
      stepStatus = "active";
      meta = stepMeta(base.id, project) ?? (project.phase?.replace(/_/g, " ") || "In progress…");
    } else {
      stepStatus = "queued";
      meta = "Waiting";
    }

    return { ...base, status: stepStatus, meta };
  });
}

export function mapSourcesToEvidence(sources: ResearchSource[]): RdEvidenceItem[] {
  return sources.slice(0, 8).map((s) => {
    const domain = domainFromUri(s.canonical_uri ?? s.original_uri);
    const parseNote = `parse ${s.parse_status}`;
    const brainNote = s.brain_status ? ` · brain ${s.brain_status}` : "";
    return {
      id: s.source_id,
      title: s.title || domain || "Untitled source",
      domain,
      ago: relativeAgoNl(s.fetched_at || s.created_at),
      confidence: null,
      supportLabel: `${parseNote}${brainNote}`,
      favicon: (domain[0] || "?").toUpperCase(),
      url: s.canonical_uri ?? s.original_uri ?? undefined,
    };
  });
}

export function mapSourcesToWeb(sources: ResearchSource[], evidence: ResearchEvidence[]): RdWebResult[] {
  const webby = sources.filter(
    (s) => (s.source_type || "").toLowerCase().includes("web") || !!s.canonical_uri,
  );
  const pool = (webby.length ? webby : sources).slice(0, 8);
  return pool.map((s, i) => {
    const domain = domainFromUri(s.canonical_uri ?? s.original_uri);
    const span = evidence.find((e) => e.source_id === s.source_id)?.span_text;
    const evCount = evidence.filter((e) => e.source_id === s.source_id).length;
    const retrieval =
      (s.metadata?.retrieval_status as string | undefined) ||
      (s.provenance?.retrieval_status as string | undefined) ||
      s.parse_status;
    const published = s.published_at ? ` · pub ${s.published_at}` : "";
    const fetched = s.fetched_at ? ` · fetched ${relativeAgoNl(s.fetched_at)}` : "";
    return {
      id: s.source_id,
      rank: i + 1,
      title: s.title || domain || "Web result",
      domain,
      snippet: span
        ? span.slice(0, 160) + (span.length > 160 ? "…" : "")
        : `${s.source_type || "source"} · ${retrieval} · evidence ${evCount}${fetched}${published}`,
      url: s.canonical_uri ?? s.original_uri ?? undefined,
    };
  });
}

export function zeroEvidenceDiagnosis(
  project: ResearchProject | null,
  webReadiness: ResearchWebReadiness | null,
  sources: ResearchSource[],
): string | null {
  if (!project || project.evidence_count > 0) return null;
  if (!project.allow_web) return null;
  if (project.web_unavailable_reason) {
    return `WEB SEARCH UNAVAILABLE — reason: ${project.web_unavailable_reason}`;
  }
  if (webReadiness && !webReadiness.search_available) {
    return webReadiness.operator_summary || "WEB SEARCH UNAVAILABLE";
  }
  const webPages = sources.filter((s) => (s.source_type || "").toLowerCase() === "web_page");
  const blocked = sources.filter((s) => {
    const st = String(s.metadata?.retrieval_status || s.provenance?.retrieval_status || "");
    return /robots|blocked|fetch_failed/i.test(st);
  });
  if (sources.length === 0) return "NO SOURCES DISCOVERED";
  if (blocked.length && webPages.length === 0) return "FETCH BLOCKED";
  if (webPages.length === 0) return "NO SOURCES FETCHED";
  return "NO EVIDENCE EXTRACTED";
}

export function mapClaimsToInsights(claims: ResearchClaim[]): RdInsight[] {
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

export function datasetIndexed(ds: DatasetRecord, jobs: DatasetJob[]): boolean | null {
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

export function isWebSource(source: ResearchSource): boolean {
  const t = (source.source_type || "").toLowerCase();
  return t.includes("web");
}

export function isDocumentSource(source: ResearchSource): boolean {
  const t = (source.source_type || "").toLowerCase();
  return t.includes("file") || t.includes("local") || t === "knowledge" || t === "seed";
}

/** Local-day buckets for last N days from project timestamps (browser local TZ). */
export function aggregateProjectStats(
  projects: ResearchProject[],
  days = 7,
  now = new Date(),
): Array<{ day: string; completed: number; active: number; failed: number }> {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));

  const buckets: Array<{ day: string; completed: number; active: number; failed: number; key: string }> =
    [];
  for (let i = 0; i < days; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    buckets.push({
      key,
      day: d.toLocaleDateString("nl-NL", { weekday: "short" }),
      completed: 0,
      active: 0,
      failed: 0,
    });
  }

  for (const p of projects) {
    const ts = p.updated_at || p.created_at;
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) continue;
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    const bucket = buckets.find((b) => b.key === key);
    if (!bucket) continue;
    if (COMPLETED_STATUSES.has(p.status)) bucket.completed += 1;
    else if (isActiveStatus(p.status)) bucket.active += 1;
    else if (FAILED_STATUSES.has(p.status)) bucket.failed += 1;
  }

  return buckets.map(({ day, completed, active, failed }) => ({ day, completed, active, failed }));
}
