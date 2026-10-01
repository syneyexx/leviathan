/**
 * Per-resource fetch state — failures must not look like successful empty data.
 *
 * - Initial failure: measured=false → UI shows UNKNOWN/UNAVAILABLE, never zero.
 * - Refresh failure: retain last known data, mark stale, surface error.
 * - Success (including empty collections): measured=true.
 */

export type ResourceState<T> = {
  data: T;
  loading: boolean;
  error: string | null;
  stale: boolean;
  fetchedAt: string | null;
  measured: boolean;
};

export function emptyResource<T>(data: T): ResourceState<T> {
  return {
    data,
    loading: false,
    error: null,
    stale: false,
    fetchedAt: null,
    measured: false,
  };
}

export function resourceLoading<T>(prev: ResourceState<T>): ResourceState<T> {
  return {
    ...prev,
    loading: true,
    // Keep prior error visible until a new outcome arrives when we already measured.
    error: prev.measured ? prev.error : null,
  };
}

export function resourceSuccess<T>(data: T, fetchedAt = new Date().toISOString()): ResourceState<T> {
  return {
    data,
    loading: false,
    error: null,
    stale: false,
    fetchedAt,
    measured: true,
  };
}

export function resourceFailure<T>(
  prev: ResourceState<T>,
  error: string,
  opts?: { fetchedAt?: string },
): ResourceState<T> {
  const hadData = prev.measured;
  return {
    data: prev.data,
    loading: false,
    error,
    stale: hadData,
    fetchedAt: opts?.fetchedAt ?? prev.fetchedAt,
    measured: hadData,
  };
}

/** Apply settled promise outcome onto a ResourceState without inventing empty success. */
export function applySettledResource<T>(
  prev: ResourceState<T>,
  settled: PromiseSettledResult<T>,
  errFallback: string,
  fetchedAt = new Date().toISOString(),
): ResourceState<T> {
  if (settled.status === "fulfilled") {
    return resourceSuccess(settled.value, fetchedAt);
  }
  const reason = settled.reason;
  const message =
    reason instanceof Error && reason.message ? reason.message : errFallback;
  return resourceFailure(prev, message, { fetchedAt });
}

/** Display helper: unmeasured → UNAVAILABLE/UNKNOWN label; measured empty is real zero. */
export function resourceAvailabilityLabel(
  state: ResourceState<unknown>,
  opts?: { loadingLabel?: string; unknownLabel?: string; unavailableLabel?: string },
): string {
  if (state.loading && !state.measured) return opts?.loadingLabel ?? "…";
  if (!state.measured) {
    return state.error
      ? (opts?.unavailableLabel ?? "UNAVAILABLE")
      : (opts?.unknownLabel ?? "UNKNOWN");
  }
  if (state.stale && state.error) return "STALE";
  return "";
}

export function anyResourceStale(
  ...states: Array<ResourceState<unknown>>
): boolean {
  return states.some((s) => s.stale);
}

export function firstResourceError(
  ...states: Array<ResourceState<unknown>>
): string | null {
  for (const s of states) {
    if (s.error) return s.error;
  }
  return null;
}
