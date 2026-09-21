/** FINALBETA Workflows — live Gen2 workflow APIs (visual shell preserved). */
"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useHadesWorkflows } from "@/components/hades/features/workflows/hooks/useHadesWorkflows";
import type { Gen2Workflow, Gen2WorkflowStep } from "@/lib/hades-api";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };
type WfTab = "overzicht" | "workflows" | "templates" | "runs";
type CanvasTab = "canvas" | "config" | "runs";

const WF_TABS: Array<{ id: WfTab; label: string }> = [
  { id: "overzicht", label: "Overzicht" },
  { id: "workflows", label: "Workflows" },
  { id: "templates", label: "Templates" },
  { id: "runs", label: "Uitvoeringen" },
];

const CANVAS_TABS: Array<{ id: CanvasTab; label: string }> = [
  { id: "canvas", label: "Canvas" },
  { id: "config", label: "Configuratie" },
  { id: "runs", label: "Uitvoeringen" },
];

const STATUS_FILTERS = [
  { id: "all", label: "Alle statussen" },
  { id: "draft", label: "Draft" },
  { id: "tested", label: "Tested" },
  { id: "promoted", label: "Promoted" },
  { id: "archived", label: "Archived" },
] as const;

const QUOTE = "Automate intelligence. Multiply impact.";

function statusTone(status: string): "green" | "gold" | "red" | "blue" | "gray" {
  const s = status.toLowerCase();
  if (s === "promoted" || s === "tested") return "green";
  if (s === "draft") return "gold";
  if (s === "archived") return "gray";
  if (s.includes("fail") || s.includes("error")) return "red";
  return "blue";
}

function stepKind(step: Gen2WorkflowStep): "trigger" | "action" | "condition" | "end" {
  const t = String(step.type || "").toLowerCase();
  if (t === "choose" || t === "check" || t === "approve") return "condition";
  if (t === "provide_secret") return "action";
  return "action";
}

function LiveWorkflowCanvas({ steps }: { steps: Gen2WorkflowStep[] }) {
  if (!steps.length) {
    return (
      <div className="prw-canvas-placeholder">
        <p>Deze workflow heeft nog geen stappen.</p>
      </div>
    );
  }

  return (
    <div className="prw-canvas" aria-label="Workflow stappen">
      <div className="prw-list-stack" style={{ padding: 12, gap: 8 }}>
        {steps.map((step, index) => {
          const kind = stepKind(step);
          return (
            <div key={step.id || `step-${index}`} className={`prw-node ${kind}`} style={{ position: "relative", left: 0, top: 0, width: "100%", marginBottom: 8 }}>
              <span className="prw-node-ico" aria-hidden="true">
                <FbIcon
                  name={kind === "condition" ? "target" : kind === "end" ? "checkcircle" : "bolt"}
                  size={12}
                />
              </span>
              <div className="prw-node-copy">
                <strong>
                  {index + 1}. {step.action || step.type || step.id || `Stap ${index + 1}`}
                </strong>
                <small>
                  {step.description ||
                    (step.depends_on?.length ? `depends: ${step.depends_on.join(", ")}` : step.type || "step")}
                </small>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function WorkflowsPage({ onNavigate }: Props) {
  const live = useHadesWorkflows();
  const [tab, setTab] = useState<WfTab>("overzicht");
  const [canvasTab, setCanvasTab] = useState<CanvasTab>("canvas");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]["id"]>("all");
  const [busy, setBusy] = useState(false);
  const [actionNote, setActionNote] = useState<string | null>(null);

  useEffect(() => {
    if (!live.selectedId && live.workflows[0]?.id) {
      live.setSelectedId(live.workflows[0].id);
    }
  }, [live.selectedId, live.workflows, live.setSelectedId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return live.workflows.filter((wf) => {
      if (statusFilter !== "all" && String(wf.status).toLowerCase() !== statusFilter) return false;
      if (!q) return true;
      return (
        wf.name.toLowerCase().includes(q) ||
        String(wf.definition?.description || "").toLowerCase().includes(q) ||
        wf.id.toLowerCase().includes(q)
      );
    });
  }, [live.workflows, query, statusFilter]);

  const selected: Gen2Workflow | null =
    filtered.find((w) => w.id === live.selectedId) || live.selected || filtered[0] || null;

  const stats = [
    {
      id: "total",
      label: "Totaal workflows",
      value: live.loading ? "…" : String(live.workflows.length),
      hint: `${live.templates.length} templates`,
      icon: "list" as const,
    },
    {
      id: "promoted",
      label: "Promoted",
      value: String(live.workflows.filter((w) => w.status === "promoted").length),
      hint: "Productie-kandidaten",
      icon: "checkcircle" as const,
    },
    {
      id: "tested",
      label: "Tested",
      value: String(live.workflows.filter((w) => w.status === "tested").length),
      hint: "Dry-run bewijs",
      icon: "flask" as const,
    },
    {
      id: "draft",
      label: "Draft",
      value: String(live.workflows.filter((w) => w.status === "draft").length),
      hint: "Nog niet gepromoveerd",
      icon: "file" as const,
    },
  ];

  async function createFromFirstTemplate() {
    if (busy) return;
    const template = live.templates[0];
    if (!template) {
      toast.error("Geen workflow-templates beschikbaar.");
      return;
    }
    setBusy(true);
    setActionNote(null);
    try {
      const created = await live.createFromTemplate(template.id);
      live.setSelectedId(created.id);
      setActionNote(`Workflow aangemaakt vanuit template «${template.name || template.id}».`);
      toast.success("Workflow aangemaakt.");
    } catch (reason) {
      const msg = reason instanceof Error ? reason.message : String(reason);
      setActionNote(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  async function runValidate() {
    if (!selected || busy) return;
    setBusy(true);
    setActionNote(null);
    try {
      const result = await live.validate(selected.id);
      setActionNote(
        result.valid
          ? `Validatie OK (${selected.id})`
          : `Validatie mislukt: ${(result.errors || []).join("; ") || "onbekend"}`,
      );
    } catch (err) {
      setActionNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      await live.refresh();
    }
  }

  async function runDryRun() {
    if (!selected || busy) return;
    setBusy(true);
    setActionNote(null);
    try {
      const result = await live.dryRun(selected.id);
      setActionNote(
        `Dry-run ${result.status || (result.passed ? "passed" : "done")}${
          result.note ? ` — ${result.note}` : ""
        }`,
      );
    } catch (err) {
      setActionNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      await live.refresh();
    }
  }

  const steps = selected?.definition?.steps || [];

  const body = (
    <div className="mc-page pr-page prw-page" data-live="workflows" data-page="workflows">
      <MediaWelcome
        title="Workflows"
        subtitle="Bouw, beheer en automatiseer AI-gedreven processen en integraties."
        quote={QUOTE}
        right={
          <div className="pr-welcome-actions">
            <button className="btn btn-outline" type="button" onClick={() => void live.refresh()}>
              <FbIcon name="bolt" size={13} />
              Vernieuwen
            </button>
            <button
              className="btn btn-gold"
              type="button"
              disabled={busy || live.templates.length === 0}
              onClick={() => void createFromFirstTemplate()}
            >
              <FbIcon name="plus" size={13} />
              {busy ? "Aanmaken…" : `Nieuwe uit template (${live.templates.length})`}
            </button>
          </div>
        }
      />

      {live.error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12 }}>
          <strong>Workflows laden mislukt.</strong> {live.error}{" "}
          <button type="button" className="mc-link-btn" onClick={() => void live.refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      {actionNote ? (
        <div className="mc-panel" style={{ marginBottom: 12, padding: "10px 14px" }}>
          {actionNote}
        </div>
      ) : null}

      <div className="prw-tabs" role="tablist" aria-label="Workflow secties">
        {WF_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            className={`prw-tab${tab === item.id ? " active" : ""}`}
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="prw-kpi-row">
        {stats.map((stat) => (
          <article key={stat.id} className="mc-kpi prw-kpi">
            <div className="prw-kpi-top">
              <span className="prw-kpi-ico">
                <FbIcon name={stat.icon} size={13} />
              </span>
              <span className="mc-kpi-label">{stat.label}</span>
            </div>
            <div className="mc-kpi-value">{stat.value}</div>
            <div className="prw-kpi-hint">{stat.hint}</div>
          </article>
        ))}
      </div>

      {tab === "templates" ? (
        <section className="mc-panel">
          <div className="mc-panel-head">
            <div>
              <h2>Templates</h2>
              <p>Gen2 workflow templates</p>
            </div>
          </div>
          {!live.templates.length ? (
            <p className="muted" style={{ padding: 12 }}>
              {live.loading ? "Templates laden…" : "Nog geen templates beschikbaar."}
            </p>
          ) : (
            <div className="prw-list-stack" style={{ padding: 12 }}>
              {live.templates.map((tpl) => (
                <div key={tpl.id} className="prw-row" style={{ cursor: "default" }}>
                  <span className="mc-dot blue" />
                  <div className="prw-row-copy">
                    <strong>{tpl.name}</strong>
                    <small>{tpl.description || tpl.id}</small>
                    <span className="prw-row-meta">
                      {(tpl.pattern_tags || []).join(", ") || "geen tags"}
                      {tpl.offline_safe ? " · offline-safe" : ""}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : (
        <div className="prw-workspace">
          <section className="mc-panel prw-list-panel">
            <div className="mc-panel-head">
              <div>
                <h2>Workflows</h2>
                <p>
                  {filtered.length} lokaal{live.loading ? " · laden…" : ""}
                </p>
              </div>
            </div>
            <div className="prw-list-tools">
              <label className="prw-search">
                <FbIcon name="search" size={12} />
                <input
                  type="search"
                  placeholder="Zoek workflows..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <select
                className="prw-filter"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
                aria-label="Statusfilter"
              >
                {STATUS_FILTERS.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="prw-list-stack">
              {!filtered.length ? (
                <p className="muted" style={{ padding: 12 }}>
                  {live.loading ? "Workflows laden…" : "Nog geen workflows. Importeer of maak er één via de API."}
                </p>
              ) : (
                filtered.map((wf) => (
                  <button
                    key={wf.id}
                    type="button"
                    className={`prw-row${selected?.id === wf.id ? " active" : ""}`}
                    onClick={() => live.setSelectedId(wf.id)}
                  >
                    <span className={`mc-dot ${statusTone(String(wf.status))}`} />
                    <div className="prw-row-copy">
                      <strong>{wf.name}</strong>
                      <small>{wf.definition?.description || wf.id}</small>
                      <span className="prw-row-meta">
                        v{wf.version ?? wf.definition?.version ?? "—"} · {wf.updated_at || wf.created_at || "—"}
                      </span>
                    </div>
                    <span className={`mc-pill ${statusTone(String(wf.status))}`}>{wf.status}</span>
                  </button>
                ))
              )}
            </div>
          </section>

          <section className="mc-panel prw-canvas-panel">
            {selected ? (
              <>
                <div className="prw-canvas-head">
                  <div className="prw-canvas-title">
                    <h2>{selected.name}</h2>
                    <span className={`mc-pill ${statusTone(String(selected.status))}`}>{selected.status}</span>
                  </div>
                  <div className="prw-canvas-actions">
                    <button className="btn btn-sm btn-outline" type="button" disabled={busy} onClick={() => void runValidate()}>
                      Valideren
                    </button>
                    <button className="btn btn-sm btn-gold" type="button" disabled={busy} onClick={() => void runDryRun()}>
                      Dry-run
                    </button>
                  </div>
                </div>

                <div className="prw-canvas-tabs" role="tablist">
                  {CANVAS_TABS.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      role="tab"
                      className={`prw-canvas-tab${canvasTab === item.id ? " active" : ""}`}
                      aria-selected={canvasTab === item.id}
                      onClick={() => setCanvasTab(item.id)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>

                {canvasTab === "canvas" ? (
                  <LiveWorkflowCanvas steps={steps} />
                ) : canvasTab === "config" ? (
                  <div className="prw-canvas-placeholder">
                    <p>
                      Offline-safe: {selected.definition?.offline_safe ? "ja" : "nee"} · stappen: {steps.length} ·
                      human_approved: {selected.definition?.human_approved ? "ja" : "nee"}
                    </p>
                    {selected.definition?.pattern_tags?.length ? (
                      <p>Tags: {selected.definition.pattern_tags.join(", ")}</p>
                    ) : null}
                  </div>
                ) : (
                  <div className="prw-canvas-placeholder">
                    <p>
                      Active run: {selected.definition?.active_run_id || "geen"} · metrics:{" "}
                      {Object.keys(selected.metrics || selected.definition?.metrics || {}).length
                        ? JSON.stringify(selected.metrics || selected.definition?.metrics)
                        : "nog geen metrics"}
                    </p>
                  </div>
                )}
              </>
            ) : (
              <div className="prw-canvas-placeholder">
                <p>Selecteer een workflow om stappen en acties te zien.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“{QUOTE}”</p>
      <section className="mc-insp-section">
        <div className="prw-insp-head">
          <h3 className="mc-insp-title">Workflow details</h3>
        </div>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Naam</span>
            <span className="v">{selected?.name || "—"}</span>
          </div>
          <div className="mc-detail-row prw-detail-desc">
            <span className="k">Beschrijving</span>
            <span className="v">{selected?.definition?.description || "Geen beschrijving"}</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className="v">{selected?.status || "—"}</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Stappen</span>
            <span className="v">{steps.length}</span>
          </div>
        </div>
      </section>
      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Runtime</h3>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">gen2 workflows · templates</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className={`v ${live.error ? "gold" : "green"}`}>
              {live.loading ? "Laden…" : live.error ? "Fout" : "Live"}
            </span>
          </div>
        </div>
      </section>
      {selected ? (
        <section className="mc-insp-section">
          <h3 className="mc-insp-title">Acties</h3>
          <div className="stats-quick-grid">
            <button type="button" className="stats-quick-btn" disabled={busy} onClick={() => void runValidate()}>
              <FbIcon name="checkcircle" size={16} />
              <span>Valideren</span>
            </button>
            <button type="button" className="stats-quick-btn" disabled={busy} onClick={() => void runDryRun()}>
              <FbIcon name="flask" size={16} />
              <span>Dry-run</span>
            </button>
          </div>
        </section>
      ) : null}
    </>
  );

  return (
    <FinalBetaShell
      page="workflows"
      appClassName="mc-app pr-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
