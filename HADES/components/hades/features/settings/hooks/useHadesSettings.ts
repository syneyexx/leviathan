"use client";

import { useCallback, useMemo, useState } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type AppSettings } from "@/lib/hades-api";
import { HADES_SETTINGS_UPDATED_EVENT } from "../settings-events";

const SETTINGS_KEY = "hades:settings";

export type SettingsPatchResult = {
  values: AppSettings;
  config_revision?: number;
};

/** Canonical settings load/patch with optimistic concurrency (config_revision). */
export function useHadesSettings() {
  const [busy, setBusy] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [revision, setRevision] = useState<number | undefined>(undefined);

  const query = useHadesQuery(
    SETTINGS_KEY,
    async () => {
      const res = await hadesApi.settings();
      if (typeof res.config_revision === "number") setRevision(res.config_revision);
      else if (typeof res.values?.config_revision === "number") setRevision(res.values.config_revision);
      return res;
    },
    { staleTime: 3_000 },
  );

  const values = query.data?.values;

  const policies = useMemo(
    () => ({
      file_read_policy: values?.file_read_policy ?? "ask",
      file_write_policy: values?.file_write_policy ?? "ask",
      network_policy: values?.network_policy ?? "block",
      subprocess_policy: values?.subprocess_policy ?? "ask",
      plugin_autonomous_tools: Boolean(values?.plugin_autonomous_tools),
      max_tool_rounds: values?.max_tool_rounds ?? null,
      request_timeout_seconds: values?.request_timeout_seconds ?? null,
      reasoning_profile: values?.reasoning_profile ?? "adaptive",
    }),
    [values],
  );

  const refresh = useCallback(async () => {
    invalidateHadesQuery(SETTINGS_KEY);
    return query.refetch();
  }, [query]);

  const patch = useCallback(
    async (partial: Partial<AppSettings>) => {
      setBusy(true);
      setLastError(null);
      try {
        const expected = revision ?? values?.config_revision;
        const res = await hadesApi.patchSettings(partial, expected);
        if (typeof res.config_revision === "number") setRevision(res.config_revision);
        else if (typeof res.values?.config_revision === "number") setRevision(res.values.config_revision);
        invalidateHadesQuery(SETTINGS_KEY);
        await query.refetch();
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent(HADES_SETTINGS_UPDATED_EVENT, { detail: res.values }));
        }
        return res as SettingsPatchResult;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setLastError(message);
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [query, revision, values?.config_revision],
  );

  return {
    values,
    storage: query.data?.storage,
    version: query.data?.version,
    policies,
    loading: query.status === "loading" && !query.data,
    error: query.error,
    lastError,
    busy,
    revision,
    refresh,
    patch,
  };
}
