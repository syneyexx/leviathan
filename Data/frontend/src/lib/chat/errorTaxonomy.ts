/**
 * Chat client error taxonomy — stable classification for UI + cancel flows.
 */

export const CHAT_ERROR_CODES = [
  "CANCELLED",
  "NETWORK_DISCONNECTED",
  "TIMEOUT",
  "PROTOCOL_FAILURE",
  "PROVIDER_FAILURE",
  "BACKEND_FAILURE",
  "VALIDATION_ERROR",
  "AUTHORIZATION_ERROR",
  "STREAM_INTERRUPTED",
  "UNKNOWN",
] as const;

export type ChatErrorCode = (typeof CHAT_ERROR_CODES)[number];

export type ChatErrorClassification = {
  code: ChatErrorCode;
  message: string;
  retryable: boolean;
  userCancel: boolean;
};

export function classifyChatError(error: unknown): ChatErrorClassification {
  if (error && typeof error === "object") {
    const rec = error as {
      name?: string;
      message?: string;
      status?: number;
      code?: string;
    };
    const msg = String(rec.message || "");
    const lower = msg.toLowerCase();
    const codeField = typeof rec.code === "string" ? rec.code.toUpperCase() : "";

    if (
      codeField === "CANCELLED" ||
      rec.name === "AbortError" ||
      lower.includes("abort") ||
      lower.includes("cancelled") ||
      lower.includes("canceled") ||
      rec.status === 499
    ) {
      return {
        code: "CANCELLED",
        message: msg || "Cancelled",
        retryable: false,
        userCancel: true,
      };
    }

    if (codeField === "NETWORK_DISCONNECTED" || lower.includes("network") || lower.includes("failed to fetch")) {
      return {
        code: "NETWORK_DISCONNECTED",
        message: msg || "Network disconnected",
        retryable: true,
        userCancel: false,
      };
    }

    if (codeField === "TIMEOUT" || lower.includes("timeout")) {
      return {
        code: "TIMEOUT",
        message: msg || "Timed out",
        retryable: true,
        userCancel: false,
      };
    }

    if (codeField === "PROTOCOL_FAILURE" || lower.includes("protocol")) {
      return {
        code: "PROTOCOL_FAILURE",
        message: msg || "Protocol failure",
        retryable: false,
        userCancel: false,
      };
    }

    if (rec.status === 401 || rec.status === 403 || lower.includes("unauthorized")) {
      return {
        code: "AUTHORIZATION_ERROR",
        message: msg || "Not authorized",
        retryable: false,
        userCancel: false,
      };
    }

    if (rec.status === 422 || lower.includes("validation")) {
      return {
        code: "VALIDATION_ERROR",
        message: msg || "Validation error",
        retryable: false,
        userCancel: false,
      };
    }

    if (rec.status != null && rec.status >= 500) {
      return {
        code: "BACKEND_FAILURE",
        message: msg || "Backend failure",
        retryable: true,
        userCancel: false,
      };
    }

    if (lower.includes("provider") || lower.includes("llm")) {
      return {
        code: "PROVIDER_FAILURE",
        message: msg || "Provider failure",
        retryable: true,
        userCancel: false,
      };
    }

    if (lower.includes("stream") && lower.includes("interrupt")) {
      return {
        code: "STREAM_INTERRUPTED",
        message: msg || "Stream interrupted",
        retryable: true,
        userCancel: false,
      };
    }

    if (msg) {
      return {
        code: "UNKNOWN",
        message: msg,
        retryable: true,
        userCancel: false,
      };
    }
  }

  if (typeof error === "string" && error.trim()) {
    return classifyChatError({ message: error });
  }

  return {
    code: "UNKNOWN",
    message: "Unknown chat error",
    retryable: true,
    userCancel: false,
  };
}

export function chatErrorUserMessage(classification: ChatErrorClassification): string {
  switch (classification.code) {
    case "CANCELLED":
      return "Antwoord gestopt.";
    case "NETWORK_DISCONNECTED":
      return "Verbinding verbroken. Controleer je netwerk en probeer opnieuw.";
    case "TIMEOUT":
      return "Verzoek time-out. Probeer opnieuw.";
    case "PROTOCOL_FAILURE":
      return `Chat protocolfout: ${classification.message}`;
    case "PROVIDER_FAILURE":
      return `Modelproviderfout: ${classification.message}`;
    case "BACKEND_FAILURE":
      return `Backendfout: ${classification.message}`;
    case "VALIDATION_ERROR":
      return `Ongeldig verzoek: ${classification.message}`;
    case "AUTHORIZATION_ERROR":
      return "Niet geautoriseerd voor deze chat-actie.";
    case "STREAM_INTERRUPTED":
      return "Stream onderbroken. Herladen kan de laatste stand tonen.";
    default:
      return classification.message;
  }
}
