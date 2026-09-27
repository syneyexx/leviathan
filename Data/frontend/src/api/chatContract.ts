/**
 * Runtime chat contract guards at the trust boundary.
 * TypeScript types do not validate JSON; malformed SSE/persisted payloads
 * must never crash the Chat page.
 */
import type { ChatResponse, Message } from "../types/api";

export type ChatProtocolFailure = {
  kind: "protocol_failure";
  reason: string;
  provisional_content: string | null;
  conversation_id: string | null;
  raw: Record<string, unknown>;
};

export type ParsedChatDone =
  | { ok: true; response: ChatResponse; provisional: false }
  | { ok: false; failure: ChatProtocolFailure };

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

/** Normalize a persisted or streamed message; never throws. */
export function normalizeMessage(raw: unknown): Message | null {
  const obj = asRecord(raw);
  if (!obj) return null;
  const role = obj.role;
  if (role !== "system" && role !== "user" && role !== "assistant") {
    // Persisted rows may omit role when partially shaped; treat unknown as assistant only if content exists.
    if (typeof obj.content !== "string" && obj.content != null && typeof obj.content !== "number") {
      return null;
    }
  }
  const content =
    typeof obj.content === "string"
      ? obj.content
      : obj.content == null
        ? ""
        : typeof obj.content === "number" || typeof obj.content === "boolean"
          ? String(obj.content)
          : null;
  if (content === null) return null;
  const created_at =
    typeof obj.created_at === "string" && obj.created_at
      ? obj.created_at
      : new Date(0).toISOString();
  const id = typeof obj.id === "number" && Number.isFinite(obj.id) ? obj.id : 0;
  const conversation_id =
    typeof obj.conversation_id === "string" ? obj.conversation_id : "";
  const normalizedRole =
    role === "system" || role === "user" || role === "assistant" ? role : "assistant";
  return {
    id,
    conversation_id,
    role: normalizedRole,
    content,
    created_at,
  };
}

/** Display-safe message content for ChatPage lists. */
export function displayMessageContent(raw: unknown): string {
  if (typeof raw === "string") return raw;
  if (raw == null) return "";
  if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
  return "";
}

function extractProvisionalText(raw: Record<string, unknown>): string | null {
  const assistant = normalizeMessage(raw.assistant_message);
  if (assistant?.content) return assistant.content;
  const legacy = normalizeMessage(raw.message);
  if (legacy?.content) return legacy.content;
  if (typeof raw.text === "string" && raw.text) return raw.text;
  if (typeof raw.content === "string" && raw.content) return raw.content;
  return null;
}

/**
 * Validate a terminal chat payload (SSE done or non-stream JSON).
 *
 * TEAM responses historically used `message` instead of `assistant_message`.
 * We accept that shape by promoting `message` → `assistant_message` when needed,
 * but never invent a successful persisted completion without a usable message body.
 */
export function parseChatDonePayload(raw: unknown): ParsedChatDone {
  const obj = asRecord(raw);
  if (!obj) {
    return {
      ok: false,
      failure: {
        kind: "protocol_failure",
        reason: "done_payload_not_object",
        provisional_content: null,
        conversation_id: null,
        raw: {},
      },
    };
  }

  const conversation_id =
    typeof obj.conversation_id === "string" && obj.conversation_id
      ? obj.conversation_id
      : null;

  // Promote TEAM legacy `message` field when assistant_message is absent.
  let assistantRaw = obj.assistant_message;
  if (assistantRaw == null && obj.message != null) {
    assistantRaw = obj.message;
  }

  const assistant = normalizeMessage(assistantRaw);
  if (!assistant) {
    return {
      ok: false,
      failure: {
        kind: "protocol_failure",
        reason:
          assistantRaw == null
            ? "missing_assistant_message"
            : "malformed_assistant_message",
        provisional_content: extractProvisionalText(obj),
        conversation_id,
        raw: obj,
      },
    };
  }

  // content may be empty string for legitimate empty replies; that is valid.
  const user =
    normalizeMessage(obj.user_message) ??
    ({
      id: 0,
      conversation_id: conversation_id ?? "",
      role: "user" as const,
      content: "",
      created_at: new Date(0).toISOString(),
    } satisfies Message);

  const model = typeof obj.model === "string" ? obj.model : "";

  const response = {
    ...obj,
    conversation_id: conversation_id ?? "",
    user_message: user,
    assistant_message: assistant,
    model,
    reasoning:
      obj.reasoning && typeof obj.reasoning === "object"
        ? (obj.reasoning as ChatResponse["reasoning"])
        : { intent: "", complexity: "", use_knowledge: false, steps: [] },
    knowledge_sources: Array.isArray(obj.knowledge_sources)
      ? (obj.knowledge_sources as ChatResponse["knowledge_sources"])
      : [],
  } as ChatResponse;

  return { ok: true, response, provisional: false };
}

export function isStreamTokenEvent(parsed: Record<string, unknown>): boolean {
  return typeof parsed.text === "string";
}

export function streamEventText(parsed: Record<string, unknown>): string {
  return typeof parsed.text === "string" ? parsed.text : "";
}
