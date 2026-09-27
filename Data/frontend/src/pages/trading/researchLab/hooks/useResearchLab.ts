import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../../../api/client";
import type { MarketDataSource, MarketStrategy } from "../../../../types/api";
import {
  asRecord,
  countRunsByStatus,
  deriveEvents,
  deriveOverview,
  derivePhases,
  resolveRunStatus,
  type CandidateRecord,
  type GenerationRecord,
  type LabRunRecord,
  type LearningRecord,
  type ResearchLabTab,
} from "../viewModels";

const POLL_MS = 5000;

export type CreateRunDraft = {
  name: string;
  strategyId: string;
  sourceId: string;
  hypothesis: string;
  autonomyCeiling: string;
  maxCandidates: number;
  maxIterations: number;
  enableLearning: boolean;
  generationBudget: number;
  trialBudget: number;
  populationSize: number;
  notes: string;
};

export const EMPTY_CREATE_DRAFT: CreateRunDraft = {
  name: "",
  strategyId: "",
  sourceId: "",
  hypothesis: "",
  autonomyCeiling: "A1",
  maxCandidates: 10,
  maxIterations: 3,
  enableLearning: true,
  generationBudget: 8,
  trialBudget: 96,
  populationSize: 12,
  notes: "",
};

export type ResearchLabState = {
  loading: boolean;
  learningLoading: boolean;
  refreshing: boolean;
  error: string | null;
  actionError: string | null;
  busyAction: string | null;
  overview: Record<string, unknown> | null;
  labs: LabRunRecord[];
  selectedLabId: string | null;
  selectedLab: LabRunRecord | null;
  learning: LearningRecord | null;
  learningError: string | null;
  candidates: CandidateRecord[];
  generations: GenerationRecord[];
  familyProbs: Record<string, number>;
  lessons: LabRunRecord[];
  runTrials: LabRunRecord[];
  trials: LabRunRecord[];
  trialCount: number;
  costPack: Record<string, unknown> | null;
  feedHealth: Record<string, unknown> | null;
  tab: ResearchLabTab;
  createOpen: boolean;
  createDraft: CreateRunDraft;
  strategies: MarketStrategy[];
  sources: MarketDataSource[];
  catalogError: string | null;
};

export function useResearchLab() {
  const [state, setState] = useState<ResearchLabState>({
    loading: true,
    learningLoading: false,
    refreshing: false,
    error: null,
    actionError: null,
    busyAction: null,
    overview: null,
    labs: [],
    selectedLabId: null,
    selectedLab: null,
    learning: null,
    learningError: null,
    candidates: [],
    generations: [],
    familyProbs: {},
    lessons: [],
    runTrials: [],
    trials: [],
    trialCount: 0,
    costPack: null,
    feedHealth: null,
    tab: "overview",
    createOpen: false,
    createDraft: EMPTY_CREATE_DRAFT,
    strategies: [],
    sources: [],
    catalogError: null,
  });

  const selectedLabIdRef = useRef<string | null>(null);
  selectedLabIdRef.current = state.selectedLabId;
  const mountedRef = useRef(true);

  const patch = useCallback((partial: Partial<ResearchLabState>) => {
    if (!mountedRef.current) return;
    setState((s) => ({ ...s, ...partial }));
  }, []);

  const refreshLearning = useCallback(
    async (labId: string, opts?: { quiet?: boolean }) => {
      if (!opts?.quiet) patch({ learningLoading: true, learningError: null });
      try {
        const [learn, gens, cands, less, runTrials] = await Promise.all([
          api.marketSimLabLearning(labId),
          api.marketSimLabGenerations(labId),
          api.marketSimLabCandidates(labId),
          api.marketSimLabLessons(labId),
          api.marketSimLabRunTrials(labId, 40).catch(() => ({ trials: [] as LabRunRecord[] })),
        ]);
        if (!mountedRef.current || selectedLabIdRef.current !== labId) return;
        const learning = learn.learning || null;
        setState((s) => ({
          ...s,
          learning,
          generations: gens.generation_summaries || [],
          familyProbs: gens.family_probabilities || {},
          candidates: cands.candidates || [],
          lessons: less.lessons || [],
          runTrials: runTrials.trials || [],
          learningLoading: false,
          learningError: null,
          // Mirror learning onto the selected rail card for truthful progress/status
          labs: s.labs.map((lab) =>
            String(lab.lab_id) === labId
              ? {
                  ...lab,
                  learning,
                  status: (learning?.status as string) || lab.status,
                }
              : lab,
          ),
          selectedLab:
            s.selectedLab && String(s.selectedLab.lab_id) === labId
              ? {
                  ...s.selectedLab,
                  learning,
                  status: (learning?.status as string) || s.selectedLab.status,
                }
              : s.selectedLab,
        }));
      } catch (err) {
        if (!mountedRef.current || selectedLabIdRef.current !== labId) return;
        const msg = err instanceof ApiError ? err.message : String(err);
        // 404 / no learning bound → honest empty, not page-level fatal
        const soft = err instanceof ApiError && (err.status === 404 || err.status === 400);
        patch({
          learning: null,
          generations: [],
          familyProbs: {},
          candidates: [],
          lessons: [],
          runTrials: [],
          learningLoading: false,
          learningError: soft
            ? "No learning run bound to this lab. Create a run with learning enabled, or start after enableLearning."
            : msg,
        });
      }
    },
    [patch],
  );

  const refresh = useCallback(
    async (opts?: { quiet?: boolean; keepSelection?: boolean }) => {
      if (opts?.quiet) patch({ refreshing: true });
      else patch({ loading: true });
      try {
        const [ov, tr, cost, labList] = await Promise.all([
          api.marketSimLabOverview(),
          api.marketSimLabTrials({ limit: 40 }),
          api.marketSimLabCostPack({ feeBps: 5, slippageBps: 2, seed: 7 }),
          api.marketSimLabListRuns(50),
        ]);
        if (!mountedRef.current) return;
        let labs = (labList.labs || []) as LabRunRecord[];
        // Enrich rail cards with learning progress (bounded fan-out; truthful get_run)
        const enrichIds = labs.slice(0, 12).map((l) => String(l.lab_id));
        if (enrichIds.length) {
          const details = await Promise.all(
            enrichIds.map((id) => api.marketSimLabGetRun(id).catch(() => null)),
          );
          const byId = new Map<string, LabRunRecord>();
          for (const d of details) {
            const lab = (d?.lab || d) as LabRunRecord | undefined;
            if (lab?.lab_id) byId.set(String(lab.lab_id), lab);
          }
          labs = labs.map((l) => {
            const full = byId.get(String(l.lab_id));
            if (!full) return l;
            const learning = asRecord(full.learning) || null;
            return {
              ...l,
              ...full,
              learning,
              status: (learning?.status as string) || full.status || l.status,
            };
          });
        }
        const prevId = selectedLabIdRef.current;
        let nextId = prevId;
        if (!nextId || !labs.some((l) => String(l.lab_id) === nextId)) {
          nextId = labs[0] ? String(labs[0].lab_id) : null;
        }
        if (opts?.keepSelection && prevId && labs.some((l) => String(l.lab_id) === prevId)) {
          nextId = prevId;
        }
        const selectedLab = nextId ? labs.find((l) => String(l.lab_id) === nextId) || null : null;
        patch({
          overview: ov,
          trials: tr.trials || [],
          trialCount: Number(tr.count || 0),
          costPack: cost.cost_pack || null,
          labs,
          selectedLabId: nextId,
          selectedLab,
          error: null,
          loading: false,
          refreshing: false,
        });
        if (nextId) await refreshLearning(nextId, { quiet: opts?.quiet });
        else {
          patch({
            learning: null,
            generations: [],
            familyProbs: {},
            candidates: [],
            lessons: [],
            runTrials: [],
            learningLoading: false,
            learningError: null,
          });
        }
      } catch (err) {
        if (!mountedRef.current) return;
        patch({
          error: err instanceof ApiError ? err.message : String(err),
          loading: false,
          refreshing: false,
        });
      }
    },
    [patch, refreshLearning],
  );

  const selectLab = useCallback(
    (labId: string | null) => {
      const lab = labId ? state.labs.find((l) => String(l.lab_id) === labId) || null : null;
      patch({
        selectedLabId: labId,
        selectedLab: lab,
        learning: null,
        generations: [],
        familyProbs: {},
        candidates: [],
        lessons: [],
        runTrials: [],
        learningError: null,
      });
      if (labId) void refreshLearning(labId);
    },
    [patch, refreshLearning, state.labs],
  );

  const setTab = useCallback((tab: ResearchLabTab) => patch({ tab }), [patch]);

  const runControl = useCallback(
    async (action: "start" | "pause" | "resume" | "cancel") => {
      const labId = selectedLabIdRef.current;
      if (!labId) return;
      patch({ busyAction: action, actionError: null });
      try {
        if (action === "start") await api.marketSimLabStartRun(labId);
        if (action === "pause") await api.marketSimLabPauseRun(labId);
        if (action === "resume") await api.marketSimLabResumeRun(labId);
        if (action === "cancel") await api.marketSimLabCancelRun(labId);
        await refresh({ quiet: true, keepSelection: true });
        await refreshLearning(labId, { quiet: true });
      } catch (err) {
        patch({
          actionError: err instanceof ApiError ? err.message : String(err),
        });
      } finally {
        patch({ busyAction: null });
      }
    },
    [patch, refresh, refreshLearning],
  );

  const openCreate = useCallback(async () => {
    patch({ createOpen: true, catalogError: null, createDraft: { ...EMPTY_CREATE_DRAFT } });
    try {
      const [strats, src] = await Promise.all([
        api.listMarketStrategies(100),
        api.listMarketData(200),
      ]);
      if (!mountedRef.current) return;
      const readySources = (src.sources || []).filter((s) => s.status === "READY");
      patch({
        strategies: strats.strategies || [],
        sources: readySources,
        createDraft: {
          ...EMPTY_CREATE_DRAFT,
          strategyId: strats.strategies?.[0]?.strategy_id || "",
          sourceId: readySources[0]?.source_id || "",
        },
      });
    } catch (err) {
      patch({
        catalogError: err instanceof ApiError ? err.message : String(err),
      });
    }
  }, [patch]);

  const closeCreate = useCallback(() => patch({ createOpen: false }), [patch]);

  const patchCreateDraft = useCallback(
    (partial: Partial<CreateRunDraft>) => {
      setState((s) => ({ ...s, createDraft: { ...s.createDraft, ...partial } }));
    },
    [],
  );

  const submitCreate = useCallback(async () => {
    const d = state.createDraft;
    if (!d.strategyId || !d.sourceId) {
      patch({ actionError: "Strategy and READY market-data source are required." });
      return;
    }
    patch({ busyAction: "create", actionError: null });
    try {
      const payload: Record<string, unknown> = {
        name: d.name.trim() || undefined,
        strategyId: d.strategyId,
        sourceId: d.sourceId,
        hypothesis: d.hypothesis,
        autonomyCeiling: d.autonomyCeiling,
        maxCandidates: d.maxCandidates,
        maxIterations: d.maxIterations,
        enableLearning: d.enableLearning,
        learning: d.enableLearning
          ? {
              generation_budget: d.generationBudget,
              trial_budget: d.trialBudget,
              population_size: d.populationSize,
            }
          : undefined,
        metadata: {
          autonomy_ceiling: d.autonomyCeiling,
          ...(d.notes.trim() ? { notes: d.notes.trim() } : {}),
        },
      };
      const res = await api.marketSimLabCreateRun(payload);
      const lab = (res.lab || res) as LabRunRecord;
      const newId = String(lab.lab_id || "");
      patch({ createOpen: false, busyAction: null });
      await refresh({ quiet: true });
      if (newId) {
        selectedLabIdRef.current = newId;
        patch({ selectedLabId: newId });
        await refreshLearning(newId);
      }
    } catch (err) {
      patch({
        busyAction: null,
        actionError: err instanceof ApiError ? err.message : String(err),
      });
    }
  }, [patch, refresh, refreshLearning, state.createDraft]);

  const probeFeed = useCallback(async () => {
    patch({ busyAction: "probe", actionError: null });
    try {
      const res = await api.marketSimLabFeedHealth({
        feedId: "paper-probe",
        lastTickTs: new Date(Date.now() - 5000).toISOString(),
        asOf: new Date().toISOString(),
        maxStalenessSeconds: 120,
        provenance: "ui_probe",
      });
      patch({ feedHealth: res.feed_health, busyAction: null });
    } catch (err) {
      patch({
        busyAction: null,
        actionError: err instanceof ApiError ? err.message : String(err),
      });
    }
  }, [patch]);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  // Poll while selected run is active — single interval, cleaned up on unmount/status change
  const pollStatus = resolveRunStatus(state.selectedLab, state.learning);
  const shouldPoll =
    pollStatus === "RUNNING" ||
    pollStatus === "QUEUED" ||
    pollStatus === "TRAIN" ||
    pollStatus === "VALIDATING" ||
    pollStatus === "ROBUSTNESS" ||
    pollStatus === "SEALED_EVALUATION";

  useEffect(() => {
    if (!shouldPoll || !state.selectedLabId) return;
    const id = window.setInterval(() => {
      void refresh({ quiet: true, keepSelection: true });
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [shouldPoll, state.selectedLabId, refresh]);

  const overviewModel = useMemo(
    () => deriveOverview(state.learning, state.candidates, state.generations, state.familyProbs),
    [state.learning, state.candidates, state.generations, state.familyProbs],
  );

  const phases = useMemo(() => derivePhases(state.learning), [state.learning]);

  const events = useMemo(
    () => deriveEvents(state.learning, state.generations, state.lessons, state.candidates),
    [state.learning, state.generations, state.lessons, state.candidates],
  );

  const runCounts = useMemo(() => countRunsByStatus(state.labs), [state.labs]);

  const live = asRecord(state.overview?.live_trading) || {};
  const truth = asRecord(state.overview?.truth) || {};
  const qualification = asRecord(state.overview?.qualification);

  return {
    state,
    overviewModel,
    phases,
    events,
    runCounts,
    live,
    truth,
    qualification,
    refresh,
    selectLab,
    setTab,
    runControl,
    openCreate,
    closeCreate,
    patchCreateDraft,
    submitCreate,
    probeFeed,
    clearActionError: () => patch({ actionError: null }),
  };
}
