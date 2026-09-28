import type { Measured, Measurement } from "../../../types/researchCommand";

export function measuredText(field: Measured | null | undefined, suffix = ""): string {
  if (!field) return "UNMEASURED";
  if (field.measurement === "EMPTY") return "EMPTY";
  if (field.measurement === "UNMEASURED" || field.value == null || field.value === "") return "UNMEASURED";
  if (field.measurement === "AGENT_ESTIMATE") return `${field.value}${suffix} · agent estimate`;
  return `${field.value}${suffix}`;
}

export function moneyText(field: Measured | null | undefined, currency: string | null | undefined): string {
  if (!field || field.measurement !== "MEASURED" || field.value == null || field.value === "") {
    return field?.measurement === "EMPTY" ? "EMPTY" : "UNMEASURED";
  }
  const amount = Number(field.value);
  if (!Number.isFinite(amount)) return String(field.value);
  if (!currency) return amount.toLocaleString("en-US", { maximumFractionDigits: 2 });
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return amount.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
}

export function percentText(field: Measured | null | undefined): string {
  if (!field || field.measurement !== "MEASURED" || field.value == null || field.value === "") {
    return field?.measurement === "EMPTY" ? "EMPTY" : "UNMEASURED";
  }
  const amount = Number(field.value);
  if (!Number.isFinite(amount)) return String(field.value);
  return `${amount.toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
}

export function formatUptime(field: Measured<number> | null | undefined): string {
  if (!field || field.measurement !== "MEASURED" || field.value == null) return "UNMEASURED";
  const total = Number(field.value);
  if (!Number.isFinite(total) || total < 0) return "UNMEASURED";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = Math.floor(total % 60);
  return `${hours}h ${minutes}m ${seconds}s`;
}

export function modeLabel(mode: string | null | undefined): string {
  if (mode === "PAPER") return "PAPER MODE";
  if (mode === "PAPER_UNBOUND") return "PAPER UNBOUND";
  if (mode === "NO_PAPER_WALLET") return "NO PAPER WALLET";
  if (!mode) return "UNMEASURED";
  return mode;
}

export function safetyClass(safety: string | null | undefined): string {
  if (safety === "SAFE") return "is-safe";
  if (safety === "NOT_SAFE") return "is-bad";
  if (safety === "NO_NEW_EXPOSURE" || safety === "PAUSED") return "is-warn";
  return "is-muted";
}

export function isExecutionSafe(safety: string | null | undefined): boolean {
  return safety === "SAFE";
}

export function signedClass(field: Measured | null | undefined): string {
  if (!field || field.measurement !== "MEASURED" || field.value == null) return "is-muted";
  const amount = Number(field.value);
  if (!Number.isFinite(amount) || amount === 0) return "is-muted";
  return amount > 0 ? "is-up" : "is-down";
}

export function whyText(why: string | null | undefined): string {
  const text = (why || "").trim();
  return text || "NOT AVAILABLE";
}

export function generationLabel(value: number | null | undefined, measurement?: Measurement): string {
  if (measurement && measurement !== "MEASURED") return "UNMEASURED";
  if (value == null || !Number.isFinite(Number(value))) return "UNMEASURED";
  return String(value);
}

export const PRIVATE_REASONING_KEYS = [
  "chain_of_thought",
  "hidden_reasoning",
  "scratchpad",
  "private_reasoning",
  "reasoning_tokens",
] as const;
