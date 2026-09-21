import { Panel, StatusBadge } from "@/components/hades/ui";
import { formatCost, formatMetric } from "@/lib/agents-console";
import { formatDate, type HadesAgent } from "@/lib/hades-api";

export function AgentUsagePanel({ selected }: { selected: HadesAgent | null }) {
  return (
    <Panel title="Usage & metrics" eyebrow="Echte providerdata of —">
      {selected ? (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Input tokens</span><strong className="mt-1 block">{selected.usage?.known ? formatMetric(selected.usage.input_tokens) : "—"}</strong></div>
            <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Output tokens</span><strong className="mt-1 block">{selected.usage?.known ? formatMetric(selected.usage.output_tokens) : "—"}</strong></div>
            <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Cached</span><strong className="mt-1 block">{selected.usage?.known ? formatMetric(selected.usage.cached_tokens) : "—"}</strong></div>
            <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Reasoning</span><strong className="mt-1 block">{selected.usage?.known ? formatMetric(selected.usage.reasoning_tokens) : "—"}</strong></div>
            <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Totaal</span><strong className="mt-1 block">{selected.usage?.known ? formatMetric(selected.usage.total_tokens) : "—"}</strong></div>
            <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Kosten</span><strong className="mt-1 block">{formatCost(selected.usage?.cost)}</strong></div>
          </div>
          {!selected.usage?.known ? (
            <p className="empty-copy">Nog geen usage ontvangen van de provider voor deze agent. Ontbrekende waarden blijven —.</p>
          ) : null}
          <div>
            <span className="mb-2 block text-xs font-semibold">Recente runs</span>
            <div className="max-h-56 space-y-2 overflow-auto">
              {(selected.recent_runs || []).slice(0, 12).map((run) => (
                <div key={`${run.kind}-${run.id}`} className="rounded-md border border-border px-2.5 py-2 text-[11px]">
                  <div className="flex items-center justify-between gap-2">
                    <strong>{run.title || run.id}</strong>
                    <StatusBadge tone={run.status === "completed" ? "success" : run.status === "failed" ? "danger" : run.status === "running" ? "info" : "neutral"}>{run.status || "—"}</StatusBadge>
                  </div>
                  <small className="text-muted-foreground">{run.kind} · {formatDate(run.updated_at ?? run.finished_at ?? null)}</small>
                  {run.error ? <div className="mt-1 text-destructive">{run.error}</div> : null}
                </div>
              ))}
              {!selected.recent_runs?.length ? <p className="empty-copy">Nog geen runs voor deze agent.</p> : null}
            </div>
          </div>
        </div>
      ) : <p className="empty-copy">Selecteer een agent.</p>}
    </Panel>
  );
}
