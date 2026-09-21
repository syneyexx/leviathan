/** FINALBETA Research — live research API (visual shell preserved). */
"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useHadesResearch } from "@/components/hades/features/research/hooks/useHadesResearch";
import {
  formatDate,
  type KnowledgeSource,
  type ResearchProject,
} from "@/lib/hades-api";
import { donutSegments } from "../hooks/dashboard-live-utils";
import { FbIcon } from "../icons";
import {
  RESEARCH_DETAIL_TABS,
  RESEARCH_RESULT_TABS,
  RESEARCH_SOURCE_CHIPS,
  type ResearchReliability,
  type ResearchSourceFilter,
} from "../mocks/research";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

type FaviconKind = "eu" | "ec" | "nos" | "nature";

type ResultCardView = {
  id: string;
  title: string;
  handle: string;
  domain: string;
  dateShort: string;
  dateFull: string;
  snippet: string;
  category: string;
  reliability: ResearchReliability;
  reliabilityLabel: string;
  favicon: FaviconKind;
  keyPoints: string[];
  quote: string;
  quoteAttr: string;
  status: string;
  progress: number;
  depth: ResearchProject["depth"];
  allowWeb: boolean;
  sourceCount: number | null;
  report: string;
  findings: string;
  error: string | null;
  raw: ResearchProject;
};

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function domainFromUri(uri: string): string {
  const value = String(uri || "").trim();
  if (!value) return "lokaal";
  try {
    if (/^https?:\/\//i.test(value)) return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    /* ignore */
  }
  if (value.includes("/") || value.includes("\\")) {
    const parts = value.replace(/\\/g, "/").split("/").filter(Boolean);
    return parts[parts.length - 1] || "lokaal";
  }
  return value.slice(0, 40);
}

function faviconFor(uriOrTopic: string): FaviconKind {
  const s = uriOrTopic.toLowerCase();
  if (s.includes("europa.eu") || s.includes("eu ")) return "eu";
  if (s.includes("ec.europa") || s.includes("commissie")) return "ec";
  if (s.includes("nos.nl") || s.includes("nieuws")) return "nos";
  return "nature";
}

function statusReliability(status: string): { tone: ResearchReliability; label: string } {
  const s = String(status || "").toLowerCase();
  if (s === "completed") return { tone: "goed", label: "Voltooid" };
  if (s === "running") return { tone: "matig", label: "Bezig" };
  if (s === "queued") return { tone: "matig", label: "In wachtrij" };
  if (s === "failed") return { tone: "matig", label: "Mislukt" };
  if (s === "cancelled") return { tone: "matig", label: "Geannuleerd" };
  if (s.includes("evidence") || s.includes("needs")) return { tone: "matig", label: "Meer bewijs nodig" };
  return { tone: "matig", label: status || "Onbekend" };
}

function categoryFor(project: ResearchProject): string {
  if (project.allow_web) return "Web";
  return project.depth === "expert" ? "Expert" : project.depth === "deep" ? "Diep" : "Lokaal";
}

function excerpt(text: string, max = 160): string {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function keyPointsFrom(project: ResearchProject): string[] {
  const body = String(project.findings || project.report || "").trim();
  if (!body) {
    if (project.error) return [project.error];
    if (project.status === "running" || project.status === "queued") {
      return ["Onderzoek loopt; bevindingen verschijnen na synthese."];
    }
    return [];
  }
  const lines = body
    .split(/\r?\n/)
    .map((line) => line.replace(/^[-*•\d.)\s]+/, "").trim())
    .filter((line) => line.length > 12);
  if (lines.length) return lines.slice(0, 6);
  return [excerpt(body, 220)].filter(Boolean);
}

function quoteFrom(project: ResearchProject): { quote: string; attr: string } {
  const report = String(project.report || "").trim();
  if (!report) {
    return {
      quote: project.findings
        ? excerpt(project.findings, 280)
        : "Nog geen rapportcitaat — start of voltooi een onderzoek voor brongebonden tekst.",
      attr: project.title ? `— ${project.title}` : "— HADES Research",
    };
  }
  const para =
    report
      .split(/\n\s*\n/)
      .map((p) => p.replace(/\s+/g, " ").trim())
      .find((p) => p.length > 40) || excerpt(report, 280);
  return { quote: para, attr: `— ${project.title || "Researchrapport"}` };
}

function formatShortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric" }).format(
      new Date(iso),
    );
  } catch {
    return "—";
  }
}

function formatFullDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "long", year: "numeric" }).format(
      new Date(iso),
    );
  } catch {
    return formatDate(iso);
  }
}

function mapProjectCard(project: ResearchProject, sourceCount: number | null): ResultCardView {
  const rel = statusReliability(project.status);
  const { quote, attr } = quoteFrom(project);
  const snippet =
    excerpt(project.findings) ||
    excerpt(project.report) ||
    (project.error ? project.error : "") ||
    `Status: ${project.status} · diepte ${project.depth}`;
  const domain = project.allow_web ? "web" : "lokaal";
  return {
    id: project.id,
    title: project.title || project.topic || "Onderzoek",
    handle: `@${domain}`,
    domain,
    dateShort: formatShortDate(project.updated_at || project.created_at),
    dateFull: formatFullDate(project.updated_at || project.created_at),
    snippet,
    category: categoryFor(project),
    reliability: rel.tone,
    reliabilityLabel: rel.label,
    favicon: faviconFor(project.topic || project.title || domain),
    keyPoints: keyPointsFrom(project),
    quote,
    quoteAttr: attr,
    status: project.status,
    progress: typeof project.progress === "number" ? project.progress : 0,
    depth: project.depth,
    allowWeb: Boolean(project.allow_web),
    sourceCount,
    report: project.report || "",
    findings: project.findings || "",
    error: project.error,
    raw: project,
  };
}

function sourceSliceColor(index: number): string {
  const colors = ["#1aa4ff", "#f0b429", "#9b5cff", "#20e38d", "#c66965", "#20c8e8"];
  return colors[index % colors.length]!;
}

function Favicon({ kind, size = "md" }: { kind: FaviconKind; size?: "sm" | "md" | "lg" }) {
  return <span className={`rs-fav rs-fav-${kind} ${size}`} aria-hidden="true" />;
}

function ReliabilityBadge({ label, tone }: { label: string; tone: ResearchReliability }) {
  return (
    <span className={`rs-reli ${tone}`}>
      <FbIcon name="checkcircle" size={11} />
      {label}
    </span>
  );
}

function ResultCard({
  result,
  active,
  onSelect,
}: {
  result: ResultCardView;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" className={`rs-card${active ? " active" : ""}`} onClick={onSelect}>
      <div className="rs-card-top">
        <Favicon kind={result.favicon} />
        <div className="rs-card-copy">
          <strong>{result.title}</strong>
          <small>
            {result.handle} | {result.dateShort}
          </small>
        </div>
        <span className="rs-card-ext" aria-hidden="true">
          <FbIcon name="external" size={12} />
        </span>
      </div>
      <p className="rs-card-snippet">{result.snippet}</p>
      <div className="rs-card-foot">
        <span className="rs-cat">{result.category}</span>
        <ReliabilityBadge label={result.reliabilityLabel} tone={result.reliability} />
      </div>
    </button>
  );
}

function insightRows(project: ResultCardView | null, sources: KnowledgeSource[]) {
  if (!project) return [];
  const fromFindings = project.keyPoints.slice(0, 3).map((body, index) => ({
    id: `kp-${index}`,
    title: index === 0 ? "Bevinding" : `Bevinding ${index + 1}`,
    body,
    icon: index === 0 ? "shield" : "globe",
    relevance: index < 2 ? ("high" as const) : ("mid" as const),
    relevanceLabel: index < 2 ? "Uit rapport" : "Bron",
  }));
  if (fromFindings.length) return fromFindings;
  return sources.slice(0, 3).map((source) => ({
    id: source.id,
    title: source.title || "Bron",
    body: source.uri || source.source_type || "Geen URI",
    icon: "file",
    relevance: "mid" as const,
    relevanceLabel: source.source_type || "bron",
  }));
}

export function ResearchPage({ onNavigate }: Props) {
  const {
    projects,
    knowledge,
    selectedId,
    setSelectedId,
    selected: selectedProject,
    sources,
    coverage,
    coverageError,
    depth,
    setDepth,
    allowWeb,
    setAllowWeb,
    loading,
    error,
    refresh,
    create,
    run,
    cancel,
  } = useHadesResearch();

  const [query, setQuery] = useState("");
  const [source, setSource] = useState<ResearchSourceFilter>("all");
  const [resultTab, setResultTab] = useState<(typeof RESEARCH_RESULT_TABS)[number]["id"]>("results");
  const [detailTab, setDetailTab] = useState<(typeof RESEARCH_DETAIL_TABS)[number]["id"]>("summary");
  const [creating, setCreating] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);

  const cards = useMemo(() => {
    const q = query.trim().toLowerCase();
    return projects
      .filter((project) => {
        if (source === "web" && !project.allow_web) return false;
        if (source === "internal" && project.allow_web) return false;
        if (!q) return true;
        const hay = `${project.title} ${project.topic} ${project.findings} ${project.status}`.toLowerCase();
        return hay.includes(q);
      })
      .map((project) =>
        mapProjectCard(
          selectedProject && selectedProject.id === project.id ? selectedProject : project,
          selectedProject && selectedProject.id === project.id ? sources.length : null,
        ),
      );
  }, [projects, query, selectedProject, source, sources.length]);

  const selected = cards.find((item) => item.id === selectedId) ?? cards[0] ?? null;

  const sourceSlices = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of sources) {
      const key = String(item.source_type || "overig").toLowerCase() || "overig";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const total = [...counts.values()].reduce((a, b) => a + b, 0);
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([label, count], index) => ({
        label: label.charAt(0).toUpperCase() + label.slice(1),
        count,
        pct: total ? `${Math.round((count / total) * 100)}%` : "0%",
        color: sourceSliceColor(index),
      }));
  }, [sources]);

  const totalSources = sourceSlices.reduce((sum, slice) => sum + slice.count, 0);
  const donut = useMemo(
    () => (sourceSlices.length ? donutSegments([...sourceSlices]) : []),
    [sourceSlices],
  );

  const statusChecks = useMemo(() => {
    if (!selected) {
      return [
        { id: "query", label: "Zoekopdracht", value: "—", tone: "plain" as const, icon: "list" },
        { id: "sources", label: "Bronnen", value: "0", tone: "plain" as const, icon: "list" },
        { id: "status", label: "Status", value: "Geen project", tone: "plain" as const, icon: "clock" },
      ];
    }
    const done = selected.status === "completed";
    return [
      {
        id: "query",
        label: "Zoekopdracht",
        value: done ? "✓ Voltooid" : selected.reliabilityLabel,
        tone: done ? ("green" as const) : ("plain" as const),
        icon: "checkcircle",
      },
      {
        id: "sources",
        label: "Bronnen doorzocht",
        value: String(selected.sourceCount ?? sources.length),
        tone: "plain" as const,
        icon: "list",
      },
      {
        id: "progress",
        label: "Voortgang",
        value: `${selected.progress}%`,
        tone: "plain" as const,
        icon: "file",
      },
      {
        id: "depth",
        label: "Diepte",
        value: selected.depth,
        tone: "plain" as const,
        icon: "clock",
      },
      {
        id: "status",
        label: "Status",
        value: selected.status,
        tone: done ? ("green" as const) : ("plain" as const),
        icon: "checkcircle",
      },
    ];
  }, [selected, sources.length]);

  const insights = insightRows(selected, sources);
  const recent = projects.slice(0, 6).map((project) => ({
    id: project.id,
    title: project.title || project.topic,
    when: formatDate(project.updated_at || project.created_at),
    results:
      typeof project.metrics?.source_count === "number"
        ? `${project.metrics.source_count} bronnen`
        : project.status,
  }));

  const resultTabCounts: Record<string, number | null> = {
    results: cards.length,
    summary: null,
    insights: insights.length || null,
    citations: sources.length || null,
    related: null,
  };

  const detailTabCounts: Record<string, number | null> = {
    summary: null,
    full: null,
    extractions: selected?.keyPoints.length || null,
    citations: sources.length || null,
    related: null,
  };

  async function startResearch() {
    const topic = query.trim();
    if (!topic) {
      toast.error("Voer een onderzoeksvraag in.");
      return;
    }
    setCreating(true);
    try {
      const project = await create({
        topic,
        depth,
        allow_web: allowWeb || source === "web",
      });
      setSelectedId(project.id);
      toast.success("Onderzoek gestart.");
    } catch (err) {
      toast.error(errMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function onRunOrCancel() {
    if (!selected) return;
    setActionBusy(true);
    try {
      if (selected.status === "running" || selected.status === "queued") {
        await cancel(selected.id);
        toast.success("Onderzoek geannuleerd.");
      } else {
        await run(selected.id);
        toast.success("Onderzoek opnieuw gestart.");
      }
    } catch (err) {
      toast.error(errMessage(err));
    } finally {
      setActionBusy(false);
    }
  }

  async function copyQuote() {
    if (!selected?.quote) return;
    try {
      await navigator.clipboard.writeText(selected.quote);
      toast.success("Citaat gekopieerd");
    } catch {
      toast.error("Kopiëren mislukt");
    }
  }

  const body = (
    <div className="research-page" data-live="research">
      <div className="rs-head">
        <div className="rs-head-copy">
          <h1>Research</h1>
          <p>Zoek, analyseer en verzamel betrouwbare informatie uit het web, documenten en interne kennis.</p>
        </div>
        <div className="rs-head-actions">
          <button type="button" className="btn btn-outline rs-saved" onClick={() => void refresh()}>
            <FbIcon name="search" size={13} />
            Vernieuwen
          </button>
          <button
            type="button"
            className="btn btn-gold"
            disabled={creating || !query.trim()}
            onClick={() => void startResearch()}
          >
            {creating ? "Bezig…" : "+ Nieuw onderzoek"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Research laden mislukt.</strong> {error.message}{" "}
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <section className="rs-search-panel">
        <div className="rs-search-row">
          <label className="rs-search-field">
            <FbIcon name="search" size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void startResearch();
              }}
              placeholder="Onderzoeksvraag of filter…"
              aria-label="Onderzoeksvraag"
            />
            {query ? (
              <button
                type="button"
                className="rs-clear"
                aria-label="Wis zoekopdracht"
                onClick={() => setQuery("")}
              >
                ×
              </button>
            ) : null}
          </label>
          <button
            type="button"
            className="btn btn-gold rs-search-btn"
            disabled={creating || !query.trim()}
            onClick={() => void startResearch()}
          >
            <FbIcon name="refresh" size={13} />
            {creating ? "Bezig…" : "Zoeken"}
          </button>
        </div>

        <div className="rs-filters">
          <span className="rs-filters-label">Bronnen:</span>
          <div className="rs-chips">
            {RESEARCH_SOURCE_CHIPS.map((chip) => (
              <button
                key={chip.id}
                type="button"
                className={`rs-chip${source === chip.id ? " active" : ""}`}
                onClick={() => {
                  setSource(chip.id);
                  if (chip.id === "web") setAllowWeb(true);
                  if (chip.id === "internal" || chip.id === "pdf") setAllowWeb(false);
                }}
              >
                <FbIcon name={chip.icon} size={11} />
                {chip.label}
              </button>
            ))}
          </div>
          <div className="rs-filter-selects">
            <label>
              <span>Diepte:</span>
              <button
                type="button"
                className="rs-select"
                onClick={() => {
                  const order: ResearchProject["depth"][] = ["quick", "standard", "deep", "expert"];
                  const idx = order.indexOf(depth);
                  setDepth(order[(idx + 1) % order.length]!);
                }}
              >
                {depth}
                <FbIcon name="chevron" size={11} />
              </button>
            </label>
            <label>
              <span>Web:</span>
              <button
                type="button"
                className="rs-select"
                onClick={() => setAllowWeb((value) => !value)}
              >
                {allowWeb ? "allow_web aan" : "lokaal"}
                <FbIcon name="chevron" size={11} />
              </button>
            </label>
          </div>
        </div>
      </section>

      <div className="rs-tabs-bar">
        <div className="rs-tabs" role="tablist">
          {RESEARCH_RESULT_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={resultTab === tab.id}
              className={`rs-tab${resultTab === tab.id ? " active" : ""}`}
              onClick={() => setResultTab(tab.id)}
            >
              {tab.label}
              {resultTabCounts[tab.id] != null ? ` (${resultTabCounts[tab.id]})` : ""}
            </button>
          ))}
        </div>
        <div className="rs-sort">
          <span>Sorteren op:</span>
          <button type="button" className="rs-select" data-toast="Sorteren">
            Relevantie
            <FbIcon name="chevron" size={11} />
          </button>
        </div>
      </div>

      <div className="rs-split">
        <div className="rs-results">
          {loading && !cards.length ? <p className="muted">Researchprojecten laden…</p> : null}
          {!loading && !cards.length ? (
            <p className="muted">Nog geen researchprojecten. Start een onderzoek hierboven.</p>
          ) : null}
          {cards.map((result) => (
            <ResultCard
              key={result.id}
              result={result}
              active={selected?.id === result.id}
              onSelect={() => setSelectedId(result.id)}
            />
          ))}
        </div>

        <section className="rs-detail card">
          {selected ? (
            <>
              <div className="rs-detail-head">
                <Favicon kind={selected.favicon} size="lg" />
                <div className="rs-detail-copy">
                  <h2>{selected.title}</h2>
                  <div className="rs-detail-meta">
                    <span>
                      <FbIcon name="globe" size={11} />
                      {selected.domain}
                    </span>
                    <span>
                      <FbIcon name="calendar" size={11} />
                      {selected.dateFull}
                    </span>
                  </div>
                </div>
                <div className="rs-detail-badges">
                  <span className="rs-cat">{selected.category}</span>
                  <ReliabilityBadge label={selected.reliabilityLabel} tone={selected.reliability} />
                </div>
              </div>

              <div className="rs-detail-tabs" role="tablist">
                {RESEARCH_DETAIL_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={detailTab === tab.id}
                    className={`rs-dtab${detailTab === tab.id ? " active" : ""}`}
                    onClick={() => setDetailTab(tab.id)}
                  >
                    {tab.label}
                    {detailTabCounts[tab.id] != null ? ` (${detailTabCounts[tab.id]})` : ""}
                  </button>
                ))}
              </div>

              <div className="rs-detail-body">
                {selected.error ? (
                  <p className="muted" role="alert" style={{ marginBottom: 10 }}>
                    {selected.error}
                  </p>
                ) : null}
                <h3>Kernpunten</h3>
                {selected.keyPoints.length ? (
                  <ul className="rs-keypoints">
                    {selected.keyPoints.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Nog geen kernpunten uit bevindingen of rapport.</p>
                )}

                <blockquote className="rs-quote">
                  <span className="rs-quote-mark" aria-hidden="true">
                    “
                  </span>
                  <p>{selected.quote}</p>
                  <footer>{selected.quoteAttr}</footer>
                  <button type="button" className="rs-copy-quote" onClick={() => void copyQuote()}>
                    <FbIcon name="copy" size={12} />
                    Kopieer citaat
                  </button>
                </blockquote>

                <div className="rs-insights-head">
                  <h3>Gevonden inzichten</h3>
                </div>
                {insights.length ? (
                  <ul className="rs-insights">
                    {insights.map((insight) => (
                      <li key={insight.id}>
                        <span className="rs-insight-ico">
                          <FbIcon name={insight.icon} size={13} />
                        </span>
                        <div>
                          <strong>{insight.title}</strong>
                          <p>{insight.body}</p>
                        </div>
                        <span className={`rs-rel-pill ${insight.relevance}`}>{insight.relevanceLabel}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Nog geen inzichten — onvoldoende bewijs of rapport.</p>
                )}

                {detailTab === "full" && selected.report ? (
                  <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", marginTop: 12 }}>
                    {selected.report}
                  </pre>
                ) : null}

                {detailTab === "citations" ? (
                  sources.length ? (
                    <ul className="rs-keypoints" style={{ marginTop: 12 }}>
                      {sources.map((item) => (
                        <li key={item.id}>
                          <strong>{item.title || item.id}</strong> — {item.uri || item.source_type}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted" style={{ marginTop: 12 }}>
                      Geen bronnen voor dit project.
                    </p>
                  )
                ) : null}
              </div>

              <div className="rs-detail-actions">
                <button
                  type="button"
                  className="rs-action"
                  disabled={actionBusy}
                  onClick={() => void onRunOrCancel()}
                >
                  <FbIcon name="plus" size={12} />
                  {selected.status === "running" || selected.status === "queued"
                    ? "Annuleren"
                    : "Opnieuw onderzoeken"}
                </button>
                <button type="button" className="rs-action" data-toast="Delen">
                  <FbIcon name="external" size={12} />
                  Delen
                </button>
                <button
                  type="button"
                  className="rs-action"
                  disabled={!selected.report}
                  onClick={() => {
                    if (!selected.report) return;
                    const blob = new Blob([selected.report], { type: "text/markdown;charset=utf-8" });
                    const url = URL.createObjectURL(blob);
                    const anchor = document.createElement("a");
                    anchor.href = url;
                    anchor.download = `${selected.title.replace(/[^a-z0-9-_]+/gi, "-") || "hades-research"}.md`;
                    anchor.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  <FbIcon name="download" size={12} />
                  Exporteren
                </button>
              </div>
            </>
          ) : (
            <p className="muted" style={{ padding: 16 }}>
              {loading ? "Laden…" : "Selecteer of start een researchproject."}
            </p>
          )}
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <section className="insp-section">
        <div className="rs-insp-head">
          <h3 className="insp-title">Research status</h3>
          <span className="rs-live">
            <i />
            LIVE
          </span>
        </div>
        <div className="insp-card rs-status-card">
          {statusChecks.map((check) => (
            <div key={check.id} className="rs-status-row">
              <span className="rs-status-ico">
                <FbIcon name={check.icon} size={12} />
              </span>
              <span className="rs-status-label">{check.label}</span>
              <b className={check.tone === "green" ? "green" : undefined}>{check.value}</b>
            </div>
          ))}
          {coverageError ? (
            <div className="rs-status-row">
              <span className="rs-status-label">Coverage</span>
              <b>{coverageError}</b>
            </div>
          ) : null}
          {coverage ? (
            <div className="rs-status-row">
              <span className="rs-status-label">Coverage (API)</span>
              <b>
                {coverage.coverage_score != null ? `${coverage.coverage_score}%` : "—"}
                {coverage.incomplete || coverage.needs_more_evidence ? " · incompleet" : ""}
              </b>
            </div>
          ) : null}
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Bronverdeling</h3>
        <div className="insp-card rs-donut-card">
          {totalSources ? (
            <>
              <div className="rs-donut-wrap">
                <svg viewBox="0 0 42 42" className="rs-donut" aria-hidden="true">
                  <circle cx="21" cy="21" r="14" fill="none" stroke="rgba(74,163,255,0.12)" strokeWidth="5" />
                  {donut.map((seg, index) => (
                    <circle
                      key={sourceSlices[index]!.label}
                      cx="21"
                      cy="21"
                      r="14"
                      fill="none"
                      stroke={seg.color}
                      strokeWidth="5"
                      strokeDasharray={seg.dash}
                      strokeDashoffset={seg.offset}
                      transform="rotate(-90 21 21)"
                    />
                  ))}
                </svg>
                <div className="rs-donut-center">
                  <strong>{totalSources}</strong>
                  <span>bronnen</span>
                </div>
              </div>
              <ul className="rs-donut-legend">
                {sourceSlices.map((slice) => (
                  <li key={slice.label}>
                    <i style={{ background: slice.color }} />
                    <span>{slice.label}</span>
                    <b>
                      {slice.count} ({slice.pct})
                    </b>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="muted" style={{ margin: 0, padding: 8 }}>
              Geen bronnen voor dit project
              {knowledge ? ` · library ${knowledge.sources}` : ""}.
            </p>
          )}
        </div>
      </section>

      <section className="insp-section">
        <div className="rs-insp-head">
          <h3 className="insp-title">
            Bewijslijst <em className="rs-count-pill">{sources.length}</em>
          </h3>
          <button type="button" className="rs-link" data-toast="Bewijslijst">
            Alles bekijken →
          </button>
        </div>
        <div className="insp-card rs-evidence-list">
          {sources.length ? (
            sources.slice(0, 8).map((item) => (
              <div key={item.id} className="rs-evidence-row">
                <Favicon kind={faviconFor(item.uri || item.title)} size="sm" />
                <div>
                  <strong>{item.title || item.id}</strong>
                  <small>{domainFromUri(item.uri || item.local_path || "")}</small>
                </div>
              </div>
            ))
          ) : (
            <p className="muted" style={{ margin: 0, padding: 8 }}>
              Geen evidence-bronnen.
            </p>
          )}
        </div>
      </section>

      <section className="insp-section">
        <div className="rs-insp-head">
          <h3 className="insp-title">Recente onderzoeken</h3>
          <button type="button" className="rs-link" onClick={() => void refresh()}>
            Vernieuwen →
          </button>
        </div>
        <div className="insp-card rs-recent-list">
          {recent.length ? (
            recent.map((item) => (
              <button
                key={item.id}
                type="button"
                className="rs-recent-row"
                onClick={() => setSelectedId(item.id)}
              >
                <span className="rs-recent-ico">
                  <FbIcon name="clock" size={13} />
                </span>
                <span className="rs-recent-copy">
                  <strong>{item.title}</strong>
                  <small>{item.when}</small>
                </span>
                <span className="rs-recent-count">{item.results}</span>
              </button>
            ))
          ) : (
            <p className="muted" style={{ margin: 0, padding: 8 }}>
              Nog geen recente onderzoeken.
            </p>
          )}
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="dash-footer research-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Local AI Platform</span>
      <span className="motto">
        Build a smarter tomorrow. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="research"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="research-app"
      mainClassName="research-main"
      footer={footer}
    />
  );
}
