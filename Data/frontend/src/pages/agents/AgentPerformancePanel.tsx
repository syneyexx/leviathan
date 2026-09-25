import { useMemo } from "react";
import type { AgentsDashboard } from "../../types/api";
import { PanelHead } from "./agentsUi";

const PERFORMANCE_WINDOWS: Array<{ hours: number; label: string }> = [
  { hours: 1, label: "Last hour" },
  { hours: 6, label: "Last 6 hours" },
  { hours: 24, label: "Last 24 hours" },
  { hours: 72, label: "Last 3 days" },
  { hours: 168, label: "Last 7 days" },
];

const W = 320;
const H = 110;
const PAD_L = 22;
const PAD_R = 26;
const PAD_T = 8;
const PAD_B = 16;

export function AgentPerformancePanel({
  dashboard,
  windowHours,
  onWindow,
}: {
  dashboard: AgentsDashboard | null;
  windowHours: number;
  onWindow: (hours: number) => void;
}) {
  const buckets = useMemo(() => dashboard?.performance.buckets ?? [], [dashboard]);
  const maxCount = Math.max(1, ...buckets.map((b) => b.completed + b.failed));
  const total = buckets.reduce((a, b) => a + b.completed + b.failed, 0);
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;
  const slot = buckets.length ? innerW / buckets.length : innerW;
  const barW = Math.max(2, slot * 0.62);

  const linePoints = buckets
    .map((b, i) =>
      b.successRate == null
        ? null
        : `${(PAD_L + slot * i + slot / 2).toFixed(1)},${(PAD_T + innerH * (1 - b.successRate)).toFixed(1)}`,
    )
    .filter((p): p is string => p != null);

  const firstLabel = buckets[0]?.start ? buckets[0].start.slice(11, 16) : "";
  const lastLabel = buckets.length ? buckets[buckets.length - 1].end.slice(11, 16) : "";

  return (
    <section className="lv-ag-panel lv-ag-perf">
      <PanelHead
        title="Performance Trends"
        right={
          <select
            className="lv-ag-mini-select"
            value={windowHours}
            onChange={(e) => onWindow(Number(e.target.value))}
            aria-label="Performance window"
          >
            {PERFORMANCE_WINDOWS.map((w) => (
              <option key={w.hours} value={w.hours}>
                {w.label}
              </option>
            ))}
          </select>
        }
      />
      <div className="lv-ag-legend">
        <span>
          <i className="is-cyan" /> Tasks completed
        </span>
        <span>
          <i className="is-red" /> Failed
        </span>
        <span>
          <i className="is-gold" /> Success rate
        </span>
      </div>
      {!dashboard ? (
        <p className="lv-ag-empty">Loading…</p>
      ) : total === 0 ? (
        <div className="lv-ag-chart-empty">
          <svg viewBox={`0 0 ${W} ${H}`} className="lv-ag-chart" aria-hidden="true">
            {[0, 0.5, 1].map((g) => (
              <line key={g} x1={PAD_L} x2={W - PAD_R} y1={PAD_T + innerH * g} y2={PAD_T + innerH * g} className="lv-ag-gridline" />
            ))}
          </svg>
          <span>No terminal missions in window</span>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} className="lv-ag-chart" role="img" aria-label="Mission completions and success rate">
          {[0, 0.5, 1].map((g) => (
            <line key={g} x1={PAD_L} x2={W - PAD_R} y1={PAD_T + innerH * g} y2={PAD_T + innerH * g} className="lv-ag-gridline" />
          ))}
          <text x={PAD_L - 4} y={PAD_T + 4} textAnchor="end" className="lv-ag-axis">
            {maxCount}
          </text>
          <text x={PAD_L - 4} y={PAD_T + innerH} textAnchor="end" className="lv-ag-axis">
            0
          </text>
          <text x={W - PAD_R + 4} y={PAD_T + 4} className="lv-ag-axis is-gold">
            100%
          </text>
          <text x={W - PAD_R + 4} y={PAD_T + innerH} className="lv-ag-axis is-gold">
            0%
          </text>
          {buckets.map((b, i) => {
            const x = PAD_L + slot * i + (slot - barW) / 2;
            const hc = (b.completed / maxCount) * innerH;
            const hf = (b.failed / maxCount) * innerH;
            return (
              <g key={b.start}>
                <title>
                  {`${b.start.slice(11, 16)}–${b.end.slice(11, 16)}: ${b.completed} completed, ${b.failed} failed`}
                </title>
                <rect x={x} y={PAD_T + innerH - hc} width={barW} height={hc} className="lv-ag-bar-c" />
                <rect x={x} y={PAD_T + innerH - hc - hf} width={barW} height={hf} className="lv-ag-bar-f" />
              </g>
            );
          })}
          {linePoints.length > 1 ? <polyline points={linePoints.join(" ")} className="lv-ag-line" /> : null}
          {linePoints.map((p) => {
            const [cx, cy] = p.split(",");
            return <circle key={p} cx={cx} cy={cy} r={1.8} className="lv-ag-line-dot" />;
          })}
          <text x={PAD_L} y={H - 3} className="lv-ag-axis">
            {firstLabel}
          </text>
          <text x={W - PAD_R} y={H - 3} textAnchor="end" className="lv-ag-axis">
            {lastLabel}
          </text>
        </svg>
      )}
    </section>
  );
}
