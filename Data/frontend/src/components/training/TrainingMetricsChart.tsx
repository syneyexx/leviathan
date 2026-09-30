import { metricSeries, perplexityFromLoss } from "../../hooks/useTrainingWorkspace";
import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Button, Panel } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function ChartIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M4 19V5M4 19h16" />
      <path d="M7 15l4-5 3 3 5-7" />
    </svg>
  );
}

function chartPolyline(values: number[], width: number, height: number): string {
  if (values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values
    .map((v, i) => {
      const x = values.length === 1 ? 0 : (i / (values.length - 1)) * width;
      const y = height - ((v - min) / span) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function TrainingMetricsChart({ ws }: Props) {
  const trainLoss = metricSeries(ws.metrics, ["loss", "train_loss", "train/loss"]);
  const evalLoss = metricSeries(ws.metrics, ["eval_loss", "val_loss", "eval/loss", "validation_loss"]);
  const trainPpl = trainLoss.map((v) => perplexityFromLoss(v) ?? v);
  const evalPpl = evalLoss.map((v) => perplexityFromLoss(v) ?? v);

  const series =
    ws.chartMode === "perplexity"
      ? [trainPpl, evalPpl]
      : [trainLoss, evalLoss];
  const labels =
    ws.chartMode === "perplexity"
      ? ["Train PPL", "Eval PPL"]
      : ["Train Loss", "Eval Loss"];
  const hasData = series.some((s) => s.length > 1);
  const width = 420;
  const height = 120;

  return (
    <Panel
      title="Live Trainingsgrafieken"
      icon={<ChartIcon />}
      className="lv-v2-training-metrics"
      action={
        <div className="lv-v2-training-metrics__modes" role="group" aria-label="Metric view">
          <Button
            variant={ws.chartMode === "loss" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => ws.setChartMode("loss")}
          >
            Loss
          </Button>
          <Button
            variant={ws.chartMode === "perplexity" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => ws.setChartMode("perplexity")}
          >
            Perplexity
          </Button>
        </div>
      }
    >
      {!ws.selectedJob ? (
        <p className="lv-v2-muted">Selecteer een run om metrieken te zien.</p>
      ) : !hasData ? (
        <p className="lv-v2-muted">Nog geen metrieken voor deze run.</p>
      ) : (
        <>
          <div className="lv-v2-training-metrics__legend">
            <span className="is-train">{labels[0]}</span>
            <span className="is-eval">{labels[1]}</span>
          </div>
          <svg
            className="lv-v2-training-metrics__svg"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={`${labels.join(" en ")} over steps`}
          >
            <line x1="0" y1={height - 1} x2={width} y2={height - 1} stroke="rgba(34,201,214,0.15)" />
            {series.map((values, i) =>
              values.length > 1 ? (
                <path
                  key={labels[i]}
                  d={chartPolyline(values, width, height - 4)}
                  fill="none"
                  stroke={i === 0 ? "var(--lv2-cyan, #22c9d6)" : "var(--lv2-gold, #d4a017)"}
                  strokeWidth="1.8"
                  vectorEffect="non-scaling-stroke"
                />
              ) : null,
            )}
          </svg>
          <p className="lv-v2-muted lv-v2-training-metrics__axis">Step / epoch — geen fake accuracy</p>
        </>
      )}
    </Panel>
  );
}
