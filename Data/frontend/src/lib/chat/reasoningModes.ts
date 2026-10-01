/**
 * Single source of truth for Chat reasoning depth modes.
 * Orthogonal to collaboration strategy (direct | team).
 */

export const REASONING_MODE_IDS = ["auto", "fast", "standard", "deep"] as const;

export type ReasoningModeId = (typeof REASONING_MODE_IDS)[number];

export type ReasoningModeOption = {
  id: ReasoningModeId;
  label: string;
  /** Short Dutch label for compact composer selects. */
  shortLabel: string;
  meta: string;
};

export const REASONING_MODE_OPTIONS: readonly ReasoningModeOption[] = [
  {
    id: "auto",
    label: "Auto",
    shortLabel: "Auto",
    meta: "Laat Hades de diepte kiezen",
  },
  {
    id: "fast",
    label: "Snel",
    shortLabel: "Snel",
    meta: "Korte, snelle antwoorden",
  },
  {
    id: "standard",
    label: "Standaard",
    shortLabel: "Standaard",
    meta: "Gebalanceerde diepte",
  },
  {
    id: "deep",
    label: "Diep Redeneren",
    shortLabel: "Diep Redeneren",
    meta: "Stap-voor-stap analyse",
  },
] as const;

export const DEFAULT_REASONING_MODE: ReasoningModeId = "auto";

export function isReasoningModeId(value: unknown): value is ReasoningModeId {
  return (
    typeof value === "string" &&
    (REASONING_MODE_IDS as readonly string[]).includes(value)
  );
}

export function parseReasoningMode(
  value: unknown,
  fallback: ReasoningModeId = DEFAULT_REASONING_MODE,
): ReasoningModeId {
  return isReasoningModeId(value) ? value : fallback;
}

export function reasoningModeOption(
  id: ReasoningModeId,
): ReasoningModeOption {
  return (
    REASONING_MODE_OPTIONS.find((o) => o.id === id) ?? REASONING_MODE_OPTIONS[0]
  );
}

/** Wire value for API: omit / null when Auto so backend resolves default. */
export function reasoningModeForApi(
  mode: ReasoningModeId,
): ReasoningModeId | null {
  return mode === "auto" ? null : mode;
}
