import type { MediaOverview } from "../../hooks/useMediaOverview";
import { MetricCard } from "../ui";

type Props = {
  overview: MediaOverview;
};

function MetricBars({ heights }: { heights: number[] }) {
  return (
    <>
      {heights.map((h, i) => (
        <span key={i} className="lv-v2-metric-card__bar" style={{ height: `${h}%` }} aria-hidden="true" />
      ))}
    </>
  );
}

const KIND_CLASS: Record<string, string> = {
  total: "lv-v2-metric-card--media-total",
  image: "lv-v2-metric-card--media-image",
  video: "lv-v2-metric-card--media-video",
  audio: "lv-v2-metric-card--media-audio",
  document: "lv-v2-metric-card--media-document",
};

export function MediaMetrics({ overview }: Props) {
  const { kpis, loading } = overview;

  return (
    <section className="lv-v2-metrics lv-v2-metrics--media" aria-label="Media KPI overzicht">
      {kpis.map((kpi) => (
        <MetricCard
          key={kpi.id}
          label={kpi.label}
          loading={loading}
          value={kpi.value}
          sublabel={kpi.sublabel}
          className={KIND_CLASS[kpi.kind] ?? ""}
          chart={<MetricBars heights={kpi.barHeights} />}
        />
      ))}
    </section>
  );
}
