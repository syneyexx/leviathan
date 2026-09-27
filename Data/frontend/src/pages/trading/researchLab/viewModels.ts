/** Pure view-model helpers for Research Lab — derived only from real API payloads. */

export type LabRunRecord = Record<string, unknown>;
export type LearningRecord = Record<string, unknown>;
export type CandidateRecord = Record<string, unknown>;
export type GenerationRecord = Record<string, unknown>;

export type RunStatusTone =
  | "running"
  | "completed"
  | "paused"
  | "failed"
  | "draft"
  | "queued"
  | "cancelled";

export type ResearchLabTab =
  | "overview"
  | "generations"
  | "population"
  | "lineage"
  | "validation"
  | "analytics"
  | "logs";

export const RESEARCH_LAB_TABS: readonly { id: ResearchLabTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "generations", label: "Generations" },
  { id: "population", label: "Population" },
  { id: "lineage", label: "Lineage" },
  { id: "validation", label: "Validation" },
  { id: "analytics", label: "Analytics" },
  { id: "logs", label: "Logs" },
] as const;

export type ActionAvailability = {
  canStart: boolean;
  canPause: boolean;
  canResume: boolean;
  canCancel: boolean;
};

export type StageMetrics = {
  fitness: number | null;
  sharpe: number | null;
  maxDrawdownPct: number | null;
  totalReturnPct: number | null;
  winRate: number | null;
  accepted: boolean | null;
  failureCategories: unknown;
};

export type CandidateCardModel = {
  id: string | null;
  label: string;
  family: string | null;
  generation: number | null;
  status: string | null;
  metrics: StageMetrics;
  sparkPoints: number[];
};

export type OverviewModel = {
  currentGeneration: number;
  generationBudget: number;
  trialsUsed: number;
  trialBudget: number;
  populationSize: number | null;
  mutationRate: number | null;
  diversity: number | null;
  explorationRate: number | null;
  stageLabel: string;
  learningStatus: string | null;
  bestTrain: CandidateCardModel;
  bestValidation: CandidateCardModel;
  qualified: CandidateCardModel & { pending: boolean };
  fitnessBest: number[];
  fitnessMedian: number[];
  diversitySeries: number[];
  familySlices: { label: string; value: number; color: string }[];
  generationRows: GenerationRow[];
};

export type GenerationRow = {
  generation: number;
  bestFitness: number | null;
  medianFitness: number | null;
  diversity: number | null;
  exploration: number | null;
  topCandidateId: string | null;
  status: string;
};

export type DerivedEvent = {
  id: string;
  ts: string | null;
  level: "info" | "warn" | "error";
  message: string;
  source: string;
};

export type PhaseState = {
  id: string;
  label: string;
  state: "pending" | "active" | "done" | "failed" | "skipped";
};

const FAMILY_COLORS = ["#22c9d6", "#818cf8", "#34d399", "#f59e0b", "#f472b6", "#60a5fa", "#a78bfa"];

const STATUS_LABEL: Record<string, string> = {
  CREATED: "Draft",
  QUEUED: "Queued",
  RUNNING: "Running",
  PAUSED: "Paused",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
  TRAIN: "Training",
  VALIDATING: "Validating",
  ROBUSTNESS: "Robustness",
  SEALED_EVALUATION: "Sealed eval",
  QUALIFIED_STRATEGY_FOUND: "Qualified",
  NO_STRATEGY_QUALIFIED: "No qualify",
};

const STAGE_LABEL: Record<string, string> = {
  TRAIN: "TRAIN LEADER",
  VALIDATING: "VALIDATION RUNNING",
  ROBUSTNESS: "ROBUSTNESS RUNNING",
  SEALED_EVALUATION: "SEALED RUNNING",
  QUALIFIED_STRATEGY_FOUND: "QUALIFIED",
  NO_STRATEGY_QUALIFIED: "NO STRATEGY QUALIFIED",
  PAUSED: "PAUSED",
  CANCELLED: "CANCELLED",
  FAILED: "FAILED",
  CREATED: "NOT RUN",
  QUEUED: "QUEUED",
  RUNNING: "RUNNING",
  COMPLETED: "COMPLETED",
};

export function asRecord(v: unknown): Record<string, unknown> | undefined {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined;
}

export function asNum(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function fmtMetric(v: unknown, digits = 4): string {
  const n = asNum(v);
  if (n == null) return "—";
  return n.toFixed(digits);
}

export function fmtPctMetric(v: unknown, digits = 1): string {
  const n = asNum(v);
  if (n == null) return "—";
  // Values may already be percentages (backend fitness often uses pct units)
  return `${n.toFixed(digits)}%`;
}

export function stageLabel(stage: string | undefined | null): string {
  const s = String(stage || "NOT_RUN").toUpperCase();
  return STAGE_LABEL[s] || s;
}

export function statusTone(status: string | undefined | null): RunStatusTone {
  const s = String(status || "").toUpperCase();
  if (s === "RUNNING" || s === "TRAIN" || s === "VALIDATING" || s === "ROBUSTNESS" || s === "SEALED_EVALUATION") {
    return "running";
  }
  if (s === "COMPLETED" || s === "QUALIFIED_STRATEGY_FOUND" || s === "NO_STRATEGY_QUALIFIED") return "completed";
  if (s === "PAUSED") return "paused";
  if (s === "FAILED") return "failed";
  if (s === "CANCELLED") return "cancelled";
  if (s === "QUEUED") return "queued";
  return "draft";
}

export function statusLabel(status: string | undefined | null): string {
  const s = String(status || "CREATED").toUpperCase();
  return STATUS_LABEL[s] || s;
}

/** Prefer learning status when bound; fall back to lab row status. */
export function resolveRunStatus(lab: LabRunRecord | null | undefined, learning: LearningRecord | null | undefined): string {
  const fromLearning = learning?.status != null ? String(learning.status) : "";
  if (fromLearning) return fromLearning.toUpperCase();
  return String(lab?.status || "CREATED").toUpperCase();
}

export function actionAvailability(status: string | undefined | null): ActionAvailability {
  const s = String(status || "CREATED").toUpperCase();
  const terminal = s === "COMPLETED" || s === "FAILED" || s === "CANCELLED" || s === "QUALIFIED_STRATEGY_FOUND" || s === "NO_STRATEGY_QUALIFIED";
  return {
    canStart: s === "CREATED" || s === "QUEUED",
    canPause: s === "RUNNING" || s === "TRAIN" || s === "VALIDATING" || s === "ROBUSTNESS" || s === "SEALED_EVALUATION" || s === "QUEUED",
    canResume: s === "PAUSED",
    canCancel: !terminal && s !== "CANCELLED",
  };
}

export function progressPct(used: number | null, budget: number | null): number | null {
  if (used == null || budget == null || budget <= 0) return null;
  return Math.min(100, Math.max(0, (used / budget) * 100));
}

function metricFromStage(stage: Record<string, unknown> | undefined, key: string): number | null {
  if (!stage) return null;
  const metrics = asRecord(stage.metrics);
  if (!metrics) {
    // fitness_score is often top-level on stage_results
    if (key === "fitness_score") return asNum(stage.fitness_score);
    return null;
  }
  const raw = metrics[key];
  if (raw && typeof raw === "object") {
    const m = raw as { value?: unknown; status?: string };
    if (m.status === "UNMEASURED") return null;
    return asNum(m.value);
  }
  return asNum(raw);
}

export function extractStageResults(candidate: CandidateRecord | null | undefined): Record<string, Record<string, unknown>> {
  const meta = asRecord(candidate?.metadata);
  const stages = asRecord(meta?.stage_results);
  if (!stages) return {};
  const out: Record<string, Record<string, unknown>> = {};
  for (const [k, v] of Object.entries(stages)) {
    const row = asRecord(v);
    if (row) out[k] = row;
  }
  return out;
}

export function stageMetrics(stage: Record<string, unknown> | undefined): StageMetrics {
  return {
    fitness: metricFromStage(stage, "fitness_score") ?? asNum(stage?.fitness_score),
    sharpe: metricFromStage(stage, "sharpe"),
    maxDrawdownPct: metricFromStage(stage, "max_drawdown_pct"),
    totalReturnPct: metricFromStage(stage, "total_return_pct"),
    winRate: metricFromStage(stage, "win_rate"),
    accepted: stage?.accepted == null ? null : Boolean(stage.accepted),
    failureCategories: stage?.failure_categories ?? null,
  };
}

export function findCandidate(
  candidates: CandidateRecord[],
  id: string | null | undefined,
): CandidateRecord | null {
  if (!id) return null;
  return candidates.find((c) => String(c.candidate_id) === String(id)) || null;
}

function sparkFromFitnessHistory(learnerState: Record<string, unknown> | undefined): number[] {
  const hist = Array.isArray(learnerState?.fitness_history) ? learnerState!.fitness_history : [];
  const pts: number[] = [];
  for (const row of hist) {
    const r = asRecord(row);
    const v = asNum(r?.best_train_fitness);
    if (v != null) pts.push(v);
  }
  return pts;
}

export function candidateCard(
  candidates: CandidateRecord[],
  id: string | null | undefined,
  stageKey: "TRAIN" | "VAL" | "SEALED",
  learnerState?: Record<string, unknown>,
): CandidateCardModel {
  const c = findCandidate(candidates, id);
  if (!c) {
    return {
      id: id ? String(id) : null,
      label: id ? String(id) : "Not recorded",
      family: null,
      generation: null,
      status: null,
      metrics: {
        fitness: null,
        sharpe: null,
        maxDrawdownPct: null,
        totalReturnPct: null,
        winRate: null,
        accepted: null,
        failureCategories: null,
      },
      sparkPoints: sparkFromFitnessHistory(learnerState),
    };
  }
  const stages = extractStageResults(c);
  const stage = stages[stageKey] || stages.TRAIN;
  return {
    id: String(c.candidate_id),
    label: `v${String(c.strategy_version ?? "?")} · ${String(c.family || "unknown")}`,
    family: c.family != null ? String(c.family) : null,
    generation: asNum(c.generation),
    status: c.status != null ? String(c.status) : null,
    metrics: stageMetrics(stage),
    sparkPoints: sparkFromFitnessHistory(learnerState),
  };
}

export function derivePhases(learning: LearningRecord | null | undefined): PhaseState[] {
  const stage = String(learning?.stage || "CREATED").toUpperCase();
  const status = String(learning?.status || "").toUpperCase();
  const order = ["TRAIN", "VALIDATING", "ROBUSTNESS", "SEALED_EVALUATION"];
  const terminalDone = status === "COMPLETED" || stage === "QUALIFIED_STRATEGY_FOUND" || stage === "NO_STRATEGY_QUALIFIED";
  const failed = status === "FAILED" || stage === "FAILED";
  const activeIdx = order.indexOf(stage);

  return [
    { id: "train", label: "Training", key: "TRAIN" },
    { id: "validation", label: "Validation", key: "VALIDATING" },
    { id: "holdout", label: "Holdout / Sealed", key: "SEALED_EVALUATION" },
  ].map((p) => {
    const idx = order.indexOf(p.key);
    let state: PhaseState["state"] = "pending";
    if (failed && (activeIdx === idx || (activeIdx < 0 && p.key === "TRAIN"))) state = "failed";
    else if (terminalDone) state = "done";
    else if (activeIdx === idx) state = "active";
    else if (activeIdx > idx) state = "done";
    else if (stage === "ROBUSTNESS" && p.key === "VALIDATING") state = "done";
    else if (stage === "ROBUSTNESS" && p.key === "SEALED_EVALUATION") state = "pending";
    else if (p.key === "SEALED_EVALUATION" && stage === "ROBUSTNESS") state = "pending";
    // Map robustness into holdout lane as active precursor
    if (p.key === "SEALED_EVALUATION" && stage === "ROBUSTNESS") state = "active";
    if (p.key === "VALIDATING" && stage === "ROBUSTNESS") state = "done";
    return { id: p.id, label: p.label, state };
  });
}

export function deriveOverview(
  learning: LearningRecord | null | undefined,
  candidates: CandidateRecord[],
  generations: GenerationRecord[],
  familyProbs: Record<string, number>,
): OverviewModel {
  const learnerState = asRecord(learning?.learner_state) || {};
  const mutationRates = asRecord(learnerState.mutation_rates) || {};
  const bestTrainId = learning?.best_train_candidate != null ? String(learning.best_train_candidate) : null;
  const bestValId =
    learning?.best_validation_candidate != null ? String(learning.best_validation_candidate) : null;
  const qualifiedId = learning?.qualified_candidate != null ? String(learning.qualified_candidate) : null;

  const fitnessBest: number[] = [];
  const fitnessMedian: number[] = [];
  const diversitySeries: number[] = [];
  const sortedGens = [...generations].sort((a, b) => (asNum(a.generation) || 0) - (asNum(b.generation) || 0));
  for (const g of sortedGens) {
    const best = asNum(g.best_train_fitness);
    const med = asNum(g.median_train_fitness);
    const div = asNum(g.diversity_score);
    if (best != null) fitnessBest.push(best);
    if (med != null) fitnessMedian.push(med);
    if (div != null) diversitySeries.push(div);
  }

  const famEntries = Object.entries(familyProbs).filter(([, v]) => Number(v) > 0);
  const familySlices = famEntries.map(([label, value], i) => ({
    label,
    value: Number(value),
    color: FAMILY_COLORS[i % FAMILY_COLORS.length],
  }));

  const generationRows: GenerationRow[] = sortedGens.map((g) => ({
    generation: asNum(g.generation) ?? 0,
    bestFitness: asNum(g.best_train_fitness),
    medianFitness: asNum(g.median_train_fitness),
    diversity: asNum(g.diversity_score),
    exploration: asNum(g.exploration_rate),
    topCandidateId: g.best_candidate_id != null ? String(g.best_candidate_id) : bestTrainId,
    status: g.status != null ? String(g.status) : "recorded",
  }));

  const qualifiedCard = candidateCard(candidates, qualifiedId, "SEALED", learnerState);

  return {
    currentGeneration: asNum(learning?.current_generation) ?? asNum(learnerState.generation_number) ?? 0,
    generationBudget: asNum(learning?.generation_budget) ?? 0,
    trialsUsed: asNum(learning?.trials_used) ?? 0,
    trialBudget: asNum(learning?.trial_budget) ?? 0,
    populationSize: asNum(learning?.population_size),
    mutationRate: asNum(mutationRates.numeric),
    diversity: asNum(learnerState.diversity_score),
    explorationRate: asNum(learnerState.exploration_rate),
    stageLabel: stageLabel(String(learning?.stage || "")),
    learningStatus: learning?.status != null ? String(learning.status) : null,
    bestTrain: candidateCard(candidates, bestTrainId, "TRAIN", learnerState),
    bestValidation: candidateCard(candidates, bestValId, "VAL", learnerState),
    qualified: { ...qualifiedCard, pending: !qualifiedId },
    fitnessBest,
    fitnessMedian,
    diversitySeries,
    familySlices,
    generationRows,
  };
}

export function runListItem(
  lab: LabRunRecord,
  learningByLab?: LearningRecord | null,
): {
  labId: string;
  name: string;
  status: string;
  tone: RunStatusTone;
  label: string;
  strategyId: string | null;
  sourceId: string | null;
  progress: number | null;
  meta: string;
  generationLabel: string | null;
} {
  const learning = learningByLab || asRecord(lab.learning) || null;
  const status = resolveRunStatus(lab, learning);
  const trialsUsed = asNum(learning?.trials_used);
  const trialBudget = asNum(learning?.trial_budget);
  const curGen = asNum(learning?.current_generation);
  const genBudget = asNum(learning?.generation_budget);
  const metaParts: string[] = [];
  if (lab.strategy_id) metaParts.push(String(lab.strategy_id).slice(0, 16));
  if (lab.source_id) metaParts.push(String(lab.source_id).slice(0, 16));
  const hyp = asRecord(lab.metadata)?.hypothesis;
  if (hyp) metaParts.push(String(hyp).slice(0, 40));

  return {
    labId: String(lab.lab_id),
    name: String(lab.name || lab.lab_id || "Untitled run"),
    status,
    tone: statusTone(status),
    label: statusLabel(status),
    strategyId: lab.strategy_id != null ? String(lab.strategy_id) : null,
    sourceId: lab.source_id != null ? String(lab.source_id) : null,
    progress: progressPct(trialsUsed, trialBudget) ?? progressPct(curGen, genBudget),
    meta: metaParts.join(" · ") || "Research run",
    generationLabel:
      curGen != null && genBudget != null ? `Gen ${curGen}/${genBudget}` : curGen != null ? `Gen ${curGen}` : null,
  };
}

export function countRunsByStatus(labs: LabRunRecord[]): {
  total: number;
  completed: number;
  running: number;
  queued: number;
  failed: number;
  paused: number;
  draft: number;
  cancelled: number;
} {
  const counts = {
    total: labs.length,
    completed: 0,
    running: 0,
    queued: 0,
    failed: 0,
    paused: 0,
    draft: 0,
    cancelled: 0,
  };
  for (const lab of labs) {
    const tone = statusTone(resolveRunStatus(lab, asRecord(lab.learning)));
    if (tone === "completed") counts.completed += 1;
    else if (tone === "running") counts.running += 1;
    else if (tone === "queued") counts.queued += 1;
    else if (tone === "failed") counts.failed += 1;
    else if (tone === "paused") counts.paused += 1;
    else if (tone === "cancelled") counts.cancelled += 1;
    else counts.draft += 1;
  }
  return counts;
}

export function deriveEvents(
  learning: LearningRecord | null | undefined,
  generations: GenerationRecord[],
  lessons: LabRunRecord[],
  candidates: CandidateRecord[],
): DerivedEvent[] {
  const events: DerivedEvent[] = [];
  if (learning?.error) {
    events.push({
      id: "learning-error",
      ts: learning.updated_at != null ? String(learning.updated_at) : null,
      level: "error",
      message: String(learning.error),
      source: "learning",
    });
  }
  if (learning?.created_at) {
    events.push({
      id: "learning-created",
      ts: String(learning.created_at),
      level: "info",
      message: `Learning run ${String(learning.learning_run_id || "")} created · status=${String(learning.status)}`,
      source: "learning",
    });
  }
  if (learning?.updated_at) {
    events.push({
      id: "learning-updated",
      ts: String(learning.updated_at),
      level: "info",
      message: `Stage ${stageLabel(String(learning.stage))} · gen ${String(learning.current_generation)} · trials ${String(learning.trials_used)}/${String(learning.trial_budget)}`,
      source: "learning",
    });
  }
  for (const g of generations) {
    events.push({
      id: `gen-${String(g.generation)}`,
      ts: g.completed_at != null ? String(g.completed_at) : null,
      level: "info",
      message: `Generation ${String(g.generation)} recorded · best=${fmtMetric(g.best_train_fitness)} · median=${fmtMetric(g.median_train_fitness)} · diversity=${fmtMetric(g.diversity_score)}`,
      source: "generation",
    });
  }
  for (const l of lessons) {
    events.push({
      id: `lesson-${String(l.lesson_id)}`,
      ts: l.created_at != null ? String(l.created_at) : null,
      level: String(l.trust || "").toUpperCase().includes("LOW") ? "warn" : "info",
      message: `[${String(l.trust || "lesson")}] ${String(l.claim || "")}`,
      source: "lesson",
    });
  }
  for (const c of candidates.slice(0, 30)) {
    const stages = extractStageResults(c);
    for (const [stageName, stage] of Object.entries(stages)) {
      if (stage.accepted === false) {
        events.push({
          id: `cand-fail-${String(c.candidate_id)}-${stageName}`,
          ts: null,
          level: "warn",
          message: `Candidate ${String(c.candidate_id)} failed ${stageName}${stage.failure_categories ? ` · ${JSON.stringify(stage.failure_categories)}` : ""}`,
          source: "candidate",
        });
      }
    }
  }
  return events.sort((a, b) => String(b.ts || "").localeCompare(String(a.ts || "")));
}

export function durationLabel(startedAt: string | null | undefined, updatedAt: string | null | undefined): string | null {
  if (!startedAt) return null;
  const start = Date.parse(String(startedAt));
  if (!Number.isFinite(start)) return null;
  const end = updatedAt ? Date.parse(String(updatedAt)) : Date.now();
  if (!Number.isFinite(end)) return null;
  const sec = Math.max(0, Math.floor((end - start) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}

export function autonomyCeilingPct(ceiling: string | null | undefined): number | null {
  if (!ceiling) return null;
  const m = String(ceiling).toUpperCase().match(/A(\d+)/);
  if (!m) return null;
  const level = Number(m[1]);
  // A0..A5 → rough gauge; A5 is impossible / blocked in product truth
  return Math.min(100, Math.max(0, (level / 5) * 100));
}
