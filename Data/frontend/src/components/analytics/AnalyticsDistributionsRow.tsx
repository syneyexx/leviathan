import type { AnalyticsDashboard, AnalyticsDistributionSegment } from "../../types/api";

const COLORS = ["#38bdf8", "#22d3ee", "#a78bfa", "#fbbf24", "#34d399", "#f472b6", "#94a3b8"];

function Donut({
  total,
  segments,
  title,
}: {
  total: number;
  segments: AnalyticsDistributionSegment[];
  title: string;
}) {
  if (!segments.length || total <= 0) {
    return <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>;
  }
  const r = 42;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="lv-an-donut-wrap">
      <svg className="lv-an-donut" viewBox="0 0 120 120" role="img" aria-label={title}>
        <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(148,163,184,0.15)" strokeWidth="14" />
        {segments.map((seg, i) => {
          const len = (seg.percent / 100) * c;
          const el = (
            <circle
              key={seg.key}
              cx="60"
              cy="60"
              r={r}
              fill="none"
              stroke={COLORS[i % COLORS.length]}
              strokeWidth="14"
              strokeDasharray={`${len} ${c - len}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 60 60)"
            >
              <title>
                {seg.label}: {seg.count} ({seg.percent}%)
              </title>
            </circle>
          );
          offset += len;
          return el;
        })}
        <text x="60" y="56" textAnchor="middle" className="lv-an-donut-total">
          {total >= 1000 ? `${(total / 1000).toFixed(1)}K` : total}
        </text>
        <text x="60" y="72" textAnchor="middle" className="lv-an-donut-sub">
          totaal
        </text>
      </svg>
      <ul className="lv-an-donut-legend">
        {segments.map((seg, i) => (
          <li key={seg.key}>
            <i style={{ background: COLORS[i % COLORS.length] }} />
            <span>{seg.label}</span>
            <strong>{seg.percent}%</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AnalyticsDistributionsRow({ dashboard }: { dashboard: AnalyticsDashboard | null }) {
  const d = dashboard?.distributions;
  return (
    <section className="lv-an-dist-row" aria-label="Verdelingen">
      <article id="lv-an-panel-item-types" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Item Types Verdeling</div>
        </div>
        <Donut
          title="Item Types"
          total={d?.itemTypes?.total ?? 0}
          segments={d?.itemTypes?.segments ?? []}
        />
      </article>
      <article id="lv-an-panel-dataset-types" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Dataset Types</div>
        </div>
        <Donut
          title="Dataset Types"
          total={d?.datasetTypes?.total ?? 0}
          segments={d?.datasetTypes?.segments ?? []}
        />
      </article>
      <article id="lv-an-panel-bronnen" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Bronnen Verdeling</div>
        </div>
        <Donut
          title="Bronnen"
          total={d?.sources?.total ?? 0}
          segments={d?.sources?.segments ?? []}
        />
      </article>
    </section>
  );
}
