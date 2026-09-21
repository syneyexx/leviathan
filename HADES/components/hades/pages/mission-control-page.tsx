"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Pause, Play, RefreshCcw, RotateCcw, ShieldCheck, ShieldX, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, StatCard, StatusBadge } from "@/components/hades/ui";
import { ProjectContinuityPanel } from "@/components/hades/features/project-continuity-panel";
import {
  type Gen2CapabilityStatus,
  type Gen2CommitteeSession,
  type Gen2EvalRun,
  type Gen2Mission,
  type Gen2MissionBudgetLedger,
  type Gen2MissionPortfolio,
  type Gen2MissionRevision,
  hadesApi,
} from "@/lib/hades-api";

type Dash = Awaited<ReturnType<typeof hadesApi.gen2Dashboard>>;

function toneForStatus(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["completed", "compiled", "ready", "benchmarked", "promoted", "approved"].includes(status)) return "success";
  if (["failed", "blocked", "cancelled", "rejected"].includes(status)) return "danger";
  if (["running", "queued", "awaiting_approval", "paused", "candidate"].includes(status)) return "warning";
  return "neutral";
}

function capabilityLabel(row: Gen2CapabilityStatus | undefined): string {
  if (!row) return "onbekend";
  if (row.unverified_on_host) return "UNVERIFIED_ON_HOST";
  if (row.blocked) return "blocked";
  if (row.degraded) return "degraded";
  if (row.quality_evaluated) return "kwaliteit gemeten";
  if (row.operationally_tested) return "operationeel getest";
  if (row.simulated) return "simulated (niet host-proof)";
  if (row.available_on_host) return "beschikbaar";
  if (row.implemented) return "geïmplementeerd (niet operationeel bewezen)";
  return "niet beschikbaar";
}

function capabilityTone(row: Gen2CapabilityStatus | undefined): "success" | "warning" | "danger" | "neutral" {
  if (!row) return "neutral";
  if (row.unverified_on_host || row.simulated || row.degraded) return "warning";
  if (row.blocked) return "danger";
  if (row.quality_evaluated || row.operationally_tested) return "success";
  if (row.implemented) return "neutral";
  return "danger";
}

const SAMPLE_FIXTURE_WORKFLOW = [
  { action: "set_ctx_flag", inputs: { flag: "prepared" } },
  { action: "check_ctx_flag", inputs: { flag: "prepared" } },
  {
    action: "record_artifact",
    inputs: { name: "brief.txt", content: "sample fixture artifact (not production proof)" },
    success_criteria: ["output:artifact"],
  },
];

const SAMPLE_FINANCE_ARTICLE = {
  title: "Sample company announces product update",
  summary: "Fixture article for offline Mission Control demos — not live market data.",
  source: "sample-fixture",
  source_count: 1,
};

export function MissionControlPage() {
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [goal, setGoal] = useState("");
  const [mission, setMission] = useState<Gen2Mission | null>(null);
  const [budget, setBudget] = useState<Gen2MissionBudgetLedger | null>(null);
  const [committeeTopic, setCommitteeTopic] = useState("");
  const [committeeEvidence, setCommitteeEvidence] = useState("");
  const [committeeMode, setCommitteeMode] = useState<"heuristic" | "live">("heuristic");
  const [committee, setCommittee] = useState<Gen2CommitteeSession | null>(null);
  const [evalSummary, setEvalSummary] = useState<Gen2EvalRun["summary"] | null>(null);
  const [evalMode, setEvalMode] = useState<
    "deterministic_software" | "quality_suite" | "live_model" | "dev_partner_software" | "dev_partner_baseline"
  >("deterministic_software");
  const [evalSuite, setEvalSuite] = useState<
    "reasoning" | "quality" | "red_team" | "generalization" | "dev_partner_v1"
  >("reasoning");
  const [humanRating, setHumanRating] = useState<
    "directly_usable" | "usable_after_small_correction" | "needs_major_correction" | "unusable"
  >("directly_usable");
  const [humanNotes, setHumanNotes] = useState("");
  const [humanSeconds, setHumanSeconds] = useState("");
  const [humanTrends, setHumanTrends] = useState<Record<string, unknown> | null>(null);
  const [evalMatrix, setEvalMatrix] = useState<{
    rows: Array<Record<string, unknown>>;
    by_model: Array<Record<string, unknown>>;
  } | null>(null);
  const [evalFlaky, setEvalFlaky] = useState<Record<string, unknown> | null>(null);
  const [prHelpRunA, setPrHelpRunA] = useState("");
  const [prHelpRunB, setPrHelpRunB] = useState("");
  const [prHelp, setPrHelp] = useState<Record<string, unknown> | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsConnected, setModelsConnected] = useState(false);
  const [financeSymbol, setFinanceSymbol] = useState("");
  const [fuseResult, setFuseResult] = useState<Record<string, unknown> | null>(null);
  const [skillName, setSkillName] = useState("");
  const [skill, setSkill] = useState<Record<string, unknown> | null>(null);
  const [knowledgeHits, setKnowledgeHits] = useState<string[]>([]);
  const [showSampleFixtures, setShowSampleFixtures] = useState(false);

  // Flight Recorder
  const [flightRunId, setFlightRunId] = useState("");
  const [flightCompareA, setFlightCompareA] = useState("");
  const [flightCompareB, setFlightCompareB] = useState("");
  const [flightEvents, setFlightEvents] = useState<Array<Record<string, unknown>> | null>(null);
  const [flightCompare, setFlightCompare] = useState<Record<string, unknown> | null>(null);
  const [flightAudit, setFlightAudit] = useState<Record<string, unknown> | null>(null);
  const [flightReplay, setFlightReplay] = useState<Record<string, unknown> | null>(null);

  // Context Compiler preview
  const [ctxGoal, setCtxGoal] = useState("");
  const [ctxItemsText, setCtxItemsText] = useState(
    '[{"item_id":"a","kind":"knowledge","content":"Relevant fact about the goal.","source":"sample"},{"item_id":"b","kind":"noise","content":"Unrelated filler text.","source":"sample"}]',
  );
  const [ctxPack, setCtxPack] = useState<Record<string, unknown> | null>(null);

  // Sandbox profiles
  const [sandboxProfiles, setSandboxProfiles] = useState<Array<Record<string, unknown>> | null>(null);
  const [sandboxProfileId, setSandboxProfileId] = useState("strict");
  const [sandboxPluginId, setSandboxPluginId] = useState("");
  const [sandboxApplied, setSandboxApplied] = useState<Record<string, unknown> | null>(null);
  const [sandboxHostCaps, setSandboxHostCaps] = useState<Record<string, unknown> | null>(null);
  const [jitCapability, setJitCapability] = useState("network");
  const [jitReason, setJitReason] = useState("");
  const [jitGrants, setJitGrants] = useState<Array<Record<string, unknown>> | null>(null);
  const [jitUx, setJitUx] = useState<Record<string, unknown> | null>(null);

  // Temporal graph
  const [graphSource, setGraphSource] = useState("");
  const [graphTarget, setGraphTarget] = useState("");
  const [graphRelation, setGraphRelation] = useState("related_to");
  const [graphEntity, setGraphEntity] = useState("");
  const [graphAsOf, setGraphAsOf] = useState("");
  const [graphAnaloguesText, setGraphAnaloguesText] = useState("");
  const [graphEdgeResult, setGraphEdgeResult] = useState<Record<string, unknown> | null>(null);
  const [graphAsOfResult, setGraphAsOfResult] = useState<Record<string, unknown> | null>(null);
  const [graphAnalogues, setGraphAnalogues] = useState<Record<string, unknown> | null>(null);
  const [graphContradictions, setGraphContradictions] = useState<Array<Record<string, unknown>> | null>(
    null,
  );

  // Compute
  const [computeNodes, setComputeNodes] = useState<Array<Record<string, unknown>> | null>(null);
  const [computeStatus, setComputeStatus] = useState<Record<string, unknown> | null>(null);
  const [computeJob, setComputeJob] = useState<Record<string, unknown> | null>(null);
  const [computeUnknownOp, setComputeUnknownOp] = useState("shell_exec");

  // Mission acceptance / replan (API depth surfaced in UI)
  const [acceptanceResult, setAcceptanceResult] = useState<Record<string, unknown> | null>(null);
  const [replanCause, setReplanCause] = useState<
    "tool" | "model" | "verification" | "budget" | "permission" | "schema"
  >("tool");
  const [replanNote, setReplanNote] = useState("");
  const [portfolio, setPortfolio] = useState<Gen2MissionPortfolio | null>(null);
  const [portfolioStatus, setPortfolioStatus] = useState("");
  const [missionRevisions, setMissionRevisions] = useState<Gen2MissionRevision[] | null>(null);
  const [missionDiff, setMissionDiff] = useState<Record<string, unknown> | null>(null);

  // Eval extras: catalog / reports / A-B / ingest
  const [evalCatalog, setEvalCatalog] = useState<Record<string, unknown> | null>(null);
  const [evalReports, setEvalReports] = useState<Gen2EvalRun[] | null>(null);
  const [evalAbStrategyA, setEvalAbStrategyA] = useState("baseline");
  const [evalAbStrategyB, setEvalAbStrategyB] = useState("variant");
  const [evalAbResult, setEvalAbResult] = useState<Record<string, unknown> | null>(null);
  const [evalIngestRunId, setEvalIngestRunId] = useState("");
  const [evalIngestResult, setEvalIngestResult] = useState<Record<string, unknown> | null>(null);

  // Factory extract-from-run
  const [extractFromRunId, setExtractFromRunId] = useState("");
  const [extractFromRun, setExtractFromRun] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await hadesApi.gen2Dashboard();
      setDash(next);
      if (mission?.id) {
        const fresh = next.missions.find((m) => m.id === mission.id);
        if (fresh) setMission(fresh);
      }
      try {
        const port = await hadesApi.gen2MissionPortfolio(
          portfolioStatus.trim() ? { status: portfolioStatus.trim() } : undefined,
        );
        setPortfolio(port);
      } catch {
        /* portfolio optional if older backend */
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Gen2 dashboard laden mislukt");
    } finally {
      setLoading(false);
    }
  }, [mission?.id, portfolioStatus]);

  const loadModels = useCallback(async () => {
    try {
      const models = await hadesApi.models();
      setModelsConnected(Boolean(models.connected));
      const ids = (models.models || []).map((m) => m.id).filter(Boolean);
      setAvailableModels(ids);
      if (!selectedModelId && (models.active_profile?.model_id || ids[0])) {
        setSelectedModelId(models.active_profile?.model_id || ids[0] || "");
      }
    } catch {
      setModelsConnected(false);
      setAvailableModels([]);
    }
  }, [selectedModelId]);

  useEffect(() => {
    void refresh();
    void loadModels();
  }, [refresh, loadModels]);

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

  async function selectMission(id: string) {
    setBusy("select");
    try {
      const detail = await hadesApi.gen2GetMission(id);
      setMission(detail);
      try {
        setBudget(await hadesApi.gen2MissionBudgets(id));
      } catch {
        setBudget(null);
      }
      try {
        const revs = await hadesApi.gen2ListMissionRevisions(id, 20);
        setMissionRevisions(revs);
        setMissionDiff(null);
        if (revs.length >= 2) {
          const versions = [...revs].map((r) => r.version).sort((a, b) => a - b);
          setMissionDiff(
            await hadesApi.gen2DiffMissionRevisions(id, versions[0], versions[versions.length - 1]),
          );
        }
      } catch {
        setMissionRevisions(null);
        setMissionDiff(null);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Missie laden mislukt");
    } finally {
      setBusy("");
    }
  }

  async function loadKnowledgeEvidence() {
    setBusy("knowledge");
    try {
      const query = committeeTopic.trim() || goal.trim() || "evidence";
      const searched = await hadesApi.searchKnowledge(query, 8);
      const lines = (searched.matches || [])
        .map((m) => `${m.title}: ${(m.content || "").slice(0, 180)}`.trim())
        .filter((line) => line.length > 3);
      if (!lines.length) {
        const pack = await hadesApi.exportKnowledgePack(8);
        const fallback = [
          ...(pack.knowledge_sources || []).map((s) => `${s.title || s.id}: ${s.uri || s.source_type}`),
          ...((pack.evidence || []) as Array<Record<string, unknown>>).map(
            (e) => `${String(e.title || e.id || "evidence")}: ${String(e.content || e.text || "").slice(0, 180)}`,
          ),
        ].filter((line) => line.length > 3);
        setKnowledgeHits(fallback.slice(0, 8));
        if (!fallback.length) toast.message("Geen lokale Knowledge/Evidence gevonden");
        else {
          setCommitteeEvidence(fallback.join("\n"));
          toast.success(`${fallback.length} bronnen geladen`);
        }
      } else {
        setKnowledgeHits(lines.slice(0, 8));
        setCommitteeEvidence(lines.join("\n"));
        toast.success(`${lines.length} bronnen geladen`);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Knowledge laden mislukt");
    } finally {
      setBusy("");
    }
  }

  async function fuseFromKnowledge() {
    setBusy("fuse");
    try {
      const query = financeSymbol.trim() || goal.trim() || "market OR earnings OR product";
      const searched = await hadesApi.searchKnowledge(query, 12);
      const articles = (searched.matches || [])
        .map((m) => ({
          title: String(m.title || "").trim(),
          summary: String(m.content || "").slice(0, 800),
          source: String(m.source_id || m.chunk_id || "knowledge"),
          uri: String((m as { uri?: string }).uri || ""),
          source_count: 1,
        }))
        .filter((a) => a.title.length > 0);
      if (!articles.length) {
        toast.message("Geen Knowledge/Evidence om te fuseren — ingest nieuws eerst, of gebruik sample fixture.");
        setFuseResult({ events: [], count: 0, note: "no_articles_to_fuse" });
        return;
      }
      const result = await hadesApi.gen2FuseFinance({
        symbol: financeSymbol.trim() || undefined,
        articles,
      });
      setFuseResult(result);
      const fuseCount = Number((result as { count?: number }).count ?? 0);
      if ((result as { ok?: boolean }).ok === false || fuseCount <= 0) {
        toast.message(
          String((result as { note?: string; error?: string }).error
            || (result as { note?: string }).note
            || "Fusie leverde 0 events"),
        );
      } else {
        toast.success(`Fusie: ${fuseCount} events`);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Finance fuse mislukt");
    } finally {
      setBusy("");
      await refresh();
    }
  }

  function workflowFromMission(source: Gen2Mission): Array<{
    action: string;
    inputs?: Record<string, unknown>;
    success_criteria?: string[];
    description?: string;
  }> {
    const subtasks = Array.isArray(source.ir?.subtasks)
      ? (source.ir?.subtasks as Array<Record<string, unknown>>)
      : [];
    const waveSteps =
      subtasks.length > 0
        ? subtasks
        : (source.ir?.execution_waves || []).flatMap((wave) =>
            (wave.steps || []).map((step) => step as Record<string, unknown>),
          );
    if (!waveSteps.length) {
      return [
        { action: "set_ctx_flag", inputs: { flag: "mission_compiled" } },
        { action: "check_ctx_flag", inputs: { flag: "mission_compiled" } },
        {
          action: "record_artifact",
          inputs: {
            name: "mission-goal.txt",
            content: String(source.goal || source.title || source.id),
          },
          success_criteria: ["output:artifact"],
          description: "Persisted mission goal as skill artifact",
        },
      ];
    }
    const workflow: Array<{
      action: string;
      inputs?: Record<string, unknown>;
      success_criteria?: string[];
      description?: string;
    }> = [
      { action: "set_ctx_flag", inputs: { flag: "trace_ready" } },
      { action: "check_ctx_flag", inputs: { flag: "trace_ready" } },
    ];
    for (const step of waveSteps.slice(0, 6)) {
      workflow.push({
        action: "record_artifact",
        inputs: {
          name: `${String(step.id || "step")}.txt`,
          content: `${String(step.title || step.id)}\nagent=${String(step.agent || "")}\n${String(step.instruction || step.title || "").slice(0, 500)}`,
        },
        success_criteria: ["output:artifact"],
        description: String(step.title || step.id || "mission-step"),
      });
    }
    return workflow;
  }

  async function extractSkillFromMissionTrace() {
    if (!mission?.id) {
      toast.message("Selecteer of compileer eerst een missie met bewezen stappen.");
      return;
    }
    setBusy("skill");
    try {
      const name =
        skillName.trim() ||
        String(mission.title || mission.goal || "mission-skill")
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "")
          .slice(0, 48) ||
        "mission-skill";
      const candidate = await hadesApi.gen2ExtractSkill({
        name,
        workflow: workflowFromMission(mission),
        pattern_source: `mission:${mission.id}`,
        tools: Array.isArray(mission.ir?.plugins_tools) ? (mission.ir?.plugins_tools as string[]) : [],
      });
      setSkill(candidate);
      setSkillName(name);
      toast.success("Skill-kandidaat uit missietrace");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Skill extractie mislukt");
    } finally {
      setBusy("");
      await refresh();
    }
  }

  const capabilityEntries = useMemo(
    () => Object.entries(dash?.capability_status || {}),
    [dash?.capability_status],
  );
  const implementedCount = capabilityEntries.filter(([, v]) => v.implemented).length;
  const testedCount = capabilityEntries.filter(([, v]) => v.operationally_tested).length;
  const qualityCount = capabilityEntries.filter(([, v]) => v.quality_evaluated).length;
  const waves = mission?.ir?.execution_waves || [];
  const pendingGate = (mission?.gates || []).find((g) => g.required && g.status !== "approved" && g.status !== "rejected");
  const canPause = ["running", "queued", "ready", "awaiting_approval"].includes(String(mission?.status || ""));
  const canResume = ["paused", "blocked", "awaiting_approval", "ready"].includes(String(mission?.status || ""));
  const canRetry = ["failed", "cancelled", "completed"].includes(String(mission?.status || ""));

  return (
    <div className="details-stack">
      <PageHeader
        title="Mission Control"
        description="Missies besturen, evalueren en delibereren — met eerlijke readiness en bewaard werk."
        actions={
          <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Vernieuwen
          </Button>
        }
      />

      <div className="stat-grid four">
        <StatCard label="Geïmplementeerd" value={`${implementedCount}/10`} note="code aanwezig" />
        <StatCard label="Getest op host" value={`${testedCount}/10`} note="operationeel bewijs" />
        <StatCard label="Kwaliteit gemeten" value={`${qualityCount}/10`} note="live quality samples" />
        <StatCard label="Missions" value={String(dash?.missions?.length ?? 0)} note="opgeslagen" />
      </div>

      <ProjectContinuityPanel />

      <Panel title="Systeemgereedheid" eyebrow="Eerlijk · E9/E10">
        <p className="panel-copy">
          {dash?.readiness_note ||
            "Onderscheid geïmplementeerd / beschikbaar / getest / kwaliteitsmatig geëvalueerd. Geen fake PASS."}
        </p>
        <div className="page-actions" style={{ marginBottom: "0.5rem", flexWrap: "wrap" }}>
          {dash?.live_model_quality_seen ? (
            <StatusBadge tone="success">live model quality seen</StatusBadge>
          ) : (
            <StatusBadge tone="warning">live model quality: incomplete</StatusBadge>
          )}
          {dash?.live_model_smoke_seen ? (
            <StatusBadge tone="neutral">live smoke seen</StatusBadge>
          ) : (
            <StatusBadge tone="warning">live smoke: not seen</StatusBadge>
          )}
          <StatusBadge tone="warning">multi-machine compute: UNVERIFIED_ON_HOST</StatusBadge>
          <StatusBadge tone="warning">Windows Job Object isolation: UNVERIFIED_ON_HOST</StatusBadge>
        </div>
        <ul className="details-stack">
          {capabilityEntries.map(([key, row]) => (
            <li key={key} className="page-actions" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <span>
                <strong>{key}</strong>
                {row.note ? <span className="muted"> · {row.note}</span> : null}
              </span>
              <StatusBadge tone={capabilityTone(row)}>{capabilityLabel(row)}</StatusBadge>
            </li>
          ))}
        </ul>
        <p className="muted" style={{ marginTop: "0.6rem" }}>
          Threat model: <code>docs/THREAT_MODEL_GEN2.md</code> · Release gates:{" "}
          <code>docs/TESTING_RELEASE_GATES.md</code>
        </p>
      </Panel>

      <div className="form-grid two">
        <Panel title="Opgeslagen missies" eyebrow="Werkplek">
          <ul className="details-stack">
            {(dash?.missions || []).length === 0 ? <li className="muted">Nog geen missies opgeslagen.</li> : null}
            {(dash?.missions || []).map((item) => (
              <li key={item.id} className="page-actions" style={{ justifyContent: "space-between" }}>
                <button
                  type="button"
                  className="linkish"
                  aria-label={`Open missie ${item.title || item.goal || item.id}`}
                  onClick={() => void selectMission(item.id)}
                  style={{ textAlign: "left", background: "none", border: 0, cursor: "pointer", color: "inherit" }}
                >
                  <strong>{item.title || item.goal || item.id}</strong>
                  <div className="muted">{item.id.slice(0, 12)}… · {item.updated_at || item.created_at || ""}</div>
                </button>
                <StatusBadge tone={toneForStatus(String(item.status))}>{String(item.status)}</StatusBadge>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Nieuwe missie" eyebrow="Compiler">
          <p className="panel-copy">Compileert een einddoel naar een typed mission DAG met waves, gates, budgets en verification.</p>
          <div className="form-stack">
            <Textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={3}
              aria-label="Missiedoel voor compiler"
              placeholder="Beschrijf een generiek doel (bijv. onderzoek X, plan Y, audit Z)…"
            />
            <div className="page-actions">
              <Button
                disabled={!!busy || !goal.trim()}
                aria-label="Compileer missie"
                onClick={() =>
                  void run("mission", async () => {
                    const compiled = await hadesApi.gen2CompileMission({ goal: goal.trim() });
                    setMission(compiled);
                    setBudget(null);
                    toast.success("Missie gecompileerd");
                  })
                }
              >
                {busy === "mission" ? <Loader2 className="animate-spin" /> : <Sparkles />} Compileer missie
              </Button>
              {mission?.id ? (
                <Button
                  variant="secondary"
                  disabled={!!busy}
                  aria-label="Start missie"
                  onClick={() =>
                    void run("start", async () => {
                      const started = await hadesApi.gen2StartMission(mission.id);
                      setMission(started);
                      toast.message(String(started.status));
                    })
                  }
                >
                  {busy === "start" ? <Loader2 className="animate-spin" /> : <Play />} Start
                </Button>
              ) : null}
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="Missieportfolio" eyebrow="B1.5">
        <p className="panel-copy">
          Overzicht van missies met status, domain, budgets en gates — filterbaar op status.
        </p>
        <div className="page-actions" style={{ marginBottom: "0.6rem", flexWrap: "wrap" }}>
          <Input
            value={portfolioStatus}
            onChange={(e) => setPortfolioStatus(e.target.value)}
            placeholder="Filter status (compiled/ready/running/…)"
            aria-label="Filter missieportfolio op status"
            style={{ maxWidth: "16rem" }}
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={!!busy}
            aria-label="Laad missieportfolio"
            onClick={() =>
              void run("portfolio", async () => {
                const port = await hadesApi.gen2MissionPortfolio(
                  portfolioStatus.trim() ? { status: portfolioStatus.trim() } : undefined,
                );
                setPortfolio(port);
                toast.message(`${port.count} missie(s) in portfolio`);
              })
            }
          >
            {busy === "portfolio" ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Laad portfolio
          </Button>
        </div>
        {portfolio ? (
          <>
            <p className="muted">
              count={portfolio.count}
              {portfolio.by_status
                ? ` · by_status=${Object.entries(portfolio.by_status)
                    .map(([k, v]) => `${k}:${v}`)
                    .join(", ")}`
                : ""}
              {portfolio.by_domain
                ? ` · by_domain=${Object.entries(portfolio.by_domain)
                    .map(([k, v]) => `${k}:${v}`)
                    .join(", ")}`
                : ""}
            </p>
            <ul className="details-stack">
              {portfolio.missions.length === 0 ? <li className="muted">Geen missies voor dit filter.</li> : null}
              {portfolio.missions.map((item) => (
                <li key={item.id} className="page-actions" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="linkish"
                    aria-label={`Open portfolio-missie ${item.title || item.goal || item.id}`}
                    onClick={() => void selectMission(item.id)}
                    style={{ textAlign: "left", background: "none", border: 0, cursor: "pointer", color: "inherit" }}
                  >
                    <strong>{item.title || item.goal || item.id}</strong>
                    <div className="muted">
                      {item.domain || "?"} · gates pending=
                      {String((item.gates_summary as { pending_required?: number } | undefined)?.pending_required ?? "?")}
                      {item.blocked_or_waiting ? " · blocked/waiting" : ""}
                    </div>
                  </button>
                  <StatusBadge tone={toneForStatus(String(item.status))}>{String(item.status)}</StatusBadge>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">Nog geen portfolio geladen.</p>
        )}
      </Panel>

      {mission ? (
        <Panel title="Missiedetail" eyebrow={mission.id}>
          <div className="page-actions" style={{ marginBottom: "0.6rem" }}>
            <StatusBadge tone={toneForStatus(String(mission.status))}>{String(mission.status)}</StatusBadge>
            {mission.task_id ? <span className="muted">Work-taak: {mission.task_id}</span> : <span className="muted">Nog geen Work-taak</span>}
            {mission.execution_id ? <span className="muted">exec: {mission.execution_id}</span> : null}
            {(mission as { confirmed_outcome?: { status?: string; confirmed?: boolean; source?: string } }).confirmed_outcome ? (
              <span className="muted">
                Bevestigde uitkomst: {String((mission as { confirmed_outcome?: { status?: string } }).confirmed_outcome?.status)}
                {(mission as { confirmed_outcome?: { confirmed?: boolean } }).confirmed_outcome?.confirmed ? " (confirmed)" : " (unconfirmed)"}
                {" · "}
                {String((mission as { confirmed_outcome?: { source?: string } }).confirmed_outcome?.source || "")}
              </span>
            ) : null}
          </div>
          <p className="panel-copy"><strong>Doel:</strong> {mission.goal || mission.title}</p>
          <div className="form-grid two">
            <div>
              <h4>Acceptatiecriteria</h4>
              <ul>
                {(mission.acceptance_criteria || []).map((c, idx) => {
                  const label =
                    typeof c === "string"
                      ? c
                      : `${String(c.type || "check")}: ${String(
                          c.name || c.expected || c.step_id || c.id || "check",
                        )}`;
                  return (
                    <li key={typeof c === "string" ? c : String(c.id || idx)}>{label}</li>
                  );
                })}
              </ul>
              <h4>Verificatie</h4>
              <p className="muted">
                status={String(mission.verification?.status || "unknown")} · required=
                {String(Boolean(mission.verification?.required))}
              </p>
              {mission.error ? <p className="muted">Blokkade: {mission.error}</p> : null}
            </div>
            <div>
              <h4>Wachten / gate</h4>
              {pendingGate ? (
                <p>
                  Gate <strong>{pendingGate.id}</strong> ({pendingGate.label || "approval"}) — {pendingGate.status}
                </p>
              ) : (
                <p className="muted">Geen openstaande startgate.</p>
              )}
              <h4>Budgetledger</h4>
              {budget ? (
                <div className="code-block"><pre>{JSON.stringify(budget.ledger, null, 2)}</pre></div>
              ) : (
                <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void selectMission(mission.id)}>
                  Laad budget
                </Button>
              )}
            </div>
          </div>

          <h4 style={{ marginTop: "0.8rem" }}>Stappen / afhankelijkheden</h4>
          <div className="code-block"><pre>{JSON.stringify(waves, null, 2)}</pre></div>

          {mission.links ? (
            <>
              <h4 style={{ marginTop: "0.8rem" }}>Identity links (B1.8)</h4>
              <p className="muted">
                mission={String(mission.links.mission_id || mission.id)} · task=
                {String(mission.links.task_id || "—")} · run={String(mission.links.run_id || "—")} · steps=
                {String((mission.links.step_ids || []).length)} · artifacts=
                {String((mission.links.artifacts || []).length)}
              </p>
            </>
          ) : null}

          {missionRevisions && missionRevisions.length > 0 ? (
            <>
              <h4 style={{ marginTop: "0.8rem" }}>Revisies / diff (B1.6)</h4>
              <ul className="details-stack">
                {missionRevisions.slice(0, 8).map((rev) => (
                  <li key={rev.id} className="muted">
                    v{rev.version} · {rev.cause || "snapshot"} · {rev.created_at || ""}
                  </li>
                ))}
              </ul>
              {missionDiff ? (
                <div className="code-block">
                  <pre>{JSON.stringify(missionDiff, null, 2)}</pre>
                </div>
              ) : null}
            </>
          ) : null}

          <h4 style={{ marginTop: "0.8rem" }}>Acceptance evaluate · bounded replan</h4>
          <p className="muted">
            Evalueert executable checks (API). Replan telt mee tegen max_replans — veroorzaakt geen nieuwe DAG-body.
          </p>
          <div className="page-actions" style={{ marginBottom: "0.5rem", flexWrap: "wrap" }}>
            <Button
              size="sm"
              variant="secondary"
              disabled={!!busy}
              onClick={() =>
                void run("accept-eval", async () => {
                  const result = await hadesApi.gen2EvaluateMissionAcceptance(mission.id);
                  setAcceptanceResult(result);
                  const ok = Boolean(result.passed ?? result.all_passed ?? result.ok);
                  toast.message(
                    ok
                      ? "Acceptance: checks passed (API-confirmed)"
                      : `Acceptance: incomplete/failed — ${String(result.summary || result.status || "see detail")}`,
                  );
                })
              }
            >
              {busy === "accept-eval" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Evaluate acceptance
            </Button>
            <select
              value={replanCause}
              onChange={(e) => setReplanCause(e.target.value as typeof replanCause)}
              className="input"
              style={{ maxWidth: "11rem" }}
            >
              <option value="tool">cause: tool</option>
              <option value="model">cause: model</option>
              <option value="verification">cause: verification</option>
              <option value="budget">cause: budget</option>
              <option value="permission">cause: permission</option>
              <option value="schema">cause: schema</option>
            </select>
            <Input
              value={replanNote}
              onChange={(e) => setReplanNote(e.target.value)}
              placeholder="replan note (optioneel)"
              style={{ maxWidth: "14rem" }}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={!!busy}
              onClick={() =>
                void run("replan", async () => {
                  const next = await hadesApi.gen2ReplanMission(mission.id, {
                    cause: replanCause,
                    note: replanNote.trim() || undefined,
                  });
                  setMission(next);
                  toast.message(
                    `Replan #${String((next as { replan_count?: number }).replan_count ?? next.ir?.replan_count ?? "?")} · ${replanCause}`,
                  );
                })
              }
            >
              {busy === "replan" ? <Loader2 className="animate-spin" /> : <RotateCcw />} Replan
            </Button>
          </div>
          {acceptanceResult ? (
            <div className="code-block" style={{ marginBottom: "0.6rem" }}>
              <pre>{JSON.stringify(acceptanceResult, null, 2)}</pre>
            </div>
          ) : null}
          {Array.isArray(mission.ir?.replan_history) && (mission.ir?.replan_history as unknown[]).length > 0 ? (
            <div className="code-block" style={{ marginBottom: "0.6rem" }}>
              <p className="muted">Replan history</p>
              <pre>{JSON.stringify(mission.ir?.replan_history, null, 2)}</pre>
            </div>
          ) : null}

          <div className="page-actions" style={{ marginTop: "0.8rem" }}>
            {(mission.gates || []).map((gate) => (
              <div key={gate.id} className="page-actions">
                <span>{gate.id} — {gate.status}</span>
                {gate.status !== "approved" && gate.status !== "rejected" ? (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!!busy}
                      onClick={() =>
                        void run("gate-approve", async () => {
                          setMission(await hadesApi.gen2DecideGate(mission.id, gate.id, true, "approved via UI"));
                        })
                      }
                    >
                      <ShieldCheck /> Goedkeuren
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!!busy}
                      onClick={() =>
                        void run("gate-reject", async () => {
                          setMission(await hadesApi.gen2DecideGate(mission.id, gate.id, false, "rejected via UI"));
                        })
                      }
                    >
                      <ShieldX /> Weigeren
                    </Button>
                  </>
                ) : null}
              </div>
            ))}
            {canPause ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={!!busy}
                onClick={() =>
                  void run("pause", async () => {
                    setMission(await hadesApi.gen2PauseMission(mission.id));
                    toast.message("Pauze aangevraagd/gezet");
                  })
                }
              >
                <Pause /> Pauzeren
              </Button>
            ) : null}
            {canResume ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={!!busy}
                onClick={() =>
                  void run("resume", async () => {
                    setMission(await hadesApi.gen2ResumeMission(mission.id));
                    toast.message("Hervat");
                  })
                }
              >
                <Play /> Hervatten
              </Button>
            ) : null}
            {canRetry ? (
              <Button
                size="sm"
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("retry", async () => {
                    setMission(await hadesApi.gen2StartMission(mission.id, { force_retry: true }));
                    toast.message("Nieuwe poging gestart");
                  })
                }
              >
                <RotateCcw /> Nieuwe poging
              </Button>
            ) : null}
          </div>
        </Panel>
      ) : null}

      <div className="form-grid two">
        <Panel title="Intelligence Evaluation Lab" eyebrow="Eval product">
          <div className="form-stack">
            <label className="muted">Suite</label>
            <select
              value={evalSuite}
              onChange={(e) => setEvalSuite(e.target.value as typeof evalSuite)}
              className="input"
            >
              <option value="reasoning">reasoning (deterministic software)</option>
              <option value="quality">quality</option>
              <option value="red_team">red_team</option>
              <option value="generalization">generalization</option>
              <option value="dev_partner_v1">dev_partner_v1 (20 coding tasks)</option>
            </select>
            <label className="muted">Modus</label>
            <select
              value={evalMode}
              onChange={(e) => setEvalMode(e.target.value as typeof evalMode)}
              className="input"
            >
              <option value="deterministic_software">Deterministic software</option>
              <option value="quality_suite">Quality suite</option>
              <option value="dev_partner_software">Dev partner software</option>
              <option value="dev_partner_baseline">Dev partner baseline compare</option>
              <option value="live_model">Live model smoke (infrastructuur)</option>
            </select>
            {evalMode === "live_model" ? (
              <>
                <label className="muted">Model {modelsConnected ? "" : "(LM niet verbonden)"}</label>
                <select
                  value={selectedModelId}
                  onChange={(e) => setSelectedModelId(e.target.value)}
                  className="input"
                  disabled={!availableModels.length}
                >
                  {!availableModels.length ? <option value="">Geen modellen beschikbaar</option> : null}
                  {availableModels.map((id) => (
                    <option key={id} value={id}>{id}</option>
                  ))}
                </select>
              </>
            ) : null}
            <div className="page-actions">
              <Button
                disabled={!!busy || (evalMode === "live_model" && !selectedModelId)}
                onClick={() =>
                  void run("eval", async () => {
                    const suite =
                      evalMode === "live_model"
                        ? "smoke"
                        : evalMode === "quality_suite"
                          ? "quality"
                          : evalSuite;
                    const mode =
                      evalSuite === "dev_partner_v1" ||
                      evalMode === "dev_partner_software" ||
                      evalMode === "dev_partner_baseline"
                        ? evalMode === "dev_partner_baseline"
                          ? "dev_partner_baseline"
                          : "dev_partner_software"
                        : evalSuite === "red_team"
                          ? "red_team_software"
                          : evalSuite === "generalization"
                            ? "generalization"
                            : evalMode === "quality_suite" || evalSuite === "quality"
                              ? "quality_suite"
                              : evalMode;
                    const report = await hadesApi.gen2RunEvals({
                      model_id:
                        evalMode === "live_model"
                          ? selectedModelId
                          : evalMode === "quality_suite" || evalSuite === "quality"
                            ? "quality-suite"
                            : evalSuite === "dev_partner_v1"
                              ? "dev-partner"
                              : undefined,
                      mode,
                      suite: evalSuite === "dev_partner_v1" ? "dev_partner_v1" : suite,
                      holdout_split: evalSuite === "dev_partner_v1" ? "holdout" : undefined,
                    });
                    setEvalSummary(report.summary || null);
                    const notQuality = Boolean(report.summary?.not_model_quality);
                    const failed = Number(report.summary?.failed || 0);
                    const passed = Number(report.summary?.passed || 0);
                    const passRate = Number(report.summary?.pass_rate || 0);
                    if (failed > 0 || (passed <= 0 && passRate <= 0)) {
                      toast.error(
                        notQuality
                          ? `Eval suite ${suite} klaar met failures (labeled: not model quality)`
                          : `Eval suite ${suite} klaar met failures (${failed} failed)`,
                      );
                    } else {
                      toast.success(
                        notQuality
                          ? `Eval suite ${suite} klaar (labeled: not model quality)`
                          : `Eval suite ${suite} klaar`,
                      );
                    }
                  })
                }
              >
                {busy === "eval" ? <Loader2 className="animate-spin" /> : <Play />} Run suite
              </Button>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("eval-matrix", async () => {
                    const matrix = await hadesApi.gen2EvalMatrix();
                    setEvalMatrix(matrix);
                    const rowCount = matrix.rows?.length ?? 0;
                    if (rowCount > 0) toast.success(`Matrix: ${rowCount} rijen`);
                    else toast.message("Matrix leeg (0 rijen)");
                  })
                }
              >
                {busy === "eval-matrix" ? <Loader2 className="animate-spin" /> : null} Laad matrix
              </Button>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("eval-flaky", async () => {
                    const result = await hadesApi.gen2EvalFlaky({
                      suite: evalSuite,
                      mode:
                        evalSuite === "red_team"
                          ? "red_team_software"
                          : evalSuite === "quality"
                            ? "quality_suite"
                            : undefined,
                      last_n: 5,
                    });
                    setEvalFlaky(result);
                    const considered = Number((result as { runs_considered?: number }).runs_considered ?? 0);
                    if (considered > 0) {
                      toast.success(
                        `Flaky-detectie: ${Number((result as { flaky_cases?: unknown[] }).flaky_cases?.length ?? 0)} flaky / ${considered} runs`,
                      );
                    } else {
                      toast.message("Flaky-detectie: geen eval-runs om te beoordelen");
                    }
                  })
                }
              >
                {busy === "eval-flaky" ? <Loader2 className="animate-spin" /> : null} Flaky check
              </Button>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("eval-catalog", async () => {
                    const catalog = await hadesApi.gen2EvalCatalog();
                    setEvalCatalog(catalog);
                    const suites = Array.isArray((catalog as { suites?: unknown[] }).suites)
                      ? ((catalog as { suites: Array<Record<string, unknown>> }).suites)
                      : [];
                    const usable = suites.filter(
                      (s) => !s.unavailable && Number(s.case_count ?? s.scenario_count ?? 1) > 0,
                    );
                    if (usable.length > 0) {
                      toast.success(`Catalog: ${usable.length} beschikbare suites`);
                    } else {
                      toast.message("Catalog leeg of geen beschikbare suites");
                    }
                  })
                }
              >
                Catalog
              </Button>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("eval-reports", async () => {
                    const reports = await hadesApi.gen2EvalReports(20);
                    setEvalReports(reports);
                    if (reports.length > 0) toast.success(`${reports.length} reports`);
                    else toast.message("0 reports");
                  })
                }
              >
                Reports
              </Button>
            </div>
            <label className="muted">A/B experiment (software honesty — geen live quality claim)</label>
            <div className="form-grid two">
              <Input
                value={evalAbStrategyA}
                onChange={(e) => setEvalAbStrategyA(e.target.value)}
                placeholder="strategy_a"
              />
              <Input
                value={evalAbStrategyB}
                onChange={(e) => setEvalAbStrategyB(e.target.value)}
                placeholder="strategy_b"
              />
            </div>
            <Button
              variant="secondary"
              disabled={!!busy || !evalAbStrategyA.trim() || !evalAbStrategyB.trim()}
              onClick={() =>
                void run("eval-ab", async () => {
                  const result = await hadesApi.gen2EvalAb({
                    strategy_a: evalAbStrategyA.trim(),
                    strategy_b: evalAbStrategyB.trim(),
                    suite: evalSuite,
                  });
                  setEvalAbResult(result as unknown as Record<string, unknown>);
                  toast.message("A/B klaar — labeled software experiment");
                })
              }
            >
              {busy === "eval-ab" ? <Loader2 className="animate-spin" /> : null} Run A/B
            </Button>
            <label className="muted">Ingest Flight Recorder run → eval</label>
            <div className="page-actions">
              <Input
                value={evalIngestRunId}
                onChange={(e) => setEvalIngestRunId(e.target.value)}
                placeholder="run_id"
                style={{ maxWidth: "16rem" }}
              />
              <Button
                variant="outline"
                disabled={!!busy || !evalIngestRunId.trim()}
                onClick={() =>
                  void run("eval-ingest", async () => {
                    const result = await hadesApi.gen2EvalIngestFlight({
                      run_id: evalIngestRunId.trim(),
                    });
                    setEvalIngestResult(result as unknown as Record<string, unknown>);
                    if ((result as { ok?: boolean }).ok === false) {
                      toast.error(
                        String((result as { error?: string }).error || "Flight ingest mislukt (geen events)"),
                      );
                    } else {
                      toast.success("Flight ingest voltooid");
                    }
                  })
                }
              >
                {busy === "eval-ingest" ? <Loader2 className="animate-spin" /> : null} Ingest flight
              </Button>
            </div>
            <label className="muted">PR-help (twee run ids)</label>
            <div className="form-grid two">
              <Input
                value={prHelpRunA}
                onChange={(e) => setPrHelpRunA(e.target.value)}
                placeholder="run_a"
              />
              <Input
                value={prHelpRunB}
                onChange={(e) => setPrHelpRunB(e.target.value)}
                placeholder="run_b"
              />
            </div>
            <Button
              variant="secondary"
              disabled={!!busy || !prHelpRunA.trim() || !prHelpRunB.trim()}
              onClick={() =>
                void run("eval-pr", async () => {
                  const result = await hadesApi.gen2EvalPrHelp({
                    run_a: prHelpRunA.trim(),
                    run_b: prHelpRunB.trim(),
                  });
                  setPrHelp(result);
                  if ((result as { ok?: boolean }).ok) {
                    toast.success("PR-help samenvatting");
                  } else {
                    toast.error(
                      String((result as { error?: string }).error || "PR-help mislukt (run niet gevonden)."),
                    );
                  }
                })
              }
            >
              {busy === "eval-pr" ? <Loader2 className="animate-spin" /> : null} PR-help
            </Button>
          </div>
          {evalSummary ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(evalSummary, null, 2)}</pre>
            </div>
          ) : null}
          <div className="form-stack" style={{ marginTop: "0.8rem" }}>
            <label className="muted">Menselijke bruikbaarheid (optioneel)</label>
            <select
              className="input"
              value={humanRating}
              onChange={(e) => setHumanRating(e.target.value as typeof humanRating)}
            >
              <option value="directly_usable">Direct bruikbaar</option>
              <option value="usable_after_small_correction">Bruikbaar na kleine correctie</option>
              <option value="needs_major_correction">Ingrijpende correctie nodig</option>
              <option value="unusable">Onbruikbaar</option>
            </select>
            <input
              className="input"
              placeholder="Wat moest worden gecorrigeerd? (optioneel)"
              value={humanNotes}
              onChange={(e) => setHumanNotes(e.target.value)}
            />
            <input
              className="input"
              placeholder="Actieve correctietijd in seconden (expliciet; geen open-venster schatting)"
              value={humanSeconds}
              onChange={(e) => setHumanSeconds(e.target.value)}
            />
            <div className="page-actions">
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("eval-human", async () => {
                    const secondsRaw = humanSeconds.trim();
                    const seconds = secondsRaw ? Number.parseFloat(secondsRaw) : null;
                    await hadesApi.gen2EvalHumanRating({
                      rating: humanRating,
                      correction_notes: humanNotes,
                      correction_seconds: Number.isFinite(seconds as number) ? seconds : null,
                      timer_opt_in: seconds != null && Number.isFinite(seconds),
                      original_result: (evalSummary as Record<string, unknown>) || {},
                      artifact_version: "coding_delivery_v1",
                    });
                    const listed = await hadesApi.gen2EvalHumanRatings({ limit: 50 });
                    setHumanTrends(listed.trends);
                    toast.success("Menselijke beoordeling opgeslagen");
                  })
                }
              >
                Opslaan beoordeling
              </Button>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("eval-human-trends", async () => {
                    const listed = await hadesApi.gen2EvalHumanRatings({ limit: 100 });
                    setHumanTrends(listed.trends);
                    const samples = Number((listed.trends as { samples?: number } | undefined)?.samples ?? 0);
                    if (samples > 0) toast.success(`Trends geladen (${samples} samples)`);
                    else toast.message("Trends: 0 human ratings");
                  })
                }
              >
                Trends
              </Button>
            </div>
            {humanTrends ? (
              <div className="code-block">
                <pre>{JSON.stringify(humanTrends, null, 2)}</pre>
              </div>
            ) : null}
          </div>
          {evalMatrix ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <p className="muted">Capability matrix rows (API-confirmed)</p>
              <pre>{JSON.stringify(evalMatrix.rows?.slice(0, 40) || [], null, 2)}</pre>
            </div>
          ) : null}
          {evalFlaky ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(evalFlaky, null, 2)}</pre>
            </div>
          ) : null}
          {prHelp ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(prHelp, null, 2)}</pre>
            </div>
          ) : null}
          {evalCatalog ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <p className="muted">Catalog (offline suites)</p>
              <pre>{JSON.stringify(evalCatalog, null, 2)}</pre>
            </div>
          ) : null}
          {evalReports ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <p className="muted">Recent reports ({evalReports.length})</p>
              <pre>
                {JSON.stringify(
                  evalReports.slice(0, 10).map((r) => ({
                    id: r.id,
                    suite: r.suite,
                    mode: r.mode,
                    status: r.status,
                    not_model_quality: r.summary?.not_model_quality,
                  })),
                  null,
                  2,
                )}
              </pre>
            </div>
          ) : null}
          {evalAbResult ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <StatusBadge tone="warning">A/B software experiment — not live model quality</StatusBadge>
              <pre>{JSON.stringify(evalAbResult, null, 2)}</pre>
            </div>
          ) : null}
          {evalIngestResult ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(evalIngestResult, null, 2)}</pre>
            </div>
          ) : null}
        </Panel>

        <Panel title="Intelligence Committee">
          <div className="form-stack">
            <Input value={committeeTopic} onChange={(e) => setCommitteeTopic(e.target.value)} />
            <label className="muted">Bronnen (één per regel) — leeg = expliciet geen bronnen</label>
            <Textarea
              value={committeeEvidence}
              onChange={(e) => setCommitteeEvidence(e.target.value)}
              rows={4}
              placeholder="Plak passages of laad Knowledge/Evidence"
            />
            <div className="page-actions">
              <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void loadKnowledgeEvidence()}>
                Laad Knowledge/Evidence
              </Button>
              <Button size="sm" variant="outline" disabled={!!busy} onClick={() => setCommitteeEvidence("")}>
                Geen bronnen
              </Button>
              <select
                value={committeeMode}
                onChange={(e) => setCommitteeMode(e.target.value as typeof committeeMode)}
                className="input"
              >
                <option value="heuristic">Heuristic</option>
                <option value="live">Live committee</option>
              </select>
            </div>
            {committeeMode === "live" ? (
              <select
                value={selectedModelId}
                onChange={(e) => setSelectedModelId(e.target.value)}
                className="input"
                disabled={!availableModels.length}
              >
                {!availableModels.length ? <option value="">Geen modellen beschikbaar</option> : null}
                {availableModels.map((id) => (
                  <option key={id} value={id}>{id}</option>
                ))}
              </select>
            ) : null}
            <Button
              disabled={!!busy || (committeeMode === "live" && !selectedModelId)}
              onClick={() =>
                void run("committee", async () => {
                  const evidence = committeeEvidence
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean);
                  const session = await hadesApi.gen2RunCommittee({
                    topic: committeeTopic,
                    domain: "research",
                    evidence,
                    mode: committeeMode,
                    model_id: committeeMode === "live" ? selectedModelId : undefined,
                  });
                  setCommittee(session);
                })
              }
            >
              {busy === "committee" ? <Loader2 className="animate-spin" /> : <Play />} Delibereer
            </Button>
            {knowledgeHits.length ? <p className="muted">{knowledgeHits.length} geladen bronregels</p> : null}
          </div>
          {committee?.consensus ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(committee.consensus, null, 2)}</pre>
            </div>
          ) : null}
        </Panel>
      </div>

      <div className="form-grid two">
        <Panel title="Financial Fusion (PAPER)">
          <div className="form-stack">
            <Input
              value={financeSymbol}
              onChange={(e) => setFinanceSymbol(e.target.value)}
              placeholder="Optioneel ticker/symbool (filter)"
            />
            <p className="muted">
              Fuseert echte Knowledge/Evidence-hits. Sample fixtures blijven optioneel.
            </p>
            <div className="page-actions">
              <Button disabled={!!busy} onClick={() => void fuseFromKnowledge()}>
                {busy === "fuse" ? <Loader2 className="animate-spin" /> : <Play />} Fuse vanuit Knowledge
              </Button>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() => setShowSampleFixtures((v) => !v)}
              >
                Sample fixtures
              </Button>
            </div>
            {showSampleFixtures ? (
              <Button
                variant="secondary"
                disabled={!!busy}
                onClick={() =>
                  void run("fuse-sample", async () => {
                    const result = await hadesApi.gen2FuseFinance({
                      symbol: financeSymbol.trim() || "SAMPLE",
                      articles: [{ ...SAMPLE_FINANCE_ARTICLE }],
                    });
                    setFuseResult(result);
                    toast.message("Sample fixture gefuseerd (niet live data)");
                  })
                }
              >
                Fuse sample article
              </Button>
            ) : null}
          </div>
          {fuseResult ? <div className="code-block" style={{ marginTop: "0.7rem" }}><pre>{JSON.stringify(fuseResult, null, 2)}</pre></div> : null}
        </Panel>

        <Panel title="Agent Factory">
          <div className="form-stack">
            <Input
              value={skillName}
              onChange={(e) => setSkillName(e.target.value)}
              placeholder="Skillnaam (optioneel; default uit missie)"
            />
            <p className="muted">
              Extraheert kandidaten uit bewezen missiestappen/traces of Flight Recorder runs.
              Extract creëert alleen candidates — nooit auto-promote. Demo-workflows staan alleen achter sample fixtures.
            </p>
            <label className="muted">Extract from Flight Recorder run</label>
            <div className="page-actions">
              <Input
                value={extractFromRunId}
                onChange={(e) => setExtractFromRunId(e.target.value)}
                placeholder="run_id"
                style={{ maxWidth: "16rem" }}
              />
              <Button
                variant="secondary"
                disabled={!!busy || !extractFromRunId.trim()}
                onClick={() =>
                  void run("extract-run", async () => {
                    const result = await hadesApi.gen2ExtractSkillFromRun({
                      run_id: extractFromRunId.trim(),
                      name: skillName.trim() || undefined,
                      create: true,
                    });
                    setExtractFromRun(result);
                    if (result.created && result.skill) {
                      setSkill(result.skill as Record<string, unknown>);
                      toast.success("Candidate from run (not promoted)");
                    } else {
                      toast.message(
                        `Geen candidate: ${String(result.reason || result.extraction || "empty/failed run")}`,
                      );
                    }
                  })
                }
              >
                {busy === "extract-run" ? <Loader2 className="animate-spin" /> : <Sparkles />} Extract from run
              </Button>
              <Button
                variant="outline"
                disabled={!!busy || !extractFromRunId.trim()}
                onClick={() =>
                  void run("extract-preview", async () => {
                    const result = await hadesApi.gen2ExtractSkillFromRun({
                      run_id: extractFromRunId.trim(),
                      create: false,
                    });
                    setExtractFromRun(result);
                    toast.message("Preview only — create=false");
                  })
                }
              >
                Preview patterns
              </Button>
            </div>
            <div className="page-actions">
              <Button disabled={!!busy || !mission?.id} onClick={() => void extractSkillFromMissionTrace()}>
                {busy === "skill" ? <Loader2 className="animate-spin" /> : <Sparkles />} Extract uit missie
              </Button>
              {showSampleFixtures ? (
                <Button
                  variant="secondary"
                  disabled={!!busy}
                  onClick={() =>
                    void run("skill-sample", async () => {
                      const candidate = await hadesApi.gen2ExtractSkill({
                        name: skillName.trim() || "sample-fixture-skill",
                        workflow: SAMPLE_FIXTURE_WORKFLOW,
                        pattern_source: "sample-fixture",
                      });
                      setSkill(candidate);
                      toast.message("Sample fixture skill (niet productie-bewijs)");
                    })
                  }
                >
                  Sample workflow
                </Button>
              ) : null}
              {skill?.id ? (
                <>
                  <Button
                    variant="secondary"
                    disabled={!!busy}
                    onClick={() =>
                      void run("bench", async () => {
                        setSkill(await hadesApi.gen2BenchmarkSkill(String(skill.id)));
                      })
                    }
                  >
                    Benchmark
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!!busy || skill.status !== "benchmarked"}
                    onClick={() =>
                      void run("promote", async () => {
                        setSkill(await hadesApi.gen2PromoteSkill(String(skill.id), true));
                        toast.success("Skill promoted (human approved)");
                      })
                    }
                  >
                    Promote
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={!!busy || skill.status !== "promoted"}
                    onClick={() =>
                      void run("execute-skill", async () => {
                        const executed = await hadesApi.gen2ExecuteSkill(String(skill.id));
                        setSkill({ ...skill, last_execution: executed });
                        if (executed.passed) toast.success("Skill executed");
                        else toast.error("Skill executed with failures");
                      })
                    }
                  >
                    Execute
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!!busy || skill.status !== "promoted"}
                    onClick={() =>
                      void run("deactivate-skill", async () => {
                        setSkill(await hadesApi.gen2DeactivateSkill(String(skill.id)));
                        toast.success("Skill deactivated");
                      })
                    }
                  >
                    Deactivate
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!!busy || !["promoted", "deactivated"].includes(String(skill.status))}
                    onClick={() =>
                      void run("rollback-skill", async () => {
                        setSkill(await hadesApi.gen2RollbackSkill(String(skill.id), "benchmarked"));
                        toast.success("Skill rolled back to benchmarked");
                      })
                    }
                  >
                    Rollback
                  </Button>
                </>
              ) : null}
            </div>
          </div>
          {extractFromRun ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <StatusBadge tone={extractFromRun.created ? "success" : "warning"}>
                {extractFromRun.created ? "candidate created" : "no candidate / incomplete"}
              </StatusBadge>
              <pre>{JSON.stringify(extractFromRun, null, 2)}</pre>
            </div>
          ) : null}
          {skill ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify({ id: skill.id, status: skill.status, benchmark: skill.benchmark }, null, 2)}</pre>
            </div>
          ) : null}
        </Panel>
      </div>

      <Panel title="Compute fabric / nodes" eyebrow="Dispatch">
        <p className="panel-copy">
          Nodes en status uit de API. Alleen getypeerde jobs (bijv. ping). Onbekende ops falen eerlijk.
        </p>
        <div className="page-actions" style={{ marginBottom: "0.5rem", flexWrap: "wrap" }}>
          <StatusBadge tone="warning">physical multi-machine: UNVERIFIED_ON_HOST</StatusBadge>
          <StatusBadge tone="neutral">local node + typed ping only</StatusBadge>
        </div>
        <div className="page-actions" style={{ marginBottom: "0.6rem" }}>
          <Button
            size="sm"
            variant="outline"
            disabled={!!busy}
            onClick={() =>
              void run("compute-load", async () => {
                const [nodes, status] = await Promise.all([
                  hadesApi.gen2ComputeNodes(),
                  hadesApi.gen2ComputeStatus(),
                ]);
                setComputeNodes(nodes);
                setComputeStatus(status);
                if (nodes.length > 0) toast.success(`${nodes.length} nodes geladen`);
                else toast.message("0 compute nodes");
              })
            }
          >
            {busy === "compute-load" ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Laad nodes/status
          </Button>
          <Button
            size="sm"
            disabled={!!busy}
            onClick={() =>
              void run("compute-ping", async () => {
                const job = await hadesApi.gen2DispatchJob({
                  payload: { type: "ping", note: "mission-control-ui" },
                  prefer_local_fallback: true,
                });
                setComputeJob(job);
                const st = String(job.status || "");
                if (st === "failed" || st === "blocked" || !st) {
                  toast.message(`Ping: ${st || "geen status"}${job.error ? ` — ${String(job.error)}` : ""}`);
                } else if (["completed", "done", "leased", "queued", "running", "succeeded"].includes(st)) {
                  toast.success(`Ping job ${String(job.id || "")}: ${st}`);
                } else {
                  toast.message(`Ping job ${String(job.id || "")}: ${st}`);
                }
              })
            }
          >
            {busy === "compute-ping" ? <Loader2 className="animate-spin" /> : <Play />} Dispatch ping
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!!busy}
            onClick={() =>
              void run("compute-unknown", async () => {
                const job = await hadesApi.gen2DispatchJob({
                  payload: { type: computeUnknownOp.trim() || "shell_exec" },
                  prefer_local_fallback: true,
                });
                setComputeJob(job);
                toast.message(
                  `Onbekende op: status=${String(job.status)} · error=${String(job.error || "none")}`,
                );
              })
            }
          >
            Probeer onbekende op
          </Button>
          <Input
            value={computeUnknownOp}
            onChange={(e) => setComputeUnknownOp(e.target.value)}
            placeholder="unsupported op name"
            style={{ maxWidth: "12rem" }}
          />
        </div>
        <ul className="details-stack">
          {(computeNodes || dash?.nodes || []).length === 0 ? (
            <li className="muted">Nog geen nodes — laad of refresh dashboard.</li>
          ) : null}
          {(computeNodes || dash?.nodes || []).map((node) => (
            <li key={String(node.id)}>
              <strong>{String(node.name || node.id)}</strong> — {String(node.status)} / {String(node.role || "")}
              {node.capabilities ? (
                <span className="muted"> · caps: {JSON.stringify(node.capabilities).slice(0, 80)}</span>
              ) : null}
            </li>
          ))}
        </ul>
        {computeStatus ? (
          <div className="code-block" style={{ marginTop: "0.7rem" }}>
            <pre>{JSON.stringify(computeStatus, null, 2)}</pre>
          </div>
        ) : null}
        {computeJob ? (
          <div className="code-block" style={{ marginTop: "0.7rem" }}>
            <p className="muted">
              Laatste job — status={String(computeJob.status)}
              {computeJob.error ? ` · ${String(computeJob.error)}` : ""}
            </p>
            <pre>{JSON.stringify(computeJob, null, 2)}</pre>
          </div>
        ) : null}
      </Panel>

      <Panel title="Flight Recorder" eyebrow="Audit / inspect">
        <p className="panel-copy">
          Timeline, compare, audit-bundle en inspect-replay. Replay is <strong>inspection_not_replay</strong> —
          geen live model/tool heruitvoering.
        </p>
        <div className="form-stack">
          <Input
            value={flightRunId}
            onChange={(e) => setFlightRunId(e.target.value)}
            placeholder="run_id"
          />
          <div className="page-actions">
            <Button
              disabled={!!busy || !flightRunId.trim()}
              onClick={() =>
                void run("flight-events", async () => {
                  const events = await hadesApi.gen2FlightEvents(flightRunId.trim());
                  setFlightEvents(events);
                  if (!events.length) {
                    toast.message("0 events — run onbekend of leeg");
                  } else {
                    toast.success(`${events.length} events`);
                  }
                })
              }
            >
              {busy === "flight-events" ? <Loader2 className="animate-spin" /> : null} Timeline
            </Button>
            <Button
              variant="outline"
              disabled={!!busy || !flightRunId.trim()}
              onClick={() =>
                void run("flight-audit", async () => {
                  const bundle = await hadesApi.gen2FlightAuditBundle(flightRunId.trim());
                  setFlightAudit(bundle);
                  if ((bundle as { ok?: boolean }).ok === false) {
                    toast.error(String((bundle as { error?: string }).error || "Audit bundle leeg"));
                  } else {
                    toast.success("Audit bundle geladen");
                  }
                })
              }
            >
              Export audit bundle
            </Button>
            <Button
              variant="secondary"
              disabled={!!busy || !flightRunId.trim()}
              onClick={() =>
                void run("flight-replay", async () => {
                  const manifest = await hadesApi.gen2FlightReplay(flightRunId.trim());
                  setFlightReplay(manifest);
                  const kind = String(manifest.kind || manifest.mode || "");
                  if ((manifest as { ok?: boolean }).ok === false) {
                    toast.error(String((manifest as { error?: string }).error || "Flight replay mislukt"));
                  } else {
                    toast.success(
                      kind === "inspection_not_replay"
                        ? "Inspect-manifest (geen live replay)"
                        : `Replay result: ${kind || "ok"}`,
                    );
                  }
                })
              }
            >
              Inspect replay
            </Button>
          </div>
          <label className="muted">Vergelijk twee runs</label>
          <div className="form-grid two">
            <Input
              value={flightCompareA}
              onChange={(e) => setFlightCompareA(e.target.value)}
              placeholder="run_a"
            />
            <Input
              value={flightCompareB}
              onChange={(e) => setFlightCompareB(e.target.value)}
              placeholder="run_b"
            />
          </div>
          <Button
            variant="outline"
            disabled={!!busy || !flightCompareA.trim() || !flightCompareB.trim()}
            onClick={() =>
              void run("flight-compare", async () => {
                const result = await hadesApi.gen2FlightCompare(
                  flightCompareA.trim(),
                  flightCompareB.trim(),
                );
                setFlightCompare(result);
                if ((result as { ok?: boolean }).ok === false) {
                  toast.error(String((result as { error?: string }).error || "Compare mislukt (lege run)"));
                } else {
                  toast.success("Compare voltooid");
                }
              })
            }
          >
            {busy === "flight-compare" ? <Loader2 className="animate-spin" /> : null} Compare runs
          </Button>
        </div>
        {flightReplay ? (
          <div className="page-actions" style={{ marginTop: "0.6rem" }}>
            <StatusBadge
              tone={String(flightReplay.kind) === "inspection_not_replay" ? "warning" : "neutral"}
            >
              {String(flightReplay.kind || flightReplay.mode || "replay")}
            </StatusBadge>
            {flightReplay.note ? <span className="muted">{String(flightReplay.note)}</span> : null}
          </div>
        ) : null}
        {flightEvents ? (
          <div className="code-block" style={{ marginTop: "0.7rem" }}>
            <pre>
              {JSON.stringify(
                flightEvents.map((e) => ({
                  seq: e.sequence ?? e.seq,
                  type: e.event_type,
                  at: e.created_at || e.ts,
                  component: e.component,
                })),
                null,
                2,
              )}
            </pre>
          </div>
        ) : null}
        {flightCompare ? (
          <div className="code-block" style={{ marginTop: "0.7rem" }}>
            <pre>{JSON.stringify(flightCompare, null, 2)}</pre>
          </div>
        ) : null}
        {flightAudit ? (
          <div className="code-block" style={{ marginTop: "0.7rem" }}>
            <pre>{JSON.stringify(flightAudit, null, 2)}</pre>
          </div>
        ) : null}
        {flightReplay ? (
          <div className="code-block" style={{ marginTop: "0.7rem" }}>
            <pre>{JSON.stringify(flightReplay, null, 2)}</pre>
          </div>
        ) : null}
      </Panel>

      <Panel title="Context Compiler preview" eyebrow="Pack">
        <p className="panel-copy">
          Compileert een doel + items tot een pack. Tokenizer is gelabeld (approx tenzij tiktoken beschikbaar).
        </p>
        <div className="page-actions" style={{ marginBottom: "0.5rem" }}>
          <StatusBadge tone="warning">tokenizer may be approx / estimate</StatusBadge>
          <StatusBadge tone="neutral">hierarchical summarization: stub/incomplete</StatusBadge>
        </div>
        <div className="form-stack">
          <Textarea
            value={ctxGoal}
            onChange={(e) => setCtxGoal(e.target.value)}
            rows={2}
            placeholder="Doel / query voor context selectie…"
          />
          <label className="muted">Items — JSON-array of regels (één content per regel)</label>
          <Textarea
            value={ctxItemsText}
            onChange={(e) => setCtxItemsText(e.target.value)}
            rows={5}
            placeholder='[{"item_id":"1","content":"..."}] of plain lines'
          />
          <Button
            disabled={!!busy || !ctxGoal.trim()}
            onClick={() =>
              void run("ctx-compile", async () => {
                let items: Array<Record<string, unknown>> = [];
                const raw = ctxItemsText.trim();
                if (raw.startsWith("[")) {
                  const parsed = JSON.parse(raw) as unknown;
                  if (!Array.isArray(parsed)) throw new Error("Items JSON moet een array zijn");
                  items = parsed as Array<Record<string, unknown>>;
                } else {
                  items = raw
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean)
                    .map((content, i) => ({
                      item_id: `line_${i}`,
                      kind: "other",
                      content,
                      source: "textarea",
                    }));
                }
                const pack = await hadesApi.gen2CompileContext({
                  goal: ctxGoal.trim(),
                  items,
                  persist: false,
                  tokenizer_mode: "approx_chars_4",
                });
                setCtxPack(pack);
                const keptCount = Array.isArray(pack.kept) ? pack.kept.length : 0;
                const droppedCount = Array.isArray(pack.dropped) ? pack.dropped.length : 0;
                if (keptCount > 0) {
                  toast.success(`Pack: kept=${keptCount} dropped=${droppedCount}`);
                } else {
                  toast.message(`Context-pack leeg (kept=0, dropped=${droppedCount})`);
                }
              })
            }
          >
            {busy === "ctx-compile" ? <Loader2 className="animate-spin" /> : <Sparkles />} Compileer preview
          </Button>
        </div>
        {ctxPack ? (
          <div className="form-grid two" style={{ marginTop: "0.7rem" }}>
            <div>
              <h4>Kept + why</h4>
              <div className="page-actions" style={{ marginBottom: "0.4rem" }}>
                <StatusBadge tone="neutral">
                  tokenizer={String(
                    (ctxPack.tokenizer as { mode?: string } | undefined)?.mode ||
                      ctxPack.tokenizer_mode_requested ||
                      ctxPack.tokenizer ||
                      "unknown",
                  )}
                </StatusBadge>
                {ctxPack.tokenizer_estimate ||
                String(ctxPack.tokenizer_mode_requested || "").includes("approx") ? (
                  <StatusBadge tone="warning">estimate — not exact tiktoken proof</StatusBadge>
                ) : null}
              </div>
              <div className="code-block">
                <pre>
                  {JSON.stringify(
                    {
                      tokenizer: ctxPack.tokenizer,
                      tokenizer_mode_requested: ctxPack.tokenizer_mode_requested,
                      tokenizer_estimate: ctxPack.tokenizer_estimate,
                      token_accounting: ctxPack.token_accounting,
                      used_tokens: ctxPack.used_tokens,
                      max_tokens: ctxPack.max_tokens,
                      kept: ctxPack.kept,
                    },
                    null,
                    2,
                  )}
                </pre>
              </div>
            </div>
            <div>
              <h4>Dropped + why</h4>
              <div className="code-block">
                <pre>{JSON.stringify(ctxPack.dropped || ctxPack.pack_preview || {}, null, 2)}</pre>
              </div>
            </div>
          </div>
        ) : null}
      </Panel>

      <div className="form-grid two">
        <Panel title="Sandbox policy profiles" eyebrow="Zero-trust">
          <p className="panel-copy">
            Host-probe tiers: preferred vs effective. Security beslist via policy_profile, niet via LLM.
            Tier 2 Job Objects blijven eerlijk gelabeld — nooit fake OS isolation success op Linux.
          </p>
          <div className="form-stack">
            <div className="page-actions">
              <Button
                size="sm"
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("sandbox-list", async () => {
                    const [profiles, caps] = await Promise.all([
                      hadesApi.gen2SandboxProfiles(),
                      hadesApi.gen2SandboxHostCapabilities(),
                    ]);
                    setSandboxProfiles(profiles);
                    setSandboxHostCaps(caps);
                    if (profiles[0]?.id) setSandboxProfileId(String(profiles[0].id));
                    if (profiles.length > 0) toast.success(`${profiles.length} profiles`);
                    else toast.message("0 sandbox profiles");
                  })
                }
              >
                {busy === "sandbox-list" ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Laad profiles
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("sandbox-selftest", async () => {
                    const report = await hadesApi.gen2SandboxTier2Selftest();
                    setSandboxHostCaps((prev) => ({ ...(prev || {}), tier2_selftest: report }));
                    const status = String(report.status || "selftest");
                    if (status === "PASS") {
                      toast.success(status);
                    } else if (status === "FAIL") {
                      toast.error(String(report.failure_reason || status));
                    } else {
                      toast.message(status);
                    }
                  })
                }
              >
                {busy === "sandbox-selftest" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Tier-2 selftest
              </Button>
            </div>
            {sandboxHostCaps ? (
              <div className="details-stack">
                <StatusBadge tone="warning">
                  {String(
                    (sandboxHostCaps.honesty as { verification_status?: string } | undefined)
                      ?.verification_status ||
                      sandboxHostCaps.verification_status ||
                      "UNVERIFIED_ON_HOST",
                  )}
                </StatusBadge>
                <span className="muted">
                  os_isolation_enforced=
                  {String(sandboxHostCaps.os_isolation_enforced ?? false)} · job_objects=
                  {String(sandboxHostCaps.job_objects ?? false)}
                </span>
              </div>
            ) : null}
            <label className="muted">Profile</label>
            <select
              value={sandboxProfileId}
              onChange={(e) => setSandboxProfileId(e.target.value)}
              className="input"
            >
              {(sandboxProfiles || [
                { id: "personal" },
                { id: "strict" },
                { id: "research" },
                { id: "coding" },
              ]).map((p) => (
                <option key={String(p.id)} value={String(p.id)}>
                  {String(p.label || p.id)}
                  {p.effective_tier != null ? ` (tier ${String(p.effective_tier)})` : ""}
                </option>
              ))}
            </select>
            <Input
              value={sandboxPluginId}
              onChange={(e) => setSandboxPluginId(e.target.value)}
              placeholder="plugin_id om envelope toe te passen"
            />
            <Button
              disabled={!!busy || !sandboxPluginId.trim() || !sandboxProfileId}
              onClick={() =>
                void run("sandbox-apply", async () => {
                  const env = await hadesApi.gen2ApplySandboxProfile(
                    sandboxProfileId,
                    sandboxPluginId.trim(),
                  );
                  setSandboxApplied(env);
                  if (
                    (env as { ok?: boolean }).ok !== false
                    && String((env as { plugin_id?: string }).plugin_id || "") === sandboxPluginId.trim()
                    && (env as { envelope?: unknown }).envelope
                  ) {
                    toast.success(`Profile ${sandboxProfileId} toegepast`);
                  } else {
                    toast.error("Sandbox profile apply leverde geen geldige envelope op.");
                  }
                })
              }
            >
              {busy === "sandbox-apply" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Apply to plugin
            </Button>
          </div>
          {sandboxProfiles ? (
            <ul className="details-stack" style={{ marginTop: "0.6rem" }}>
              {sandboxProfiles.map((p) => (
                <li key={String(p.id)}>
                  <strong>{String(p.label || p.id)}</strong>
                  {" — "}
                  preferred={String(p.preferred_tier)} / effective={String(p.effective_tier)}
                  {p.tier_available === false ? (
                    <StatusBadge tone="warning">tier UNVERIFIED/unavailable</StatusBadge>
                  ) : null}
                  <div className="muted">{String(p.note || p.description || "")}</div>
                </li>
              ))}
            </ul>
          ) : null}
          {sandboxApplied ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(sandboxApplied, null, 2)}</pre>
            </div>
          ) : null}
          <div className="form-stack" style={{ marginTop: "0.9rem" }}>
            <label className="muted">JIT grant (least privilege)</label>
            <p className="panel-copy">
              Just-in-time grants volgen het policy profile. Strict weigert JIT. Application-level —
              geen OS isolation claim.
            </p>
            <div className="page-actions">
              <Button
                size="sm"
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("jit-ux", async () => {
                    const [ux, grants] = await Promise.all([
                      hadesApi.gen2SandboxJitUx(sandboxProfileId),
                      hadesApi.gen2SandboxJitGrants({
                        plugin_id: sandboxPluginId.trim() || undefined,
                      }),
                    ]);
                    setJitUx(ux);
                    setJitGrants(grants);
                    const grantCount = Array.isArray(grants) ? grants.length : 0;
                    if (grantCount > 0) toast.success(`JIT panel: ${grantCount} grants`);
                    else toast.message("JIT panel: 0 grants");
                  })
                }
              >
                {busy === "jit-ux" ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Laad JIT
              </Button>
            </div>
            <Input
              value={jitCapability}
              onChange={(e) => setJitCapability(e.target.value)}
              placeholder="capability (network/subprocess/...)"
            />
            <Input
              value={jitReason}
              onChange={(e) => setJitReason(e.target.value)}
              placeholder="reden voor grant"
            />
            <Button
              disabled={!!busy || !sandboxPluginId.trim() || !jitCapability.trim()}
              onClick={() =>
                void run("jit-request", async () => {
                  const result = await hadesApi.gen2RequestJitGrant({
                    plugin_id: sandboxPluginId.trim(),
                    profile_id: sandboxProfileId,
                    capability: jitCapability.trim(),
                    reason: jitReason.trim() || "mission-control",
                  });
                  const grants = await hadesApi.gen2SandboxJitGrants({
                    plugin_id: sandboxPluginId.trim(),
                  });
                  setJitGrants(grants);
                  if (result.ok) toast.success("JIT grant issued");
                  else toast.error(String(result.reason || "JIT geweigerd"));
                })
              }
            >
              {busy === "jit-request" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Request JIT
            </Button>
            {jitUx ? (
              <ul className="details-stack">
                {(Array.isArray(jitUx.honesty) ? jitUx.honesty : []).map((line) => (
                  <li key={String(line)} className="muted">
                    {String(line)}
                  </li>
                ))}
              </ul>
            ) : null}
            {jitGrants && jitGrants.length > 0 ? (
              <ul className="details-stack">
                {jitGrants.map((g) => (
                  <li key={String(g.id)}>
                    <strong>{String(g.capability)}</strong> · {String(g.status)} · {String(g.profile_id)}
                    {g.status === "active" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        style={{ marginLeft: "0.5rem" }}
                        disabled={!!busy}
                        onClick={() =>
                          void run("jit-revoke", async () => {
                            await hadesApi.gen2RevokeJitGrant(String(g.id), "ui-revoke");
                            const grants = await hadesApi.gen2SandboxJitGrants({
                              plugin_id: sandboxPluginId.trim() || undefined,
                            });
                            setJitGrants(grants);
                            toast.success("JIT revoked");
                          })
                        }
                      >
                        Revoke
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </Panel>

        <Panel title="Temporal graph" eyebrow="Beliefs">
          <p className="panel-copy">
            Edge assert, as-of beliefs, analogues en contradictions — valid-time + observed-time.
          </p>
          <div className="form-stack">
            <label className="muted">Nieuwe edge</label>
            <div className="form-grid two">
              <Input
                value={graphSource}
                onChange={(e) => setGraphSource(e.target.value)}
                placeholder="source_id"
              />
              <Input
                value={graphTarget}
                onChange={(e) => setGraphTarget(e.target.value)}
                placeholder="target_id"
              />
            </div>
            <Input
              value={graphRelation}
              onChange={(e) => setGraphRelation(e.target.value)}
              placeholder="relation / relation_kind"
            />
            <Button
              disabled={!!busy || !graphSource.trim() || !graphTarget.trim()}
              onClick={() =>
                void run("graph-edge", async () => {
                  const edge = await hadesApi.gen2GraphAddEdge({
                    source_id: graphSource.trim(),
                    target_id: graphTarget.trim(),
                    relation: graphRelation.trim() || "related_to",
                    relation_kind: graphRelation.trim() || "related_to",
                    provenance: "mission-control-ui",
                    confidence: 0.5,
                  });
                  setGraphEdgeResult(edge);
                  toast.success("Edge toegevoegd");
                })
              }
            >
              {busy === "graph-edge" ? <Loader2 className="animate-spin" /> : null} Add edge
            </Button>
            <label className="muted">As-of query</label>
            <div className="form-grid two">
              <Input
                value={graphEntity}
                onChange={(e) => setGraphEntity(e.target.value)}
                placeholder="entity_id"
              />
              <Input
                value={graphAsOf}
                onChange={(e) => setGraphAsOf(e.target.value)}
                placeholder="as_of ISO datetime"
              />
            </div>
            <div className="page-actions">
              <Button
                variant="outline"
                disabled={!!busy || !graphEntity.trim() || !graphAsOf.trim()}
                onClick={() =>
                  void run("graph-asof", async () => {
                    const result = await hadesApi.gen2GraphAsOf(
                      graphEntity.trim(),
                      graphAsOf.trim(),
                    );
                    setGraphAsOfResult(result);
                    const beliefCount = Number(
                      (result as { count?: number }).count
                        ?? (Array.isArray((result as { beliefs?: unknown[] }).beliefs)
                          ? (result as { beliefs: unknown[] }).beliefs.length
                          : 0),
                    );
                    if (beliefCount > 0) toast.success(`As-of: ${beliefCount} beliefs`);
                    else toast.message("As-of: 0 beliefs");
                  })
                }
              >
                As-of
              </Button>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void run("graph-contra", async () => {
                    const rows = await hadesApi.gen2GraphContradictions(
                      graphEntity.trim() || undefined,
                    );
                    setGraphContradictions(rows);
                    if (rows.length > 0) toast.success(`${rows.length} contradictions`);
                    else toast.message("0 contradictions");
                  })
                }
              >
                Contradictions
              </Button>
            </div>
            <Input
              value={graphAnaloguesText}
              onChange={(e) => setGraphAnaloguesText(e.target.value)}
              placeholder="Analogues text search (optioneel)"
            />
            <Button
              variant="secondary"
              disabled={!!busy || (!graphEntity.trim() && !graphAnaloguesText.trim())}
              onClick={() =>
                void run("graph-analogues", async () => {
                  const result = await hadesApi.gen2GraphAnalogues({
                    entity_id: graphEntity.trim() || undefined,
                    text: graphAnaloguesText.trim() || undefined,
                    relation_kind: graphRelation.trim() || undefined,
                    limit: 20,
                  });
                  setGraphAnalogues(result);
                  const analogueCount = Number(
                    (result as { count?: number }).count
                      ?? (Array.isArray((result as { analogues?: unknown[] }).analogues)
                        ? (result as { analogues: unknown[] }).analogues.length
                        : 0),
                  );
                  if (analogueCount > 0) toast.success(`Analogues: ${analogueCount}`);
                  else toast.message("0 analogues gevonden");
                })
              }
            >
              Analogues search
            </Button>
          </div>
          {graphEdgeResult ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(graphEdgeResult, null, 2)}</pre>
            </div>
          ) : null}
          {graphAsOfResult ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(graphAsOfResult, null, 2)}</pre>
            </div>
          ) : null}
          {graphAnalogues ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(graphAnalogues, null, 2)}</pre>
            </div>
          ) : null}
          {graphContradictions ? (
            <div className="code-block" style={{ marginTop: "0.7rem" }}>
              <pre>{JSON.stringify(graphContradictions, null, 2)}</pre>
            </div>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}
