import { ProgressBar } from "../ui";
import type { SystemTelemetryResponse, TaskAgentActivity, TaskEvent, TaskSummary } from "../../types/api";
import { formatActivityLine, formatRelative, taskTypeLabel } from "../../pages/tasks/taskUtils";

type Props = {
  activity: TaskEvent[];
  agentActivity: TaskAgentActivity[];
  summary: TaskSummary | null;
  telemetry: SystemTelemetryResponse | null;
  telemetryError?: string | null;
  onSelectTask?: (taskId: string) => void;
};

const TYPE_COLORS: Record<string, string> = {
  research: "#a78bfa",
  trading: "#f59e0b",
  data: "#3b82f6",
  training: "#6366f1",
  analysis: "#34d399",
  system: "#ef4444",
  browser: "#22d3ee",
  tool: "#14b8a6",
  development: "#ec4899",
  evaluation: "#84cc16",
  knowledge: "#eab308",
  general: "#64748b",
};

function formatBytes(bytes: number | null | undefined): string | null {
  if (bytes == null || !Number.isFinite(bytes)) return null;
  return `${(bytes / 1024 ** 3).toFixed(1)}`;
}

export function TasksBottomGrid({
  activity,
  agentActivity,
  summary,
  telemetry,
  telemetryError,
  onSelectTask,
}: Props) {
  const typeCounts = summary?.typeCounts ?? {};
  const typeEntries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  const typeTotal = typeEntries.reduce((s, [, n]) => s + n, 0);
  let cursor = 0;
  const gradientParts = typeEntries.map(([key, count]) => {
    const start = cursor;
    const pct = typeTotal > 0 ? (count / typeTotal) * 100 : 0;
    cursor += pct;
    const color = TYPE_COLORS[key] || TYPE_COLORS.general;
    return `${color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  });
  const donutStyle =
    typeTotal > 0
      ? { background: `conic-gradient(${gradientParts.join(", ")})` }
      : { background: "rgba(100,116,139,0.25)" };

  const activeAgents = agentActivity.filter((a) => (a.activeTaskCount || 0) > 0);
  const maxAgentTasks = Math.max(1, ...activeAgents.map((a) => a.activeTaskCount || 0), 1);

  const cpu = telemetry?.dashboard.cpuPct ?? null;
  const ramPct = telemetry?.dashboard.ramPct ?? null;
  const gpu = telemetry?.dashboard.gpuPct ?? null;
  const diskPct = telemetry?.dashboard.diskPct ?? null;
  const ramUsed = formatBytes(telemetry?.memory?.available ? telemetry.memory.usedBytes : null);
  const ramTotal = formatBytes(telemetry?.memory?.available ? telemetry.memory.totalBytes : null);
  const diskUsed = formatBytes(telemetry?.disk?.available ? telemetry.disk.usedBytes : null);
  const diskTotal = formatBytes(telemetry?.disk?.available ? telemetry.disk.totalBytes : null);

  return (
    <section className="lv-v2-tasks-bottom" aria-label="Taken telemetry">
      <article className="lv-v2-panel lv-v2-tasks-bottom-card">
        <header className="lv-v2-panel__head">
          <h3 className="lv-v2-panel__title">Recente Activiteit</h3>
        </header>
        <div className="lv-v2-panel__body">
          {activity.length === 0 ? (
            <p className="lv-v2-muted">Geen recente activiteit</p>
          ) : (
            <ul className="lv-v2-tasks-activity">
              {activity.slice(0, 12).map((ev) => (
                <li key={ev.eventId}>
                  <time>{formatRelative(ev.createdAt) || "—"}</time>
                  <button
                    type="button"
                    className="lv-v2-tasks-activity-link"
                    onClick={() => onSelectTask?.(ev.taskId)}
                  >
                    {formatActivityLine(ev)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </article>

      <article className="lv-v2-panel lv-v2-tasks-bottom-card">
        <header className="lv-v2-panel__head">
          <h3 className="lv-v2-panel__title">Resource Gebruik</h3>
        </header>
        <div className="lv-v2-panel__body lv-v2-tasks-resources">
          {telemetryError && !telemetry ? (
            <p className="lv-v2-muted">Telemetry: {telemetryError}</p>
          ) : null}
          <ResourceRow
            label="CPU"
            value={telemetry?.cpu?.available ? cpu : null}
            detail={telemetry?.cpu?.available && cpu != null ? `${Math.round(cpu)}%` : "UNAVAILABLE"}
            tone="default"
          />
          <ResourceRow
            label="RAM"
            value={telemetry?.memory?.available ? ramPct : null}
            detail={
              telemetry?.memory?.available && ramUsed && ramTotal && ramPct != null
                ? `${ramUsed} / ${ramTotal} GB · ${Math.round(ramPct)}%`
                : "UNAVAILABLE"
            }
            tone="research"
          />
          <ResourceRow
            label="GPU"
            value={telemetry?.gpu?.available ? gpu : null}
            detail={telemetry?.gpu?.available && gpu != null ? `${Math.round(gpu)}%` : "UNAVAILABLE"}
            tone="warning"
          />
          <ResourceRow
            label="Disk"
            value={telemetry?.disk?.available ? diskPct : null}
            detail={
              telemetry?.disk?.available && diskUsed && diskTotal && diskPct != null
                ? `${diskUsed} / ${diskTotal} GB · ${Math.round(diskPct)}%`
                : "UNAVAILABLE"
            }
            tone="trading"
          />
        </div>
      </article>

      <article className="lv-v2-panel lv-v2-tasks-bottom-card">
        <header className="lv-v2-panel__head">
          <h3 className="lv-v2-panel__title">Taak Types</h3>
        </header>
        <div className="lv-v2-panel__body lv-v2-tasks-types">
          <div className="lv-v2-tasks-donut" style={donutStyle} aria-hidden="true">
            <div className="lv-v2-tasks-donut__center">
              <strong>{typeTotal}</strong>
              <span>taken</span>
            </div>
          </div>
          {typeEntries.length === 0 ? (
            <p className="lv-v2-muted">Geen typeverdeling</p>
          ) : (
            <ul className="lv-v2-tasks-type-legend">
              {typeEntries.map(([key, count]) => (
                <li key={key}>
                  <i style={{ background: TYPE_COLORS[key] || TYPE_COLORS.general }} />
                  <span>{taskTypeLabel(key)}</span>
                  <em>
                    {count}
                    {typeTotal ? ` · ${Math.round((count / typeTotal) * 100)}%` : ""}
                  </em>
                </li>
              ))}
            </ul>
          )}
        </div>
      </article>

      <article className="lv-v2-panel lv-v2-tasks-bottom-card">
        <header className="lv-v2-panel__head">
          <h3 className="lv-v2-panel__title">Agents Activiteit</h3>
        </header>
        <div className="lv-v2-panel__body">
          {activeAgents.length === 0 ? (
            <p className="lv-v2-muted">Geen actieve agenttaken</p>
          ) : (
            <ul className="lv-v2-tasks-agents">
              {activeAgents.slice(0, 8).map((agent) => {
                const count = agent.activeTaskCount || 0;
                const pct = Math.round((count / maxAgentTasks) * 100);
                return (
                  <li key={agent.agentId}>
                    <div className="lv-v2-tasks-agents__row">
                      <strong>{agent.name}</strong>
                      <span>{count} taken</span>
                    </div>
                    <ProgressBar value={pct} label={`${count} actieve taken`} />
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </article>
    </section>
  );
}

function ResourceRow({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: number | null;
  detail: string;
  tone: "default" | "research" | "warning" | "trading";
}) {
  return (
    <div className="lv-v2-tasks-resource-row">
      <div className="lv-v2-tasks-resource-row__label">
        <span>{label}</span>
        <em>{detail}</em>
      </div>
      <ProgressBar value={value} tone={tone} label={detail} />
    </div>
  );
}
