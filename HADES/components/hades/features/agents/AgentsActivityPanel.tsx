import { Activity, GitBranch, XCircle } from "lucide-react";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { formatDate, type AgentsConsoleResponse, type HadesAgent } from "@/lib/hades-api";

type AgentsActivityPanelProps = {
  activity: AgentsConsoleResponse["activity"];
  selected: HadesAgent | null;
  onSelect: (agentId: string) => void;
};

export function AgentsActivityPanel({ activity, selected, onSelect }: AgentsActivityPanelProps) {
  return (
    <Panel title="Recente activiteit" actions={<StatusBadge tone="info"><GitBranch />live</StatusBadge>}>
      <div className="max-h-[28rem] space-y-2.5 overflow-auto">
        {activity.map((item, index) => (
          <div key={`${item.at}-${item.agent_id}-${index}`} className="grid grid-cols-[4.8rem_auto_1fr] items-start gap-2 text-[11px]">
            <span className="tabular-nums text-muted-foreground">{formatDate(item.at ?? null)}</span>
            <span className={`mt-0.5 grid h-4 w-4 place-items-center rounded-full ${item.level === "error" || item.level === "danger" ? "bg-destructive/10 text-destructive" : item.level === "success" ? "bg-accent text-[var(--success)]" : "bg-accent text-[var(--info)]"}`}>
              {item.level === "error" || item.level === "danger" ? <XCircle className="h-2.5 w-2.5" /> : <Activity className="h-2.5 w-2.5" />}
            </span>
            <span>
              <button type="button" className="font-semibold hover:underline" onClick={() => item.agent_id && onSelect(String(item.agent_id))}>
                {item.agent_id || "system"}
              </button>
              <span className="text-muted-foreground"> — {item.message}</span>
            </span>
          </div>
        ))}
        {!activity.length ? <p className="empty-copy">Nog geen runtime-activiteit. Start een taak of chat om telemetrie te vullen.</p> : null}
      </div>
      {selected?.recent_logs?.length ? (
        <div className="mt-4">
          <span className="mb-2 block text-xs font-semibold">Logs · {selected.name}</span>
          <div className="log-view max-h-48 overflow-auto">
            {selected.recent_logs.slice(0, 40).map((event) => (
              <code key={`${event.id}-${event.created_at}`}>[{formatDate(event.created_at ?? null)}] {event.message}</code>
            ))}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
