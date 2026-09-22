import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type {
  ResearchBudget,
  ResearchClaim,
  ResearchConflict,
  ResearchCoverage,
  ResearchEvidence,
  ResearchProject,
  ResearchReport,
  ResearchSource,
} from "../types/api";

type MainTab = "projects" | "create";
type DetailTab = "overview" | "sources" | "evidence" | "claims" | "conflicts" | "coverage" | "report";

const ACTIVE = new Set(["queued", "researching", "synthesizing", "cancelling"]);

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function ResearchPage() {
  const toast = useAppToast();
  const [mainTab, setMainTab] = useState<MainTab>("projects");
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ResearchProject | null>(null);

  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [evidence, setEvidence] = useState<ResearchEvidence[]>([]);
  const [claims, setClaims] = useState<ResearchClaim[]>([]);
  const [conflicts, setConflicts] = useState<ResearchConflict[]>([]);
  const [coverage, setCoverage] = useState<ResearchCoverage | null>(null);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [budgets, setBudgets] = useState<Record<string, ResearchBudget> | null>(null);

  // Create form
  const [topic, setTopic] = useState("");
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [depth, setDepth] = useState("standard");
  const [allowWeb, setAllowWeb] = useState(false);
  const [localScopes, setLocalScopes] = useState("");
  const [seedSources, setSeedSources] = useState("");

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, budgetRes] = await Promise.all([
        api.listResearchProjects(),
        api.researchBudgets().catch(() => ({ presets: null as Record<string, ResearchBudget> | null })),
      ]);
      setProjects(list.projects);
      if (budgetRes.presets) setBudgets(budgetRes.presets);
      if (list.projects.length === 0) {
        setSelectedId(null);
      } else if (!selectedId || !list.projects.some((p) => p.project_id === selectedId)) {
        setSelectedId(list.projects[0].project_id);
      }
    } catch (err) {
      setError(errMsg(err, "Failed to load research projects"));
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void loadProjects();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setSources([]);
      setEvidence([]);
      setClaims([]);
      setConflicts([]);
      setCoverage(null);
      setReport(null);
      return;
    }
    let cancelled = false;
    const loadDetail = async () => {
      setDetailError(null);
      try {
        const res = await api.getResearchProject(selectedId);
        if (cancelled) return;
        setSelected(res.project);
      } catch (err) {
        if (!cancelled) setDetailError(errMsg(err, "Failed to load project"));
      }
    };
    void loadDetail();
    const id = window.setInterval(() => {
      if (selected && ACTIVE.has(selected.status)) void loadDetail();
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps -- poll when selected changes

  useEffect(() => {
    if (!selectedId || detailTab === "overview") return;
    let cancelled = false;
    (async () => {
      setDetailError(null);
      try {
        if (detailTab === "sources") {
          const res = await api.listResearchSources(selectedId);
          if (!cancelled) setSources(res.sources);
        } else if (detailTab === "evidence") {
          const res = await api.listResearchEvidence(selectedId);
          if (!cancelled) setEvidence(res.evidence);
        } else if (detailTab === "claims") {
          const res = await api.listResearchClaims(selectedId);
          if (!cancelled) setClaims(res.claims);
        } else if (detailTab === "conflicts") {
          const res = await api.listResearchConflicts(selectedId);
          if (!cancelled) setConflicts(res.conflicts);
        } else if (detailTab === "coverage") {
          const res = await api.getResearchCoverage(selectedId);
          if (!cancelled) setCoverage(res.coverage);
        } else if (detailTab === "report") {
          try {
            const res = await api.getResearchReport(selectedId);
            if (!cancelled) setReport(res.report);
          } catch (err) {
            if (!cancelled) {
              setReport(null);
              setDetailError(errMsg(err, "No report yet"));
            }
          }
        }
      } catch (err) {
        if (!cancelled) setDetailError(errMsg(err, "Failed to load detail"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, detailTab, selected?.updated_at]);

  async function withBusy(fn: () => Promise<void>, ok?: string) {
    setBusy(true);
    try {
      await fn();
      if (ok) toast(ok);
    } catch (err) {
      toast(errMsg(err, "Action failed"));
    } finally {
      setBusy(false);
    }
  }

  async function onCreate() {
    if (!topic.trim()) {
      toast("Topic is required");
      return;
    }
    await withBusy(async () => {
      const res = await api.createResearchProject({
        topic: topic.trim(),
        title: title.trim() || undefined,
        objective: objective.trim(),
        depth,
        allowWeb,
        localScopes: localScopes
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        seedSources: seedSources
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setTopic("");
      setTitle("");
      setObjective("");
      setLocalScopes("");
      setSeedSources("");
      setSelectedId(res.project.project_id);
      setMainTab("projects");
      await loadProjects();
    }, "Project created");
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Search research projects…"
      pageClass="lv-app--research"
      layout="wide"
    >
      <main className="lv-main">
        <header className="lv-models-header">
          <div>
            <div className="lv-models-kicker">Evidence-driven inquiry</div>
            <h1 className="lv-models-title">Research</h1>
            <p className="lv-muted">
              Real projects only — empty until you create one. Web stays off unless configured.
            </p>
          </div>
          <div className="lv-models-header-actions">
            <button className="lv-btn" type="button" disabled={busy || loading} onClick={() => void loadProjects()}>
              Refresh
            </button>
            <button className="lv-btn lv-btn-gold" type="button" onClick={() => setMainTab("create")}>
              New project
            </button>
          </div>
        </header>
        {error ? (
          <div className="lv-models-banner is-error" role="alert">
            <strong>Research unavailable</strong>
            <span>{error}</span>
          </div>
        ) : null}

        <div className="lv-tabs" role="tablist">
          <button
            className={`lv-tab${mainTab === "projects" ? " is-active" : ""}`}
            type="button"
            onClick={() => setMainTab("projects")}
          >
            Projects
          </button>
          <button
            className={`lv-tab${mainTab === "create" ? " is-active" : ""}`}
            type="button"
            onClick={() => setMainTab("create")}
          >
            Create
          </button>
        </div>

        {mainTab === "create" ? (
          <section className="lv-panel" aria-label="Create research project">
            <div className="lv-form-grid">
              <div className="lv-form-field full">
                <label htmlFor="rs-topic">Topic</label>
                <input
                  id="rs-topic"
                  className="lv-input"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="What should be investigated?"
                />
              </div>
              <div className="lv-form-field">
                <label htmlFor="rs-title">Title (optional)</label>
                <input id="rs-title" className="lv-input" value={title} onChange={(e) => setTitle(e.target.value)} />
              </div>
              <div className="lv-form-field">
                <label htmlFor="rs-depth">Depth</label>
                <select id="rs-depth" className="lv-input" value={depth} onChange={(e) => setDepth(e.target.value)}>
                  <option value="quick">quick</option>
                  <option value="standard">standard</option>
                  <option value="deep">deep</option>
                  <option value="expert">expert</option>
                </select>
              </div>
              <div className="lv-form-field full">
                <label htmlFor="rs-objective">Objective</label>
                <textarea
                  id="rs-objective"
                  className="lv-input"
                  rows={3}
                  value={objective}
                  onChange={(e) => setObjective(e.target.value)}
                />
              </div>
              <div className="lv-form-field full">
                <label className="lv-models-check">
                  <input type="checkbox" checked={allowWeb} onChange={(e) => setAllowWeb(e.target.checked)} />
                  Allow web retrieval
                </label>
                <p className="lv-muted">
                  When web is unavailable or disallowed, projects still run against local scopes and seeds —
                  they will not invent citations.
                </p>
              </div>
              <div className="lv-form-field full">
                <label htmlFor="rs-scopes">Local scopes (one path/scope per line)</label>
                <textarea
                  id="rs-scopes"
                  className="lv-input"
                  rows={3}
                  value={localScopes}
                  onChange={(e) => setLocalScopes(e.target.value)}
                />
              </div>
              <div className="lv-form-field full">
                <label htmlFor="rs-seeds">Seed sources (one URI per line)</label>
                <textarea
                  id="rs-seeds"
                  className="lv-input"
                  rows={3}
                  value={seedSources}
                  onChange={(e) => setSeedSources(e.target.value)}
                />
              </div>
              {budgets?.[depth] ? (
                <p className="lv-muted full">
                  Budget for {depth}: {budgets[depth].max_sources} sources · {budgets[depth].rounds} round(s) ·{" "}
                  {budgets[depth].search_queries} search queries
                </p>
              ) : null}
              <div className="lv-form-actions full">
                <button
                  className="lv-btn lv-btn-gold"
                  type="button"
                  disabled={busy || !topic.trim()}
                  onClick={() => void onCreate()}
                >
                  Create project
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {mainTab === "projects" ? (
          <section className="lv-panel" aria-label="Research projects">
            {loading ? (
              <div className="lv-models-banner" role="status">
                Loading projects…
              </div>
            ) : null}
            {!loading && projects.length === 0 ? (
              <div className="lv-models-empty">
                <h2>NO RESEARCH PROJECTS</h2>
                <p>Create a project with a topic. Sources and citations appear only after a real run.</p>
                <button className="lv-btn lv-btn-gold" type="button" onClick={() => setMainTab("create")}>
                  Create project
                </button>
              </div>
            ) : (
              <div className="lv-models-table-wrap">
                <table className="lv-models-table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Depth</th>
                      <th>Web</th>
                      <th>Sources</th>
                      <th>Claims</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {projects.map((p) => (
                      <tr
                        key={p.project_id}
                        className={p.project_id === selectedId ? "is-selected" : undefined}
                        onClick={() => {
                          setSelectedId(p.project_id);
                          setDetailTab("overview");
                        }}
                      >
                        <td>
                          <strong>{p.title || p.topic}</strong>
                          <div className="lv-muted">{p.topic}</div>
                        </td>
                        <td>{p.status}</td>
                        <td>{p.depth}</td>
                        <td>{p.allow_web ? "on" : "off"}</td>
                        <td>{p.source_count}</td>
                        <td>{p.claim_count}</td>
                        <td>{p.updated_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {selected ? (
              <div style={{ marginTop: "1.25rem" }}>
                <div className="lv-card-head">
                  <div>
                    <div className="lv-section-label">Project</div>
                    <h2>{selected.title || selected.topic}</h2>
                    <p className="lv-muted">
                      {selected.status} · round {selected.current_round}/{selected.total_rounds}
                      {selected.web_unavailable_reason
                        ? ` · web unavailable: ${selected.web_unavailable_reason}`
                        : selected.allow_web
                          ? " · web allowed"
                          : " · web not requested"}
                    </p>
                    {selected.error ? <p className="lv-muted">Error: {selected.error}</p> : null}
                  </div>
                  <div className="lv-row-actions" style={{ flexWrap: "wrap" }}>
                    <button
                      className="lv-btn"
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void withBusy(async () => {
                          const res = await api.planResearchProject(selected.project_id);
                          setSelected(res.project);
                          toast("Plan ready");
                        })
                      }
                    >
                      Plan
                    </button>
                    <button
                      className="lv-btn lv-btn-gold"
                      type="button"
                      disabled={busy || ACTIVE.has(selected.status)}
                      title={ACTIVE.has(selected.status) ? "Already running" : undefined}
                      onClick={() =>
                        void withBusy(async () => {
                          const res = await api.runResearchProject(selected.project_id);
                          setSelected(res.project);
                          await loadProjects();
                        }, "Run started")
                      }
                    >
                      Run
                    </button>
                    <button
                      className="lv-btn"
                      type="button"
                      disabled={busy || !ACTIVE.has(selected.status)}
                      title={!ACTIVE.has(selected.status) ? "No active run to cancel" : undefined}
                      onClick={() =>
                        void withBusy(async () => {
                          const res = await api.cancelResearchProject(selected.project_id);
                          setSelected(res.project);
                        }, "Cancel requested")
                      }
                    >
                      Cancel
                    </button>
                    <button
                      className="lv-btn"
                      type="button"
                      disabled={busy || !["interrupted", "cancelled", "failed"].includes(selected.status)}
                      title={
                        !["interrupted", "cancelled", "failed"].includes(selected.status)
                          ? "Resume only for interrupted/cancelled/failed"
                          : undefined
                      }
                      onClick={() =>
                        void withBusy(async () => {
                          const res = await api.resumeResearchProject(selected.project_id);
                          setSelected(res.project);
                        }, "Resume requested")
                      }
                    >
                      Resume
                    </button>
                    <button
                      className="lv-btn"
                      type="button"
                      disabled={busy || selected.status !== "completed"}
                      title={selected.status !== "completed" ? "Deepen after a completed run" : undefined}
                      onClick={() =>
                        void withBusy(async () => {
                          const res = await api.deepenResearchProject(selected.project_id, 1);
                          setSelected(res.project);
                        }, "Deepen queued")
                      }
                    >
                      Deepen
                    </button>
                  </div>
                </div>

                <div className="lv-tabs" role="tablist">
                  {(
                    [
                      ["overview", "Overview"],
                      ["sources", "Sources"],
                      ["evidence", "Evidence"],
                      ["claims", "Claims"],
                      ["conflicts", "Conflicts"],
                      ["coverage", "Coverage"],
                      ["report", "Report"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      className={`lv-tab${detailTab === id ? " is-active" : ""}`}
                      type="button"
                      onClick={() => setDetailTab(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {detailError && detailTab !== "overview" ? (
                  <p className="lv-muted">{detailError}</p>
                ) : null}

                {detailTab === "overview" ? (
                  <div>
                    {selected.plan ? (
                      <>
                        <h3>Plan</h3>
                        <p>{selected.plan.interpreted_question || selected.topic}</p>
                        <p className="lv-muted">Scope: {selected.plan.scope || "—"}</p>
                        {selected.plan.subquestions.length > 0 ? (
                          <ul>
                            {selected.plan.subquestions.map((q) => (
                              <li key={q}>{q}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="lv-muted">No subquestions yet — run Plan.</p>
                        )}
                      </>
                    ) : (
                      <p className="lv-muted">No plan yet. Click Plan to generate one.</p>
                    )}
                    {selected.allow_web && selected.web_unavailable_reason ? (
                      <div className="lv-models-banner is-warn" role="status">
                        <strong>Web unavailable</strong>
                        <span>{selected.web_unavailable_reason}</span>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {detailTab === "sources" ? (
                  sources.length === 0 ? (
                    <div className="lv-models-empty">
                      <h2>NO SOURCES</h2>
                      <p>Sources appear after a successful retrieval run — none are invented.</p>
                    </div>
                  ) : (
                    <div className="lv-models-table-wrap">
                      <table className="lv-models-table">
                        <thead>
                          <tr>
                            <th>Title</th>
                            <th>Type</th>
                            <th>URI</th>
                            <th>Parse</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sources.map((s) => (
                            <tr key={s.source_id}>
                              <td>{dash(s.title)}</td>
                              <td>{s.source_type}</td>
                              <td>{dash(s.canonical_uri ?? s.original_uri)}</td>
                              <td>{s.parse_status}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )
                ) : null}

                {detailTab === "evidence" ? (
                  evidence.length === 0 ? (
                    <div className="lv-models-empty">
                      <h2>NO EVIDENCE</h2>
                      <p>Evidence spans are extracted from real sources only.</p>
                    </div>
                  ) : (
                    <ul>
                      {evidence.map((e) => (
                        <li key={e.evidence_id}>
                          <code>{e.citation_key}</code> — {e.span_text.slice(0, 240)}
                          {e.span_text.length > 240 ? "…" : ""}
                        </li>
                      ))}
                    </ul>
                  )
                ) : null}

                {detailTab === "claims" ? (
                  claims.length === 0 ? (
                    <div className="lv-models-empty">
                      <h2>NO CLAIMS</h2>
                      <p>Claims are synthesized after evidence collection.</p>
                    </div>
                  ) : (
                    <ul>
                      {claims.map((c) => (
                        <li key={c.claim_id}>
                          [{c.status}] {c.proposition}
                        </li>
                      ))}
                    </ul>
                  )
                ) : null}

                {detailTab === "conflicts" ? (
                  conflicts.length === 0 ? (
                    <div className="lv-models-empty">
                      <h2>NO CONFLICTS</h2>
                      <p>No conflicting evidence recorded for this project.</p>
                    </div>
                  ) : (
                    <ul>
                      {conflicts.map((c) => (
                        <li key={c.conflict_id}>{c.summary}</li>
                      ))}
                    </ul>
                  )
                ) : null}

                {detailTab === "coverage" ? (
                  !coverage ? (
                    <p className="lv-muted">Coverage not available yet.</p>
                  ) : (
                    <div className="lv-meta-grid">
                      <div className="lv-meta-item">
                        <span>Sources</span>
                        <strong>{coverage.source_count}</strong>
                      </div>
                      <div className="lv-meta-item">
                        <span>Supported claims</span>
                        <strong>{coverage.claims_supported}</strong>
                      </div>
                      <div className="lv-meta-item">
                        <span>Conflicts</span>
                        <strong>{coverage.claims_with_conflicts}</strong>
                      </div>
                      <div className="lv-meta-item">
                        <span>Web status</span>
                        <strong>{coverage.web_status}</strong>
                      </div>
                      <div className="lv-meta-item">
                        <span>Rounds</span>
                        <strong>{coverage.rounds_completed}</strong>
                      </div>
                      {coverage.notes.length > 0 ? (
                        <p className="lv-muted full">{coverage.notes.join(" · ")}</p>
                      ) : null}
                    </div>
                  )
                ) : null}

                {detailTab === "report" ? (
                  !report ? (
                    <div className="lv-models-empty">
                      <h2>NO REPORT</h2>
                      <p>Generate a report after the project has evidence and claims.</p>
                      <button
                        className="lv-btn"
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void withBusy(async () => {
                            const res = await api.regenerateResearchReport(selected.project_id);
                            setReport(res.report);
                            setDetailError(null);
                          }, "Report generated")
                        }
                      >
                        Generate report
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="lv-row-actions">
                        <button
                          className="lv-btn"
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void withBusy(async () => {
                              const res = await api.regenerateResearchReport(selected.project_id);
                              setReport(res.report);
                            }, "Report regenerated")
                          }
                        >
                          Regenerate
                        </button>
                        <button
                          className="lv-btn"
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void withBusy(async () => {
                              const res = await api.exportResearchProject(selected.project_id, "markdown");
                              toast(`Export ready (${Object.keys(res.export).join(", ") || "bundle"})`);
                            })
                          }
                        >
                          Export markdown
                        </button>
                      </div>
                      <h3>{report.title}</h3>
                      <pre className="lv-code-block" style={{ maxHeight: 480, overflow: "auto", whiteSpace: "pre-wrap" }}>
                        {report.body_markdown}
                      </pre>
                    </>
                  )
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
