import {
  latestMetric,
  perplexityFromLoss,
  visualNowMs,
} from "../../hooks/useTrainingWorkspace";
import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { ACTIVE_TRAINING_STATUSES, TRAINING_STATUS_LABELS, trainingStatusTone } from "../../training/constants";
import { Badge, Button, Panel, ProgressBar } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

function DetailIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5M12 16h.01" />
    </svg>
  );
}

function dash(value: string | number | null | undefined, digits?: number): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && digits != null) return value.toFixed(digits);
  return String(value);
}

function etaFromJob(progress: number | null | undefined, startedAt?: string | null): string {
  if (progress == null || !startedAt || progress <= 0) return "—";
  const pct = progress <= 1 ? progress : progress / 100;
  if (pct <= 0.01) return "—";
  const start = Date.parse(startedAt);
  if (Number.isNaN(start)) return "—";
  const elapsed = visualNowMs() - start;
  if (elapsed <= 0) return "—";
  const remaining = elapsed * (1 / pct - 1);
  if (!Number.isFinite(remaining) || remaining < 0) return "—";
  const mins = Math.round(remaining / 60_000);
  if (mins < 60) return `~ ${mins} minuten (geschat)`;
  return `~ ${(mins / 60).toFixed(1)} uur (geschat)`;
}

export function TrainingRunDetailPanel({ ws }: Props) {
  const job = ws.selectedJob;
  const trainLoss = latestMetric(ws.metrics, ["loss", "train_loss", "train/loss"]);
  const evalLoss = latestMetric(ws.metrics, ["eval_loss", "val_loss", "eval/loss", "validation_loss"]);
  const tokensPerSec = latestMetric(ws.metrics, [
    "tokens_per_second",
    "tokens_per_sec",
    "tok_s",
    "train_tokens_per_second",
  ]);
  const evalTok = latestMetric(ws.metrics, ["eval_tokens_per_second", "eval_tok_s"]);
  const epochMetric = latestMetric(ws.metrics, ["epoch"]);
  const progress =
    job?.progress == null ? null : Math.max(0, Math.min(100, job.progress * (job.progress <= 1 ? 100 : 1)));
  const epochsTotal = job?.config?.epochs;
  const epochCurrent =
    epochMetric?.metricValue ??
    (typeof job?.metricsSummary?.epoch === "number" ? job.metricsSummary.epoch : null);
  const ppl = perplexityFromLoss(evalLoss?.metricValue ?? trainLoss?.metricValue);

  const gpu = ws.hardware?.gpus?.[0];
  const gpuUtil = gpu?.utilizationPct ?? null;
  const vramUsed = gpu?.usedVramBytes;
  const vramTotal = gpu?.totalVramBytes;
  const ramUsed =
    ws.hardware?.ramTotalBytes != null && ws.hardware.ramAvailableBytes != null
      ? ws.hardware.ramTotalBytes - ws.hardware.ramAvailableBytes
      : null;

  return (
    <Panel title="Huidige Run Details" icon={<DetailIcon />} className="lv-v2-training-detail">
      {!job ? (
        <p className="lv-v2-muted">Geen run geselecteerd.</p>
      ) : (
        <div className="lv-v2-training-detail__grid">
          <div className="lv-v2-training-detail__main">
            <div className="lv-v2-training-detail__head">
              <strong>{job.name}</strong>
              <Badge tone={trainingStatusTone(job.status)}>
                {TRAINING_STATUS_LABELS[job.status] || job.status}
              </Badge>
            </div>
            <ProgressBar value={progress} label={progress == null ? undefined : `${Math.round(progress)}%`} />
            <div className="lv-v2-training-detail__meta">
              <span>{progress == null ? "—" : `${Math.round(progress)}%`}</span>
              <span>Resterend: {etaFromJob(job.progress, job.startedAt)}</span>
              <span>
                Epoch:{" "}
                {epochCurrent != null
                  ? `${dash(epochCurrent, 1)}${epochsTotal != null ? ` / ${epochsTotal}` : ""}`
                  : "—"}
              </span>
            </div>
            {ACTIVE_TRAINING_STATUSES.has(job.status) ? (
              <Button variant="secondary" size="sm" disabled={ws.busy} onClick={() => void ws.cancelJob(job.jobId)}>
                Stop
              </Button>
            ) : null}
          </div>

          <div className="lv-v2-training-detail__metrics">
            <h4>Huidige Metrics</h4>
            <ul>
              <li>
                <span>Train loss</span>
                <strong>{dash(trainLoss?.metricValue, 3)}</strong>
              </li>
              <li>
                <span>Validatie loss</span>
                <strong>{dash(evalLoss?.metricValue, 3)}</strong>
              </li>
              <li>
                <span>Perplexity</span>
                <strong>{dash(ppl, 2)}</strong>
              </li>
            </ul>
          </div>

          <div className="lv-v2-training-detail__speeds">
            <h4>Snelheden &amp; gebruik</h4>
            <ul>
              <li>
                <span>Training snelheid</span>
                <strong>
                  {tokensPerSec ? `${tokensPerSec.metricValue.toFixed(1)} tok/s` : "—"}
                </strong>
              </li>
              <li>
                <span>Validatie snelheid</span>
                <strong>{evalTok ? `${evalTok.metricValue.toFixed(1)} tok/s` : "—"}</strong>
              </li>
              <li>
                <span>GPU gebruik</span>
                <strong>{gpuUtil != null ? `${Math.round(gpuUtil)}%` : "—"}</strong>
              </li>
              <li>
                <span>VRAM gebruikt</span>
                <strong>
                  {vramUsed != null && vramTotal != null
                    ? `${ws.formatBytes(vramUsed)} / ${ws.formatBytes(vramTotal, 0)}`
                    : "—"}
                </strong>
              </li>
              <li>
                <span>Systeem RAM</span>
                <strong>
                  {ramUsed != null && ws.hardware?.ramTotalBytes != null
                    ? `${ws.formatBytes(ramUsed)} / ${ws.formatBytes(ws.hardware.ramTotalBytes, 0)}`
                    : "—"}
                </strong>
              </li>
            </ul>
          </div>
        </div>
      )}
    </Panel>
  );
}
