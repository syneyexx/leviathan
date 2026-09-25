import { useMemo } from "react";
import type { AgentsDashboard } from "../../types/api";
import { donutSegments } from "./helpers";
import { PanelHead } from "./agentsUi";

const TEAM_COLORS: Record<string, string> = {
  Research: "#22c9d6",
  Development: "#d6a957",
  Trading: "#34d399",
  Planning: "#a78bfa",
  Risk: "#f87171",
  Memory: "#60a5fa",
  Evaluation: "#fbbf24",
  Vision: "#f472b6",
  Other: "#8b8f88",
};

const R = 34;
const STROKE = 11;
const C = 2 * Math.PI * R;

export function TeamDistributionPanel({ dashboard }: { dashboard: AgentsDashboard | null }) {
  const items = useMemo(
    () => (dashboard?.teamDistribution ?? []).map((t) => ({ label: t.team, value: t.count })),
    [dashboard],
  );
  const segments = useMemo(() => donutSegments(items), [items]);
  const total = items.reduce((a, b) => a + b.value, 0);

  return (
    <section className="lv-ag-panel lv-ag-team">
      <PanelHead title="Team Distribution" />
      {!dashboard ? (
        <p className="lv-ag-empty">Loading…</p>
      ) : total === 0 ? (
        <p className="lv-ag-empty">No fleet agents.</p>
      ) : (
        <div className="lv-ag-donut-wrap">
          <svg viewBox="0 0 90 90" className="lv-ag-donut" role="img" aria-label="Agents by team">
            <circle cx="45" cy="45" r={R} className="lv-ag-donut-track" strokeWidth={STROKE} />
            {segments.map((s) => (
              <circle
                key={s.label}
                cx="45"
                cy="45"
                r={R}
                fill="none"
                stroke={TEAM_COLORS[s.label] ?? TEAM_COLORS.Other}
                strokeWidth={STROKE}
                strokeDasharray={`${Math.max(0.5, (s.end - s.start) * C - 1)} ${C}`}
                strokeDashoffset={-s.start * C}
                transform="rotate(-90 45 45)"
              >
                <title>{`${s.label}: ${s.value}`}</title>
              </circle>
            ))}
            <text x="45" y="44" textAnchor="middle" className="lv-ag-donut-num">
              {total}
            </text>
            <text x="45" y="54" textAnchor="middle" className="lv-ag-donut-cap">
              agents
            </text>
          </svg>
          <ul className="lv-ag-donut-legend">
            {items.map((t) => (
              <li key={t.label}>
                <i style={{ background: TEAM_COLORS[t.label] ?? TEAM_COLORS.Other }} />
                <span>{t.label}</span>
                <em>{Math.round((t.value / total) * 100)}%</em>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
