import { Bot, Loader2, Power, PowerOff, RefreshCcw, StopCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { formatDuration, healthTone, statusTone } from "@/lib/agents-console";
import { formatDate, type HadesAgent } from "@/lib/hades-api";
import { currentTaskLabel, dash } from "./helpers";
import type { AgentMutationAction } from "./types";

type AgentDetailPanelProps = {
  selected: HadesAgent | null;
  detailLoading: boolean;
  mutating: AgentMutationAction | null;
  onMutate: (action: AgentMutationAction) => void;
  onSelect: (agentId: string) => void;
};

export function AgentDetailPanel({
  selected,
  detailLoading,
  mutating,
  onMutate,
  onSelect,
}: AgentDetailPanelProps) {
  return (
    <Panel
      title={selected ? `Agent: ${selected.name}` : "Geen agent geselecteerd"}
      actions={selected ? (
        <>
          <StatusBadge tone={statusTone(selected.status)}>{selected.status_label || selected.status}</StatusBadge>
          <StatusBadge tone={healthTone(selected.health)}>{selected.health_label || selected.health}</StatusBadge>
          {detailLoading ? <Loader2 className="spin muted-icon" /> : null}
        </>
      ) : null}
    >
      {selected ? (
        <div className="grid gap-4 lg:grid-cols-[1.05fr_1fr]">
          <div className="space-y-3">
            <div className="mb-1 flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-xl border border-border bg-accent/55"><Bot className="h-5 w-5" /></span>
              <div>
                <strong className="block">{selected.name}</strong>
                <span className="text-xs text-muted-foreground">{selected.id} · {selected.role}</span>
              </div>
            </div>
            <p className="m-0 text-xs leading-5 text-muted-foreground">{selected.description || "—"}</p>
            <dl className="detail-list">
              <div><dt>Model</dt><dd>{dash(selected.model)}</dd></div>
              <div><dt>Provider</dt><dd>{dash(selected.provider)}</dd></div>
              <div><dt>Profiel</dt><dd>{dash(selected.reasoning_profile)}</dd></div>
              <div><dt>Temp / Top P / Max</dt><dd>
                {dash(selected.model_settings?.temperature)}
                {" / "}
                {dash(selected.model_settings?.top_p)}
                {" / "}
                {dash(selected.model_settings?.max_tokens)}
              </dd></div>
              <div><dt>Heartbeat</dt><dd>{formatDate(selected.heartbeat_at ?? null)}</dd></div>
              <div><dt>Laatste fout</dt><dd className={selected.last_error ? "text-destructive" : undefined}>{dash(selected.last_error)}</dd></div>
            </dl>
            <div>
              <span className="mb-1 block text-xs font-semibold">Capabilities</span>
              <div className="flex flex-wrap gap-1.5">
                {(selected.capabilities?.length ? selected.capabilities : ["—"]).map((item) => (
                  <span key={item} className="rounded-md border border-border bg-muted/40 px-2 py-1 text-[11px]">{item}</span>
                ))}
              </div>
            </div>
            <div>
              <span className="mb-1 block text-xs font-semibold">Tools</span>
              <div className="flex flex-wrap gap-1.5">
                {(selected.tools?.length ? selected.tools : ["—"]).map((item) => (
                  <span key={item} className="rounded-md border border-border bg-muted/40 px-2 py-1 text-[11px]">{item}</span>
                ))}
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <div className="rounded-lg border border-border bg-muted/25 p-3">
              <span className="text-[11px] text-muted-foreground">Huidige taak</span>
              <strong className="mt-1 block text-sm">{currentTaskLabel(selected)}</strong>
              <small className="text-muted-foreground">
                {selected.current_task?.task_id ? `task ${selected.current_task.task_id}` : "—"}
                {selected.current_task?.step_id ? ` · step ${selected.current_task.step_id}` : ""}
                {selected.current_task?.started_at ? ` · sinds ${formatDate(selected.current_task.started_at)}` : ""}
                {typeof selected.current_task?.progress === "number" ? ` · ${selected.current_task.progress}%` : ""}
              </small>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Requests</span><strong className="mt-1 block">{selected.usage?.known ? selected.usage.requests : "—"}</strong></div>
              <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Avg. runtime</span><strong className="mt-1 block">{formatDuration(selected.metrics?.avg_execution_seconds)}</strong></div>
              <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Succes</span><strong className="mt-1 block">{selected.metrics?.successful_runs ?? 0}</strong></div>
              <div className="rounded-lg border border-border p-2.5"><span className="text-[10px] text-muted-foreground">Fails</span><strong className="mt-1 block">{selected.metrics?.failed_runs ?? 0}</strong></div>
            </div>
            <div>
              <span className="mb-1 block text-xs font-semibold">Hiërarchie</span>
              <div className="flex flex-wrap gap-1.5 text-[11px]">
                {selected.hierarchy?.parent_id ? <span className="rounded-md border border-border px-2 py-1">parent: {selected.hierarchy.parent_id}</span> : <span className="text-muted-foreground">Geen parent</span>}
                {(selected.hierarchy?.child_ids || []).map((child) => (
                  <button key={child} type="button" className="rounded-md border border-border bg-muted/40 px-2 py-1" onClick={() => onSelect(child)}>{child}</button>
                ))}
              </div>
            </div>
            <div>
              <span className="mb-2 block text-xs font-semibold">Acties</span>
              <div className="flex flex-wrap gap-2">
                {selected.controls?.can_enable ? (
                  <Button size="sm" variant="outline" disabled={mutating !== null} onClick={() => onMutate("enable")}>
                    {mutating === "enable" ? <Loader2 className="spin" /> : <Power />}Inschakelen
                  </Button>
                ) : null}
                {selected.controls?.can_disable ? (
                  <Button size="sm" variant="outline" disabled={mutating !== null} onClick={() => onMutate("disable")}>
                    {mutating === "disable" ? <Loader2 className="spin" /> : <PowerOff />}Uitschakelen
                  </Button>
                ) : null}
                {selected.controls?.can_cancel_current ? (
                  <Button size="sm" variant="destructive" disabled={mutating !== null} onClick={() => onMutate("cancel")}>
                    {mutating === "cancel" ? <Loader2 className="spin" /> : <StopCircle />}Annuleer huidige run
                  </Button>
                ) : null}
                <Button size="sm" variant="outline" disabled={mutating !== null} onClick={() => onMutate("refresh")}>
                  <RefreshCcw />Status vernieuwen
                </Button>
                {selected.controls?.can_view_runs ? (
                  <Button size="sm" variant="outline" asChild>
                    <a href="#/tasks">Open Taken</a>
                  </Button>
                ) : null}
              </div>
              {selected.planned ? <p className="empty-copy mt-2">Deze agent is gepland (*) en doet niet alsof hij live is.</p> : null}
            </div>
          </div>
        </div>
      ) : (
        <p className="empty-copy">Selecteer een agent in de tabel.</p>
      )}
    </Panel>
  );
}
