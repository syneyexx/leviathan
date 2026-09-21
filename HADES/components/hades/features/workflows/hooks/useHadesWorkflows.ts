"use client";

import { useCallback, useState } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type Gen2Workflow } from "@/lib/hades-api";

const KEY = "hades:workflows";

export function useHadesWorkflows() {
  const [selectedId, setSelectedId] = useState("");
  const query = useHadesQuery(
    KEY,
    async () => {
      const [workflows, templates] = await Promise.all([
        hadesApi.gen2Workflows().catch((err) => ({
          error: err instanceof Error ? err.message : String(err),
        })),
        hadesApi.gen2WorkflowTemplates().catch(() => []),
      ]);
      return { workflows, templates };
    },
    { staleTime: 6_000, refetchInterval: 20_000 },
  );

  const refresh = useCallback(async () => {
    invalidateHadesQuery(KEY);
    return query.refetch();
  }, [query]);

  const wfRaw = query.data?.workflows;
  const workflows: Gen2Workflow[] = Array.isArray(wfRaw) ? wfRaw : [];
  const error =
    query.error?.message ||
    (wfRaw && typeof wfRaw === "object" && !Array.isArray(wfRaw) && "error" in wfRaw
      ? String((wfRaw as { error: string }).error)
      : null);

  const selected = workflows.find((w) => w.id === selectedId) || workflows[0] || null;

  return {
    workflows,
    templates: Array.isArray(query.data?.templates) ? query.data!.templates : [],
    selected,
    selectedId: selected?.id || "",
    setSelectedId,
    loading: query.status === "loading" && !query.data,
    error,
    refresh,
    validate: async (id: string) => hadesApi.gen2ValidateWorkflow(id),
    dryRun: async (id: string) => hadesApi.gen2DryRunWorkflow(id),
    createFromTemplate: async (templateId: string, name?: string) => {
      const created = await hadesApi.gen2CreateWorkflowFromTemplate(templateId, name);
      await refresh();
      return created;
    },
  };
}
