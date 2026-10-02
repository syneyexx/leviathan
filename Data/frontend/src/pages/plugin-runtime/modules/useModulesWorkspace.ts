import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../../api/client";
import { isTerminalJobStatus } from "../../../lib/jobStatus";
import {
  MODULES_V2_VISUAL_FIXTURE,
  isModulesVisualFixtureActive,
} from "../../../mocks/modulesV2VisualFixture";
import { useAppToast } from "../../../state/useAppToast";
import type { ModuleSnapshot } from "../../../types/api";
import {
  actionAvailability,
  capabilitiesFromRow,
  declaredOperations,
  deriveKpis,
  filterCounts,
  filterModules,
  installActionText,
  lifecycleFailureText,
  moduleId,
  parseCapabilities,
  parseInstallOperation,
  parseInstallPlan,
  primaryInstallCta,
  tryParseArgs,
  type DetailTabId,
  type InstallOperationView,
  type InstallPlanView,
  type ManagedModuleRow,
  type ModuleFilterId,
  type ModuleKpis,
} from "./viewModels";

const JOB_POLL_MS = 900;
const JOB_POLL_TIMEOUT_MS = 180_000;

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
}

function extractJobId(response: unknown): string | null {
  if (!response || typeof response !== "object") return null;
  const obj = response as Record<string, unknown>;
  const direct = obj.job_id ?? obj.jobId;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const job = obj.job;
  if (job && typeof job === "object") {
    const j = job as Record<string, unknown>;
    const id = j.job_id ?? j.jobId ?? j.id;
    if (typeof id === "string" && id.trim()) return id.trim();
  }
  return null;
}

function isQueuedResponse(response: unknown): boolean {
  if (!response || typeof response !== "object") return false;
  const obj = response as Record<string, unknown>;
  if (obj.queued === true) return true;
  const state = String(obj.state ?? obj.status ?? "").toUpperCase();
  return state === "QUEUED" || state === "RUNNING" || state === "CREATED" || state === "RETRY_WAIT";
}

export type LifecycleAction =
  | "install"
  | "start"
  | "stop"
  | "restart"
  | "ensure-ready"
  | "logs"
  | "health"
  | "jobs"
  | "versions"
  | "check-update"
  | "install-version"
  | "activate-version"
  | "rollback"
  | "capabilities"
  | "sweep-idle";

export type PendingLifecycle = {
  jobId: string;
  action: string;
  moduleId: string;
  acceptedAt: string;
  state: string;
};

export type WorkspaceView = "modules" | "runtimes" | "installation" | "environments";

export function useModulesWorkspace() {
  const toast = useAppToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [snapshot, setSnapshot] = useState<ModuleSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("module"));
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ModuleFilterId>("all");
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTabId>("runtime");
  const [operation, setOperation] = useState("");
  const [argsJson, setArgsJson] = useState("{}");
  const [executing, setExecuting] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[] | null>(null);
  const [jobsPayload, setJobsPayload] = useState<unknown[] | null>(null);
  const [versionsPayload, setVersionsPayload] = useState<unknown[] | null>(null);
  const [capabilitiesPayload, setCapabilitiesPayload] = useState<unknown[] | null>(null);
  const [healthPayload, setHealthPayload] = useState<Record<string, unknown> | null>(null);
  const [panelJson, setPanelJson] = useState<string | null>(null);
  const [versionRef, setVersionRef] = useState("");
  const [versionId, setVersionId] = useState("");
  const [updateEvidenceByModule, setUpdateEvidenceByModule] = useState<
    Record<string, Record<string, unknown> | null | undefined>
  >({});
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [installPlan, setInstallPlan] = useState<InstallPlanView | null>(null);
  const [installOperation, setInstallOperation] = useState<InstallOperationView | null>(null);
  const [installPanelOpen, setInstallPanelOpen] = useState(false);
  const [installPolling, setInstallPolling] = useState(false);
  const [pendingLifecycle, setPendingLifecycle] = useState<PendingLifecycle | null>(null);
  const [newModuleOpen, setNewModuleOpen] = useState(false);
  const [activityEvents, setActivityEvents] = useState<Array<Record<string, unknown>>>([]);
  const jobPollAbort = useRef(0);

  const viewParam = searchParams.get("view");
  const workspaceView: WorkspaceView =
    viewParam === "runtimes" || viewParam === "installation" || viewParam === "environments"
      ? viewParam
      : "modules";

  const applySnapshot = useCallback((next: ModuleSnapshot) => {
    setSnapshot(next);
    const evidence: Record<string, Record<string, unknown> | null | undefined> = {};
    for (const row of next.modules ?? []) {
      const id = moduleId(row);
      if (row.update_evidence && typeof row.update_evidence === "object") {
        evidence[id] = row.update_evidence as Record<string, unknown>;
      }
    }
    if (Object.keys(evidence).length > 0) {
      setUpdateEvidenceByModule((prev) => ({ ...prev, ...evidence }));
    }
    const ids = (next.modules ?? []).map(moduleId);
    setSelectedId((prev) => {
      if (prev && ids.includes(prev)) return prev;
      return ids[0] ?? null;
    });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // TEST-ONLY: Screen 1 visual fixture — never used as production default.
      if (isModulesVisualFixtureActive()) {
        const fixture = MODULES_V2_VISUAL_FIXTURE;
        const snap = {
          enabled: fixture.enabled,
          modules: fixture.modules as unknown as ModuleSnapshot["modules"],
          telemetry: fixture.telemetry as ModuleSnapshot["telemetry"],
          discovery_roots: [...fixture.discovery_roots],
          truth: { ...fixture.truth },
        } satisfies ModuleSnapshot;
        applySnapshot(snap);
        setUpdateEvidenceByModule(() => {
          const evidence: Record<string, Record<string, unknown> | null | undefined> = {};
          for (const row of snap.modules ?? []) {
            const id = moduleId(row);
            if (row.update_evidence && typeof row.update_evidence === "object") {
              evidence[id] = row.update_evidence as Record<string, unknown>;
            }
          }
          return evidence;
        });
        setSelectedId(fixture.selectedModuleId);
        setActivityEvents(fixture.activity.map((e) => ({ ...e })));
        setStale(false);
        return;
      }
      const snap = await api.listModules();
      applySnapshot(snap);
      setStale(false);
    } catch (err) {
      setLoadError(errorMessage(err));
      setStale((prev) => prev || snapshot != null);
      if (snapshot == null) setSnapshot(null);
    } finally {
      setLoading(false);
    }
  }, [applySnapshot, snapshot]);

  useEffect(() => {
    // Initial load only — refresh is explicit.
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const awaitJob = useCallback(
    async (jobId: string, actionLabel: string): Promise<{ ok: boolean; message?: string; state?: string }> => {
      const token = ++jobPollAbort.current;
      const deadline = Date.now() + JOB_POLL_TIMEOUT_MS;
      setPendingLifecycle((prev) =>
        prev && prev.jobId === jobId
          ? { ...prev, state: "RUNNING" }
          : {
              jobId,
              action: actionLabel,
              moduleId: prev?.moduleId ?? "",
              acceptedAt: prev?.acceptedAt ?? new Date().toISOString(),
              state: "QUEUED",
            },
      );
      while (Date.now() < deadline) {
        if (token !== jobPollAbort.current) {
          return { ok: false, message: "Operatie geannuleerd" };
        }
        try {
          const res = await api.getJob(jobId);
          const job = res.job as Record<string, unknown>;
          const state = String(job.state ?? job.status ?? "").toUpperCase();
          setPendingLifecycle((prev) => (prev && prev.jobId === jobId ? { ...prev, state } : prev));
          if (isTerminalJobStatus(state)) {
            setPendingLifecycle(null);
            if (state === "SUCCEEDED" || state === "COMPLETED" || state === "SUCCESS") {
              return { ok: true, state };
            }
            if (state === "CANCELLED" || state === "CANCELED") {
              return { ok: false, message: "Geannuleerd", state };
            }
            if (state === "TIMED_OUT" || state === "TIMEOUT") {
              return { ok: false, message: "Timed out", state };
            }
            return {
              ok: false,
              message: String(job.error ?? job.error_code ?? `Job ${state}`),
              state,
            };
          }
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            setPendingLifecycle(null);
            return { ok: false, message: "Job niet gevonden" };
          }
        }
        await new Promise((r) => window.setTimeout(r, JOB_POLL_MS));
      }
      setPendingLifecycle(null);
      return { ok: false, message: "Timeout tijdens wachten op module_runtime job", state: "TIMED_OUT" };
    },
    [],
  );

  const cancelPendingJob = useCallback(async () => {
    const pending = pendingLifecycle;
    if (!pending?.jobId) return;
    try {
      await api.cancelJob(pending.jobId);
      jobPollAbort.current += 1;
      setPendingLifecycle((prev) => (prev ? { ...prev, state: "CANCEL_REQUESTED" } : prev));
      toast("Cancel requested");
      setLastAction("Cancel requested");
    } catch (err) {
      toast(errorMessage(err));
    }
  }, [pendingLifecycle, toast]);

  function applyInstallResponse(res: Record<string, unknown>) {
    const op = parseInstallOperation(res);
    const plan = parseInstallPlan(res.plan) ?? op?.plan ?? null;
    if (plan) setInstallPlan(plan);
    if (op) setInstallOperation(op);
    else if (plan) {
      setInstallOperation({
        operationId: res.operation_id == null ? null : String(res.operation_id),
        status: String(res.status ?? "PLANNING").toUpperCase(),
        phase: res.phase == null ? null : String(res.phase).toUpperCase(),
        progress: typeof res.progress === "number" ? res.progress : null,
        jobId: res.job_id == null ? null : String(res.job_id),
        approvalId:
          res.approval && typeof res.approval === "object"
            ? String((res.approval as Record<string, unknown>).approval_id ?? "") || null
            : res.approval_id == null
              ? null
              : String(res.approval_id),
        planHash: plan.planHash,
        errorCode: null,
        errorDetail: null,
        retryable: false,
        plan,
      });
    }
    setInstallPanelOpen(true);
    setPanelJson(JSON.stringify(res, null, 2));
    const status = String(res.status ?? "").toUpperCase();
    if (status === "QUEUED" || status === "RUNNING" || res.job_id) {
      setInstallPolling(true);
    }
    return installActionText("install", res);
  }

  async function approveAndInstallEverything() {
    if (!selected) return;
    const id = moduleId(selected);
    const plan = installPlan;
    const op = installOperation;
    if (!plan) {
      toast("No install plan available");
      return;
    }
    setLifecycleBusy(true);
    try {
      let approvalId = op?.approvalId ?? null;
      if (plan.requiresApproval || op?.status === "APPROVAL_REQUIRED") {
        if (!approvalId) {
          toast("Approval id missing from install plan");
          return;
        }
        await api.approveApproval(approvalId, `Approve install plan ${plan.planHash.slice(0, 12)}`, {
          // Operator grant only — plan_hash alone never elevates system deps.
          allow_system_deps: Array.isArray(plan.privilegedMutations) && plan.privilegedMutations.length > 0,
        });
      }
      const res = await api.installModule(id, {
        ref: plan.requestedRef || versionRef.trim() || undefined,
        activate: true,
        approval_id: approvalId ?? undefined,
        plan_hash: plan.planHash || undefined,
        auto_resolve_dependencies: true,
      });
      const text = applyInstallResponse(res);
      toast(text);
      setLastAction(text);
      const snap = await api.listModules().catch(() => null);
      if (snap) applySnapshot(snap);
    } catch (err) {
      const msg = lifecycleFailureText("install", errorMessage(err));
      setLastAction(msg);
      toast(msg);
    } finally {
      setLifecycleBusy(false);
    }
  }

  async function retryInstall() {
    if (!selected) return;
    setInstallPlan(null);
    setInstallOperation(null);
    await onLifecycle("install");
  }

  const modules = useMemo(() => snapshot?.modules ?? [], [snapshot]);
  const managerEnabled = snapshot != null && snapshot.enabled !== false;

  const rows = useMemo(
    () => filterModules(modules, query, filter, updateEvidenceByModule),
    [modules, query, filter, updateEvidenceByModule],
  );

  const kpis = useMemo((): ModuleKpis => {
    if (isModulesVisualFixtureActive()) {
      const d = MODULES_V2_VISUAL_FIXTURE.displayKpis;
      return {
        featureFlag: d.featureFlag,
        totalModules: d.totalModules,
        executable: d.executable,
        healthIssues: d.healthIssues,
        updateAvailable: d.updateAvailable,
      };
    }
    return deriveKpis(snapshot, updateEvidenceByModule);
  }, [snapshot, updateEvidenceByModule]);

  const counts = useMemo(() => {
    if (isModulesVisualFixtureActive()) {
      return { ...MODULES_V2_VISUAL_FIXTURE.displayKpis.filterCounts };
    }
    return filterCounts(modules, updateEvidenceByModule);
  }, [modules, updateEvidenceByModule]);

  const visualSparklines = useMemo(() => {
    if (!isModulesVisualFixtureActive()) return undefined;
    return { ...MODULES_V2_VISUAL_FIXTURE.sparklines };
  }, [snapshot]);

  const effectiveSelectedId = useMemo(() => {
    if (selectedId && rows.some((row) => moduleId(row) === selectedId)) return selectedId;
    if (selectedId && !rows.some((row) => moduleId(row) === selectedId)) {
      return rows[0] ? moduleId(rows[0]) : null;
    }
    return selectedId ?? (rows[0] ? moduleId(rows[0]) : null);
  }, [rows, selectedId]);

  const selected: ManagedModuleRow | null = useMemo(() => {
    const id = effectiveSelectedId;
    if (!id) return null;
    return modules.find((row) => moduleId(row) === id) ?? null;
  }, [modules, effectiveSelectedId]);

  useEffect(() => {
    const id = effectiveSelectedId;
    if (!id) {
      setActivityEvents([]);
      return;
    }
    if (isModulesVisualFixtureActive()) {
      setActivityEvents(MODULES_V2_VISUAL_FIXTURE.activity.map((e) => ({ ...e })));
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const res = await api.moduleActivity(id, 20);
        if (!cancelled) setActivityEvents(Array.isArray(res.events) ? res.events : []);
      } catch {
        if (!cancelled) setActivityEvents([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [effectiveSelectedId]);

  useEffect(() => {
    setInstallPlan(null);
    setInstallOperation(null);
    setInstallPanelOpen(false);
    setInstallPolling(false);
  }, [effectiveSelectedId]);

  useEffect(() => {
    if (!installPolling || !effectiveSelectedId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await api.moduleInstallState(effectiveSelectedId);
        if (cancelled) return;
        const op = parseInstallOperation(res.operation ?? res);
        if (op) {
          setInstallOperation(op);
          if (op.plan) setInstallPlan(op.plan);
          const terminal = ["READY", "FAILED", "CANCELLED", "INSTALLED", "COMPLETED"].includes(op.status);
          const phaseTerminal = ["READY", "FAILED", "CANCELLED"].includes(op.phase || "");
          if (terminal || phaseTerminal) {
            setInstallPolling(false);
            const snap = await api.listModules().catch(() => null);
            if (snap && !cancelled) applySnapshot(snap);
            if (op.status === "READY" || op.phase === "READY") {
              setLastAction("Install complete");
              toast("Install complete");
            } else if (op.status === "FAILED" || op.phase === "FAILED") {
              const msg = [op.errorCode, op.errorDetail].filter(Boolean).join(": ") || "Install failed";
              setLastAction(msg);
              toast(msg);
            }
          }
        }
      } catch {
        /* keep polling until terminal or unmount */
      }
    };
    void tick();
    const handle = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [installPolling, effectiveSelectedId, applySnapshot, toast]);

  useEffect(() => {
    const id = effectiveSelectedId;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        let changed = false;
        if (id) {
          if (next.get("module") !== id) {
            next.set("module", id);
            changed = true;
          }
        }
        if (!viewParam || viewParam === "modules") {
          if (next.has("view")) {
            next.delete("view");
            changed = true;
          }
        }
        return changed ? next : prev;
      },
      { replace: true },
    );
  }, [effectiveSelectedId, setSearchParams, viewParam]);

  const setWorkspaceView = useCallback(
    (view: WorkspaceView) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (view === "modules") next.delete("view");
          else next.set("view", view);
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  const ops = useMemo(() => declaredOperations(selected), [selected]);
  const resolvedOperation = operation && ops.includes(operation) ? operation : ops[0] || operation || "health";

  const actions = useMemo(
    () =>
      actionAvailability(selected, {
        managerEnabled,
        lifecycleBusy: lifecycleBusy || pendingLifecycle != null,
        hasVersionId: Boolean(versionId.trim()),
      }),
    [selected, managerEnabled, lifecycleBusy, pendingLifecycle, versionId],
  );

  const selectModule = useCallback((id: string) => {
    setSelectedId(id);
    setLastResult(null);
    setLogLines(null);
    setJobsPayload(null);
    setPanelJson(null);
    setHealthPayload(null);
    setOperation("");
    setWorkspaceView("modules");
  }, [setWorkspaceView]);

  async function onDiscover() {
    setDiscovering(true);
    setLoadError(null);
    try {
      const res = await api.discoverModules();
      applySnapshot(res.snapshot);
      const n = Array.isArray(res.discovered) ? res.discovered.length : 0;
      toast(`Discovered ${n} module manifest(s)`);
      setLastAction("Discover completed");
    } catch (err) {
      const msg = errorMessage(err);
      setLoadError(msg);
      toast(msg);
    } finally {
      setDiscovering(false);
    }
  }

  async function reconcileAfterTerminal(id: string) {
    const snap = await api.listModules().catch(() => null);
    if (snap) applySnapshot(snap);
    try {
      const jobsRes = await api.moduleJobs(id);
      const jobs = Array.isArray(jobsRes.jobs) ? jobsRes.jobs : [];
      setJobsPayload(jobs);
    } catch {
      /* optional refresh */
    }
  }

  async function onLifecycle(action: LifecycleAction) {
    if (action === "sweep-idle") {
      setLifecycleBusy(true);
      try {
        const res = await api.sweepIdleModules();
        toast(`Sweep idle: stopped ${res.count ?? (res.stopped?.length ?? 0)}`);
        setPanelJson(JSON.stringify(res, null, 2));
        setLastAction("Sweep idle completed");
        const snap = await api.listModules().catch(() => null);
        if (snap) applySnapshot(snap);
      } catch (err) {
        toast(errorMessage(err));
      } finally {
        setLifecycleBusy(false);
      }
      return;
    }
    if (!selected) return;
    const id = moduleId(selected);
    setLifecycleBusy(true);
    try {
      if (action === "install") {
        // Plan-first: generate install plan, then show panel for approval/execute.
        const ref = versionRef.trim() || undefined;
        try {
          const planRes = await api.moduleInstallPlan(id, { ref, auto_resolve_dependencies: true });
          const plan = parseInstallPlan(planRes.plan ?? planRes);
          if (plan) setInstallPlan(plan);
          const op = parseInstallOperation(planRes);
          if (op) setInstallOperation(op);
          else if (plan) {
            setInstallOperation({
              operationId: null,
              status: plan.requiresApproval ? "APPROVAL_REQUIRED" : "PLANNING",
              phase: "PLANNING",
              progress: null,
              jobId: null,
              approvalId:
                planRes.approval && typeof planRes.approval === "object"
                  ? String((planRes.approval as Record<string, unknown>).approval_id ?? "") || null
                  : null,
              planHash: plan.planHash,
              errorCode: null,
              errorDetail: null,
              retryable: false,
              plan,
            });
          }
          setInstallPanelOpen(true);
          setPanelJson(JSON.stringify(planRes, null, 2));
          setLastAction("Install plan prepared");
          toast(plan?.requiresApproval ? "Approval required — review the install plan" : "Install plan ready");
        } catch {
          // Fallback: direct install path still durable via JobRuntime.
          const res = await api.installModule(id, { ref, activate: true, auto_resolve_dependencies: true });
          const text = applyInstallResponse(res);
          toast(text);
          setLastAction(text);
        }
      } else if (
        action === "start" ||
        action === "stop" ||
        action === "restart" ||
        action === "ensure-ready"
      ) {
        const apiCall =
          action === "start"
            ? api.startModule(id)
            : action === "stop"
              ? api.stopModule(id)
              : action === "restart"
                ? api.restartModule(id)
                : api.ensureReadyModule(id);
        const res = await apiCall;
        const jobId = extractJobId(res);
        setPanelJson(JSON.stringify(res, null, 2));
        if (jobId && isQueuedResponse(res)) {
          const acceptedAt =
            typeof (res as Record<string, unknown>).accepted_at === "string"
              ? String((res as Record<string, unknown>).accepted_at)
              : new Date().toISOString();
          setPendingLifecycle({
            jobId,
            action,
            moduleId: id,
            acceptedAt,
            state: String((res as Record<string, unknown>).state ?? "QUEUED"),
          });
          setLastAction(`${action} requested`);
          toast(`${action} queued — waiting for module_runtime`);
          const terminal = await awaitJob(jobId, action);
          await reconcileAfterTerminal(id);
          if (terminal.ok) {
            setLastAction(`${action} succeeded`);
            toast(`${action} succeeded`);
          } else {
            const msg = terminal.message || `${action} failed`;
            setLastAction(msg);
            toast(msg);
          }
        } else if ((res as Record<string, unknown>).inprocess_test) {
          setLastAction(`${action} completed (inprocess_test)`);
          toast(`${action} completed`);
          await reconcileAfterTerminal(id);
        } else {
          setLastAction(`${action} accepted`);
          toast(`${action} accepted`);
          await reconcileAfterTerminal(id);
        }
      } else if (action === "health") {
        const res = await api.moduleHealth(id);
        const health = (res.health ?? res) as Record<string, unknown>;
        setHealthPayload(health);
        setPanelJson(JSON.stringify(health, null, 2));
        setDetailTab("health");
        toast(`Health: ${JSON.stringify(health?.status ?? "ok")}`);
        setLastAction("Health checked");
        const snap = await api.listModules().catch(() => null);
        if (snap) applySnapshot(snap);
      } else if (action === "jobs") {
        const res = await api.moduleJobs(id);
        const jobs = Array.isArray(res.jobs) ? res.jobs : [];
        setJobsPayload(jobs);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("jobs");
        toast(`Jobs: ${res.count ?? jobs.length}`);
        setLastAction("Jobs refreshed");
      } else if (action === "versions") {
        const res = await api.moduleVersions(id);
        const versions = Array.isArray(res.versions) ? res.versions : [];
        setVersionsPayload(versions);
        setPanelJson(JSON.stringify(versions, null, 2));
        setDetailTab("versions");
        toast(`Versions: ${res.count ?? versions.length}`);
        setLastAction("Versions listed");
      } else if (action === "check-update") {
        const res = await api.moduleCheckUpdate(id);
        const result = (res.result ?? res) as Record<string, unknown>;
        setUpdateEvidenceByModule((prev) => ({ ...prev, [id]: result }));
        setPanelJson(JSON.stringify(result, null, 2));
        setDetailTab("versions");
        toast(`Update available: ${String(result?.update_available ?? "?")}`);
        setLastAction("Update check completed");
        const snap = await api.listModules().catch(() => null);
        if (snap) applySnapshot(snap);
      } else if (action === "install-version") {
        const ref = versionRef.trim() || undefined;
        const res = await api.installModuleVersion(id, { ref, activate: false });
        const text = installActionText("install-version", res);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("versions");
        const jobId = extractJobId(res);
        if (jobId && isQueuedResponse(res)) {
          setLastAction("Version install queued");
          toast("Version install queued — waiting for module_runtime");
          setPendingLifecycle({
            jobId,
            action: "install-version",
            moduleId: id,
            acceptedAt: new Date().toISOString(),
            state: "QUEUED",
          });
          const terminal = await awaitJob(jobId, "install-version");
          await reconcileAfterTerminal(id);
          if (terminal.ok) {
            setLastAction("Version installed");
            toast("Version installed");
          } else {
            toast(terminal.message || "Version install failed");
            setLastAction(terminal.message || "Version install failed");
          }
        } else {
          toast(text);
          setLastAction(text);
        }
      } else if (action === "activate-version") {
        const vid = versionId.trim();
        if (!vid) {
          toast("version_id is required to activate");
          return;
        }
        const res = await api.activateModuleVersion(id, vid);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("versions");
        const jobId = extractJobId(res);
        if (jobId && isQueuedResponse(res)) {
          setLastAction("Activate version requested");
          toast("Activate queued — waiting for module_runtime");
          setPendingLifecycle({
            jobId,
            action: "activate-version",
            moduleId: id,
            acceptedAt: new Date().toISOString(),
            state: "QUEUED",
          });
          const terminal = await awaitJob(jobId, "activate-version");
          await reconcileAfterTerminal(id);
          if (terminal.ok) {
            setLastAction("Version activated");
            toast("Version activated");
          } else {
            toast(terminal.message || "Activate failed");
            setLastAction(terminal.message || "Activate failed");
          }
        } else {
          toast(`Activate version: ${JSON.stringify((res as Record<string, unknown>).result ?? "ok")}`);
          setLastAction("Version activated");
          await reconcileAfterTerminal(id);
        }
      } else if (action === "rollback") {
        const res = await api.rollbackModuleVersion(id, versionId.trim() || undefined);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("versions");
        const jobId = extractJobId(res);
        if (jobId && isQueuedResponse(res)) {
          setLastAction("Rollback requested");
          toast("Rollback queued — waiting for module_runtime");
          setPendingLifecycle({
            jobId,
            action: "rollback",
            moduleId: id,
            acceptedAt: new Date().toISOString(),
            state: "QUEUED",
          });
          const terminal = await awaitJob(jobId, "rollback");
          await reconcileAfterTerminal(id);
          if (terminal.ok) {
            setLastAction("Rollback completed");
            toast("Rollback completed");
          } else {
            toast(terminal.message || "Rollback failed");
            setLastAction(terminal.message || "Rollback failed");
          }
        } else {
          toast(`Rollback: ${JSON.stringify((res as Record<string, unknown>).result ?? "ok")}`);
          setLastAction("Rollback completed");
          await reconcileAfterTerminal(id);
        }
      } else if (action === "capabilities") {
        const res = await api.moduleCapabilities(id);
        const caps = Array.isArray(res.capabilities) ? res.capabilities : [];
        setCapabilitiesPayload(caps);
        setPanelJson(JSON.stringify(caps, null, 2));
        setDetailTab("capabilities");
        toast(`Capabilities: ${res.count ?? caps.length}`);
        setLastAction("Capabilities loaded");
      } else {
        const logs = await api.moduleLogs(id);
        setLogLines(logs.lines ?? []);
        setDetailTab("logs");
        setLastAction("Logs refreshed");
      }
    } catch (err) {
      const msg = lifecycleFailureText(action, errorMessage(err));
      setLastAction(msg);
      toast(msg);
      const snap = await api.listModules().catch(() => null);
      if (snap) applySnapshot(snap);
    } finally {
      setLifecycleBusy(false);
    }
  }

  async function onExecute() {
    if (!selected) return;
    const op = operation.trim();
    if (!op) {
      toast("Operation is required");
      return;
    }
    const parsed = tryParseArgs(argsJson);
    if (!parsed.ok) {
      toast(parsed.error);
      return;
    }
    setExecuting(true);
    setLastResult(null);
    setDetailTab("execute");
    try {
      const res = await api.executeModule(moduleId(selected), resolvedOperation.trim() || op, parsed.value);
      const jobId = extractJobId(res);
      if (jobId && isQueuedResponse(res)) {
        setLastResult(JSON.stringify({ queued: true, job_id: jobId, state: "QUEUED" }, null, 2));
        setLastAction(`Execute requested: ${op}`);
        toast(`Execute queued — waiting for module_runtime`);
        setPendingLifecycle({
          jobId,
          action: `execute:${op}`,
          moduleId: moduleId(selected),
          acceptedAt: new Date().toISOString(),
          state: "QUEUED",
        });
        const terminal = await awaitJob(jobId, `execute:${op}`);
        const jobRes = await api.getJob(jobId).catch(() => null);
        const job = jobRes?.job as Record<string, unknown> | undefined;
        setLastResult(
          JSON.stringify(
            {
              state: terminal.state,
              ok: terminal.ok,
              error: terminal.message ?? null,
              result: job?.result ?? job?.output ?? null,
            },
            null,
            2,
          ),
        );
        await reconcileAfterTerminal(moduleId(selected));
        if (terminal.ok) {
          setLastAction(`Executed ${op}`);
          toast(`Executed ${op}`);
        } else {
          setLastAction(terminal.message || `Execute failed: ${op}`);
          toast(terminal.message || `Execute failed: ${op}`);
        }
      } else {
        setLastResult(JSON.stringify((res as Record<string, unknown>).result ?? res, null, 2));
        setLastAction(`Executed ${op}`);
        const snap = await api.listModules().catch(() => null);
        if (snap) applySnapshot(snap);
      }
    } catch (err) {
      const msg = errorMessage(err);
      setLastResult(msg);
      toast(msg);
    } finally {
      setExecuting(false);
    }
  }

  const selectedCaps = useMemo(() => {
    if (capabilitiesPayload) return parseCapabilities(capabilitiesPayload);
    return capabilitiesFromRow(selected);
  }, [capabilitiesPayload, selected]);

  const realInstalledCount = useMemo(() => {
    if (isModulesVisualFixtureActive()) {
      return MODULES_V2_VISUAL_FIXTURE.displayKpis.installedCount;
    }
    return counts.installed;
  }, [counts.installed]);

  return {
    snapshot,
    loading,
    discovering,
    loadError,
    stale,
    managerEnabled,
    modules,
    rows,
    counts,
    kpis,
    installedCount: realInstalledCount,
    visualSparklines,
    selected,
    selectedId: effectiveSelectedId,
    query,
    setQuery,
    filter,
    setFilter,
    detailTab,
    setDetailTab,
    operation: resolvedOperation,
    setOperation,
    argsJson,
    setArgsJson,
    executing,
    lastResult,
    logLines,
    jobsPayload,
    versionsPayload,
    capabilitiesPayload: selectedCaps,
    healthPayload,
    panelJson,
    versionRef,
    setVersionRef,
    versionId,
    setVersionId,
    updateEvidenceByModule,
    lastAction,
    installPlan,
    installOperation,
    installPanelOpen,
    setInstallPanelOpen,
    installPolling,
    approveAndInstallEverything,
    retryInstall,
    primaryInstallCta: primaryInstallCta(installPlan, installOperation?.status ?? null),
    actions,
    ops,
    lifecycleBusy: lifecycleBusy || pendingLifecycle != null,
    pendingLifecycle,
    cancelPendingJob,
    workspaceView,
    setWorkspaceView,
    newModuleOpen,
    setNewModuleOpen,
    activityEvents,
    load,
    onDiscover,
    onLifecycle,
    onExecute,
    selectModule,
  };
}
