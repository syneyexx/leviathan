import type { HadesAgent, SpecialistContract } from "@/lib/hades-api";

export function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function currentTaskLabel(agent: HadesAgent): string {
  const current = agent.current_task;
  if (!current) return agent.planned ? "Nog niet geïmplementeerd" : "Geen actieve taak";
  const parts = [current.task_title, current.step_title].filter(Boolean);
  return parts.join(" · ") || current.task_id || "Actieve run";
}

export function traceSummary(trace: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(trace)) {
    if (value === null || value === undefined) continue;
    if (typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
      parts.push(`${key}: ${String(value)}`);
    } else if (Array.isArray(value)) {
      parts.push(`${key}: [${value.length}]`);
    } else {
      const compact = JSON.stringify(value);
      parts.push(`${key}: ${compact.length > 72 ? `${compact.slice(0, 72)}…` : compact}`);
    }
  }
  return parts.join(" · ") || "—";
}

export function ioSummary(contract: SpecialistContract): string {
  const inputs = contract.required_inputs?.length ? contract.required_inputs.join(", ") : "—";
  const outputs = contract.expected_outputs?.length ? contract.expected_outputs.join(", ") : "—";
  return `in: ${inputs} · out: ${outputs}`;
}
