/**
 * Voice API accessors. Prefer hadesApi methods when the parent wires them;
 * otherwise fall back to fetch against API_BASE so this frontend stays runnable.
 */

import { API_BASE, HadesApiError, hadesApi } from "@/lib/hades-api";
import type {
  VoiceSessionStartResult,
  VoiceSpeakableResult,
  VoiceStatus,
  VoiceTranscribeResult,
  VoiceVoiceInfo,
} from "./types";

type AnyFn = (...args: never[]) => unknown;

type VoiceInstallOptions = {
  steps?: string[];
  voice_asr_model?: string;
  voice_tts_voice?: string;
  approved_network?: boolean;
  approved_subprocess?: boolean;
};

function apiFn(name: string): AnyFn | undefined {
  const record = hadesApi as unknown as Record<string, unknown>;
  const fn = record[name];
  return typeof fn === "function" ? (fn as AnyFn).bind(hadesApi) : undefined;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new HadesApiError("De lokale FastAPI-backend is niet bereikbaar. Start eerst START_HADES.bat.");
  }
  if (!response.ok) {
    let message = `API-fout ${response.status}`;
    let detail: unknown = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = body.detail;
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
        message = String((body.detail as { message: unknown }).message);
      }
    } catch {
      // keep status fallback
    }
    throw new HadesApiError(message, response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new HadesApiError("De lokale FastAPI-backend is niet bereikbaar. Start eerst START_HADES.bat.");
  }
  if (!response.ok) {
    let message = `API-fout ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
        message = String((body.detail as { message: unknown }).message);
      }
    } catch {
      // keep status
    }
    throw new HadesApiError(message, response.status);
  }
  return response.blob();
}

async function callOrFallback<T>(name: string, args: unknown[], fallback: () => Promise<T>): Promise<T> {
  const fn = apiFn(name);
  if (fn) return (fn as (...a: unknown[]) => Promise<T>)(...args);
  return fallback();
}

export const voiceApi = {
  voiceStatus: () => callOrFallback<VoiceStatus>("voiceStatus", [], () => requestJson("/voice/status")),

  voiceDoctor: () =>
    callOrFallback<VoiceStatus>("voiceDoctor", [], () => requestJson("/voice/doctor", { method: "POST", body: "{}" })),

  voiceInstall: (input?: string[] | VoiceInstallOptions) => {
    const values: VoiceInstallOptions = Array.isArray(input) ? { steps: input } : { ...(input ?? {}) };
    const request = {
      ...values,
      steps: values.steps ?? ["deps", "whisper", "piper_voice"],
      approved_network: Boolean(values.approved_network),
      approved_subprocess: Boolean(values.approved_subprocess),
    };
    return callOrFallback<Record<string, unknown>>(
      "voiceInstall",
      [request],
      () =>
        requestJson("/voice/install", {
          method: "POST",
          body: JSON.stringify(request),
        }),
    );
  },

  voiceTranscribe: (values: {
    audio_base64: string;
    mime_type: string;
    language?: string;
    session_id?: string;
    turn_id?: string;
    is_final?: boolean;
  }) =>
    callOrFallback<VoiceTranscribeResult>("voiceTranscribe", [values], () =>
      requestJson("/voice/transcribe", { method: "POST", body: JSON.stringify(values) }),
    ),

  voiceSpeak: async (values: {
    text: string;
    voice_id?: string;
    language?: string;
    speed?: number;
    style?: "compact" | "full";
    already_speakable?: boolean;
    message_id?: string;
    session_id?: string;
  }): Promise<Blob> => {
    const fn = apiFn("voiceSpeak");
    if (fn) {
      const result = await (fn as (v: typeof values) => Promise<Blob | Response>)(values);
      if (result instanceof Blob) return result;
      if (result && typeof (result as Response).blob === "function") return (result as Response).blob();
    }
    return requestBlob("/voice/speak", { method: "POST", body: JSON.stringify(values) });
  },

  voiceSpeakable: (values: { text: string; style: "compact" | "full"; language: string }) =>
    callOrFallback<VoiceSpeakableResult>("voiceSpeakable", [values], () =>
      requestJson("/voice/speakable", { method: "POST", body: JSON.stringify(values) }),
    ),

  voiceVoices: (language?: string) =>
    callOrFallback<{ voices: VoiceVoiceInfo[]; provider?: string; availability?: unknown }>(
      "voiceVoices",
      [language],
      () => requestJson(`/voice/voices${language ? `?language=${encodeURIComponent(language)}` : ""}`),
    ),

  voiceSessionStart: (values: {
    conversation_id?: string | null;
    client_tab_id: string;
    keep_audio?: boolean;
    force?: boolean;
    idle_timeout_seconds?: number;
  }) =>
    callOrFallback<VoiceSessionStartResult>("voiceSessionStart", [values], () =>
      requestJson("/voice/session/start", { method: "POST", body: JSON.stringify(values) }),
    ),

  voiceSessionStop: (sessionId: string, reason = "user") =>
    callOrFallback<Record<string, unknown>>("voiceSessionStop", [sessionId], () =>
      requestJson(`/voice/session/${encodeURIComponent(sessionId)}/stop`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    ),

  voiceSessionInterrupt: (sessionId: string, reason = "user") =>
    callOrFallback<Record<string, unknown>>("voiceSessionInterrupt", [sessionId], () =>
      requestJson(`/voice/session/${encodeURIComponent(sessionId)}/interrupt`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    ),

  voiceSessionSpeakResponse: (values: {
    session_id: string;
    response_id: string;
    text: string;
    force_replay?: boolean;
  }) =>
    callOrFallback<{ ok: boolean; segments: number; events: Array<Record<string, unknown>> }>(
      "voiceSessionSpeakResponse",
      [values],
      () => requestJson("/voice/session/speak-response", { method: "POST", body: JSON.stringify(values) }),
    ),

  voiceWakeProbe: (values: { audio_base64: string; mime_type: string; language?: string }) =>
    callOrFallback<Record<string, unknown>>("voiceWakeProbe", [values], () =>
      requestJson("/voice/wake/probe", { method: "POST", body: JSON.stringify(values) }),
    ),

  voiceMetricsReference: () =>
    callOrFallback<Record<string, unknown>>("voiceMetricsReference", [], () =>
      requestJson("/voice/metrics/reference"),
    ),

  voiceRecordingsList: () =>
    callOrFallback<{ sessions: Array<{ session_id: string; files: Array<{ name: string; bytes: number; path: string }>; file_count: number }>; root: string }>(
      "voiceRecordingsList",
      [],
      () => requestJson("/voice/recordings"),
    ),

  voiceRecordingsDelete: (sessionId: string) =>
    callOrFallback<{ ok: boolean; deleted: string }>("voiceRecordingsDelete", [sessionId], () =>
      requestJson(`/voice/recordings/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
    ),
};

export function ensureClientTabId(storageKey = "hades.voice.client_tab_id"): string {
  if (typeof sessionStorage === "undefined") {
    return `tab_${Math.random().toString(36).slice(2, 10)}`;
  }
  try {
    const existing = sessionStorage.getItem(storageKey);
    if (existing) return existing;
    const id = `tab_${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2, 12)}`;
    sessionStorage.setItem(storageKey, id);
    return id;
  } catch {
    return `tab_${Math.random().toString(36).slice(2, 10)}`;
  }
}
