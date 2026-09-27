export type ProjectionState =
  | "LOADING"
  | "LIVE"
  | "STALE"
  | "TRANSPORT_ERROR"
  | "UNAVAILABLE";

export interface ReadProjection<T> {
  data: T | null;
  state: ProjectionState;
  lastAttemptAt: number | null;
  lastSuccessAt: number | null;
  errorCode: string | null;
  errorDetail: string | null;
}

export function loadingProjection<T>(): ReadProjection<T> {
  return {
    data: null,
    state: "LOADING",
    lastAttemptAt: null,
    lastSuccessAt: null,
    errorCode: null,
    errorDetail: null,
  };
}

export function liveProjection<T>(data: T, now: number = Date.now()): ReadProjection<T> {
  return {
    data,
    state: "LIVE",
    lastAttemptAt: now,
    lastSuccessAt: now,
    errorCode: null,
    errorDetail: null,
  };
}

export function classifyFetchError(error: unknown): { code: string; detail: string } {
  if (error && typeof error === "object") {
    const record = error as {
      name?: unknown;
      message?: unknown;
      status?: unknown;
      code?: unknown;
      path?: unknown;
    };
    if (typeof record.status === "number") {
      const path = typeof record.path === "string" ? record.path : "";
      return {
        code: typeof record.code === "string" ? record.code : `HTTP_${record.status}`,
        detail: path ? `${path} returned ${record.status}` : `HTTP ${record.status}`,
      };
    }
    if (record.name === "AbortError") {
      return { code: "ABORTED", detail: "request aborted" };
    }
    if (record.name === "TypeError") {
      return {
        code: "NETWORK",
        detail: typeof record.message === "string" && record.message.trim()
          ? record.message.trim()
          : "network request failed",
      };
    }
    if (typeof record.code === "string" && record.code.trim()) {
      return {
        code: record.code.trim(),
        detail: typeof record.message === "string" && record.message.trim()
          ? record.message.trim()
          : record.code.trim(),
      };
    }
    if (typeof record.message === "string" && record.message.trim()) {
      const message = record.message.trim();
      const match = /returned (\d{3})\b/.exec(message);
      if (match) return { code: `HTTP_${match[1]}`, detail: message };
      return { code: "FETCH_ERROR", detail: message };
    }
  }
  if (typeof error === "string" && error.trim()) {
    return { code: "FETCH_ERROR", detail: error.trim() };
  }
  return { code: "FETCH_ERROR", detail: "request failed" };
}

/**
 * Mark a projection as failing transport.
 * - Prior valid value whose last success exceeded freshness → STALE (data retained)
 * - Prior valid value still within freshness window → TRANSPORT_ERROR (data retained briefly)
 * - No prior data → TRANSPORT_ERROR
 */
export function markTransportError<T>(
  prev: ReadProjection<T>,
  error: unknown,
  now: number = Date.now(),
  staleMs: number = 15_000,
): ReadProjection<T> {
  const { code, detail } = classifyFetchError(error);
  if (prev.data != null) {
    const age = prev.lastSuccessAt != null ? now - prev.lastSuccessAt : Number.POSITIVE_INFINITY;
    const state: ProjectionState = age > staleMs ? "STALE" : "TRANSPORT_ERROR";
    return {
      data: prev.data,
      state,
      lastAttemptAt: now,
      lastSuccessAt: prev.lastSuccessAt,
      errorCode: code,
      errorDetail: detail,
    };
  }
  return {
    data: null,
    state: "TRANSPORT_ERROR",
    lastAttemptAt: now,
    lastSuccessAt: prev.lastSuccessAt,
    errorCode: code,
    errorDetail: detail,
  };
}

export function isProjection<T>(value: unknown): value is ReadProjection<T> {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    "state" in record &&
    "data" in record &&
    "lastAttemptAt" in record &&
    "lastSuccessAt" in record &&
    typeof record.state === "string"
  );
}

/** Normalize plain payloads or projections into a ReadProjection. */
export function asProjection<T>(value: ReadProjection<T> | T | null | undefined): ReadProjection<T> {
  if (value == null) return loadingProjection<T>();
  if (isProjection<T>(value)) return value;
  return liveProjection(value as T);
}

export function transportFailed(projection: ReadProjection<unknown>): boolean {
  return projection.state === "TRANSPORT_ERROR" || projection.state === "STALE" || projection.state === "UNAVAILABLE";
}
