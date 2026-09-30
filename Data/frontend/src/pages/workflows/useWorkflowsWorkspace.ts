/**
 * Runtime & Tools → Workflows V2 workspace orchestration.
 *
 * Authorities:
 * - Overview KPIs/charts/resources: GET /api/workflows/overview
 * - Definitions: GET /api/workflows
 * - Palette: GET /api/workflows/palette
 * - Mutations: create/patch/delete/duplicate/run/cancel/restore via workflow APIs
 *
 * Visual fixture is TEST-ONLY behind window.__LV_V2_VISUAL_FIXTURE__ === 'workflows'.
 * Production never falls back to fixture numbers on API failure.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import {
  WORKFLOWS_V2_VISUAL_FIXTURE,
  isWorkflowsVisualFixtureActive,
} from "../../mocks/workflowsV2VisualFixture";
import { useAppToast } from "../../state/useAppToast";
import type {
  WorkflowDefinition,
  WorkflowExecution,
  WorkflowGraph,
  WorkflowLayoutNode,
  WorkflowOverview,
  WorkflowPalette,
  WorkflowRecord,
  WorkflowVariableDef,
} from "../../types/api";

export type LibraryFilter = "all" | "active" | "inactive" | "templates";
export type CenterTab = "canvas" | "config" | "executions" | "logs";
export type DetailTab = "overview" | "config" | "variables" | "versions";
export type ViewMode = "list" | "grid";
export type ModalKind = "create" | "templates" | "delete" | "unsaved" | null;

export type EditorDraft = {
  name: string;
  description: string;
  category: string;
  status: string;
  graph: WorkflowGraph;
  layout: WorkflowLayoutNode[];
  variables: WorkflowVariableDef[];
  config: Record<string, unknown>;
  revision?: number;
};

const POLL_MS = 8000;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function asDefinition(row: WorkflowRecord | WorkflowDefinition): WorkflowDefinition {
  const status =
    (row as WorkflowDefinition).status ||
    (row as WorkflowRecord).definition_status ||
    (row as WorkflowRecord).status ||
    "DRAFT";
  return {
    workflow_id: row.workflow_id,
    name: row.name,
    description: row.description ?? "",
    category: row.category ?? "",
    tags: row.tags ?? [],
    status: String(status),
    definition_status: String(status),
    current_version: (row as WorkflowDefinition).current_version ?? (row as WorkflowRecord).workflow_version ?? 1,
    graph: row.graph ?? { nodes: [], edges: [] },
    variables: row.variables ?? [],
    layout: row.layout ?? [],
    config: row.config ?? {},
    trigger_bindings: (row as WorkflowDefinition).trigger_bindings,
    triggers: row.triggers,
    revision: row.revision,
    created_at: row.created_at,
    updated_at: row.updated_at,
    metadata: row.metadata,
    steps: row.steps,
    tools: row.tools,
    agents: row.agents,
    mcp_servers: row.mcp_servers,
    execution_count: row.execution_count,
    avg_duration_ms: row.avg_duration_ms,
    running_executions: (row as WorkflowDefinition).running_executions,
    validation: (row as WorkflowDefinition).validation,
  };
}

function draftFromDefinition(def: WorkflowDefinition): EditorDraft {
  return {
    name: def.name,
    description: def.description ?? "",
    category: def.category ?? "",
    status: String(def.status || "DRAFT"),
    graph: {
      nodes: [...(def.graph?.nodes ?? [])],
      edges: [...(def.graph?.edges ?? [])],
    },
    layout: [...(def.layout ?? [])],
    variables: [...(def.variables ?? [])],
    config: { ...(def.config ?? {}) },
    revision: def.revision,
  };
}

function draftsEqual(a: EditorDraft | null, b: EditorDraft | null): boolean {
  if (!a || !b) return a === b;
  return JSON.stringify(a) === JSON.stringify(b);
}

export function definitionIsActive(status: string | undefined | null): boolean {
  return String(status || "").toUpperCase() === "ACTIVE";
}

export function definitionIsTemplate(status: string | undefined | null): boolean {
  return String(status || "").toUpperCase() === "TEMPLATE";
}

export function definitionIsInactive(status: string | undefined | null): boolean {
  const s = String(status || "").toUpperCase();
  return s === "INACTIVE" || s === "ARCHIVED" || s === "DRAFT";
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

export function formatRelativeNl(iso: string | null | undefined, nowMs = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diff = Math.max(0, nowMs - t);
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s geleden`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min geleden`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs}u geleden`;
  const days = Math.floor(hrs / 24);
  return `${days}d geleden`;
}

export function statusLabelNl(status: string | undefined | null): string {
  const s = String(status || "").toUpperCase();
  if (s === "ACTIVE") return "Actief";
  if (s === "INACTIVE") return "Inactief";
  if (s === "TEMPLATE") return "Template";
  if (s === "DRAFT") return "Concept";
  if (s === "ARCHIVED") return "Gearchiveerd";
  return s || "—";
}

export function executionStateLabelNl(state: string | undefined | null): string {
  const s = String(state || "").toUpperCase();
  if (s === "COMPLETED") return "Succesvol";
  if (s === "FAILED") return "Gefaald";
  if (s === "CANCELLED" || s === "CANCELLING") return "Geannuleerd";
  if (s === "RUNNING" || s === "STARTING" || s === "QUEUED") return "Draait";
  if (s === "WAITING" || s === "WAITING_APPROVAL") return "Wacht";
  return s || "—";
}

function initialNowMs(): number {
  if (typeof window !== "undefined") {
    const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
    if (frozen) {
      const t = Date.parse(frozen);
      if (!Number.isNaN(t)) return t;
    }
  }
  return Date.now();
}

export function useWorkflowsWorkspace() {
  const toast = useAppToast();

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);

  const [definitions, setDefinitions] = useState<WorkflowDefinition[]>([]);
  const [overview, setOverview] = useState<WorkflowOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [palette, setPalette] = useState<WorkflowPalette | null>(null);
  const [templates, setTemplates] = useState<WorkflowRecord[]>([]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [centerTab, setCenterTab] = useState<CenterTab>("canvas");
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");

  const [baseline, setBaseline] = useState<EditorDraft | null>(null);
  const [draft, setDraft] = useState<EditorDraft | null>(null);

  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [executionsError, setExecutionsError] = useState<string | null>(null);
  const [versions, setVersions] = useState<Array<Record<string, unknown>>>([]);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [logsError, setLogsError] = useState<string | null>(null);

  const [modal, setModal] = useState<ModalKind>(null);
  const [createName, setCreateName] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [createFromTemplateId, setCreateFromTemplateId] = useState<string | null>(null);
  const [pendingSelectId, setPendingSelectId] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(initialNowMs);

  const pollInflight = useRef(false);
  const loadGen = useRef(0);
  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedId;

  const dirty = useMemo(() => !draftsEqual(draft, baseline), [draft, baseline]);

  const applySelection = useCallback((def: WorkflowDefinition | null) => {
    if (!def) {
      setSelectedId(null);
      setBaseline(null);
      setDraft(null);
      setExecutions([]);
      setVersions([]);
      setLogs([]);
      return;
    }
    setSelectedId(def.workflow_id);
    const next = draftFromDefinition(def);
    setBaseline(next);
    setDraft(next);
  }, []);

  const loadDetailPanels = useCallback(async (workflowId: string) => {
    if (isWorkflowsVisualFixtureActive()) {
      const fx = WORKFLOWS_V2_VISUAL_FIXTURE;
      setExecutions([...fx.executions]);
      setVersions(fx.versions.map((v) => ({ ...v })));
      setLogs(fx.logs.map((l) => ({ ...l })));
      setExecutionsError(null);
      setVersionsError(null);
      setLogsError(null);
      return;
    }
    try {
      const [ex, ver, lg] = await Promise.all([
        api.listWorkflowExecutions(workflowId, 50),
        api.listWorkflowVersions(workflowId),
        api.workflowLogs(workflowId, { limit: 100 }),
      ]);
      setExecutions(ex.executions ?? []);
      setVersions(ver.versions ?? []);
      setLogs(lg.logs ?? []);
      setExecutionsError(null);
      setVersionsError(null);
      setLogsError(null);
    } catch (err) {
      const msg = errMsg(err, "Detail laden mislukt");
      setExecutionsError(msg);
      setVersionsError(msg);
      setLogsError(msg);
    }
  }, []);

  const load = useCallback(
    async (opts?: { quiet?: boolean }) => {
      const quiet = Boolean(opts?.quiet);
      const gen = ++loadGen.current;
      if (!quiet) {
        setLoading(true);
        setLoadError(null);
      }
      try {
        if (isWorkflowsVisualFixtureActive()) {
          const fx = WORKFLOWS_V2_VISUAL_FIXTURE;
          if (gen !== loadGen.current) return;
          setDefinitions(fx.definitions.map((d) => ({ ...d, graph: d.graph ? { ...d.graph, nodes: [...d.graph.nodes], edges: [...d.graph.edges] } : { nodes: [], edges: [] } })));
          setOverview({ ...fx.overview });
          setPalette({ ...fx.palette });
          setTemplates([...fx.templates]);
          setOverviewError(null);
          setStale(false);
          const selected =
            fx.definitions.find((d) => d.workflow_id === fx.selectedWorkflowId) ?? fx.definitions[0] ?? null;
          if (!selectedIdRef.current && selected) {
            applySelection(selected);
            await loadDetailPanels(selected.workflow_id);
          } else if (selectedIdRef.current) {
            const still = fx.definitions.find((d) => d.workflow_id === selectedIdRef.current);
            if (still && !dirty) {
              applySelection(still);
            }
            if (selectedIdRef.current) await loadDetailPanels(selectedIdRef.current);
          }
          return;
        }

        const [listRes, overviewRes, paletteRes, templatesRes] = await Promise.all([
          api.listWorkflows(200),
          api.workflowsOverview({ chartHours: 24, topDays: 7 }),
          api.workflowPalette(),
          api.workflowTemplates(50),
        ]);
        if (gen !== loadGen.current) return;

        const defs = (listRes.workflows ?? []).map(asDefinition);
        setDefinitions(defs);
        setOverview(overviewRes.overview ?? null);
        setPalette(paletteRes.palette ?? null);
        setTemplates(templatesRes.templates ?? []);
        setOverviewError(null);
        setStale(false);
        setLoadError(null);

        const currentId = selectedIdRef.current;
        if (!currentId && defs.length > 0) {
          applySelection(defs[0]);
          await loadDetailPanels(defs[0].workflow_id);
        } else if (currentId) {
          const still = defs.find((d) => d.workflow_id === currentId);
          if (!still) {
            applySelection(defs[0] ?? null);
            if (defs[0]) await loadDetailPanels(defs[0].workflow_id);
          } else if (!dirty) {
            applySelection(still);
            await loadDetailPanels(still.workflow_id);
          } else {
            await loadDetailPanels(currentId);
          }
        }
      } catch (err) {
        if (gen !== loadGen.current) return;
        const msg = errMsg(err, "Workflows laden mislukt");
        setLoadError(msg);
        setOverviewError(msg);
        setStale((prev) => prev || overview != null || definitions.length > 0);
      } finally {
        if (gen === loadGen.current) setLoading(false);
      }
    },
    [applySelection, definitions.length, dirty, loadDetailPanels, overview],
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      if (pollInflight.current) return;
      pollInflight.current = true;
      void load({ quiet: true }).finally(() => {
        pollInflight.current = false;
      });
    }, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        if (pollInflight.current) return;
        pollInflight.current = true;
        void load({ quiet: true }).finally(() => {
          pollInflight.current = false;
        });
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== "hidden") {
        const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
        if (frozen) {
          const t = Date.parse(frozen);
          if (!Number.isNaN(t)) {
            setNowMs(t);
            return;
          }
        }
        setNowMs(Date.now());
      }
    }, 5000);
    return () => window.clearInterval(id);
  }, []);

  const selected = useMemo(
    () => definitions.find((d) => d.workflow_id === selectedId) ?? null,
    [definitions, selectedId],
  );

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const d of definitions) {
      if (d.category) set.add(d.category);
    }
    return Array.from(set).sort();
  }, [definitions]);

  const counts = useMemo(() => {
    if (isWorkflowsVisualFixtureActive() && overview) {
      return {
        all: overview.counts.total_definitions,
        active: overview.counts.active_definitions,
        inactive: overview.counts.inactive_definitions,
        templates: overview.counts.templates,
      };
    }
    const nonTemplate = definitions.filter((d) => !definitionIsTemplate(d.status));
    return {
      all: nonTemplate.length,
      active: nonTemplate.filter((d) => definitionIsActive(d.status)).length,
      inactive: nonTemplate.filter((d) => !definitionIsActive(d.status)).length,
      templates: definitions.filter((d) => definitionIsTemplate(d.status)).length,
    };
  }, [definitions, overview]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return definitions.filter((d) => {
      const status = String(d.status || "").toUpperCase();
      if (filter === "active" && status !== "ACTIVE") return false;
      if (filter === "inactive" && (status === "ACTIVE" || status === "TEMPLATE")) return false;
      if (filter === "templates" && status !== "TEMPLATE") return false;
      if (filter === "all" && status === "TEMPLATE") return false;
      if (category !== "all" && (d.category || "") !== category) return false;
      if (!q) return true;
      const hay = `${d.name} ${d.description ?? ""} ${d.category ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [definitions, filter, category, query]);

  const requestSelect = useCallback(
    (id: string) => {
      if (id === selectedId) return;
      if (dirty) {
        setPendingSelectId(id);
        setModal("unsaved");
        return;
      }
      const def = definitions.find((d) => d.workflow_id === id) ?? null;
      applySelection(def);
      if (def) void loadDetailPanels(def.workflow_id);
    },
    [applySelection, definitions, dirty, loadDetailPanels, selectedId],
  );

  const discardAndSelect = useCallback(() => {
    const id = pendingSelectId;
    setModal(null);
    setPendingSelectId(null);
    if (!id) return;
    const def = definitions.find((d) => d.workflow_id === id) ?? null;
    applySelection(def);
    if (def) void loadDetailPanels(def.workflow_id);
  }, [applySelection, definitions, loadDetailPanels, pendingSelectId]);

  const updateDraft = useCallback((patch: Partial<EditorDraft>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  const setGraph = useCallback((graph: WorkflowGraph, layout?: WorkflowLayoutNode[]) => {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            graph,
            layout: layout ?? prev.layout,
          }
        : prev,
    );
  }, []);

  const save = useCallback(async () => {
    if (!selectedId || !draft) return;
    setBusy(true);
    try {
      if (isWorkflowsVisualFixtureActive()) {
        setBaseline(draft);
        toast("Workflow opgeslagen (fixture)" );
        return;
      }
      const res = await api.patchWorkflow(selectedId, {
        name: draft.name,
        description: draft.description,
        category: draft.category,
        status: draft.status,
        graph: draft.graph,
        layout: draft.layout,
        variables: draft.variables,
        config: draft.config,
        revision: draft.revision,
        change_summary: "Canvas / configuratie update",
      });
      const next = asDefinition(res.workflow);
      setDefinitions((prev) => prev.map((d) => (d.workflow_id === next.workflow_id ? next : d)));
      applySelection(next);
      toast("Workflow opgeslagen");
    } catch (err) {
      toast(errMsg(err, "Opslaan mislukt") );
    } finally {
      setBusy(false);
    }
  }, [applySelection, draft, selectedId, toast]);

  const run = useCallback(
    async (workflowId?: string) => {
      const id = workflowId || selectedId;
      if (!id) return;
      setBusy(true);
      try {
        if (isWorkflowsVisualFixtureActive()) {
          toast("Workflow gestart (fixture)");
          return;
        }
        await api.runWorkflow(id, {});
        toast("Workflow gestart");
        await loadDetailPanels(id);
        void load({ quiet: true });
      } catch (err) {
        toast(errMsg(err, "Uitvoeren mislukt"));
      } finally {
        setBusy(false);
      }
    },
    [load, loadDetailPanels, selectedId, toast],
  );

  const cancelSelected = useCallback(async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      if (isWorkflowsVisualFixtureActive()) {
        toast("Geannuleerd (fixture)" );
        return;
      }
      await api.cancelWorkflow(selectedId);
      toast("Workflow geannuleerd");
      await loadDetailPanels(selectedId);
    } catch (err) {
      toast(errMsg(err, "Annuleren mislukt") );
    } finally {
      setBusy(false);
    }
  }, [loadDetailPanels, selectedId, toast]);

  const duplicate = useCallback(async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      if (isWorkflowsVisualFixtureActive()) {
        toast("Gedupliceerd (fixture)" );
        return;
      }
      const res = await api.duplicateWorkflow(selectedId);
      const next = asDefinition(res.workflow);
      setDefinitions((prev) => [next, ...prev]);
      applySelection(next);
      toast("Workflow gedupliceerd");
      await loadDetailPanels(next.workflow_id);
    } catch (err) {
      toast(errMsg(err, "Dupliceren mislukt") );
    } finally {
      setBusy(false);
    }
  }, [applySelection, loadDetailPanels, selectedId, toast]);

  const remove = useCallback(async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      if (isWorkflowsVisualFixtureActive()) {
        setDefinitions((prev) => prev.filter((d) => d.workflow_id !== selectedId));
        applySelection(null);
        setModal(null);
        toast("Verwijderd (fixture)" );
        return;
      }
      await api.deleteWorkflow(selectedId, false);
      setDefinitions((prev) => prev.filter((d) => d.workflow_id !== selectedId));
      applySelection(null);
      setModal(null);
      toast("Workflow verwijderd");
      void load({ quiet: true });
    } catch (err) {
      toast(errMsg(err, "Verwijderen mislukt") );
    } finally {
      setBusy(false);
    }
  }, [applySelection, load, selectedId, toast]);

  const create = useCallback(async () => {
    const name = createName.trim() || "Nieuwe workflow";
    setBusy(true);
    try {
      if (isWorkflowsVisualFixtureActive()) {
        const id = `wf-new-${Date.now()}`;
        const next: WorkflowDefinition = {
          workflow_id: id,
          name,
          description: createDesc,
          category: "Research",
          tags: [],
          status: "DRAFT",
          graph: { nodes: [], edges: [] },
          variables: [],
          layout: [],
          config: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        setDefinitions((prev) => [next, ...prev]);
        applySelection(next);
        setModal(null);
        setCreateName("");
        setCreateDesc("");
        setCreateFromTemplateId(null);
        toast("Workflow aangemaakt (fixture)" );
        return;
      }
      const res = await api.createWorkflow({
        name,
        description: createDesc,
        status: "DRAFT",
        from_template_id: createFromTemplateId ?? undefined,
        graph: { nodes: [], edges: [] },
      });
      const next = asDefinition(res.workflow);
      setDefinitions((prev) => [next, ...prev]);
      applySelection(next);
      setModal(null);
      setCreateName("");
      setCreateDesc("");
      setCreateFromTemplateId(null);
      toast("Workflow aangemaakt");
      await loadDetailPanels(next.workflow_id);
    } catch (err) {
      toast(errMsg(err, "Aanmaken mislukt") );
    } finally {
      setBusy(false);
    }
  }, [applySelection, createDesc, createFromTemplateId, createName, loadDetailPanels, toast]);

  const restoreVersion = useCallback(
    async (version: number) => {
      if (!selectedId) return;
      setBusy(true);
      try {
        if (isWorkflowsVisualFixtureActive()) {
          toast(`Versie ${version} hersteld (fixture)`);
          return;
        }
        const res = await api.restoreWorkflowVersion(selectedId, version);
        const next = asDefinition(res.workflow);
        setDefinitions((prev) => prev.map((d) => (d.workflow_id === next.workflow_id ? next : d)));
        applySelection(next);
        toast(`Versie ${version} hersteld`);
        await loadDetailPanels(next.workflow_id);
      } catch (err) {
        toast(errMsg(err, "Versie herstellen mislukt") );
      } finally {
        setBusy(false);
      }
    },
    [applySelection, loadDetailPanels, selectedId, toast],
  );

  const patchStatus = useCallback(
    async (status: string) => {
      if (!selectedId) return;
      setBusy(true);
      try {
        if (isWorkflowsVisualFixtureActive()) {
          setDefinitions((prev) =>
            prev.map((d) => (d.workflow_id === selectedId ? { ...d, status } : d)),
          );
          updateDraft({ status });
          setBaseline((prev) => (prev ? { ...prev, status } : prev));
          toast("Status bijgewerkt (fixture)" );
          return;
        }
        const res = await api.patchWorkflow(selectedId, { status });
        const next = asDefinition(res.workflow);
        setDefinitions((prev) => prev.map((d) => (d.workflow_id === next.workflow_id ? next : d)));
        if (!dirty) applySelection(next);
        else updateDraft({ status: String(next.status) });
        toast("Status bijgewerkt");
      } catch (err) {
        toast(errMsg(err, "Status wijzigen mislukt") );
      } finally {
        setBusy(false);
      }
    },
    [applySelection, dirty, selectedId, toast, updateDraft],
  );

  return {
    loading,
    loadError,
    stale,
    busy,
    definitions,
    overview,
    overviewError,
    palette,
    templates,
    selected,
    selectedId,
    query,
    setQuery,
    category,
    setCategory,
    categories,
    filter,
    setFilter,
    viewMode,
    setViewMode,
    centerTab,
    setCenterTab,
    detailTab,
    setDetailTab,
    draft,
    baseline,
    dirty,
    updateDraft,
    setGraph,
    executions,
    executionsError,
    versions,
    versionsError,
    logs,
    logsError,
    modal,
    setModal,
    createName,
    setCreateName,
    createDesc,
    setCreateDesc,
    createFromTemplateId,
    setCreateFromTemplateId,
    counts,
    filtered,
    nowMs,
    load,
    requestSelect,
    discardAndSelect,
    save,
    run,
    cancelSelected,
    duplicate,
    remove,
    create,
    restoreVersion,
    patchStatus,
  };
}

export type WorkflowsWorkspace = ReturnType<typeof useWorkflowsWorkspace>;
