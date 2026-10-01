/**
 * Strategy Lab (WAVE 5) — single composition hook for the native, pixel-exact page.
 *
 * Absorbs Research Lab + Strategieën + Simulatie data sources behind one hook so
 * StrategyLabPage/View/Drawers never talk to `fetch` directly. Every value is
 * derived from real backend responses; anything the backend does not measure
 * renders literally as "UNMEASURED" (never invented client-side).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../../../api/client";
import { marketSimLabApi } from "../../../../api/domains/marketSimLab";
import type {
  MarketDataSource,
  MarketSimLiveState,
  MarketSimPaperDeployment,
  MarketSimRun,
  MarketStrategy,
  MarketStrategyVersion,
  PaperPortfolio,
} from "../../../../types/api";
import { UNMEASURED, asNumber, asRec } from "../commandHub/hubFormat";

/* ---------------------------------------------------------------- helpers */

function asStr(v: unknown, fallback = UNMEASURED): string {
  if (typeof v === "string" && v.trim()) return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return fallback;
}

function upper(v: unknown): string {
  return asStr(v, "").toUpperCase();
}

function fmtMetric(raw: unknown, pct = false): string {
  const rec = asRec(raw);
  if (rec) {
    if (rec.status === "UNMEASURED" || rec.value == null) return UNMEASURED;
    const n = asNumber(rec.value);
    if (n == null) return UNMEASURED;
    return pct ? `${(n * 100).toFixed(1)}%` : n.toFixed(3);
  }
  const n = asNumber(raw);
  if (n == null) return UNMEASURED;
  return pct ? `${(n * 100).toFixed(1)}%` : n.toFixed(3);
}

function fmtUsd(v: unknown): string {
  const n = asNumber(v);
  if (n == null) return UNMEASURED;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function humanizeMode(mode: string): string {
  if (!mode) return "Onbekend";
  return mode
    .split("_")
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(" ");
}

const ACTIVE_LAB_STATUSES = ["RUNNING", "ACTIVE", "LEARNING", "STARTED"];

/* --------------------------------------------------------------- KPI/ladder */

export type StrategyLabKpi = { id: string; label: string; value: string; note: string; href?: string };
export type LadderStep = { id: string; label: string; value: string; note: string };

/* -------------------------------------------------------------- Discovery */

export type DiscoveryRow = {
  id: string;
  name: string;
  family: string;
  market: string;
  mode: string;
  sharpe: string;
  winRate: string;
  maxDrawdown: string;
  paperPnl: string;
  confidence: string;
  status: string;
  strategyId: string | null;
  labId: string | null;
  createdAt: string;
  raw: Record<string, unknown>;
};

export type PipelineStage = { id: string; label: string; active: number; total: number };

export type ResearchSessionRow = {
  id: string;
  name: string;
  strategyId: string | null;
  status: string;
  outcome: string;
  candidateCount: number;
  createdAt: string;
};

export type PaperValidationSnapshot = {
  deployments: number;
  shadow: number;
  autonomous: number;
  portfolios: number;
  bestEquity: string;
  bestReturnPct: string;
  recent: Array<{ id: string; label: string; status: string; mode: string }>;
};

/* -------------------------------------------------------------- Lab detail */

export type LabDetailBundle = {
  labId: string;
  loading: boolean;
  error: string | null;
  run: Record<string, unknown> | null;
  candidates: Record<string, unknown>[];
  qualifiedCandidate: string | null;
  bestTrainCandidate: string | null;
  bestValidationCandidate: string | null;
  generations: Record<string, unknown>[];
  currentGeneration: number | null;
  familyProbabilities: Record<string, number>;
  hypotheses: Record<string, unknown>[];
  perception: Record<string, unknown> | null;
  perceptionStatus: string;
  lessons: Record<string, unknown>[];
  learning: Record<string, unknown> | null;
  trials: Record<string, unknown>[];
  costPack: Record<string, unknown> | null;
  explain: Record<string, unknown> | null;
  explainCandidateId: string | null;
  explainError: string | null;
};

function emptyLabDetail(labId: string): LabDetailBundle {
  return {
    labId,
    loading: true,
    error: null,
    run: null,
    candidates: [],
    qualifiedCandidate: null,
    bestTrainCandidate: null,
    bestValidationCandidate: null,
    generations: [],
    currentGeneration: null,
    familyProbabilities: {},
    hypotheses: [],
    perception: null,
    perceptionStatus: "UNMEASURED",
    lessons: [],
    learning: null,
    trials: [],
    costPack: null,
    explain: null,
    explainCandidateId: null,
    explainError: null,
  };
}

/* ------------------------------------------------------------------ hook */

export function useStrategyLabData() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [labs, setLabs] = useState<Record<string, unknown>[]>([]);
  const [trials, setTrials] = useState<Record<string, unknown>[]>([]);
  const [families, setFamilies] = useState<Record<string, unknown>[]>([]);
  const [strategies, setStrategies] = useState<MarketStrategy[]>([]);
  const [sources, setSources] = useState<MarketDataSource[]>([]);
  const [portfolios, setPortfolios] = useState<PaperPortfolio[]>([]);
  const [deployments, setDeployments] = useState<MarketSimPaperDeployment[]>([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, labList, trialList, fam, strat, data, ports, deps] = await Promise.all([
        marketSimLabApi.marketSimLabOverview().catch(() => null),
        marketSimLabApi.marketSimLabListRuns(100).catch(() => ({ labs: [] as Record<string, unknown>[] })),
        marketSimLabApi.marketSimLabTrials({ limit: 150 }).catch(() => ({
          trials: [] as Record<string, unknown>[],
          count: 0,
          truth: {},
        })),
        marketSimLabApi.marketSimStrategyFamilies().catch(() => ({
          families: [] as Record<string, unknown>[],
          generatable: [],
          count: 0,
        })),
        api.listMarketStrategies(200).catch(() => ({ strategies: [] as MarketStrategy[] })),
        api.listMarketData(200).catch(() => ({ sources: [] as MarketDataSource[] })),
        api.listPortfolios(50).catch(() => ({ portfolios: [] as PaperPortfolio[] })),
        api.listPaperDeployments({ limit: 100 }).catch(() => ({
          deployments: [] as MarketSimPaperDeployment[],
          truth: {},
        })),
      ]);
      setOverview(ov);
      setLabs(labList.labs || []);
      setTrials(trialList.trials || []);
      setFamilies(fam.families || []);
      setStrategies(strat.strategies || []);
      setSources(data.sources || []);
      setPortfolios(ports.portfolios || []);
      setDeployments(deps.deployments || []);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Failed to load Strategy Lab");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const strategyById = useMemo(() => {
    const map = new Map<string, MarketStrategy>();
    for (const s of strategies) map.set(s.strategy_id, s);
    return map;
  }, [strategies]);

  const sourceById = useMemo(() => {
    const map = new Map<string, MarketDataSource>();
    for (const s of sources) map.set(s.source_id, s);
    return map;
  }, [sources]);

  const labById = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>();
    for (const l of labs) map.set(String(l.lab_id ?? ""), l);
    return map;
  }, [labs]);

  /* ---------------------------------------------------------- derived KPIs */

  const qualificationState = String((overview as { qualificationState?: string } | null)?.qualificationState ?? "UNMEASURED");
  const liveTrading = "BLOCKED";

  const trialLedgerCount = asNumber((overview as { trial_ledger_count?: number } | null)?.trial_ledger_count) ?? trials.length;
  const activeLabs = labs.filter((l) => ACTIVE_LAB_STATUSES.includes(upper(l.status)));
  const qualifiedLabs = labs.filter((l) => upper(l.outcome) === "QUALIFIED_STRATEGY_FOUND");
  const readySources = sources.filter((s) => s.status === "READY");
  const totalBars = readySources.reduce((sum, s) => sum + (s.bar_count || 0), 0);
  const autonomousDeployments = deployments.filter((d) => d.mode === "autonomous_paper");

  const kpis: StrategyLabKpi[] = [
    {
      id: "candidates",
      label: "Candidate Strategieën",
      value: String(trialLedgerCount),
      note: "Trial ledger (append-only)",
    },
    {
      id: "experiments",
      label: "Actieve Experimenten",
      value: String(activeLabs.length),
      note: `${labs.length} research sessies totaal`,
    },
    {
      id: "sessions",
      label: "Research Sessies",
      value: String(labs.length),
      note: "market_sim_agent_labs",
    },
    {
      id: "paper",
      label: "Paper Validaties",
      value: String(deployments.length),
      note: `${portfolios.length} paper portefeuilles`,
    },
    {
      id: "promotion",
      label: "Promotie Klaar",
      value: String(qualifiedLabs.length),
      note: "QUALIFIED_STRATEGY_FOUND",
    },
    {
      id: "sources",
      label: "Databronnen",
      value: `${readySources.length}/${sources.length || 0}`,
      note: totalBars ? `${totalBars.toLocaleString("nl-NL")} bars geïndexeerd` : "Nog geen bars geïndexeerd",
    },
  ];

  const ladder: LadderStep[] = [
    { id: "discovered", label: "Ontdekt", value: String(trialLedgerCount), note: "Trial ledger" },
    { id: "researching", label: "Onderzoekend", value: String(activeLabs.length), note: "Lab runs actief" },
    { id: "backtesting", label: "Backtesten", value: String(labs.length), note: "Lab runs totaal" },
    { id: "paper", label: "Paper Validatie", value: String(deployments.length), note: "Shadow + autonomous" },
    { id: "promotable", label: "Promotie Gereed", value: String(qualifiedLabs.length), note: "Qualification PASS" },
    { id: "promoted", label: "Gepromoveerd", value: String(autonomousDeployments.length), note: "Autonomous paper" },
  ];

  /* ------------------------------------------------------ discovery table */

  const discovery: DiscoveryRow[] = trials.map((t) => {
    const config = asRec(t.config) ?? {};
    const results = asRec(t.results) ?? {};
    const metrics = asRec(results.metrics) ?? results;
    const meta = asRec(t.metadata) ?? {};
    const strategyId = t.strategy_id != null ? String(t.strategy_id) : null;
    const strategy = strategyId ? strategyById.get(strategyId) : undefined;
    const sourceIdRaw = config.source_id ?? config.sourceId ?? meta.source_id;
    const source = sourceIdRaw ? sourceById.get(String(sourceIdRaw)) : undefined;
    const labIdRaw = meta.lab_id ?? config.lab_id ?? null;
    return {
      id: String(t.trial_id ?? ""),
      name: strategy?.name ?? asStr(meta.strategy_name, strategyId ? `Strategie ${strategyId.slice(0, 8)}` : "Onbekend"),
      family: asStr(meta.family ?? config.family, "—"),
      market: source ? `${source.symbol} ${source.timeframe}` : asStr(meta.symbol ?? config.symbol, "—"),
      mode: humanizeMode(asStr(meta.proposal_method ?? config.mode, "—")),
      sharpe: fmtMetric(metrics.sharpe),
      winRate: fmtMetric(metrics.win_rate, true),
      maxDrawdown: fmtMetric(metrics.max_drawdown_pct ?? metrics.max_drawdown, true),
      paperPnl: fmtUsd(metrics.total_return ?? metrics.pnl),
      confidence: fmtMetric(meta.confidence ?? results.confidence, true),
      status: asStr(t.status, "UNKNOWN"),
      strategyId,
      labId: labIdRaw ? String(labIdRaw) : null,
      createdAt: asStr(t.created_at, "—"),
      raw: t,
    };
  });

  const matchLabForStrategy = useCallback(
    (strategyId: string | null): Record<string, unknown> | null => {
      if (!strategyId) return null;
      const hit = labs.find((l) => String(l.strategy_id ?? "") === strategyId);
      return hit ?? null;
    },
    [labs],
  );

  /* ------------------------------------------------------ experiment pipeline */

  const pipeline: PipelineStage[] = useMemo(() => {
    const byMode = new Map<string, { active: number; total: number }>();
    for (const l of labs) {
      const mode = asStr((l.metadata as Record<string, unknown> | undefined)?.run_mode ?? l.run_mode, "ONBEKEND");
      const entry = byMode.get(mode) ?? { active: 0, total: 0 };
      entry.total += 1;
      if (ACTIVE_LAB_STATUSES.includes(upper(l.status))) entry.active += 1;
      byMode.set(mode, entry);
    }
    return Array.from(byMode.entries()).map(([mode, v]) => ({
      id: mode,
      label: humanizeMode(mode),
      active: v.active,
      total: v.total,
    }));
  }, [labs]);

  /* ------------------------------------------------------ research sessions */

  const researchSessions: ResearchSessionRow[] = labs.slice(0, 40).map((l) => ({
    id: String(l.lab_id ?? ""),
    name: asStr(l.name, `Lab ${String(l.lab_id ?? "").slice(0, 8)}`),
    strategyId: l.strategy_id != null ? String(l.strategy_id) : null,
    status: asStr(l.status, "UNKNOWN"),
    outcome: asStr(l.outcome, "IN_PROGRESS"),
    candidateCount: Array.isArray(l.candidates) ? l.candidates.length : 0,
    createdAt: asStr(l.updated_at ?? l.created_at, "—"),
  }));

  /* ------------------------------------------------------ paper validation */

  const paperValidation: PaperValidationSnapshot = useMemo(() => {
    const shadow = deployments.filter((d) => d.mode === "shadow").length;
    const autonomous = deployments.filter((d) => d.mode === "autonomous_paper").length;
    const bestPortfolio = portfolios.reduce<PaperPortfolio | null>((best, p) => {
      const eq = asNumber(p.equity);
      const bestEq = best ? asNumber(best.equity) : null;
      if (eq == null) return best;
      if (bestEq == null || eq > bestEq) return p;
      return best;
    }, null);
    const bestReturnPct = bestPortfolio
      ? (() => {
          const initial = asNumber(bestPortfolio.initial_equity);
          const eq = asNumber(bestPortfolio.equity);
          if (initial == null || eq == null || initial === 0) return UNMEASURED;
          return `${(((eq - initial) / initial) * 100).toFixed(2)}%`;
        })()
      : UNMEASURED;
    return {
      deployments: deployments.length,
      shadow,
      autonomous,
      portfolios: portfolios.length,
      bestEquity: bestPortfolio ? fmtUsd(bestPortfolio.equity) : UNMEASURED,
      bestReturnPct,
      recent: deployments.slice(0, 8).map((d) => ({
        id: d.deployment_id,
        label: `${d.strategy_asset_id.slice(0, 8)} v${d.strategy_version}`,
        status: d.status,
        mode: d.mode ?? "—",
      })),
    };
  }, [deployments, portfolios]);

  /* --------------------------------------------------------- lab detail API */

  const [labDetails, setLabDetails] = useState<Record<string, LabDetailBundle>>({});
  const inFlightLabs = useRef<Set<string>>(new Set());

  const loadLabDetail = useCallback(async (labId: string, force = false) => {
    if (!labId) return;
    if (!force && inFlightLabs.current.has(labId)) return;
    inFlightLabs.current.add(labId);
    setLabDetails((prev) => ({ ...prev, [labId]: prev[labId] ? { ...prev[labId], loading: true } : emptyLabDetail(labId) }));
    try {
      const [runRes, candRes, genRes, hypRes, percRes, lessonRes, learnRes, trialRes] = await Promise.all([
        marketSimLabApi.marketSimLabGetRun(labId).catch(() => null),
        marketSimLabApi.marketSimLabCandidates(labId).catch(() => null),
        marketSimLabApi.marketSimLabGenerations(labId).catch(() => null),
        marketSimLabApi.marketSimLabHypotheses(labId, 50).catch(() => null),
        marketSimLabApi.marketSimLabPerception(labId).catch(() => null),
        marketSimLabApi.marketSimLabLessons(labId).catch(() => null),
        marketSimLabApi.marketSimLabLearning(labId).catch(() => null),
        marketSimLabApi.marketSimLabRunTrials(labId, 100).catch(() => null),
      ]);
      setLabDetails((prev) => ({
        ...prev,
        [labId]: {
          labId,
          loading: false,
          error: null,
          run: runRes?.lab ?? null,
          candidates: candRes?.candidates ?? [],
          qualifiedCandidate: (candRes?.qualified_candidate as string | null) ?? null,
          bestTrainCandidate: (candRes?.best_train_candidate as string | null) ?? null,
          bestValidationCandidate: (candRes?.best_validation_candidate as string | null) ?? null,
          generations: genRes?.generation_summaries ?? [],
          currentGeneration: genRes?.current_generation ?? null,
          familyProbabilities: genRes?.family_probabilities ?? {},
          hypotheses: hypRes?.hypotheses ?? [],
          perception: percRes?.perception ?? null,
          perceptionStatus: percRes?.status ?? "UNMEASURED",
          lessons: lessonRes?.lessons ?? [],
          learning: learnRes?.learning ?? null,
          trials: trialRes?.trials ?? [],
          costPack: prev[labId]?.costPack ?? null,
          explain: prev[labId]?.explain ?? null,
          explainCandidateId: prev[labId]?.explainCandidateId ?? null,
          explainError: prev[labId]?.explainError ?? null,
        },
      }));
    } catch (err) {
      setLabDetails((prev) => ({
        ...prev,
        [labId]: {
          ...(prev[labId] ?? emptyLabDetail(labId)),
          loading: false,
          error: err instanceof Error ? err.message : "Failed to load lab detail",
        },
      }));
    } finally {
      inFlightLabs.current.delete(labId);
    }
  }, []);

  const explainCandidate = useCallback(async (labId: string, candidateId: string) => {
    setLabDetails((prev) => ({
      ...prev,
      [labId]: { ...(prev[labId] ?? emptyLabDetail(labId)), explainCandidateId: candidateId, explainError: null },
    }));
    try {
      const res = await marketSimLabApi.marketSimLabExplainCandidate(labId, candidateId);
      setLabDetails((prev) => ({
        ...prev,
        [labId]: { ...(prev[labId] ?? emptyLabDetail(labId)), explain: res, explainCandidateId: candidateId },
      }));
    } catch (err) {
      setLabDetails((prev) => ({
        ...prev,
        [labId]: {
          ...(prev[labId] ?? emptyLabDetail(labId)),
          explainError: err instanceof Error ? err.message : "Explain failed",
        },
      }));
    }
  }, []);

  const loadCostPack = useCallback(
    async (labId: string, params?: { feeBps?: number; slippageBps?: number; seed?: number }) => {
      try {
        const res = await marketSimLabApi.marketSimLabCostPack(params);
        setLabDetails((prev) => ({
          ...prev,
          [labId]: { ...(prev[labId] ?? emptyLabDetail(labId)), costPack: res.cost_pack },
        }));
      } catch {
        /* keep prior cost pack on failure */
      }
    },
    [],
  );

  const createLabRun = useCallback(
    async (payload: Record<string, unknown>, autostart = true) => {
      const { lab } = await marketSimLabApi.marketSimLabCreateRun(payload);
      setLabs((prev) => [lab, ...prev]);
      const labId = String(lab.lab_id ?? "");
      if (autostart && labId) {
        try {
          await marketSimLabApi.marketSimLabStartRun(labId);
        } catch {
          /* creation still succeeds; start can be retried from drawer */
        }
      }
      await refresh();
      return lab;
    },
    [refresh],
  );

  const pauseLab = useCallback(
    async (labId: string) => {
      await marketSimLabApi.marketSimLabPauseRun(labId);
      await refresh();
    },
    [refresh],
  );
  const resumeLab = useCallback(
    async (labId: string) => {
      await marketSimLabApi.marketSimLabResumeRun(labId);
      await refresh();
    },
    [refresh],
  );
  const cancelLab = useCallback(
    async (labId: string) => {
      await marketSimLabApi.marketSimLabCancelRun(labId);
      await refresh();
    },
    [refresh],
  );

  /* ------------------------------------------------------ strategy builder */

  const [strategyVersions, setStrategyVersions] = useState<Record<string, MarketStrategyVersion[]>>({});

  const loadStrategyVersions = useCallback(async (strategyId: string) => {
    try {
      const detail = await api.getMarketStrategy(strategyId);
      setStrategyVersions((prev) => ({ ...prev, [strategyId]: detail.versions }));
      return detail.versions;
    } catch {
      return [];
    }
  }, []);

  const createStrategy = useCallback(
    async (payload: Parameters<typeof api.createMarketStrategy>[0]) => {
      const created = await api.createMarketStrategy(payload);
      setStrategies((prev) => [created.strategy, ...prev]);
      return created;
    },
    [],
  );

  const versionStrategy = useCallback(
    async (strategyId: string, payload: Parameters<typeof api.versionMarketStrategy>[1]) => {
      const updated = await api.versionMarketStrategy(strategyId, payload);
      setStrategies((prev) =>
        prev.map((s) => (s.strategy_id === updated.strategy.strategy_id ? updated.strategy : s)),
      );
      setStrategyVersions((prev) => ({
        ...prev,
        [strategyId]: [updated.version, ...(prev[strategyId] ?? [])],
      }));
      return updated;
    },
    [],
  );

  /* ------------------------------------------------------ simulation runs */

  const [simRuns, setSimRuns] = useState<MarketSimRun[]>([]);
  const [simLive, setSimLive] = useState<MarketSimLiveState | null>(null);
  const [selectedSimRunId, setSelectedSimRunId] = useState<string | null>(null);

  const refreshSimRuns = useCallback(async () => {
    try {
      const { runs } = await api.listMarketSimRuns(50);
      setSimRuns(runs);
      return runs;
    } catch {
      return [] as MarketSimRun[];
    }
  }, []);

  useEffect(() => {
    if (!selectedSimRunId) {
      setSimLive(null);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const state = await api.getMarketSimLive(selectedSimRunId);
        if (!cancelled) setSimLive(state);
      } catch {
        /* transient poll errors ignored */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [selectedSimRunId]);

  const createSimRun = useCallback(
    async (payload: Parameters<typeof api.createMarketSimRun>[0]) => {
      const { run } = await api.createMarketSimRun(payload);
      setSimRuns((prev) => [run, ...prev]);
      setSelectedSimRunId(run.run_id);
      return run;
    },
    [],
  );

  const startSimRun = useCallback(async (runId: string) => {
    await api.startMarketSimRun(runId);
    await refreshSimRuns();
  }, [refreshSimRuns]);
  const pauseSimRun = useCallback(async (runId: string) => {
    await api.pauseMarketSimRun(runId);
    await refreshSimRuns();
  }, [refreshSimRuns]);
  const stepSimRun = useCallback(async (runId: string) => {
    await api.stepMarketSimRun(runId);
    await refreshSimRuns();
  }, [refreshSimRuns]);
  const stopSimRun = useCallback(async (runId: string) => {
    await api.stopMarketSimRun(runId);
    await refreshSimRuns();
  }, [refreshSimRuns]);

  useEffect(() => {
    void refreshSimRuns();
  }, [refreshSimRuns]);

  /* --------------------------------------------------------- qualification */

  const getQualificationGates = useCallback(async (qualificationId: string) => {
    return api.getQualificationGates(qualificationId);
  }, []);
  const getQualificationRun = useCallback(async (qualificationId: string) => {
    return api.getQualificationRun(qualificationId);
  }, []);

  return {
    loading,
    error,
    overview,
    kpis,
    ladder,
    discovery,
    pipeline,
    researchSessions,
    paperValidation,
    labs,
    labById,
    strategies,
    strategyById,
    sources,
    families,
    portfolios,
    deployments,
    qualificationState,
    liveTrading,
    refresh,
    matchLabForStrategy,

    labDetails,
    loadLabDetail,
    explainCandidate,
    loadCostPack,
    createLabRun,
    pauseLab,
    resumeLab,
    cancelLab,

    strategyVersions,
    loadStrategyVersions,
    createStrategy,
    versionStrategy,

    simRuns,
    simLive,
    selectedSimRunId,
    setSelectedSimRunId,
    createSimRun,
    startSimRun,
    pauseSimRun,
    stepSimRun,
    stopSimRun,
    refreshSimRuns,

    getQualificationGates,
    getQualificationRun,
  };
}

export type StrategyLabData = ReturnType<typeof useStrategyLabData>;
