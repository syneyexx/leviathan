"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type HadesQueryStatus = "idle" | "loading" | "success" | "error";
export type HadesQueryFetcher<T> = (signal: AbortSignal) => Promise<T>;

export type HadesQueryOptions = {
  enabled?: boolean;
  staleTime?: number;
  refetchInterval?: number;
  refetchOnVisibility?: boolean;
};

type QueryEntry<T> = {
  data: T | undefined;
  error: Error | null;
  status: HadesQueryStatus;
  updatedAt: number;
  promise: Promise<T> | null;
  controller: AbortController | null;
  listeners: Set<() => void>;
  /** Set by invalidate; enabled subscribers clear + refetch. */
  needsRefetch: boolean;
  /** Monotonic id so aborted responses cannot overwrite newer fetches. */
  fetchEpoch: number;
};

const queryCache = new Map<string, QueryEntry<unknown>>();

function entryFor<T>(key: string): QueryEntry<T> {
  const cached = queryCache.get(key);
  if (cached) return cached as QueryEntry<T>;
  const entry: QueryEntry<T> = {
    data: undefined,
    error: null,
    status: "idle",
    updatedAt: 0,
    promise: null,
    controller: null,
    listeners: new Set(),
    needsRefetch: false,
    fetchEpoch: 0,
  };
  queryCache.set(key, entry as QueryEntry<unknown>);
  return entry;
}

function notify(entry: QueryEntry<unknown>) {
  entry.listeners.forEach((listener) => listener());
}

/** Pure auto-fetch gate used by visibility / interval paths. */
export function shouldAutoFetch(options: {
  enabled: boolean;
  refetchOnVisibility?: boolean;
  visibilityState?: string;
}): boolean {
  if (!options.enabled) return false;
  if (options.refetchOnVisibility === false) return false;
  if (options.visibilityState && options.visibilityState !== "visible") return false;
  return true;
}

async function fetchEntry<T>(
  key: string,
  fetcher: HadesQueryFetcher<T>,
  staleTime: number,
  force = false,
): Promise<T> {
  const entry = entryFor<T>(key);
  // Deduplicate in-flight requests unless an explicit force refresh is requested.
  if (entry.promise && !force) return entry.promise;
  if (!force && entry.data !== undefined && Date.now() - entry.updatedAt < staleTime) return entry.data;

  entry.controller?.abort();
  const controller = new AbortController();
  entry.controller = controller;
  const epoch = entry.fetchEpoch + 1;
  entry.fetchEpoch = epoch;
  entry.status = entry.data === undefined ? "loading" : entry.status;
  entry.error = null;
  entry.needsRefetch = false;
  notify(entry as QueryEntry<unknown>);

  const promise = fetcher(controller.signal)
    .then((data) => {
      // Only the latest non-aborted epoch may commit results.
      if (!controller.signal.aborted && entry.fetchEpoch === epoch) {
        entry.data = data;
        entry.error = null;
        entry.status = "success";
        entry.updatedAt = Date.now();
      }
      return data;
    })
    .catch((reason: unknown) => {
      if (!controller.signal.aborted && entry.fetchEpoch === epoch) {
        entry.error = reason instanceof Error ? reason : new Error(String(reason));
        entry.status = "error";
      }
      throw reason;
    })
    .finally(() => {
      if (entry.controller === controller) entry.controller = null;
      if (entry.promise === promise) entry.promise = null;
      notify(entry as QueryEntry<unknown>);
    });
  entry.promise = promise;
  return promise;
}

export function invalidateHadesQuery(key: string): void {
  const entry = queryCache.get(key);
  if (!entry) return;
  entry.updatedAt = 0;
  entry.needsRefetch = true;
  notify(entry);
}

/**
 * Manual refetch is always allowed (explicit caller intent), even when the
 * query hook is mounted with ``enabled=false``. Automatic paths must use
 * ``shouldAutoFetch`` / the enabled gate instead.
 */
export function refetchHadesQuery<T>(
  key: string,
  fetcher: HadesQueryFetcher<T>,
  staleTime = 0,
  force = true,
): Promise<T> {
  return fetchEntry(key, fetcher, staleTime, force);
}

export function useHadesQuery<T>(
  key: string,
  fetcher: HadesQueryFetcher<T>,
  options: HadesQueryOptions = {},
) {
  const {
    enabled = true,
    staleTime = 0,
    refetchInterval = 0,
    refetchOnVisibility = true,
  } = options;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const [, render] = useState(0);
  const entry = entryFor<T>(key);

  const refetch = useCallback(
    (force = true) => fetchEntry(key, (signal) => fetcherRef.current(signal), staleTime, force),
    [key, staleTime],
  );
  const invalidate = useCallback(() => {
    invalidateHadesQuery(key);
    if (enabled) void refetch(true).catch(() => undefined);
  }, [enabled, key, refetch]);

  useEffect(() => {
    const current = entryFor<T>(key);
    const listener = () => {
      render((value) => value + 1);
      // Invalidation from any subscriber: enabled mounts refresh; disabled do not.
      if (enabledRef.current && current.needsRefetch) {
        void refetch(true).catch(() => undefined);
      }
    };
    current.listeners.add(listener);
    if (enabled) void refetch(false).catch(() => undefined);

    const refreshWhenVisible = () => {
      if (
        shouldAutoFetch({
          enabled: enabledRef.current,
          refetchOnVisibility: true,
          visibilityState: document.visibilityState,
        })
      ) {
        void refetch(false).catch(() => undefined);
      }
    };
    if (refetchOnVisibility) document.addEventListener("visibilitychange", refreshWhenVisible);

    let interval = 0;
    if (enabled && refetchInterval > 0) {
      interval = window.setInterval(() => {
        if (
          shouldAutoFetch({
            enabled: enabledRef.current,
            visibilityState: document.visibilityState,
          })
        ) {
          void refetch(true).catch(() => undefined);
        }
      }, refetchInterval);
    }
    return () => {
      current.listeners.delete(listener);
      if (refetchOnVisibility) document.removeEventListener("visibilitychange", refreshWhenVisible);
      if (interval) window.clearInterval(interval);
      if (!current.listeners.size && current.controller) {
        current.controller.abort();
        current.controller = null;
        current.promise = null;
      }
    };
  }, [enabled, key, refetch, refetchInterval, refetchOnVisibility]);

  return {
    data: entry.data,
    error: entry.error,
    status: entry.status,
    isLoading: entry.status === "loading",
    isFetching: Boolean(entry.promise),
    updatedAt: entry.updatedAt,
    refetch,
    invalidate,
  };
}

/** Test-only helpers — not part of the production UI contract. */
export const __hadesQueryTestUtils = {
  resetCache() {
    queryCache.clear();
  },
  entryFor,
  fetchEntry,
  getCacheSize() {
    return queryCache.size;
  },
};
