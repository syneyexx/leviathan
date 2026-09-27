export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly code: string;

  constructor(path: string, status: number, statusText = "") {
    super(statusText ? `${path} returned ${status} ${statusText}`.trim() : `${path} returned ${status}`);
    this.name = "ApiError";
    this.path = path;
    this.status = status;
    this.code = `HTTP_${status}`;
  }
}

export async function getJson<T>(base: string, path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(path, response.status, response.statusText);
  }
  return (await response.json()) as T;
}

export type JsonResult<T> =
  | { ok: true; data: T; errorCode: null; errorDetail: null }
  | { ok: false; data: null; errorCode: string; errorDetail: string };

export async function getJsonResult<T>(base: string, path: string, signal: AbortSignal): Promise<JsonResult<T>> {
  try {
    const data = await getJson<T>(base, path, signal);
    return { ok: true, data, errorCode: null, errorDetail: null };
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, data: null, errorCode: error.code, errorDetail: error.message };
    }
    const message = error instanceof Error && error.message.trim() ? error.message.trim() : "request failed";
    const code = error instanceof Error && error.name === "TypeError" ? "NETWORK" : "FETCH_ERROR";
    return { ok: false, data: null, errorCode: code, errorDetail: message };
  }
}

export async function invokeHost<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const mod = await import("@tauri-apps/api/core");
  return mod.invoke<T>(command, args);
}

export function tauriAvailable(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
