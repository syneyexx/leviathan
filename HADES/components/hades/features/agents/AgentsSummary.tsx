import { Activity, Bot, CheckCircle2, Database, FileText, Workflow } from "lucide-react";
import { StatCard } from "@/components/hades/ui";
import { formatCost, formatMetric } from "@/lib/agents-console";
import type { AgentsConsoleResponse } from "@/lib/hades-api";

export function AgentsSummary({ summary }: { summary: AgentsConsoleResponse["summary"] | undefined }) {
  return (
    <section className="stat-grid agents-stat-grid">
      <StatCard
        label="Actieve agents"
        value={summary ? `${summary.enabled} / ${summary.total}` : "—"}
        note={summary ? `${summary.running} bezig · ${summary.planned} gepland (*)` : "Laden…"}
        icon={<Bot />}
      />
      <StatCard
        label="Gepland (*)"
        value={summary ? String(summary.planned) : "—"}
        note="Nog niet operationeel"
        icon={<Workflow />}
      />
      <StatCard
        label="Tokens (bekend)"
        value={formatMetric(summary?.total_tokens ?? null, { compact: true })}
        note={summary?.provider_connected ? `${summary.provider} · ${summary.active_model || "geen model"}` : "Provider offline / onbekend"}
        icon={<Database />}
      />
      <StatCard
        label="Kosten"
        value={formatCost(summary?.total_cost ?? null)}
        note="Alleen wanneer de provider kosten levert"
        icon={<FileText />}
      />
      <StatCard
        label="Succesratio"
        value={summary?.avg_success_rate == null ? "—" : `${(summary.avg_success_rate * 100).toFixed(1).replace(".", ",")}%`}
        note="Over agents met voltooide/gefaalde runs"
        icon={<CheckCircle2 />}
      />
      <StatCard
        label="Open queue"
        value={summary ? String(summary.open_queue) : "—"}
        note={summary?.errors ? `${summary.errors} in foutstatus` : "Taken + work-stappen"}
        icon={<Activity />}
      />
    </section>
  );
}
