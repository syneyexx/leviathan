/** Product reasoning modes and legacy compatibility (fast/standard/maximum). */

export const PRODUCT_REASONING_MODES = ["normal", "medium", "high", "adaptive"] as const;
export type ProductReasoningMode = (typeof PRODUCT_REASONING_MODES)[number];
export type StoredReasoningMode = ProductReasoningMode | "fast" | "standard" | "maximum";

const LEGACY: Record<string, ProductReasoningMode> = {
  fast: "normal",
  standard: "medium",
  maximum: "high",
  normal: "normal",
  medium: "medium",
  high: "high",
  adaptive: "adaptive",
};

export function normalizeReasoningMode(profile: string | undefined | null): ProductReasoningMode {
  const key = String(profile || "").trim().toLowerCase();
  return LEGACY[key] ?? "adaptive";
}

export function reasoningModeLabel(profile: string | undefined | null): string {
  const mode = normalizeReasoningMode(profile);
  return ({ normal: "Normal", medium: "Medium", high: "High", adaptive: "Adaptive" } as const)[mode];
}

/** Persist Maximum until the user explicitly picks a product mode. */
export function reasoningProfileForRequest(
  storedRaw: string | undefined | null,
  selected: ProductReasoningMode,
): string {
  const raw = String(storedRaw || "").trim().toLowerCase();
  if (raw === "maximum" && selected === "high") return "maximum";
  return selected;
}

export const REASONING_MODE_OPTIONS: Array<{ id: ProductReasoningMode; label: string; hint: string }> = [
  { id: "normal", label: "Normal", hint: "Direct antwoorden wanneer de vraag duidelijk is; extra stappen alleen als nodig" },
  { id: "medium", label: "Medium", hint: "Extra structuur bij meerdere eisen; begrensd herstel van fouten" },
  { id: "high", label: "High", hint: "Meer ruimte voor analyse, uitvoering en verificatie; eenvoudige vragen blijven direct" },
  { id: "adaptive", label: "Adaptive", hint: "Begint zuinig en schaalt alleen bij concrete fouten of ontbrekend bewijs" },
];
