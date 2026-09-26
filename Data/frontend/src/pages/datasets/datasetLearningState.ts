/**
 * Canonical dataset learning state helpers.
 *
 * Backend DatasetService.learning_state_for_dataset is the source of truth.
 * Job lists may be shown as detail — never as Brain-readiness truth.
 */

export type DatasetLearningCanonicalState =
  | "REGISTERED"
  | "SOURCE_READY"
  | "MATERIALIZING"
  | "VALIDATING"
  | "READY_FOR_INDEX"
  | "INDEX_QUEUED"
  | "INDEXING"
  | "LEARNED"
  | "REBUILDING"
  | "FAILED"
  | "STALE_JOB"
  | "SOURCE_MISSING"
  | "CANCELLED";

export type DatasetLearningState = {
  datasetId: string;
  versionId?: string | null;
  sourceState?: string;
  materializationState?: string;
  validationState?: string;
  indexState?: string;
  brainState?: string;
  jobState?: string | null;
  progress?: number | null;
  phase?: string | null;
  indexId?: string | null;
  documentCount?: number | null;
  chunkCount?: number | null;
  embeddingMode?: string | null;
  semanticEmbeddings?: boolean | null;
  relations?: Record<string, unknown>;
  updatedAt?: string | null;
  stale?: boolean;
  error?: string | null;
  truth?: Record<string, unknown>;
  canonicalState: DatasetLearningCanonicalState | string;
  brainStatus: string;
  label?: string;
  learned?: boolean;
  sourceMissing?: boolean;
  jobId?: string | null;
  usableIndexId?: string | null;
  priorReadyPreserved?: boolean;
  learning?: Record<string, unknown>;
};

/** Surfaces that previously guessed INDEXING from job lists alone. */
export type LearningDisplayStatus =
  | "learned"
  | "indexing"
  | "queued"
  | "rebuilding"
  | "failed"
  | "not_learned"
  | "source_missing"
  | "cancelled"
  | "ready_for_index"
  | "unknown";

const LEARNED_CANONICAL = new Set(["LEARNED", "STALE_JOB"]);

/**
 * Prefer explicit learningState / brain projection from the API.
 * Never invent a permanent 35% progress fallback.
 */
export function resolveLearningState(input: {
  learningState?: DatasetLearningState | null;
  brain?: Partial<DatasetLearningState> | null;
  brainStatus?: string | null;
  learned?: boolean | null;
  canonicalState?: string | null;
}): DatasetLearningState | null {
  if (input.learningState && input.learningState.canonicalState) {
    return input.learningState;
  }
  if (input.brain && (input.brain.canonicalState || input.brain.brainStatus)) {
    return {
      datasetId: String(input.brain.datasetId ?? ""),
      canonicalState: String(
        input.brain.canonicalState ??
          input.canonicalState ??
          mapBrainStatusToCanonical(input.brain.brainStatus ?? input.brainStatus),
      ),
      brainStatus: String(input.brain.brainStatus ?? input.brainStatus ?? "not_learned"),
      learned: Boolean(input.brain.learned ?? input.learned),
      label: input.brain.label,
      progress: input.brain.progress ?? null,
      phase: input.brain.phase ?? null,
      jobId: input.brain.jobId ?? null,
      indexId: input.brain.indexId ?? null,
      stale: Boolean(input.brain.stale),
      sourceMissing: Boolean(input.brain.sourceMissing),
      usableIndexId: input.brain.usableIndexId ?? null,
      priorReadyPreserved: Boolean(input.brain.priorReadyPreserved),
      truth: input.brain.truth,
    };
  }
  if (input.brainStatus || input.canonicalState) {
    const brainStatus = String(input.brainStatus ?? "not_learned");
    return {
      datasetId: "",
      canonicalState: String(input.canonicalState ?? mapBrainStatusToCanonical(brainStatus)),
      brainStatus,
      learned: Boolean(input.learned ?? brainStatus === "learned"),
      progress: null,
    };
  }
  return null;
}

export function mapBrainStatusToCanonical(brainStatus: string | null | undefined): string {
  const s = (brainStatus || "").toLowerCase();
  if (s === "learned") return "LEARNED";
  if (s === "indexing") return "INDEXING";
  if (s === "queued") return "INDEX_QUEUED";
  if (s === "failed") return "FAILED";
  if (s === "not_learned") return "READY_FOR_INDEX";
  return "REGISTERED";
}

export function displayStatusFromLearning(
  state: DatasetLearningState | null | undefined,
): LearningDisplayStatus {
  if (!state) return "unknown";
  const c = String(state.canonicalState || "").toUpperCase();
  if (c === "REBUILDING") return "rebuilding";
  if (LEARNED_CANONICAL.has(c)) return "learned";
  if (c === "INDEXING") return "indexing";
  if (c === "INDEX_QUEUED") return "queued";
  if (c === "FAILED") return "failed";
  if (c === "SOURCE_MISSING") return "source_missing";
  if (c === "CANCELLED") return "cancelled";
  if (c === "READY_FOR_INDEX") return "ready_for_index";
  if (state.learned) return "learned";
  const b = (state.brainStatus || "").toLowerCase();
  if (b === "learned") return "learned";
  if (b === "indexing") return "indexing";
  if (b === "queued") return "queued";
  if (b === "failed") return "failed";
  return "not_learned";
}

/**
 * Progress for UI. Returns null when indeterminate — never a fake 35%.
 */
export function honestLearningProgress(
  state: DatasetLearningState | null | undefined,
): number | null {
  if (!state) return null;
  const c = String(state.canonicalState || "").toUpperCase();
  if (LEARNED_CANONICAL.has(c) && c !== "REBUILDING") return 100;
  if (state.progress == null || !Number.isFinite(Number(state.progress))) return null;
  const pct = Math.round(Number(state.progress) * 100);
  if (pct < 0 || pct > 100) return null;
  return pct;
}

export function learningStatusLabel(
  state: DatasetLearningState | null | undefined,
  fallback = "—",
): string {
  if (!state) return fallback;
  if (state.label) return state.label;
  const d = displayStatusFromLearning(state);
  if (d === "learned") return "Geleerd";
  if (d === "rebuilding") return "Hernieuwd indexeren";
  if (d === "indexing") return "Bezig met leren";
  if (d === "queued") return "In wachtrij";
  if (d === "failed") return "Leren mislukt";
  if (d === "source_missing") return "Bron ontbreekt";
  if (d === "ready_for_index") return "Klaar voor index";
  if (d === "cancelled") return "Geannuleerd";
  return fallback;
}

/**
 * Active index jobs are detail only. They must NOT override LEARNED / READY truth
 * unless the canonical state is REBUILDING / INDEXING / INDEX_QUEUED.
 */
export function shouldShowJobAsLearningTruth(
  state: DatasetLearningState | null | undefined,
): boolean {
  if (!state) return false;
  const c = String(state.canonicalState || "").toUpperCase();
  return c === "INDEXING" || c === "INDEX_QUEUED" || c === "REBUILDING";
}
