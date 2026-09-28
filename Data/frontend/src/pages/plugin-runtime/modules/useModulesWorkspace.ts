import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../../api/client";
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
  tryParseArgs,
  type DetailTabId,
  type ManagedModuleRow,
  type ModuleFilterId,
} from "./viewModels";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
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

export function useModulesWorkspace() {
  const toast = useAppToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [snapshot, setSnapshot] = useState<ModuleSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("module"));
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ModuleFilterId>("all");
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTabId>("configuration");
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

  const applySnapshot = useCallback((next: ModuleSnapshot) => {
    setSnapshot(next);
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
      const snap = await api.listModules();
      applySnapshot(snap);
    } catch (err) {
      setLoadError(errorMessage(err));
      setSnapshot(null);
    } finally {
      setLoading(false);
    }
  }, [applySnapshot]);

  useEffect(() => {
    void load();
  }, [load]);

  // Honor ?module= deep links from Brain / other pages.
  useEffect(() => {
    const fromUrl = searchParams.get("module");
    if (fromUrl) setSelectedId(fromUrl);
  }, [searchParams]);

  const modules = useMemo(() => snapshot?.modules ?? [], [snapshot]);
  const managerEnabled = snapshot != null && snapshot.enabled !== false;

  const rows = useMemo(
    () => filterModules(modules, query, filter, updateEvidenceByModule),
    [modules, query, filter, updateEvidenceByModule],
  );

  const counts = useMemo(
    () => filterCounts(modules, updateEvidenceByModule),
    [modules, updateEvidenceByModule],
  );

  const kpis = useMemo(
    () => deriveKpis(snapshot, updateEvidenceByModule),
    [snapshot, updateEvidenceByModule],
  );

  // When the active filter hides the selected row, show the first visible row
  // without mutating the underlying selection (restored when the filter clears).
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
    if (!id) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (next.get("module") === id) return prev;
        next.set("module", id);
        return next;
      },
      { replace: true },
    );
  }, [effectiveSelectedId, setSearchParams]);

  const ops = useMemo(() => declaredOperations(selected), [selected]);
  const resolvedOperation = operation && ops.includes(operation) ? operation : ops[0] || operation || "health";

  const actions = useMemo(
    () =>
      actionAvailability(selected, {
        managerEnabled,
        lifecycleBusy,
        hasVersionId: Boolean(versionId.trim()),
      }),
    [selected, managerEnabled, lifecycleBusy, versionId],
  );

  const selectModule = useCallback((id: string) => {
    setSelectedId(id);
    setLastResult(null);
    setLogLines(null);
    setJobsPayload(null);
    setPanelJson(null);
    setHealthPayload(null);
    setOperation("");
  }, []);

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
        const res = await api.installModule(id);
        const text = installActionText("install", res);
        setPanelJson(JSON.stringify(res, null, 2));
        toast(text);
        setLastAction(text);
      } else if (action === "start") {
        await api.startModule(id);
        toast(`Started ${id}`);
        setLastAction("Started successfully");
      } else if (action === "stop") {
        await api.stopModule(id);
        toast(`Stopped ${id}`);
        setLastAction("Stopped successfully");
      } else if (action === "restart") {
        await api.restartModule(id);
        toast(`Restarted ${id}`);
        setLastAction("Restarted successfully");
      } else if (action === "ensure-ready") {
        const res = await api.ensureReadyModule(id);
        toast(`Ensure ready: ${JSON.stringify(res.result ?? "ok")}`);
        setLastAction("Ensure ready completed");
      } else if (action === "health") {
        const res = await api.moduleHealth(id);
        const health = (res.health ?? res) as Record<string, unknown>;
        setHealthPayload(health);
        setPanelJson(JSON.stringify(health, null, 2));
        setDetailTab("health");
        toast(`Health: ${JSON.stringify(health?.status ?? "ok")}`);
        setLastAction("Health checked");
      } else if (action === "jobs") {
        const res = await api.moduleJobs(id);
        const jobs = Array.isArray(res.jobs) ? res.jobs : [];
        setJobsPayload(jobs);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("jobs");
        toast(`Active jobs: ${res.count ?? jobs.length}`);
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
      } else if (action === "install-version") {
        const ref = versionRef.trim() || undefined;
        const res = await api.installModuleVersion(id, { ref, activate: false });
        const text = installActionText("install-version", res);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("versions");
        toast(text);
        setLastAction(text);
      } else if (action === "activate-version") {
        const vid = versionId.trim();
        if (!vid) {
          toast("version_id is required to activate");
          return;
        }
        const res = await api.activateModuleVersion(id, vid);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("versions");
        toast(`Activate version: ${JSON.stringify(res.result ?? "ok")}`);
        setLastAction("Version activated");
      } else if (action === "rollback") {
        const res = await api.rollbackModuleVersion(id, versionId.trim() || undefined);
        setPanelJson(JSON.stringify(res, null, 2));
        setDetailTab("versions");
        toast(`Rollback: ${JSON.stringify(res.result ?? "ok")}`);
        setLastAction("Rollback completed");
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
      const snap = await api.listModules().catch(() => null);
      if (snap) applySnapshot(snap);
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
      setLastResult(JSON.stringify(res.result ?? res, null, 2));
      setLastAction(`Executed ${op}`);
      const snap = await api.listModules().catch(() => null);
      if (snap) applySnapshot(snap);
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

  return {
    snapshot,
    loading,
    discovering,
    loadError,
    managerEnabled,
    modules,
    rows,
    counts,
    kpis,
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
    actions,
    ops,
    lifecycleBusy,
    load,
    onDiscover,
    onLifecycle,
    onExecute,
    selectModule,
  };
}
