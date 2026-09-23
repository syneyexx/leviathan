/**
 * Shared Dataset Activity polling / merge hook.
 *
 * Canonical job truth remains DatasetJob from the API — this only
 * derives console entries and drives adaptive polling.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { DatasetActivityEntry, DatasetJob } from "../../types/api";
import {
  isActiveJob,
  mergeActivityEntries,
  pollingIntervalMs,
} from "./datasetActivity";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export type UseDatasetActivityOptions = {
  /** Called when any job status changes (create/complete/fail/cancel). */
  onLifecycleChange?: () => void;
  limit?: number;
};

export type UseDatasetActivityResult = {
  jobs: DatasetJob[];
  jobsError: string | null;
  activityEntries: DatasetActivityEntry[];
  preferredJobId: string | null;
  setPreferredJobId: (jobId: string | null) => void;
  loadJobs: () => Promise<DatasetJob[]>;
  clearActivityView: () => void;
  live: boolean;
};

export function useDatasetActivity(
  options: UseDatasetActivityOptions = {},
): UseDatasetActivityResult {
  const { onLifecycleChange, limit = 50 } = options;
  const [jobs, setJobs] = useState<DatasetJob[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [activityEntries, setActivityEntries] = useState<DatasetActivityEntry[]>([]);
  const [preferredJobId, setPreferredJobId] = useState<string | null>(null);

  const prevJobsRef = useRef<Map<string, DatasetJob>>(new Map());
  const activityEntriesRef = useRef<DatasetActivityEntry[]>([]);
  const clearedEntryIdsRef = useRef<Set<string>>(new Set());
  const jobsFailRef = useRef(0);
  const pollTimerRef = useRef<number | null>(null);
  const onLifecycleChangeRef = useRef(onLifecycleChange);
  onLifecycleChangeRef.current = onLifecycleChange;

  activityEntriesRef.current = activityEntries;

  const loadJobs = useCallback(async () => {
    try {
      const res = await api.listDatasetJobs(undefined, limit);
      const next = res.jobs;
      setJobsError(null);
      jobsFailRef.current = 0;
      setJobs((prev) => {
        const prevById = new Map(prev.map((j) => [j.jobId, j]));
        const merged = mergeActivityEntries(
          activityEntriesRef.current,
          next,
          prevJobsRef.current,
        );
        const filtered = merged.filter((e) => !clearedEntryIdsRef.current.has(e.id));
        activityEntriesRef.current = filtered;
        setActivityEntries(filtered);
        prevJobsRef.current = new Map(next.map((j) => [j.jobId, j]));

        const lifecycleHit = next.some((j) => {
          const old = prevById.get(j.jobId);
          if (!old) return true;
          return old.status !== j.status;
        });
        if (lifecycleHit) {
          onLifecycleChangeRef.current?.();
        }
        return next;
      });
      return next;
    } catch (err) {
      jobsFailRef.current += 1;
      setJobsError(errMsg(err, "Failed to load dataset jobs"));
      return [] as DatasetJob[];
    }
  }, [limit]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    let cancelled = false;

    const schedule = () => {
      if (cancelled) return;
      if (pollTimerRef.current != null) window.clearTimeout(pollTimerRef.current);
      const hasActive = jobs.some(isActiveJob);
      const delay = pollingIntervalMs({
        hasActive,
        hasJobs: jobs.length > 0,
        consecutiveFailures: jobsFailRef.current,
      });
      pollTimerRef.current = window.setTimeout(() => {
        void (async () => {
          await loadJobs();
          if (!cancelled) schedule();
        })();
      }, delay);
    };

    schedule();
    return () => {
      cancelled = true;
      if (pollTimerRef.current != null) window.clearTimeout(pollTimerRef.current);
    };
  }, [jobs, loadJobs]);

  const clearActivityView = useCallback(() => {
    for (const e of activityEntriesRef.current) {
      clearedEntryIdsRef.current.add(e.id);
    }
    setActivityEntries([]);
    activityEntriesRef.current = [];
  }, []);

  return {
    jobs,
    jobsError,
    activityEntries,
    preferredJobId,
    setPreferredJobId,
    loadJobs,
    clearActivityView,
    live: jobs.some(isActiveJob) && !jobsError,
  };
}
