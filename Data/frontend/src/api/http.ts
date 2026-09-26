/** Shared HTTP helpers for domain API modules (W18B). */

import type { ApiErrorBody } from "../types/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function detailMessage(data: ApiErrorBody | null, status: number): string {
  if (!data?.detail) {
    return `Request failed (${status})`;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    return data.detail
      .map((item) => {
        const row = item as { msg?: string; loc?: Array<string | number>; type?: string };
        const loc = Array.isArray(row.loc) ? row.loc.filter((p) => p !== "body").join(".") : "";
        const msg = row.msg || "validation error";
        if (loc === "system_prompt" || loc.endsWith(".system_prompt")) {
          return "System prompt payload missing: expected `system_prompt`";
        }
        if (loc === "values" || loc.endsWith(".values")) {
          return "Behavior update body missing `values`";
        }
        if (row.type === "missing" && loc) {
          return `Field required: ${loc}`;
        }
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (typeof data.detail === "object" && data.detail !== null && "message" in data.detail) {
    const body = data.detail as { code?: string; message?: string };
    if (body.code === "MODEL_NOT_CHAT_CAPABLE") {
      return "Dit model kan geen chat-antwoorden genereren. Kies een chatmodel of gebruik Auto.";
    }
    if (body.code === "NO_CHAT_MODEL_AVAILABLE") {
      return "No chat-capable generative model is configured. Configure one under Models.";
    }
    return body.code ? `${body.code}: ${body.message ?? ""}` : String(body.message ?? `Request failed (${status})`);
  }
  if (typeof data.detail === "object" && data.detail !== null && "error" in data.detail) {
    const body = data.detail as { error?: unknown; detail?: unknown; message?: string };
    if (typeof body.error === "string") {
      const msg =
        typeof body.detail === "string"
          ? body.detail
          : typeof body.message === "string"
            ? body.message
            : "";
      return msg ? `${body.error}: ${msg}` : body.error;
    }
    const nested = body.error as { code?: string; message?: string };
    if (nested?.message) {
      return nested.code ? `${nested.code}: ${nested.message}` : nested.message;
    }
  }
  return `Request failed (${status})`;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = new Headers(options.headers ?? undefined);
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isFormData) {
    // Browser must set multipart boundary — never force application/json.
    headers.delete("Content-Type");
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  let data: ApiErrorBody | null = null;
  try {
    data = (await response.json()) as ApiErrorBody;
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new ApiError(response.status, detailMessage(data, response.status));
  }

  return data as T;
}

export async function requestBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const response = await fetch(path, { ...options });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = (await response.json()) as ApiErrorBody;
      message = detailMessage(data, response.status);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(response.status, message);
  }
  return response.blob();
}

