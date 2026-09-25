import type { AgentsDashboard } from "../../types/api";
import { formatPct } from "./helpers";
import { Bar, PanelHead } from "./agentsUi";

const FAILURE_WINDOWS: Array<{ hours: number; label: string }> = [
  { hours: 24, label: "Last 24 hours" },
  { hours: 72, label: "Last 3 days" },
  { hours: 168, label: "Last 7 days" },
  { hours: 720, label: "Last 30 days" },
];

export function FailureRetryPanel({
  dashboard,
  windowHours,
  onWindow,
}: {
  dashboard: AgentsDashboard | null;
  windowHours: number;
  onWindow: (hours: number) => void;
}) {
  const fr = dashboard?.failureRetry;
  const rows = fr
    ? [
        { key: "success", label: "Success", ratio: fr.successRate, count: fr.success, tone: "ok" },
        { key: "retry", label: "Retry", ratio: fr.retryRate, count: fr.retry, tone: "warn" },
        { key: "failed", label: "Failed", ratio: fr.failedRate, count: fr.failed, tone: "bad" },
      ]
    : [];

  return (
    <section className="lv-ag-panel lv-ag-failure">
      <PanelHead
        title="Failure / Retry Insights"
        right={
          <select
            className="lv-ag-mini-select"
            value={windowHours}
            onChange={(e) => onWindow(Number(e.target.value))}
            aria-label="Failure window"
          >
            {FAILURE_WINDOWS.map((w) => (
              <option key={w.hours} value={w.hours}>
                {w.label}
              </option>
            ))}
          </select>
        }
      />
      {!fr ? (
        <p className="lv-ag-empty">Loading…</p>
      ) : fr.success + fr.failed + fr.retry === 0 ? (
        <p className="lv-ag-empty">No terminal missions or job retries in window.</p>
      ) : (
        <ul className="lv-ag-fr">
          {rows.map((r) => (
            <li key={r.key}>
              <span className="lv-ag-fr-label">{r.label}</span>
              <em className={`is-${r.tone}`}>{formatPct(r.ratio)}</em>
              <Bar ratio={r.ratio} tone={r.tone} />
              <strong>{r.count.toLocaleString()}</strong>
            </li>
          ))}
        </ul>
      )}
      <p className="lv-ag-field-hint">Retries from job attempt numbers; cancelled missions are not counted as success.</p>
    </section>
  );
}
