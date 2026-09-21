"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { consumeCodingHandoff } from "@/lib/chat-handoff";
import { CODING_JOB_POLL_MS } from "@/lib/ui-poll-intervals";
import {
  AppSettings,
  formatDate,
  hadesApi,
  HadesApiError,
  ModelProfile,
  SystemHealth,
} from "@/lib/hades-api";
import {
  buildStatusLabel,
  collectBuildLogs,
  collectReviewDiffText,
  extractChangedFiles,
  extractCodingFailureReason,
  extractFrontierStatus,
  evaluateCodingPreflightClient,
  formatOmnirouteRouting,
  JOB_SUCCESS,
  JOB_TERMINAL,
  mergeJobEvents,
  parseArgv,
  parseContextFiles,
  parseEdits,
  persistActiveJobId,
  readCodingJobFromLocation,
  readJobEventCursor,
  readPersistedActiveJobId,
  TEST_SUITES,
  writeCodingJobToLocation,
  writeJobEventCursor,
  type CodingAutonomyProfile,
  type CodingStrategy,
  type CodingTestSuite,
} from "@/components/hades/features/coding/coding-runtime-core";

export type SessionRun = {
  id: string;
  title: string;
  sourceRepo: string;
  testSuite: CodingTestSuite;
  status: string;
  startedAt: string;
  result: Record<string, unknown> | null;
  error: string | null;
};

export type SymbolHit = {
  name: string;
  kind: string;
  path: string;
  line: number;
};

export type TerminalResult = {
  argv: string[];
  cwd: string;
  exit_code: number;
  duration_ms: number;
  stdout: string;
  stderr: string;
  status: string;
};

export type OmnirouteStatus = {
  installed: boolean;
  enabled: boolean;
  ready: boolean;
  usable: boolean;
  toggle_enabled: boolean;
  enabled_by_default?: boolean;
  status_code: string;
  status_label: string;
  reason: string;
  explanation?: string;
};

export type ReleaseReport = {
  overall: string;
  gates: Array<{ id: string; label: string; status: string; detail?: string }>;
  note?: string;
  smoke?: Record<string, unknown>;
  platform?: string;
  what_broke?: Array<{ kind?: string; label?: string } | string>;
  verify_stages?: Array<{ id?: string; label?: string; status?: string; detail?: string }>;
};

export type HadesCodingRuntime = ReturnType<typeof useHadesCodingRuntime>;

export function useHadesCodingRuntime() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [profile, setProfile] = useState<ModelProfile | null>(null);
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);

  const [runs, setRuns] = useState<SessionRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const [sourceRepo, setSourceRepo] = useState("");
  const [testSuite, setTestSuite] = useState<CodingTestSuite>("auto");
  const [editsJson, setEditsJson] = useState("");
  const [maxAttempts, setMaxAttempts] = useState("2");
  const [building, setBuilding] = useState(false);

  const [conflicts, setConflicts] = useState<Array<Record<string, unknown>> | null>(null);
  const [applyPreview, setApplyPreview] = useState<Record<string, unknown> | null>(null);
  const [applyResult, setApplyResult] = useState<Record<string, unknown> | null>(null);
  const [conflictsLoading, setConflictsLoading] = useState(false);
  const [applyApproved, setApplyApproved] = useState(false);
  const [mutatingRun, setMutatingRun] = useState<string | null>(null);

  const [terminalArgv, setTerminalArgv] = useState("python --version");
  const [terminalCwd, setTerminalCwd] = useState("");
  const [terminalRunning, setTerminalRunning] = useState(false);
  const [terminalResult, setTerminalResult] = useState<TerminalResult | null>(null);
  const [terminalError, setTerminalError] = useState<string | null>(null);

  const [symbolsPath, setSymbolsPath] = useState("");
  const [symbolsQuery, setSymbolsQuery] = useState("");
  const [symbolsLoading, setSymbolsLoading] = useState(false);
  const [symbolsRefreshing, setSymbolsRefreshing] = useState(false);
  const [symbols, setSymbols] = useState<SymbolHit[]>([]);
  const [symbolsMeta, setSymbolsMeta] = useState<{
    root: string;
    files_scanned: number;
    truncated: boolean;
    from_cache?: boolean;
    embeddings?: boolean;
    embeddings_note?: string;
    tree?: { root: string; entries: Array<{ name: string; kind: string; code_files: number }>; truncated?: boolean };
  } | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolHit | null>(null);
  const [definitionHits, setDefinitionHits] = useState<Array<{ name: string; kind: string; path: string; line: number }>>([]);
  const [referenceHits, setReferenceHits] = useState<Array<{ name: string; kind: string; path: string; line: number; snippet?: string }>>([]);
  const [outline, setOutline] = useState<Record<string, unknown> | null>(null);
  const [lspLoading, setLspLoading] = useState<"definition" | "references" | "outline" | null>(null);

  const [fsRelative, setFsRelative] = useState("");
  const [fsFilter, setFsFilter] = useState("");
  const [fsLoading, setFsLoading] = useState(false);
  const [fsEntries, setFsEntries] = useState<Array<{ name: string; path: string; kind: string; size?: number | null; dirty?: boolean }>>([]);
  const [fsMeta, setFsMeta] = useState<{ root: string; relative: string; truncated: boolean } | null>(null);
  const [fsPreview, setFsPreview] = useState<{ path: string; content: string; truncated: boolean } | null>(null);
  const [fsPreviewLoading, setFsPreviewLoading] = useState(false);

  const [gitLoading, setGitLoading] = useState(false);
  const [gitStatus, setGitStatus] = useState<Record<string, unknown> | null>(null);
  const [gitCommitMsg, setGitCommitMsg] = useState("");
  const [gitCommitApproved, setGitCommitApproved] = useState(false);
  const [gitCommitting, setGitCommitting] = useState(false);

  const [composerGoal, setComposerGoal] = useState("");
  const [repairWavesJson, setRepairWavesJson] = useState("");
  const [composerPlan, setComposerPlan] = useState<Record<string, unknown> | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planApproved, setPlanApproved] = useState(false);
  const [codingStrategy, setCodingStrategy] = useState<CodingStrategy>("fast");
  const [autonomyProfile, setAutonomyProfile] = useState<CodingAutonomyProfile>("reviewable_result");
  const [humanJobRating, setHumanJobRating] = useState<
    "directly_usable" | "usable_after_small_correction" | "needs_major_correction" | "unusable"
  >("directly_usable");
  const [backgroundRun, setBackgroundRun] = useState(true);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobRedirectNote, setJobRedirectNote] = useState("");
  const [jobSnapshot, setJobSnapshot] = useState<Record<string, unknown> | null>(null);
  const [recentJobs, setRecentJobs] = useState<Array<Record<string, unknown>>>([]);
  const [jobObserving, setJobObserving] = useState(false);
  const [, setJobEventCursor] = useState(0);
  const [jobEvents, setJobEvents] = useState<Array<Record<string, unknown>>>([]);
  const [selectorMode, setSelectorMode] = useState<"deterministic" | "model">("deterministic");
  const [useOmniroute, setUseOmniroute] = useState(false);
  const omniDefaultAppliedRef = useRef(false);
  const [omnirouteStatus, setOmnirouteStatus] = useState<OmnirouteStatus | null>(null);
  const observeJobIdRef = useRef<string | null>(null);
  const jobEventCursorRef = useRef(0);

  const [debugLogs, setDebugLogs] = useState("");
  const [debugFailingTest, setDebugFailingTest] = useState("");
  const [debugContextJson, setDebugContextJson] = useState("");
  const [debugLoading, setDebugLoading] = useState(false);
  const [debugResult, setDebugResult] = useState<Record<string, unknown> | null>(null);
  const [debugError, setDebugError] = useState<string | null>(null);

  const [releaseLoading, setReleaseLoading] = useState(false);
  const [releaseSmokeLoading, setReleaseSmokeLoading] = useState(false);
  const [releaseReport, setReleaseReport] = useState<ReleaseReport | null>(null);
  const [releaseError, setReleaseError] = useState<string | null>(null);

  const [controlValues, setControlValues] = useState<Record<string, unknown> | null>(null);
  const [controlSaving, setControlSaving] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);

  const [newTaskOpen, setNewTaskOpen] = useState(false);

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedRunId) ?? null,
    [runs, selectedRunId],
  );

  const lmConnected = health?.lm_studio === "connected";
  const activeModel = health?.active_model || profile?.model_id || null;
  const workspacePath = symbolsPath.trim() || sourceRepo.trim();

  const refreshMeta = useCallback(async (quiet = false) => {
    if (!quiet) setLoadingMeta(true);
    try {
      const [status, config, models, omni] = await Promise.all([
        hadesApi.health(),
        hadesApi.settings(),
        hadesApi.models().catch(() => null),
        hadesApi.buildOmnirouteStatus().catch(() => null),
      ]);
      setHealth(status);
      setSettings(config.values);
      setProfile(models?.active_profile ?? null);
      if (omni) {
        setOmnirouteStatus(omni);
        if (!omniDefaultAppliedRef.current) {
          omniDefaultAppliedRef.current = true;
          if (omni.usable && omni.enabled_by_default) setUseOmniroute(true);
        }
        if (!omni.usable) setUseOmniroute(false);
      }
      setMetaError(null);
      setConnectionLost(false);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Backend niet bereikbaar.";
      setMetaError(message);
      setHealth(null);
      if (!quiet) toast.error(message);
    } finally {
      if (!quiet) setLoadingMeta(false);
    }
  }, []);

  const refreshControlValues = useCallback(async () => {
    try {
      const payload = await hadesApi.controlValues();
      setControlValues(payload.values || {});
      setControlError(null);
      const autonomy = payload.values?.["coding.autonomy.profile"];
      if (
        autonomy === "analyze_only" ||
        autonomy === "managed_workspace_modify" ||
        autonomy === "reviewable_result"
      ) {
        setAutonomyProfile(autonomy);
      }
    } catch (reason) {
      setControlError(reason instanceof Error ? reason.message : "Control Plane laden mislukt.");
    }
  }, []);

  const saveControlPatch = useCallback(async (patch: Record<string, unknown>) => {
    setControlSaving(true);
    setControlError(null);
    try {
      const result = await hadesApi.controlPatchSettings(patch);
      setControlValues(result.values || {});
      toast.success("Coding-instellingen opgeslagen.");
      return true;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Opslaan mislukt.";
      setControlError(message);
      toast.error(message);
      return false;
    } finally {
      setControlSaving(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshMeta();
      void refreshControlValues();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshMeta, refreshControlValues]);

  useEffect(() => {
    const pending = consumeCodingHandoff();
    if (!pending) return;
    setComposerGoal(pending.goal);
    setNewTaskOpen(true);
    if (pending.useOmniroute) {
      setUseOmniroute(true);
      omniDefaultAppliedRef.current = true;
    }
  }, []);

  const refreshRecentJobs = useCallback(async () => {
    try {
      const listed = await hadesApi.buildJobsList(20, true);
      setRecentJobs(listed.jobs || []);
    } catch {
      /* optional */
    }
  }, []);

  const attachJob = useCallback(async (jobId: string, options?: { observe?: boolean }) => {
    const observe = options?.observe !== false;
    setActiveJobId(jobId);
    observeJobIdRef.current = jobId;
    persistActiveJobId(jobId);
    writeCodingJobToLocation(jobId);
    try {
      const snap = await hadesApi.buildJobGet(jobId);
      setJobSnapshot(snap);
      const after = readJobEventCursor(jobId);
      setJobEventCursor(after);
      jobEventCursorRef.current = after;
      const ev = await hadesApi.buildJobEvents(jobId, 100, after);
      setJobEvents((prev) => mergeJobEvents(prev, ev.events || []));
      if (ev.next_cursor != null) {
        setJobEventCursor(Number(ev.next_cursor));
        jobEventCursorRef.current = Number(ev.next_cursor);
        writeJobEventCursor(jobId, Number(ev.next_cursor));
      }
      if (observe && !JOB_TERMINAL.has(String(snap.status || ""))) {
        setJobObserving(true);
      } else {
        setJobObserving(false);
      }
      setConnectionLost(false);
      return snap;
    } catch (reason) {
      // Transient fetch failure must not destroy persisted active-job identity.
      setConnectionLost(true);
      setJobObserving(true);
      throw reason;
    }
  }, []);

  useEffect(() => {
    const candidate = readCodingJobFromLocation() || readPersistedActiveJobId();
    if (!candidate) {
      void refreshRecentJobs();
      return;
    }
    void attachJob(candidate, { observe: true })
      .then(() => toast.message(`Job hersteld: ${candidate}`))
      .catch(() => toast.error("Opgeslagen job niet meer beschikbaar."))
      .finally(() => void refreshRecentJobs());
  }, [attachJob, refreshRecentJobs]);

  useEffect(() => {
    if (!activeJobId || !jobObserving) return;
    const watchedId = activeJobId;
    observeJobIdRef.current = watchedId;
    let cancelled = false;
    const tick = async () => {
      if (observeJobIdRef.current !== watchedId) return;
      try {
        const snap = await hadesApi.buildJobGet(watchedId);
        if (cancelled || observeJobIdRef.current !== watchedId) return;
        setJobSnapshot(snap);
        setConnectionLost(false);
        const cursor = jobEventCursorRef.current || undefined;
        const ev = await hadesApi.buildJobEvents(watchedId, 50, cursor);
        if (cancelled || observeJobIdRef.current !== watchedId) return;
        if (ev.events?.length) {
          setJobEvents((prev) => mergeJobEvents(prev, ev.events));
        }
        if (ev.next_cursor != null) {
          const next = Number(ev.next_cursor);
          jobEventCursorRef.current = next;
          setJobEventCursor(next);
          writeJobEventCursor(watchedId, next);
        }
        const st = String(snap.status || "");
        if (JOB_TERMINAL.has(st)) {
          setJobObserving(false);
          const result = (snap.result as Record<string, unknown> | undefined) || snap;
          const runId = String(result.run_id ?? result.id ?? watchedId);
          const params = snap.params as Record<string, unknown> | undefined;
          const jobSuite = String(params?.test_suite || (result as { test_suite?: string }).test_suite || "auto") as CodingTestSuite;
          const sessionRun: SessionRun = {
            id: runId,
            title:
              String(params?.source_repo || "job")
                .split(/[/\\]/)
                .filter(Boolean)
                .pop() || "job",
            sourceRepo: String(params?.source_repo || ""),
            testSuite: jobSuite,
            status: st,
            startedAt: new Date().toISOString(),
            result: {
              ...result,
              coding_job: snap,
              job_model_id: params?.model_id ?? null,
              job_test_suite: jobSuite,
            },
            error: typeof snap.error === "string" ? snap.error : null,
          };
          setRuns((current) => [sessionRun, ...current.filter((item) => item.id !== sessionRun.id)]);
          setSelectedRunId(sessionRun.id);
          if (JOB_SUCCESS.has(st)) toast.success(`Job eindstatus: ${buildStatusLabel(st)}`);
          else toast.error(`Job eindstatus: ${buildStatusLabel(st)}`);
          void refreshRecentJobs();
        }
      } catch {
        setConnectionLost(true);
      }
    };
    const id = window.setInterval(() => void tick(), CODING_JOB_POLL_MS);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [activeJobId, jobObserving, refreshRecentJobs]);

  const startNewRun = useCallback(() => {
    setSelectedRunId(null);
    setConflicts(null);
    setApplyPreview(null);
    setApplyResult(null);
    setNewTaskOpen(true);
  }, []);

  const submitBuild = useCallback(async () => {
    const repo = sourceRepo.trim();
    if (!repo) {
      toast.error("Vul een source_repo pad in (bijv. C:\\Projects\\mijn-repo).");
      return false;
    }
    let edits: Array<Record<string, unknown>> = [];
    let repairWaves: Array<Array<Record<string, unknown>>> = [];
    try {
      edits = parseEdits(editsJson);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Edits JSON is ongeldig.");
      return false;
    }
    try {
      const trimmed = repairWavesJson.trim();
      if (trimmed) {
        const parsed = JSON.parse(trimmed) as unknown;
        if (!Array.isArray(parsed) || !parsed.every((wave) => Array.isArray(wave))) {
          throw new Error("repair_waves moet een JSON-array van edit-arrays zijn.");
        }
        repairWaves = parsed as Array<Array<Record<string, unknown>>>;
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "repair_waves JSON is ongeldig.");
      return false;
    }
    const attempts = Number.parseInt(maxAttempts, 10);
    if (!Number.isFinite(attempts) || attempts < 1 || attempts > 5) {
      toast.error("max_attempts moet tussen 1 en 5 liggen.");
      return false;
    }
    const goalText = composerGoal.trim();
    if (edits.length) {
      if (!composerPlan) {
        toast.error("Maak eerst een multi-file plan (Plan) vóór Start run.");
        return false;
      }
      if (!planApproved) {
        toast.error("Keur het composer-plan expliciet goed vóór Start run.");
        return false;
      }
    } else if (!goalText) {
      toast.error("Geef een goal (natuurlijke opdracht) of edits-JSON op.");
      return false;
    }

    const preflight = evaluateCodingPreflightClient({
      sourceRepo: repo,
      goal: goalText,
      hasManualEdits: edits.length > 0,
      backendReachable: !metaError && Boolean(health || settings),
      lmConnected: Boolean(lmConnected),
      activeModel,
      useOmniroute: useOmniroute && Boolean(omnirouteStatus?.usable),
      omnirouteUsable: Boolean(omnirouteStatus?.usable),
      autonomyProfile,
    });
    if (!preflight.ready && !edits.length) {
      toast.error(preflight.humanSummaryNl);
      return false;
    }

    if (!symbolsPath.trim()) setSymbolsPath(repo);
    setBuilding(true);
    try {
      const resolvedModelId = activeModel;
      if (!edits.length && goalText && backgroundRun) {
        const started = await hadesApi.buildFromGoalAsync({
          source_repo: repo,
          goal: goalText,
          repair_waves: repairWaves,
          test_suite: testSuite,
          max_attempts: attempts,
          auto_repair: true,
          strategy: codingStrategy,
          selector_mode: selectorMode,
          autonomy_profile: autonomyProfile,
          use_omniroute: useOmniroute && Boolean(omnirouteStatus?.usable),
          model_id: resolvedModelId,
        });
        const jobId = String(started.job_id || "");
        if (!jobId.trim()) {
          toast.error("Achtergrondjob startte zonder job_id.");
          return false;
        }
        setJobEvents([]);
        setJobEventCursor(0);
        jobEventCursorRef.current = 0;
        const snap = await attachJob(jobId, { observe: true });
        const st = String((snap as { status?: string } | null | undefined)?.status || "");
        if (["failed", "cancelled", "interrupted", "tests_failed", "model_unavailable", "model_output_invalid", "no_change", "implementation_missing"].includes(st)) {
          toast.error(`Achtergrondjob startte in status: ${st}`);
        } else {
          toast.success(`Achtergrondjob gestart: ${jobId}`);
        }
        void refreshRecentJobs();
        setNewTaskOpen(false);
        return true;
      }

      const result =
        !edits.length && goalText
          ? await hadesApi.buildFromGoal({
              source_repo: repo,
              goal: goalText,
              repair_waves: repairWaves,
              test_suite: testSuite,
              max_attempts: attempts,
              auto_repair: true,
              strategy: codingStrategy,
              autonomy_profile: autonomyProfile,
              use_omniroute: useOmniroute && Boolean(omnirouteStatus?.usable),
              model_id: resolvedModelId,
            })
          : await hadesApi.buildRun({
              source_repo: repo,
              edits,
              repair_waves: repairWaves,
              test_suite: (testSuite === "auto" ? "unittest" : testSuite) as
                | "unittest"
                | "pytest"
                | "npm_test"
                | "go_test"
                | "cargo_test"
                | "ctest",
              max_attempts: attempts,
              goal: goalText || undefined,
              auto_repair: Boolean(goalText && !edits.length),
            });
      const runId = String(result.run_id ?? "");
      const status = String(result.status ?? "unknown");
      const sessionRun: SessionRun = {
        id: runId || `run_${Date.now()}`,
        title: repo.split(/[/\\]/).filter(Boolean).pop() || repo,
        sourceRepo: repo,
        testSuite,
        status,
        startedAt: new Date().toISOString(),
        result: { ...result, job_model_id: resolvedModelId, job_test_suite: testSuite },
        error: typeof result.error === "string" ? result.error : null,
      };
      setRuns((current) => [sessionRun, ...current.filter((item) => item.id !== sessionRun.id)]);
      setSelectedRunId(sessionRun.id);
      setConflicts(null);
      setApplyPreview(null);
      setApplyResult(null);
      const plan = (result.report as Record<string, unknown> | undefined)?.composer_plan;
      if (plan && typeof plan === "object") setComposerPlan(plan as Record<string, unknown>);
      const failReason = extractCodingFailureReason(result);
      if (JOB_SUCCESS.has(status)) toast.success(`Build-run voltooid: ${buildStatusLabel(status)}`);
      else toast.error(failReason || `Build-run eindstatus: ${buildStatusLabel(status)}`);
      setNewTaskOpen(false);
      return true;
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Build-run mislukt.");
      return false;
    } finally {
      setBuilding(false);
    }
  }, [
    activeModel,
    attachJob,
    autonomyProfile,
    backgroundRun,
    codingStrategy,
    composerGoal,
    composerPlan,
    editsJson,
    health,
    lmConnected,
    maxAttempts,
    metaError,
    omnirouteStatus?.usable,
    planApproved,
    refreshRecentJobs,
    repairWavesJson,
    selectorMode,
    settings,
    sourceRepo,
    symbolsPath,
    testSuite,
    useOmniroute,
  ]);

  const loadConflicts = useCallback(async () => {
    if (!selectedRun?.id) return;
    setConflictsLoading(true);
    try {
      const [payload, preview] = await Promise.all([
        hadesApi.buildConflicts(selectedRun.id),
        hadesApi.buildPreview(selectedRun.id).catch(() => null),
      ]);
      const items = Array.isArray(payload.conflicts) ? (payload.conflicts as Array<Record<string, unknown>>) : [];
      setConflicts(items);
      if (preview) setApplyPreview(preview);
      toast.message(items.length ? `${items.length} conflict(en) gevonden.` : "Geen apply-conflicten.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Conflicten ophalen mislukt.");
    } finally {
      setConflictsLoading(false);
    }
  }, [selectedRun?.id]);

  const applyRun = useCallback(async () => {
    if (!selectedRun?.id) return false;
    if (!applyApproved) {
      toast.error("Vink expliciete goedkeuring aan voordat je wijzigingen toepast.");
      return false;
    }
    setMutatingRun("apply");
    try {
      const result = await hadesApi.buildApply(selectedRun.id, true);
      setApplyResult(result);
      if (result.status === "conflict") {
        setConflicts(Array.isArray(result.conflicts) ? (result.conflicts as Array<Record<string, unknown>>) : []);
        toast.error("Apply geblokkeerd door conflicten.");
        return false;
      }
      if (result.applied === true && Number(result.file_count ?? 0) > 0) {
        toast.success(
          typeof result.message === "string"
            ? result.message
            : `${Number(result.file_count ?? (Array.isArray(result.files) ? result.files.length : 0))} bestand(en) toegepast.`,
        );
        return true;
      }
      toast.error(
        typeof result.error === "string"
          ? result.error
          : typeof result.message === "string"
            ? result.message
            : "Apply leverde geen bestanden op.",
      );
      return false;
    } catch (reason) {
      if (reason instanceof HadesApiError && reason.status === 403) {
        toast.error(`Geblokkeerd (403): ${reason.message}`);
      } else {
        toast.error(reason instanceof Error ? reason.message : "Toepassen mislukt.");
      }
      return false;
    } finally {
      setMutatingRun(null);
    }
  }, [applyApproved, selectedRun?.id]);

  const restoreRun = useCallback(async () => {
    if (!selectedRun?.id) return false;
    setMutatingRun("restore");
    try {
      const result = await hadesApi.buildRestore(selectedRun.id);
      const restoredCount = Array.isArray(result.files) ? result.files.length : Number(result.file_count ?? 0);
      if (result.restored === true || (result.status === "restored" && restoredCount > 0)) {
        toast.success(
          typeof result.message === "string" ? result.message : `${restoredCount} bestand(en) hersteld.`,
        );
        return true;
      }
      toast.error(
        typeof result.error === "string"
          ? result.error
          : typeof result.message === "string"
            ? result.message
            : "Backup herstel leverde geen bestanden op.",
      );
      return false;
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Herstellen mislukt.");
      return false;
    } finally {
      setMutatingRun(null);
    }
  }, [selectedRun?.id]);

  const runTerminal = useCallback(async () => {
    let argv: string[] = [];
    try {
      argv = parseArgv(terminalArgv);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Argv is ongeldig.");
      return;
    }
    if (!argv.length) {
      toast.error("Geef minstens één terminalargument op.");
      return;
    }
    setTerminalRunning(true);
    setTerminalError(null);
    try {
      const result = await hadesApi.terminalRun({
        argv,
        cwd: terminalCwd.trim() || workspacePath || undefined,
        approved: true,
      });
      setTerminalResult(result);
    } catch (reason) {
      setTerminalResult(null);
      if (reason instanceof HadesApiError) {
        if (reason.status === 403) setTerminalError(`Geblokkeerd (403): ${reason.message}`);
        else if (reason.status === 428) {
          setTerminalError(
            `Goedkeuring vereist (428): ${reason.message}. Zet file_write_policy op allow of keur expliciet goed.`,
          );
        } else setTerminalError(reason.message);
      } else {
        setTerminalError(reason instanceof Error ? reason.message : "Terminal-run mislukt.");
      }
    } finally {
      setTerminalRunning(false);
    }
  }, [terminalArgv, terminalCwd, workspacePath]);

  const searchSymbolsFn = useCallback(
    async (refresh = false) => {
      setSymbolsLoading(true);
      try {
        const payload = await hadesApi.searchSymbols({
          path: workspacePath || undefined,
          query: symbolsQuery.trim(),
          refresh,
        });
        setSymbols(payload.symbols ?? []);
        setSelectedSymbol(null);
        setDefinitionHits([]);
        setReferenceHits([]);
        setSymbolsMeta({
          root: payload.root,
          files_scanned: payload.files_scanned,
          truncated: payload.truncated,
          from_cache: payload.from_cache,
          embeddings: payload.embeddings,
          embeddings_note: payload.embeddings_note,
          tree: payload.tree,
        });
      } catch (reason) {
        setSymbols([]);
        setSymbolsMeta(null);
        toast.error(reason instanceof Error ? reason.message : "Symbolen zoeken mislukt.");
      } finally {
        setSymbolsLoading(false);
      }
    },
    [symbolsQuery, workspacePath],
  );

  const refreshSymbolIndex = useCallback(async () => {
    if (!workspacePath) {
      toast.error("Geef een workspace pad op om de index te vernieuwen.");
      return;
    }
    setSymbolsRefreshing(true);
    try {
      const result = await hadesApi.refreshSymbols({ path: workspacePath, force: true });
      toast.message(
        `Index vernieuwd: ${result.symbol_count ?? "?"} symbolen · ${result.files_rescanned ?? "?"} rescanned.`,
      );
      await searchSymbolsFn(false);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Index vernieuwen mislukt.");
    } finally {
      setSymbolsRefreshing(false);
    }
  }, [searchSymbolsFn, workspacePath]);

  const loadSymbolDefinition = useCallback(
    async (symbol: SymbolHit) => {
      setLspLoading("definition");
      setSelectedSymbol(symbol);
      try {
        const payload = await hadesApi.codeDefinition({
          path: workspacePath || undefined,
          symbol: symbol.name,
        });
        setDefinitionHits(payload.definitions ?? []);
      } catch (reason) {
        setDefinitionHits([]);
        toast.error(reason instanceof Error ? reason.message : "Go-to-definition mislukt.");
      } finally {
        setLspLoading(null);
      }
    },
    [workspacePath],
  );

  const loadSymbolReferences = useCallback(
    async (symbol: SymbolHit) => {
      setLspLoading("references");
      setSelectedSymbol(symbol);
      try {
        const payload = await hadesApi.codeReferences({
          path: workspacePath || undefined,
          symbol: symbol.name,
        });
        setReferenceHits(payload.references ?? []);
      } catch (reason) {
        setReferenceHits([]);
        toast.error(reason instanceof Error ? reason.message : "Find-references mislukt.");
      } finally {
        setLspLoading(null);
      }
    },
    [workspacePath],
  );

  const loadCodeOutline = useCallback(
    async (relativePath?: string) => {
      const path = relativePath || fsPreview?.path || workspacePath;
      if (!path) return;
      setLspLoading("outline");
      try {
        const payload = await hadesApi.codeOutline({ path });
        setOutline(payload);
      } catch (reason) {
        setOutline(null);
        toast.error(reason instanceof Error ? reason.message : "Outline laden mislukt.");
      } finally {
        setLspLoading(null);
      }
    },
    [fsPreview?.path, workspacePath],
  );

  const loadGitStatus = useCallback(async () => {
    if (!workspacePath) {
      toast.error("Geef eerst een workspace pad op.");
      return;
    }
    setGitLoading(true);
    try {
      const payload = await hadesApi.workspaceGitStatus({ path: workspacePath });
      setGitStatus(payload as Record<string, unknown>);
      if (!payload.is_git) toast.message(payload.message || payload.error || "Geen Git-repository.");
    } catch (reason) {
      setGitStatus(null);
      toast.error(reason instanceof Error ? reason.message : "Git status mislukt.");
    } finally {
      setGitLoading(false);
    }
  }, [workspacePath]);

  const commitGit = useCallback(async () => {
    if (!workspacePath) return false;
    if (!gitCommitApproved) {
      toast.error("Vink expliciete commit-goedkeuring aan.");
      return false;
    }
    if (!gitCommitMsg.trim()) {
      toast.error("Commit message ontbreekt.");
      return false;
    }
    setGitCommitting(true);
    try {
      const result = await hadesApi.workspaceGitCommit({
        path: workspacePath,
        message: gitCommitMsg.trim(),
        approved: true,
      });
      if (result.committed) {
        toast.success("Commit gemaakt.");
        setGitCommitApproved(false);
        setGitCommitMsg("");
        await loadGitStatus();
        return true;
      }
      toast.error(result.message || result.error || "Commit mislukt.");
      return false;
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Commit mislukt.");
      return false;
    } finally {
      setGitCommitting(false);
    }
  }, [gitCommitApproved, gitCommitMsg, loadGitStatus, workspacePath]);

  const loadWorkspaceTree = useCallback(
    async (relative = fsRelative) => {
      if (!workspacePath) {
        toast.error("Geef eerst een workspace pad op.");
        return;
      }
      setFsLoading(true);
      try {
        const payload = await hadesApi.workspaceTree({
          path: workspacePath,
          relative,
          query: fsFilter.trim() || undefined,
        });
        setFsRelative(payload.relative || "");
        setFsEntries(payload.entries ?? []);
        setFsMeta({ root: payload.root, relative: payload.relative || "", truncated: Boolean(payload.truncated) });
      } catch (reason) {
        toast.error(reason instanceof Error ? reason.message : "Workspace tree laden mislukt.");
      } finally {
        setFsLoading(false);
      }
    },
    [fsFilter, fsRelative, workspacePath],
  );

  const openFsEntry = useCallback(
    async (entry: { name: string; path: string; kind: string }) => {
      if (entry.kind === "dir") {
        setFsPreview(null);
        await loadWorkspaceTree(entry.path);
        return;
      }
      if (!workspacePath) return;
      setFsPreviewLoading(true);
      try {
        const payload = await hadesApi.workspacePreview({ path: workspacePath, relative: entry.path });
        setFsPreview({ path: payload.path, content: payload.content, truncated: Boolean(payload.truncated) });
      } catch (reason) {
        setFsPreview(null);
        toast.error(reason instanceof Error ? reason.message : "Bestandspreview mislukt.");
      } finally {
        setFsPreviewLoading(false);
      }
    },
    [loadWorkspaceTree, workspacePath],
  );

  const openInEditor = useCallback(
    async (relative?: string) => {
      const rel = relative || fsPreview?.path || fsRelative;
      if (!workspacePath || !rel) {
        toast.error("Geen bestand geselecteerd om te openen.");
        return;
      }
      try {
        const result = await hadesApi.workspaceOpenExternal({ path: workspacePath, relative: rel });
        if (result.opened) toast.success(result.message || `Geopend in ${result.editor || "editor"}`);
        else toast.error(result.error || result.message || "Editor integration unavailable");
      } catch (reason) {
        toast.error(reason instanceof Error ? reason.message : "Editor integration unavailable");
      }
    },
    [fsPreview?.path, fsRelative, workspacePath],
  );

  const previewComposerPlan = useCallback(async () => {
    let edits: Array<Record<string, unknown>> = [];
    try {
      edits = parseEdits(editsJson);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Edits JSON is ongeldig.");
      return;
    }
    if (!edits.length) {
      toast.error("Composer plan vereist minstens één edit.");
      return;
    }
    setPlanLoading(true);
    try {
      const plan = await hadesApi.buildPlan({ edits, goal: composerGoal.trim() || undefined });
      setComposerPlan(plan);
      setPlanApproved(false);
      toast.message(`Plan: ${plan.file_count} bestand(en), goedkeuring vereist.`);
    } catch (reason) {
      setComposerPlan(null);
      toast.error(reason instanceof Error ? reason.message : "Plan maken mislukt.");
    } finally {
      setPlanLoading(false);
    }
  }, [composerGoal, editsJson]);

  const loadDebugFromSelectedRun = useCallback(() => {
    if (!selectedRun?.result) {
      toast.error("Geen geselecteerde build-run met logs.");
      return;
    }
    setDebugLogs(collectBuildLogs(selectedRun.result));
    toast.message("Build-logs in diagnose geladen.");
  }, [selectedRun?.result]);

  const loadProposedEditsIntoComposer = useCallback(() => {
    const edits = Array.isArray(debugResult?.proposed_edits) ? debugResult?.proposed_edits : [];
    if (!edits.length) {
      toast.error("Geen voorgestelde edits in de diagnose.");
      return;
    }
    setEditsJson(JSON.stringify(edits, null, 2));
    setComposerPlan(null);
    setPlanApproved(false);
    setApplyApproved(false);
    const broke = Array.isArray(debugResult?.what_broke)
      ? (debugResult?.what_broke as string[]).slice(0, 2).join("; ")
      : "";
    if (!composerGoal.trim() && broke) setComposerGoal(`Debug fix: ${broke}`);
    setNewTaskOpen(true);
    toast.message("Stubs in composer — review content, Plan → approve → Start run. Nooit auto-apply.");
  }, [composerGoal, debugResult]);

  const runDebugDiagnose = useCallback(async () => {
    const logs = debugLogs.trim();
    if (!logs && !debugFailingTest.trim()) {
      setDebugError("Plak build/test logs of geef een falende test op.");
      return;
    }
    let contextFiles: Array<{ path: string; content?: string }> = [];
    try {
      contextFiles = parseContextFiles(debugContextJson);
    } catch (reason) {
      setDebugError(reason instanceof Error ? reason.message : "context_files JSON is ongeldig.");
      return;
    }
    setDebugLoading(true);
    setDebugError(null);
    try {
      const result = await hadesApi.debugDiagnose({
        logs,
        failing_test: debugFailingTest.trim() || undefined,
        context_files: contextFiles.length ? contextFiles : undefined,
      });
      setDebugResult(result);
    } catch (reason) {
      setDebugResult(null);
      setDebugError(reason instanceof Error ? reason.message : "Diagnose mislukt.");
    } finally {
      setDebugLoading(false);
    }
  }, [debugContextJson, debugFailingTest, debugLogs]);

  const loadReleaseConfidence = useCallback(async () => {
    setReleaseLoading(true);
    setReleaseError(null);
    try {
      const result = await hadesApi.releaseConfidence();
      setReleaseReport(result);
    } catch (reason) {
      setReleaseReport(null);
      setReleaseError(reason instanceof Error ? reason.message : "Release confidence ophalen mislukt.");
    } finally {
      setReleaseLoading(false);
    }
  }, []);

  const runReleaseSmoke = useCallback(async () => {
    setReleaseSmokeLoading(true);
    setReleaseError(null);
    try {
      const result = await hadesApi.releaseConfidenceSmoke(true);
      setReleaseReport(result as ReleaseReport);
      const smokeOk =
        typeof result.smoke === "object" && result.smoke && "ok" in result.smoke && Boolean((result.smoke as { ok?: boolean }).ok);
      toast.message(smokeOk ? "Smoke geslaagd." : "Smoke afgerond — controleer het rapport.");
    } catch (reason) {
      setReleaseError(reason instanceof Error ? reason.message : "Smoke-test mislukt.");
    } finally {
      setReleaseSmokeLoading(false);
    }
  }, []);

  const pauseJob = useCallback(async () => {
    if (!activeJobId) return;
    try {
      await hadesApi.buildJobPause(activeJobId);
      const snap = await hadesApi.buildJobGet(activeJobId);
      setJobSnapshot(snap);
      toast.message("Pauze aangevraagd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Pauzeren mislukt.");
    }
  }, [activeJobId]);

  const resumeJob = useCallback(async () => {
    if (!activeJobId) return;
    try {
      const snap = await hadesApi.buildJobResume(activeJobId);
      setJobSnapshot(snap);
      setJobObserving(true);
      toast.message("Job hervat.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Hervatten mislukt.");
    }
  }, [activeJobId]);

  const cancelJob = useCallback(async () => {
    if (!activeJobId) return;
    try {
      const snap = await hadesApi.buildJobCancel(activeJobId);
      setJobSnapshot(snap);
      toast.message("Annulering aangevraagd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Annuleren mislukt.");
    }
  }, [activeJobId]);

  const redirectJob = useCallback(async () => {
    if (!activeJobId || !jobRedirectNote.trim()) return;
    try {
      const snap = await hadesApi.buildJobRedirect(activeJobId, jobRedirectNote.trim());
      setJobSnapshot(snap);
      setJobRedirectNote("");
      toast.message("Redirect-note verzonden.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Redirect mislukt.");
    }
  }, [activeJobId, jobRedirectNote]);

  const recoverJobs = useCallback(async () => {
    try {
      const result = await hadesApi.buildJobsRecover(false);
      toast.message(typeof result.message === "string" ? result.message : "Job recover uitgevoerd.");
      void refreshRecentJobs();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Recover mislukt.");
    }
  }, [refreshRecentJobs]);

  const rateActiveJob = useCallback(async () => {
    if (!activeJobId) return;
    try {
      await hadesApi.gen2EvalHumanRating({
        coding_job_id: activeJobId,
        rating: humanJobRating,
      });
      toast.success("Beoordeling opgeslagen.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Beoordeling mislukt.");
    }
  }, [activeJobId, humanJobRating]);

  const buildLogs = collectBuildLogs(selectedRun?.result ?? null);
  const reviewDiffText = collectReviewDiffText(selectedRun?.result ?? null);
  const changedFiles = useMemo(() => {
    const fromPreview = Array.isArray(applyPreview?.files)
      ? (applyPreview.files as Array<Record<string, unknown>>).map((row) => ({
          path: String(row.path || row.file || ""),
          action: String(row.action || row.status || "modify"),
          diff: typeof row.diff === "string" ? row.diff : typeof row.unified_diff === "string" ? row.unified_diff : undefined,
        }))
      : [];
    if (fromPreview.length) return fromPreview.filter((f) => f.path);
    return extractChangedFiles(selectedRun?.result);
  }, [applyPreview, selectedRun?.result]);

  const frontierStatus = extractFrontierStatus(selectedRun?.result) || extractFrontierStatus(jobSnapshot);
  const codingFailureReason =
    extractCodingFailureReason(selectedRun?.result) ||
    extractCodingFailureReason(
      (jobSnapshot?.result as Record<string, unknown> | undefined) || jobSnapshot || undefined,
    );
  const preflight = useMemo(
    () =>
      evaluateCodingPreflightClient({
        sourceRepo,
        goal: composerGoal,
        hasManualEdits: Boolean(editsJson.trim()),
        backendReachable: !metaError && Boolean(health || settings),
        lmConnected: Boolean(lmConnected),
        activeModel,
        useOmniroute: useOmniroute && Boolean(omnirouteStatus?.usable),
        omnirouteUsable: Boolean(omnirouteStatus?.usable),
        autonomyProfile,
      }),
    [
      activeModel,
      autonomyProfile,
      composerGoal,
      editsJson,
      health,
      lmConnected,
      metaError,
      omnirouteStatus?.usable,
      settings,
      sourceRepo,
      useOmniroute,
    ],
  );
  const omnirouteLabel = formatOmnirouteRouting(
    (jobSnapshot?.result as Record<string, unknown> | undefined)?.omniroute ||
      (selectedRun?.result as Record<string, unknown> | undefined)?.omniroute ||
      jobSnapshot,
  );

  const jobPhase = useMemo(() => {
    const last = [...jobEvents].reverse().find((e) => e.phase || e.event || e.type);
    if (!last) return String(jobSnapshot?.status || selectedRun?.status || "idle");
    return String(last.phase || last.event || last.type || jobSnapshot?.status || "idle");
  }, [jobEvents, jobSnapshot, selectedRun?.status]);

  return {
    TEST_SUITES,
    formatDate,
    health,
    settings,
    profile,
    loadingMeta,
    metaError,
    connectionLost,
    lmConnected,
    activeModel,
    refreshMeta,
    runs,
    selectedRun,
    selectedRunId,
    setSelectedRunId,
    sourceRepo,
    setSourceRepo,
    testSuite,
    setTestSuite,
    editsJson,
    setEditsJson,
    maxAttempts,
    setMaxAttempts,
    building,
    conflicts,
    applyPreview,
    applyResult,
    conflictsLoading,
    applyApproved,
    setApplyApproved,
    mutatingRun,
    terminalArgv,
    setTerminalArgv,
    terminalCwd,
    setTerminalCwd,
    terminalRunning,
    terminalResult,
    terminalError,
    symbolsPath,
    setSymbolsPath,
    symbolsQuery,
    setSymbolsQuery,
    symbolsLoading,
    symbolsRefreshing,
    symbols,
    symbolsMeta,
    selectedSymbol,
    definitionHits,
    referenceHits,
    outline,
    lspLoading,
    fsRelative,
    setFsRelative,
    fsFilter,
    setFsFilter,
    fsLoading,
    fsEntries,
    fsMeta,
    fsPreview,
    fsPreviewLoading,
    gitLoading,
    gitStatus,
    gitCommitMsg,
    setGitCommitMsg,
    gitCommitApproved,
    setGitCommitApproved,
    gitCommitting,
    composerGoal,
    setComposerGoal,
    repairWavesJson,
    setRepairWavesJson,
    composerPlan,
    planLoading,
    planApproved,
    setPlanApproved,
    codingStrategy,
    setCodingStrategy,
    autonomyProfile,
    setAutonomyProfile,
    humanJobRating,
    setHumanJobRating,
    backgroundRun,
    setBackgroundRun,
    activeJobId,
    jobRedirectNote,
    setJobRedirectNote,
    jobSnapshot,
    recentJobs,
    jobObserving,
    jobEvents,
    selectorMode,
    setSelectorMode,
    useOmniroute,
    setUseOmniroute,
    omnirouteStatus,
    omnirouteLabel,
    debugLogs,
    setDebugLogs,
    debugFailingTest,
    setDebugFailingTest,
    debugContextJson,
    setDebugContextJson,
    debugLoading,
    debugResult,
    debugError,
    releaseLoading,
    releaseSmokeLoading,
    releaseReport,
    releaseError,
    controlValues,
    controlSaving,
    controlError,
    refreshControlValues,
    saveControlPatch,
    newTaskOpen,
    setNewTaskOpen,
    workspacePath,
    buildLogs,
    reviewDiffText,
    changedFiles,
    frontierStatus,
    codingFailureReason,
    preflight,
    jobPhase,
    startNewRun,
    submitBuild,
    loadConflicts,
    applyRun,
    restoreRun,
    runTerminal,
    searchSymbols: searchSymbolsFn,
    refreshSymbolIndex,
    loadSymbolDefinition,
    loadSymbolReferences,
    loadCodeOutline,
    loadGitStatus,
    commitGit,
    loadWorkspaceTree,
    openFsEntry,
    openInEditor,
    previewComposerPlan,
    loadDebugFromSelectedRun,
    loadProposedEditsIntoComposer,
    runDebugDiagnose,
    loadReleaseConfidence,
    runReleaseSmoke,
    attachJob,
    refreshRecentJobs,
    pauseJob,
    resumeJob,
    cancelJob,
    redirectJob,
    recoverJobs,
    rateActiveJob,
  };
}
