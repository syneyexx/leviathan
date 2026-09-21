"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Download,
  Loader2,
  Play,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Archive,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, StatCard, StatusBadge } from "@/components/hades/ui";
import {
  type Gen2Workflow,
  type Gen2WorkflowDefinition,
  type Gen2WorkflowMetrics,
  type Gen2WorkflowRunResult,
  type Gen2WorkflowStep,
  type Gen2WorkflowTemplate,
  type Gen2WorkflowValidateResult,
  hadesApi,
} from "@/lib/hades-api";

function toneForStatus(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["promoted", "tested", "passed", "completed", "valid"].includes(status)) return "success";
  if (["failed", "rejected", "archived", "invalid"].includes(status)) return "danger";
  if (["draft", "awaiting_human", "running", "human_resolved"].includes(status)) return "warning";
  return "neutral";
}

function awaitingFromWorkflow(wf: Gen2Workflow | null): {
  step_id?: string;
  prompt?: string;
  type?: string;
  choices?: string[];
} | null {
  if (!wf) return null;
  const fromDef = wf.definition?.awaiting_human;
  if (fromDef && typeof fromDef === "object") return fromDef;
  const evidence = (wf.definition?.test_evidence || {}) as Record<string, unknown>;
  const stepId = evidence.awaiting_step;
  if (typeof stepId === "string" && stepId) {
    const step = (wf.definition?.steps || []).find((s) => s.id === stepId);
    return {
      step_id: stepId,
      prompt: String(step?.prompt || step?.description || stepId),
      type: String(step?.type || "approve"),
      choices: Array.isArray(step?.choices) ? step!.choices : undefined,
    };
  }
  return null;
}

function topoSortedSteps(steps: Gen2WorkflowStep[]): Gen2WorkflowStep[] {
  const byId = new Map(steps.filter((s) => s.id).map((s) => [s.id, s]));
  const ordered: Gen2WorkflowStep[] = [];
  const visiting = new Set<string>();
  const visited = new Set<string>();

  function visit(id: string) {
    if (visited.has(id) || !byId.has(id)) return;
    if (visiting.has(id)) return;
    visiting.add(id);
    for (const dep of byId.get(id)?.depends_on || []) visit(dep);
    visiting.delete(id);
    visited.add(id);
    ordered.push(byId.get(id)!);
  }

  for (const step of steps) {
    if (step.id) visit(step.id);
  }
  for (const step of steps) {
    if (!step.id || !visited.has(step.id)) ordered.push(step);
  }
  return ordered;
}

/** Layered DAG preview (depends_on). Not a canvas editor — B2.4 partial. */
function dagLayers(steps: Gen2WorkflowStep[]): Gen2WorkflowStep[][] {
  const byId = new Map(steps.filter((s) => s.id).map((s) => [s.id, s]));
  const depth = new Map<string, number>();

  function depthOf(id: string, stack: Set<string>): number {
    if (depth.has(id)) return depth.get(id)!;
    if (stack.has(id)) return 0;
    stack.add(id);
    const deps = (byId.get(id)?.depends_on || []).filter((d) => byId.has(d));
    const d = deps.length ? Math.max(...deps.map((dep) => depthOf(dep, stack))) + 1 : 0;
    stack.delete(id);
    depth.set(id, d);
    return d;
  }

  for (const step of steps) {
    if (step.id) depthOf(step.id, new Set());
  }
  const max = Math.max(0, ...Array.from(depth.values()));
  const layers: Gen2WorkflowStep[][] = Array.from({ length: max + 1 }, () => []);
  for (const step of steps) {
    if (!step.id) {
      layers[0].push(step);
      continue;
    }
    layers[depth.get(step.id) ?? 0].push(step);
  }
  return layers.filter((layer) => layer.length > 0);
}

export function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Gen2Workflow[]>([]);
  const [templates, setTemplates] = useState<Gen2WorkflowTemplate[]>([]);
  const [selected, setSelected] = useState<Gen2Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [goal, setGoal] = useState("");
  const [draft, setDraft] = useState<Gen2WorkflowDefinition | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [humanApproved, setHumanApproved] = useState(false);
  const [validateResult, setValidateResult] = useState<Gen2WorkflowValidateResult | null>(null);
  const [lastRun, setLastRun] = useState<Gen2WorkflowRunResult | null>(null);
  const [metrics, setMetrics] = useState<Gen2WorkflowMetrics | null>(null);
  const [exportJson, setExportJson] = useState("");
  const [hitlDecision, setHitlDecision] = useState("approve");
  const [hitlValue, setHitlValue] = useState("");
  const [revisions, setRevisions] = useState<
    Awaited<ReturnType<typeof hadesApi.gen2ListWorkflowRevisions>> | null
  >(null);
  const [revisionDiff, setRevisionDiff] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [list, tpls] = await Promise.all([
        hadesApi.gen2ListWorkflows({ limit: 100 }),
        hadesApi.gen2ListWorkflowTemplates(),
      ]);
      setWorkflows(list);
      setTemplates(tpls);
      if (!templateId && tpls[0]?.id) setTemplateId(tpls[0].id);
      if (selected?.id) {
        const fresh = list.find((w) => w.id === selected.id);
        if (fresh) setSelected(fresh);
        else {
          try {
            setSelected(await hadesApi.gen2GetWorkflow(selected.id));
          } catch {
            setSelected(null);
          }
        }
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Workflows laden mislukt");
    } finally {
      setLoading(false);
    }
  }, [selected?.id, templateId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    try {
      await fn();
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Actie mislukt");
    } finally {
      setBusy("");
    }
  }

  async function selectWorkflow(id: string) {
    setBusy("select");
    setValidateResult(null);
    setLastRun(null);
    setExportJson("");
    setHumanApproved(false);
    setRevisions(null);
    setRevisionDiff(null);
    try {
      const detail = await hadesApi.gen2GetWorkflow(id);
      setSelected(detail);
      try {
        setMetrics(await hadesApi.gen2WorkflowMetrics(id));
      } catch {
        setMetrics(null);
      }
      try {
        setRevisions(await hadesApi.gen2ListWorkflowRevisions(id, 20));
      } catch {
        setRevisions(null);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Workflow laden mislukt");
    } finally {
      setBusy("");
    }
  }

  const steps = useMemo(
    () => topoSortedSteps(selected?.definition?.steps || []),
    [selected?.definition?.steps],
  );
  const layers = useMemo(() => dagLayers(selected?.definition?.steps || []), [selected?.definition?.steps]);
  const awaiting = awaitingFromWorkflow(selected) || (lastRun?.awaiting_human ?? null);
  const awaitingStepId = awaiting?.step_id;

  const draftCount = workflows.filter((w) => w.status === "draft").length;
  const testedCount = workflows.filter((w) => w.status === "tested").length;
  const promotedCount = workflows.filter((w) => w.status === "promoted").length;

  return (
    <div className="details-stack">
      <PageHeader
        title="Workflows"
        description="Typed workflow IR: dry-run (geen live), sandbox (heritage), product execute (Coding/Research), promote met menselijke goedkeuring."
        actions={
          <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Vernieuwen
          </Button>
        }
      />

      <div className="stat-grid four">
        <StatCard label="Totaal" value={String(workflows.length)} note="niet-gearchiveerd" />
        <StatCard label="Draft" value={String(draftCount)} note="nog niet getest" />
        <StatCard label="Tested" value={String(testedCount)} note="dry/sandbox bewijs" />
        <StatCard label="Promoted" value={String(promotedCount)} note="mens goedgekeurd" />
      </div>

      <Panel title="Eerlijke labels" eyebrow="Contract">
        <ul className="details-stack">
          <li>
            <strong>Dry-run ≠ live</strong>
            <span className="muted"> — valideert/plant stappen; claimt geen echte uitvoering.</span>
          </li>
          <li>
            <strong>Sandbox-run</strong>
            <span className="muted"> — heritage skill primitives alleen; promoveert coding/research niet naar Ready.</span>
          </li>
          <li>
            <strong>Execute (product)</strong>
            <span className="muted"> — echte CodingAgent / ResearchRunner / plugins / artifacts; async met poll.</span>
          </li>
          <li>
            <strong>Promote → promoted</strong>
            <span className="muted"> — product-workflows vereisen product-run bewijs + human_approved.</span>
          </li>
        </ul>
      </Panel>

      <div className="form-grid two">
        <Panel title="Opgeslagen workflows" eyebrow="Lijst">
          <ul className="details-stack">
            {workflows.length === 0 ? <li className="muted">Nog geen workflows.</li> : null}
            {workflows.map((item) => (
              <li key={item.id} className="page-actions" style={{ justifyContent: "space-between" }}>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => void selectWorkflow(item.id)}
                  style={{ textAlign: "left", background: "none", border: 0, cursor: "pointer", color: "inherit" }}
                >
                  <strong>{item.name || item.id}</strong>
                  <div className="muted">
                    {item.id.slice(0, 12)}… · v{item.version ?? item.definition?.version ?? 1} ·{" "}
                    {item.updated_at || item.created_at || ""}
                  </div>
                </button>
                <StatusBadge tone={toneForStatus(String(item.status))}>{String(item.status)}</StatusBadge>
              </li>
            ))}
          </ul>
        </Panel>

        <div className="details-stack">
          <Panel title="Maak van template" eyebrow="Library">
            <div className="form-stack">
              <label className="muted" htmlFor="wf-template">
                Template
              </label>
              <select
                id="wf-template"
                className="input"
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                style={{ width: "100%", padding: "0.45rem 0.6rem" }}
              >
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name || t.id}
                    {t.offline_safe === false ? " (netwerk)" : ""}
                  </option>
                ))}
              </select>
              <Input
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder="Optionele naam"
              />
              <Button
                disabled={!!busy || !templateId}
                onClick={() =>
                  void run("template", async () => {
                    const created = await hadesApi.gen2CreateWorkflowFromTemplate(
                      templateId,
                      templateName.trim() || undefined,
                    );
                    setSelected(created);
                    toast.success(`Workflow aangemaakt: ${created.name}`);
                  })
                }
              >
                {busy === "template" ? <Loader2 className="animate-spin" /> : <Sparkles />} Maak van template
              </Button>
              {templates.find((t) => t.id === templateId)?.description ? (
                <p className="panel-copy muted">{templates.find((t) => t.id === templateId)?.description}</p>
              ) : null}
            </div>
          </Panel>

          <Panel title="NL draft" eyebrow="Offline-safe">
            <p className="panel-copy">Doel → draft IR → daarna expliciet create. Draft alleen is nog geen workflow.</p>
            <div className="form-stack">
              <Textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                rows={3}
                placeholder="Bijv. research evidence for X, of coding plan for Y…"
              />
              <div className="page-actions">
                <Button
                  variant="secondary"
                  disabled={!!busy || !goal.trim()}
                  onClick={() =>
                    void run("draft", async () => {
                      const next = await hadesApi.gen2DraftWorkflow(goal.trim());
                      setDraft(next);
                      toast.success("Draft IR klaar (nog niet opgeslagen)");
                    })
                  }
                >
                  {busy === "draft" ? <Loader2 className="animate-spin" /> : <Sparkles />} Draft
                </Button>
                <Button
                  disabled={!!busy || !draft}
                  onClick={() =>
                    void run("create-draft", async () => {
                      if (!draft) return;
                      const created = await hadesApi.gen2CreateWorkflow({
                        definition: draft as unknown as Record<string, unknown>,
                        name: draft.name,
                        note: "nl_draft",
                      });
                      setSelected(created);
                      setDraft(null);
                      toast.success(`Workflow opgeslagen: ${created.name}`);
                    })
                  }
                >
                  {busy === "create-draft" ? <Loader2 className="animate-spin" /> : <Check />} Create van draft
                </Button>
              </div>
              {draft ? (
                <div className="muted">
                  Draft: <strong>{draft.name}</strong> · {draft.steps?.length || 0} stappen · bron{" "}
                  {String(draft.draft_source || "nl")}
                </div>
              ) : null}
            </div>
          </Panel>
        </div>
      </div>

      {selected ? (
        <Panel title="Workflowdetail" eyebrow={selected.id}>
          <div className="page-actions" style={{ marginBottom: "0.6rem", flexWrap: "wrap" }}>
            <StatusBadge tone={toneForStatus(String(selected.status))}>{String(selected.status)}</StatusBadge>
            <span className="muted">v{selected.version ?? selected.definition?.version ?? 1}</span>
            {selected.definition?.offline_safe ? (
              <StatusBadge tone="success">offline_safe</StatusBadge>
            ) : (
              <StatusBadge tone="warning">network possible</StatusBadge>
            )}
            {selected.definition?.human_approved ? (
              <StatusBadge tone="success">human_approved</StatusBadge>
            ) : (
              <StatusBadge tone="neutral">geen human_approved</StatusBadge>
            )}
          </div>
          <p className="panel-copy">{selected.definition?.description || selected.name}</p>

          <h3 style={{ marginTop: "0.75rem" }}>Stappen (DAG via depends_on)</h3>
          <p className="muted">
            Layered DAG preview — not a full visual canvas editor (B2.4 partial / incomplete for drag-canvas).
          </p>
          {layers.length > 0 ? (
            <div className="code-block" style={{ marginBottom: "0.75rem" }}>
              <pre style={{ whiteSpace: "pre-wrap" }}>
                {layers
                  .map((layer, li) => {
                    const ids = layer.map((s) => s.id || "?").join("  |  ");
                    const edges = layer
                      .filter((s) => (s.depends_on || []).length > 0)
                      .map((s) => `${(s.depends_on || []).join(",") } → ${s.id}`)
                      .join("\n    ");
                    return `L${li}: [ ${ids} ]${edges ? `\n    ${edges}` : ""}`;
                  })
                  .join("\n")}
              </pre>
            </div>
          ) : null}
          <ul className="details-stack">
            {steps.length === 0 ? <li className="muted">Geen stappen.</li> : null}
            {steps.map((step, index) => (
              <li key={step.id || index}>
                <strong>
                  {index + 1}. {step.id}
                </strong>{" "}
                <StatusBadge tone="neutral">{String(step.type || "action")}</StatusBadge>
                {step.action ? <span className="muted"> · {step.action}</span> : null}
                {step.depends_on && step.depends_on.length > 0 ? (
                  <div className="muted">depends_on: {step.depends_on.join(" → ")}</div>
                ) : (
                  <div className="muted">depends_on: (root)</div>
                )}
                {step.description || step.prompt ? (
                  <div className="muted">{String(step.description || step.prompt)}</div>
                ) : null}
              </li>
            ))}
          </ul>

          <div className="page-actions" style={{ marginTop: "0.85rem", flexWrap: "wrap" }}>
            <Button
              variant="secondary"
              disabled={!!busy}
              onClick={() =>
                void run("validate", async () => {
                  const result = await hadesApi.gen2ValidateWorkflow(selected.id);
                  setValidateResult(result);
                  if (result.valid) toast.success("Validatie OK");
                  else toast.error(`Validatie: ${result.errors.length} fout(en)`);
                })
              }
            >
              {busy === "validate" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Validate
            </Button>
            <Button
              variant="secondary"
              disabled={!!busy}
              onClick={() =>
                void run("dry-run", async () => {
                  const result = await hadesApi.gen2DryRunWorkflow(selected.id);
                  setLastRun({ ...result, mode: "dry_run" });
                  toast.message(
                    result.passed
                      ? "Dry-run geslaagd (geen live uitvoering)"
                      : "Dry-run niet geslaagd — geen live claim",
                  );
                })
              }
            >
              {busy === "dry-run" ? <Loader2 className="animate-spin" /> : <Play />} Dry-run ≠ live
            </Button>
            <Button
              disabled={!!busy}
              onClick={() =>
                void run("sandbox", async () => {
                  const result = await hadesApi.gen2SandboxRunWorkflow(selected.id);
                  setLastRun(result);
                  if (result.awaiting_human || String(result.status) === "awaiting_human") {
                    toast.message("Sandbox gepauzeerd — awaiting_human");
                  } else if (result.passed) {
                    toast.success("Sandbox-run geslaagd (niet product-ready)");
                  } else {
                    toast.error("Sandbox-run niet geslaagd");
                  }
                  setMetrics(await hadesApi.gen2WorkflowMetrics(selected.id));
                })
              }
            >
              {busy === "sandbox" ? <Loader2 className="animate-spin" /> : <Play />} Sandbox-run
            </Button>
            <Button
              disabled={!!busy}
              onClick={() =>
                void run("execute", async () => {
                  const accepted = await hadesApi.gen2ExecuteWorkflow(selected.id, {
                    async_mode: true,
                    blocking: false,
                  });
                  setLastRun({ ...accepted, mode: "product" });
                  const runId = String(accepted.run_id || "");
                  if (!runId) {
                    toast.error("Geen run_id van product execute");
                    return;
                  }
                  toast.message("Product-run geaccepteerd — poll status");
                  for (let i = 0; i < 90; i += 1) {
                    await new Promise((r) => setTimeout(r, 1000));
                    const snap = await hadesApi.gen2GetWorkflowRun(selected.id, runId);
                    const status = String(snap.status || "");
                    const result = {
                      ...(typeof snap.result === "object" && snap.result ? (snap.result as object) : {}),
                      run_id: runId,
                      workflow_id: selected.id,
                      status,
                      mode: "product",
                    } as Gen2WorkflowRunResult;
                    setLastRun(result);
                    if (["passed", "failed", "cancelled", "timeout", "awaiting_human"].includes(status)) {
                      if (status === "passed") toast.success("Product-run geslaagd");
                      else if (status === "awaiting_human") toast.message("Product-run wacht op human");
                      else toast.error(`Product-run: ${status}`);
                      break;
                    }
                  }
                  setMetrics(await hadesApi.gen2WorkflowMetrics(selected.id));
                })
              }
            >
              {busy === "execute" ? <Loader2 className="animate-spin" /> : <Play />} Execute (product)
            </Button>
            <label className="page-actions" style={{ gap: "0.35rem" }}>
              <input
                type="checkbox"
                checked={humanApproved}
                onChange={(e) => setHumanApproved(e.target.checked)}
              />
              <span className="muted">human_approved (vereist voor promoted)</span>
            </label>
            <Button
              disabled={!!busy}
              onClick={() =>
                void run("promote", async () => {
                  const updated = await hadesApi.gen2PromoteWorkflow(selected.id, {
                    human_approved: humanApproved,
                  });
                  setSelected(updated);
                  toast.success(`Status: ${updated.status}`);
                })
              }
            >
              {busy === "promote" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Promote
            </Button>
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() =>
                void run("export", async () => {
                  const pkg = await hadesApi.gen2ExportWorkflow(selected.id);
                  setExportJson(JSON.stringify(pkg, null, 2));
                  toast.success("Export JSON klaar");
                })
              }
            >
              {busy === "export" ? <Loader2 className="animate-spin" /> : <Download />} Export JSON
            </Button>
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() =>
                void run("metrics", async () => {
                  const metrics = await hadesApi.gen2WorkflowMetrics(selected.id);
                  setMetrics(metrics);
                  const runCount = Array.isArray(metrics.runs) ? metrics.runs.length : 0;
                  const metricKeys = Object.keys((metrics.metrics as Record<string, unknown>) || {}).length;
                  if (runCount > 0 || metricKeys > 0) {
                    toast.success(`Metrics vernieuwd (${runCount} runs)`);
                  } else {
                    toast.message("Geen workflow runs/metrics");
                  }
                })
              }
            >
              Metrics
            </Button>
            <Button
              variant="secondary"
              disabled={!!busy || selected.status !== "promoted"}
              onClick={() =>
                void run("to-skill", async () => {
                  const result = await hadesApi.gen2WorkflowToSkill(selected.id);
                  const skillId = String(
                    (result as { skill?: { id?: string }; id?: string; skill_id?: string }).skill?.id ||
                      (result as { skill_id?: string }).skill_id ||
                      (result as { id?: string }).id ||
                      "",
                  );
                  if (skillId) toast.success(`Skill candidate: ${skillId}`);
                  else toast.error("Workflow→skill bridge leverde geen skill id op.");
                })
              }
            >
              {busy === "to-skill" ? <Loader2 className="animate-spin" /> : <Sparkles />} → Skill candidate
            </Button>
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() =>
                void run("archive", async () => {
                  await hadesApi.gen2ArchiveWorkflow(selected.id);
                  setSelected(null);
                  toast.success("Workflow gearchiveerd");
                })
              }
            >
              {busy === "archive" ? <Loader2 className="animate-spin" /> : <Archive />} Archive
            </Button>
          </div>

          {validateResult ? (
            <div style={{ marginTop: "0.75rem" }}>
              <StatusBadge tone={validateResult.valid ? "success" : "danger"}>
                {validateResult.valid ? "valid" : "invalid"}
              </StatusBadge>
              {!validateResult.valid ? (
                <ul className="details-stack">
                  {validateResult.errors.map((err) => (
                    <li key={err} className="muted">
                      {err}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {lastRun ? (
            <Panel title="Laatste run" eyebrow={String(lastRun.mode || lastRun.status || "run")} className="mt-panel">
              <div className="page-actions">
                <StatusBadge tone={toneForStatus(String(lastRun.status || (lastRun.passed ? "passed" : "failed")))}>
                  {String(lastRun.status || (lastRun.passed ? "passed" : "failed"))}
                </StatusBadge>
                {lastRun.mode === "dry_run" || lastRun.mode === "dry-run" ? (
                  <span className="muted">Dry-run is geen live uitvoering.</span>
                ) : null}
                {lastRun.run_id ? <span className="muted">run: {lastRun.run_id}</span> : null}
              </div>
              {lastRun.note ? <p className="panel-copy">{String(lastRun.note)}</p> : null}
            </Panel>
          ) : null}

          {awaitingStepId ? (
            <Panel title="Human-in-the-loop" eyebrow="awaiting_human">
              <p className="panel-copy">{awaiting?.prompt || `Beslis over stap ${awaitingStepId}`}</p>
              <div className="form-stack">
                <label className="muted" htmlFor="hitl-decision">
                  Decision ({String(awaiting?.type || "approve")})
                </label>
                {Array.isArray(awaiting?.choices) && awaiting!.choices!.length > 0 ? (
                  <select
                    id="hitl-decision"
                    value={hitlValue || awaiting!.choices![0]}
                    onChange={(e) => {
                      setHitlValue(e.target.value);
                      setHitlDecision(e.target.value);
                    }}
                    style={{ width: "100%", padding: "0.45rem 0.6rem" }}
                  >
                    {awaiting!.choices!.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                ) : (
                  <>
                    <select
                      id="hitl-decision"
                      value={hitlDecision}
                      onChange={(e) => setHitlDecision(e.target.value)}
                      style={{ width: "100%", padding: "0.45rem 0.6rem" }}
                    >
                      <option value="approve">approve</option>
                      <option value="reject">reject</option>
                    </select>
                    <Input
                      value={hitlValue}
                      onChange={(e) => setHitlValue(e.target.value)}
                      placeholder="Optionele value / secret"
                    />
                  </>
                )}
                <Button
                  disabled={!!busy}
                  onClick={() =>
                    void run("hitl", async () => {
                      const result = await hadesApi.gen2DecideWorkflowHuman(selected.id, awaitingStepId, {
                        decision: hitlDecision,
                        value: hitlValue || undefined,
                        resume: true,
                      });
                      setLastRun(result);
                      const hitlStatus = String(result.status || "");
                      const resume = (result as { resume?: { passed?: boolean; status?: string; error?: string } }).resume;
                      const resumeFailed =
                        resume != null &&
                        (resume.passed === false ||
                          ["failed", "blocked", "error"].includes(String(resume.status || "").toLowerCase()) ||
                          Boolean(resume.error));
                      if (hitlStatus === "failed" || hitlDecision === "reject" || resumeFailed) {
                        toast.error(
                          resumeFailed
                            ? `HITL resume mislukt: ${resume?.error || resume?.status || "failed"}`
                            : `HITL: ${hitlStatus || "afgewezen"}`,
                        );
                      } else {
                        toast.success(`HITL: ${hitlStatus || "besloten"}`);
                      }
                      setSelected(await hadesApi.gen2GetWorkflow(selected.id));
                    })
                  }
                >
                  {busy === "hitl" ? <Loader2 className="animate-spin" /> : <Check />} Decide
                </Button>
              </div>
            </Panel>
          ) : null}

          {metrics ? (
            <Panel title="Metrics" eyebrow={metrics.workflow_id}>
              <ul className="details-stack">
                {Object.entries(metrics.metrics || {}).map(([key, value]) => (
                  <li key={key}>
                    <strong>{key}</strong>: {typeof value === "object" ? JSON.stringify(value) : String(value)}
                  </li>
                ))}
              </ul>
              {(metrics.runs || []).length > 0 ? (
                <>
                  <h3>Recente runs</h3>
                  <ul className="details-stack">
                    {(metrics.runs || []).slice(0, 8).map((runRow) => (
                      <li key={String(runRow.id || JSON.stringify(runRow))}>
                        <StatusBadge tone={toneForStatus(String(runRow.status || ""))}>
                          {String(runRow.status || "—")}
                        </StatusBadge>{" "}
                        <span className="muted">
                          {String(runRow.mode || "")} · {String(runRow.id || "").slice(0, 12)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </Panel>
          ) : null}

          {revisions && revisions.length > 0 ? (
            <Panel title="Revisions" eyebrow="version history">
              <ul className="details-stack">
                {revisions.slice(0, 12).map((rev) => (
                  <li key={String(rev.id || rev.version)}>
                    <strong>v{String(rev.version)}</strong>
                    <span className="muted">
                      {" "}
                      · {String(rev.note || rev.created_at || "")}
                    </span>
                  </li>
                ))}
              </ul>
              {revisions.length >= 2 ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!!busy}
                  onClick={() =>
                    void run("diff-rev", async () => {
                      const from = Number(revisions[revisions.length - 1]?.version);
                      const to = Number(revisions[0]?.version);
                      if (!Number.isFinite(from) || !Number.isFinite(to)) {
                        toast.message("Geen vergelijkbare versies");
                        return;
                      }
                      setRevisionDiff(
                        await hadesApi.gen2DiffWorkflowRevisions(selected.id, from, to),
                      );
                      toast.success(`Diff v${from} → v${to}`);
                    })
                  }
                >
                  Diff oudste↔nieuwste
                </Button>
              ) : null}
              {revisionDiff ? (
                <div className="code-block" style={{ marginTop: "0.6rem" }}>
                  <pre>{JSON.stringify(revisionDiff, null, 2)}</pre>
                </div>
              ) : null}
            </Panel>
          ) : null}

          {exportJson ? (
            <Panel title="Export" eyebrow="HadesWorkflow JSON">
              <Textarea readOnly value={exportJson} rows={12} />
            </Panel>
          ) : null}
        </Panel>
      ) : null}
    </div>
  );
}
