import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../../../api/client";
import { useAppToast } from "../../../../state/useAppToast";
import {
  asSkill,
  buildActionModels,
  buildFilterChips,
  buildInfoFields,
  buildKpiModels,
  type SkillDetailTab,
  type SkillFilter,
  type SkillRecord,
  type SkillTotals,
} from "../viewModels";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
}

const PAGE_LIMIT = 40;
const SEARCH_DEBOUNCE_MS = 280;

export function useSkillsPage() {
  const toast = useAppToast();
  const [filter, setFilter] = useState<SkillFilter>("all");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [totals, setTotals] = useState<SkillTotals | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [instructions, setInstructions] = useState<string | null>(null);
  const [instructionsLoading, setInstructionsLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<SkillDetailTab>("description");
  const [structuredResult, setStructuredResult] = useState<{
    label: string;
    format: "json" | "text";
    body: string;
  } | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const requestSeq = useRef(0);
  const detailSeq = useRef(0);

  // Debounce search input.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      setQuery(queryInput.trim());
      setOffset(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [queryInput]);

  const loadList = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.listSkills({
        query: query || undefined,
        classification: filter,
        include_catalog: true,
        enabled_only: false,
        limit: PAGE_LIMIT,
        offset,
      });
      if (seq !== requestSeq.current) return;
      const rows = (res.skills ?? [])
        .map((r) => asSkill(r as Record<string, unknown>))
        .filter((s): s is SkillRecord => Boolean(s));
      setSkills(rows);
      setTotals((res.totals as SkillTotals) ?? null);
      setSelectedId((prev) => {
        if (prev && rows.some((r) => r.skill_id === prev)) return prev;
        return rows[0]?.skill_id ?? null;
      });
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError(errorMessage(err));
      setSkills([]);
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [filter, offset, query]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const selectedSummary = useMemo(
    () => skills.find((s) => s.skill_id === selectedId) ?? null,
    [skills, selectedId],
  );

  // Load detail metadata (without instructions) when selection changes.
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setInstructions(null);
      setStructuredResult(null);
      return;
    }
    const seq = ++detailSeq.current;
    setDetailLoading(true);
    setInstructions(null);
    void (async () => {
      try {
        const res = await api.getSkill(selectedId, false);
        if (seq !== detailSeq.current) return;
        const skill = asSkill(res.skill as Record<string, unknown>);
        setDetail(skill);
      } catch (err) {
        if (seq !== detailSeq.current) return;
        toast(errorMessage(err));
        setDetail(selectedSummary);
      } finally {
        if (seq === detailSeq.current) setDetailLoading(false);
      }
    })();
  }, [selectedId, selectedSummary, toast]);

  const skill = detail ?? selectedSummary;
  const kpis = useMemo(() => buildKpiModels(totals), [totals]);
  const chips = useMemo(() => buildFilterChips(totals), [totals]);
  const actions = useMemo(() => buildActionModels(skill), [skill]);
  const infoFields = useMemo(() => (skill ? buildInfoFields(skill) : []), [skill]);

  const selectSkill = useCallback((id: string) => {
    setSelectedId(id);
    setTab("description");
    setMoreOpen(false);
    setStructuredResult(null);
  }, []);

  const changeFilter = useCallback((next: SkillFilter) => {
    setFilter(next);
    setOffset(0);
  }, []);

  async function loadInstructions() {
    if (!skill) return;
    setInstructionsLoading(true);
    try {
      const res = await api.getSkill(skill.skill_id, true);
      const next = asSkill(res.skill as Record<string, unknown>);
      if (next) setDetail(next);
      setInstructions(String((res.skill as { instructions?: string }).instructions || ""));
    } catch (err) {
      toast(errorMessage(err));
    } finally {
      setInstructionsLoading(false);
    }
  }

  async function onToggleEnabled() {
    if (!skill || skill.catalog_only) return;
    const enabled = !skill.enabled;
    setActionBusy("disable");
    try {
      const res = await api.setSkillEnabled(skill.skill_id, enabled);
      const next = asSkill(res.skill as Record<string, unknown>);
      if (next) setDetail(next);
      toast(`${enabled ? "Enabled" : "Disabled"} ${skill.name}`);
      void loadList();
    } catch (err) {
      toast(errorMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function onTest() {
    if (!skill) return;
    setActionBusy("test");
    try {
      const res = await api.testSkill(skill.skill_id);
      const result = res.result;
      setStructuredResult({
        label: "LAST RESULT",
        format: "json",
        body: JSON.stringify(result, null, 2),
      });
      setTab("description");
      toast(result.ok ? `Test passed for ${skill.name}` : `Test failed for ${skill.name}`);
      if (res.skill) setDetail(asSkill(res.skill as Record<string, unknown>));
    } catch (err) {
      toast(errorMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function onExecute() {
    if (!skill) return;
    const required = skill.required_capabilities || skill.declarations?.required_capabilities || [];
    if (!required.length) {
      toast("Instruction-only skill; no executable capability");
      return;
    }
    setActionBusy("execute");
    try {
      const res = await api.executeSkill(skill.skill_id, {
        capability_id: required[0],
        arguments: {},
      });
      setStructuredResult({
        label: "LAST RESULT",
        format: "json",
        body: JSON.stringify(res, null, 2),
      });
      toast(`Executed via ${res.capability_id}`);
    } catch (err) {
      toast(errorMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function onConfigure() {
    if (!skill?.module_id) return;
    // Navigate via hash/path the Modules page understands.
    window.location.hash = `#/modules?module=${encodeURIComponent(skill.module_id)}`;
    toast(`Open module ${skill.module_id} for configuration`);
  }

  async function onUpdate() {
    if (!skill?.module_id) return;
    setActionBusy("update");
    try {
      const res = await api.moduleCheckUpdate(skill.module_id);
      setStructuredResult({
        label: "LAST RESULT",
        format: "json",
        body: JSON.stringify(res, null, 2),
      });
      const available = Boolean(
        (res as { update_available?: boolean }).update_available ??
          (res as { result?: { update_available?: boolean } }).result?.update_available,
      );
      toast(
        available
          ? `Update available for module ${skill.module_id}`
          : `No update reported for module ${skill.module_id}`,
      );
    } catch (err) {
      toast(errorMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function onViewExamples() {
    if (!skill) return;
    setTab("examples");
    const examples = skill.declarations?.examples;
    const refs = skill.declarations?.example_refs || [];
    if (examples != null) {
      setStructuredResult({
        label: "EXAMPLE OUTPUT",
        format: "json",
        body: typeof examples === "string" ? examples : JSON.stringify(examples, null, 2),
      });
    } else if (refs.length) {
      setStructuredResult({
        label: "EXAMPLE OUTPUT",
        format: "json",
        body: JSON.stringify({ example_refs: refs }, null, 2),
      });
    } else {
      setStructuredResult({
        label: "EXAMPLE OUTPUT",
        format: "text",
        body: "No examples declared.",
      });
      toast("No examples declared.");
    }
  }

  async function onLoadModuleLogs() {
    if (!skill?.module_id) {
      setStructuredResult({
        label: "LOGS",
        format: "text",
        body: "No skill/module logs available.",
      });
      return;
    }
    setActionBusy("logs");
    try {
      const res = await api.moduleLogs(skill.module_id, 100);
      const lines = (res as { lines?: string[] }).lines ?? [];
      setStructuredResult({
        label: "LOGS",
        format: "text",
        body: lines.length ? lines.join("\n") : "No skill/module logs available.",
      });
    } catch (err) {
      toast(errorMessage(err));
      setStructuredResult({
        label: "LOGS",
        format: "text",
        body: "No skill/module logs available.",
      });
    } finally {
      setActionBusy(null);
    }
  }

  async function onLoadVersions() {
    if (!skill?.module_id) {
      setStructuredResult({
        label: "VERSION HISTORY",
        format: "text",
        body: "No canonical version history for this skill.",
      });
      return;
    }
    setActionBusy("versions");
    try {
      const res = await api.moduleVersions(skill.module_id);
      setStructuredResult({
        label: "VERSION HISTORY",
        format: "json",
        body: JSON.stringify(res, null, 2),
      });
    } catch (err) {
      toast(errorMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  return {
    PAGE_LIMIT,
    filter,
    changeFilter,
    queryInput,
    setQueryInput,
    skills,
    totals,
    offset,
    setOffset,
    loading,
    error,
    selectedId,
    selectSkill,
    skill,
    detailLoading,
    instructions,
    instructionsLoading,
    loadInstructions,
    actionBusy,
    actions,
    kpis,
    chips,
    infoFields,
    tab,
    setTab,
    structuredResult,
    setStructuredResult,
    moreOpen,
    setMoreOpen,
    reload: loadList,
    onToggleEnabled,
    onTest,
    onExecute,
    onConfigure,
    onUpdate,
    onViewExamples,
    onLoadModuleLogs,
    onLoadVersions,
  };
}
