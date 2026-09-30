import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Panel } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function StatsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M4 19V5M4 19h16" />
      <path d="M8 17V10M12 17V7M16 17v-4" />
    </svg>
  );
}

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function TrainingStatsCard({ ws }: Props) {
  const s = ws.stats;
  const rows: Array<{ label: string; value: string }> = [
    { label: "Actieve trainingen", value: dash(s.active) },
    { label: "In de wachtrij", value: dash(s.queued) },
    { label: "Voltooide runs", value: dash(s.completed) },
    {
      label: "Totale trainingstijd",
      value: s.totalTrainingHours != null ? `${s.totalTrainingHours} uur` : "—",
    },
    {
      label: "Beste validatie loss",
      value: s.bestEvalLoss != null ? s.bestEvalLoss.toFixed(3) : "—",
    },
    {
      label: "Totale compute gebruikt",
      value: s.totalComputeHours != null ? `${s.totalComputeHours} GPU-uur` : "—",
    },
  ];

  return (
    <Panel title="Trainings Statistieken" icon={<StatsIcon />} className="lv-v2-training-stats">
      <ul className="lv-v2-training-stats__list">
        {rows.map((row) => (
          <li key={row.label} className="lv-v2-training-stats__row">
            <span>{row.label}</span>
            <strong>{row.value}</strong>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
