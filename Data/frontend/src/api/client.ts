import type {
  ApiErrorBody,
  ChatResponse,
  Conversation,
  HealthResponse,
  Message,
} from "../types/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function detailMessage(data: ApiErrorBody | null, status: number): string {
  if (!data?.detail) {
    return `Request failed (${status})`;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    return data.detail.map((item) => item.msg).join("; ");
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
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

export const api = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/api/health");
  },

  listConversations(): Promise<{ conversations: Conversation[] }> {
    return request<{ conversations: Conversation[] }>("/api/conversations");
  },

  createConversation(title = "New conversation"): Promise<{ conversation: Conversation }> {
    return request<{ conversation: Conversation }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  },

  getConversation(
    conversationId: string,
  ): Promise<{ conversation: Conversation; messages: Message[] }> {
    return request<{ conversation: Conversation; messages: Message[] }>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
    );
  },

  chat(message: string, conversationId: string | null): Promise<ChatResponse> {
    return request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
      }),
    });
  },
};
