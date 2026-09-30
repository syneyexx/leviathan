import type { AnalyticsDashboard } from "../../types/api";
import type { ChartRange } from "../../pages/analytics/useAnalyticsWorkspace";

type Props = {
  dashboard: AnalyticsDashboard | null;
  chartRange: ChartRange;
  onChartRange: (r: ChartRange) => void;
};

const RANGES: Array<{ id: ChartRange; label: string }> = [
  { id: "7d", label: "Laatste 7 dagen" },
  { id: "30d", label: "Laatste 30 dagen" },
  { id: "90d", label: "Laatste 90 dagen" },
];

function RangeSelect({
  value,
  onChange,
  id,
}: {
  value: ChartRange;
  onChange: (r: ChartRange) => void;
  id: string;
}) {
  return (
    <label className="lv-an-range-select">
      <span className="sr-only">Periode</span>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value as ChartRange)}
        aria-label="Periode"
      >
        {RANGES.map((r) => (
          <option key={r.id} value={r.id}>
            {r.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function LineChart({
  points,
  color = "#38bdf8",
}: {
  points: Array<{ t: string; value: number | null }>;
  color?: string;
}) {
  const known = points.filter((p) => p.value != null) as Array<{ t: string; value: number }>;
  if (!known.length) {
    return <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>;
  }
  const w = 320;
  const h = 140;
  const pad = 16;
  const ys = known.map((p) => p.value);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const span = Math.max(maxY - minY, 1);
  const coords = known.map((p, i) => {
    const x = pad + (i / Math.max(known.length - 1, 1)) * (w - pad * 2);
    const y = h - pad - ((p.value - minY) / span) * (h - pad * 2);
    return { x, y, p };
  });
  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  return (
    <svg className="lv-an-chart-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Lijngrafiek">
      <path d={path} fill="none" stroke={color} strokeWidth="2" />
      {coords.map((c, i) => (
        <circle key={i} cx={c.x} cy={c.y} r="2.5" fill={color}>
          <title>
            {c.p.t}: {c.p.value.toLocaleString("nl-NL")}
          </title>
        </circle>
      ))}
      <text x={pad} y={12} className="lv-an-axis" fill="currentColor">
        {maxY.toLocaleString("nl-NL")}
      </text>
      <text x={pad} y={h - 2} className="lv-an-axis" fill="currentColor">
        {minY.toLocaleString("nl-NL")}
      </text>
    </svg>
  );
}

function DualChart({
  points,
}: {
  points: Array<{ t: string; count: number | null; sizeGb: number | null }>;
}) {
  const known = points.filter((p) => p.count != null);
  if (!known.length) {
    return <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>;
  }
  const w = 320;
  const h = 140;
  const pad = 16;
  const counts = known.map((p) => p.count as number);
  const sizes = known.map((p) => p.sizeGb ?? 0);
  const maxC = Math.max(...counts, 1);
  const maxS = Math.max(...sizes, 1);
  const barW = Math.max(3, (w - pad * 2) / known.length - 2);
  const linePts = known.map((p, i) => {
    const x = pad + i * ((w - pad * 2) / Math.max(known.length - 1, 1));
    const y = h - pad - ((p.sizeGb ?? 0) / maxS) * (h - pad * 2);
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg className="lv-an-chart-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Dataset groei">
      {known.map((p, i) => {
        const x = pad + i * ((w - pad * 2) / Math.max(known.length, 1));
        const bh = ((p.count as number) / maxC) * (h - pad * 2);
        return (
          <rect
            key={i}
            x={x}
            y={h - pad - bh}
            width={barW}
            height={bh}
            fill="#22d3ee"
            opacity="0.75"
          >
            <title>
              {p.t}: {p.count} datasets
            </title>
          </rect>
        );
      })}
      <path d={linePts.join(" ")} fill="none" stroke="#a78bfa" strokeWidth="2" />
    </svg>
  );
}

function MultiLineChart({
  series,
}: {
  series: Array<{ key: string; label: string; points: Array<{ t: string; value: number }>; color: string }>;
}) {
  const any = series.some((s) => s.points.some((p) => p.value > 0));
  if (!any && series.every((s) => !s.points.length)) {
    return <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>;
  }
  const w = 320;
  const h = 140;
  const pad = 16;
  const len = Math.max(...series.map((s) => s.points.length), 1);
  const maxY = Math.max(...series.flatMap((s) => s.points.map((p) => p.value)), 1);
  return (
    <div className="lv-an-multiline">
      <svg className="lv-an-chart-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Onderzoek activiteit">
        {series.map((s) => {
          const path = s.points
            .map((p, i) => {
              const x = pad + (i / Math.max(len - 1, 1)) * (w - pad * 2);
              const y = h - pad - (p.value / maxY) * (h - pad * 2);
              return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ");
          return <path key={s.key} d={path} fill="none" stroke={s.color} strokeWidth="1.8" />;
        })}
      </svg>
      <ul className="lv-an-legend">
        {series.map((s) => (
          <li key={s.key}>
            <i style={{ background: s.color }} />
            {s.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

const ACTIVITY_COLORS: Record<string, string> = {
  web_research: "#38bdf8",
  analyse: "#34d399",
  trading: "#fbbf24",
  agent_research: "#a78bfa",
};

export function AnalyticsChartsRow({ dashboard, chartRange, onChartRange }: Props) {
  const kg = dashboard?.knowledgeGrowth;
  const dg = dashboard?.datasetGrowth;
  const ra = dashboard?.researchActivity;

  return (
    <section className="lv-an-charts-row" aria-label="Groei en activiteit">
      <article id="lv-an-panel-kennis-groei" className="lv-panel lv-an-card lv-an-card--chart">
        <div className="lv-an-card-head">
          <div>
            <div className="lv-section-label">Kennis Groei</div>
            <p className="lv-muted lv-an-sub">{kg?.subtitle ?? "Totale kennis items in de tijd"}</p>
          </div>
          <RangeSelect id="kg-range" value={chartRange} onChange={onChartRange} />
        </div>
        {kg?.error ? (
          <p className="lv-an-error">{kg.error}</p>
        ) : (
          <LineChart points={kg?.points ?? []} />
        )}
      </article>

      <article id="lv-an-panel-dataset-groei" className="lv-panel lv-an-card lv-an-card--chart">
        <div className="lv-an-card-head">
          <div>
            <div className="lv-section-label">Dataset Groei</div>
            <p className="lv-muted lv-an-sub">{dg?.subtitle ?? "Aantal datasets en totale grootte"}</p>
          </div>
          <RangeSelect id="dg-range" value={chartRange} onChange={onChartRange} />
        </div>
        {dg?.error ? (
          <p className="lv-an-error">{dg.error}</p>
        ) : (
          <>
            <DualChart points={dg?.points ?? []} />
            {dg?.coverage?.coveragePercent != null ? (
              <p className="lv-muted lv-an-coverage">
                {dg.coverage.coveragePercent}% gemeten
                {dg.coverage.unknownCount ? ` · ${dg.coverage.unknownCount} size unknown` : ""}
              </p>
            ) : null}
          </>
        )}
      </article>

      <article id="lv-an-panel-onderzoek-activiteit" className="lv-panel lv-an-card lv-an-card--chart">
        <div className="lv-an-card-head">
          <div>
            <div className="lv-section-label">Onderzoek Activiteit</div>
            <p className="lv-muted lv-an-sub">Runs per categorie</p>
          </div>
          <RangeSelect id="ra-range" value={chartRange} onChange={onChartRange} />
        </div>
        {ra?.error ? (
          <p className="lv-an-error">{ra.error}</p>
        ) : (
          <MultiLineChart
            series={(ra?.series ?? []).map((s) => ({
              ...s,
              color: ACTIVITY_COLORS[s.key] ?? "#94a3b8",
            }))}
          />
        )}
      </article>
    </section>
  );
}
