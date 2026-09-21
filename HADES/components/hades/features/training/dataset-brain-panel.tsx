"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Brain, Database, HardDrive, Loader2, RefreshCcw, RotateCcw, Square, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel, StatCard, StatusBadge } from "@/components/hades/ui";
import { hadesTrainingApi, TrainingDataset } from "@/lib/hades-training-api";
import {
  DatasetBrainJob,
  DatasetBrainStatus,
  hadesDatasetBrainApi,
} from "@/lib/hades-dataset-brain-api";

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount.toLocaleString("nl-NL", { maximumFractionDigits: 1 })} ${units[index]}`;
}

function tone(status: string): "success" | "warning" | "info" | "danger" | "neutral" {
  if (status === "ready" || status === "completed") return "success";
  if (["running", "materializing", "indexing"].includes(status)) return "info";
  if (["queued", "cancelling", "cancelled", "interrupted"].includes(status)) return "warning";
  if (status === "failed" || status === "error") return "danger";
  return "neutral";
}

export function DatasetBrainPanel() {
  const [datasets, setDatasets] = useState<TrainingDataset[]>([]);
  const [statuses, setStatuses] = useState<DatasetBrainStatus[]>([]);
  const [jobs, setJobs] = useState<DatasetBrainJob[]>([]);
  const [hfToken, setHfToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [log, setLog] = useState<{ id: string; content: string } | null>(null);

  const byDataset = useMemo(() => new Map(statuses.map((item) => [item.dataset_id, item])), [statuses]);
  const active = useMemo(
    () => jobs.filter((job) => ["queued", "running", "cancelling"].includes(job.status)),
    [jobs],
  );
  const readyCount = statuses.filter((item) => item.status === "ready").length;
  const localBytes = statuses.reduce((sum, item) => sum + Number(item.snapshot_size_bytes || 0), 0);
  const chunkCount = statuses.reduce((sum, item) => sum + Number(item.chunks_indexed || 0), 0);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextDatasets, nextStatuses, nextJobs] = await Promise.all([
        hadesTrainingApi.datasets(),
        hadesDatasetBrainApi.statuses(),
        hadesDatasetBrainApi.jobs(),
      ]);
      setDatasets(nextDatasets);
      setStatuses(nextStatuses);
      setJobs(nextJobs);
    } catch (reason) {
      if (!quiet) toast.error(reason instanceof Error ? reason.message : "Dataset Brain-status laden is mislukt.");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(true), 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!active.length) return undefined;
    const timer = window.setInterval(() => void refresh(true), 2500);
    return () => window.clearInterval(timer);
  }, [active.length, refresh]);

  const start = async (
    dataset: TrainingDataset,
    options: { rebuild_index?: boolean; rematerialize?: boolean } = {},
  ) => {
    setBusy(`index:${dataset.id}`);
    try {
      const job = await hadesDatasetBrainApi.index(dataset.id, {
        hf_token: dataset.source_type === "huggingface" && hfToken ? hfToken : undefined,
        approved_network: dataset.source_type === "huggingface",
        approved_file_read: dataset.source_type !== "huggingface",
        approved_subprocess: true,
        rebuild_index: Boolean(options.rebuild_index),
        rematerialize: Boolean(options.rematerialize),
      });
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      toast.success(
        options.rematerialize
          ? `Bron '${dataset.name}' wordt opnieuw lokaal opgeslagen en geïndexeerd.`
          : `Dataset '${dataset.name}' wordt in het HADES-brein geïndexeerd.`,
      );
      await refresh(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Dataset Brain-indexering starten mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const cancel = async (jobId: string) => {
    setBusy(`cancel:${jobId}`);
    try {
      await hadesDatasetBrainApi.cancel(jobId);
      await refresh(true);
      toast.success("Stopverzoek opgeslagen; de worker stopt op een veilig checkpoint.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Brain-indexering stoppen mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const remove = async (dataset: TrainingDataset) => {
    if (!window.confirm(`Offline Brain-data en de zoekindex voor '${dataset.name}' verwijderen? De datasetregistratie zelf blijft bestaan.`)) return;
    setBusy(`remove:${dataset.id}`);
    try {
      await hadesDatasetBrainApi.remove(dataset.id);
      await refresh(true);
      toast.success(`Offline Brain-data van '${dataset.name}' verwijderd; datasetregistratie blijft bestaan.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Brain-data verwijderen mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const openLog = async (jobId: string) => {
    setBusy(`log:${jobId}`);
    try {
      const result = await hadesDatasetBrainApi.jobLog(jobId);
      setLog({ id: jobId, content: result.content });
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Brain-log laden mislukt.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section id="dataset-brain" className="details-stack" aria-labelledby="dataset-brain-title">
      <div>
        <h2 id="dataset-brain-title">HADES BRAIN</h2>
        <p className="panel-copy">Maak geregistreerde datasets duurzaam offline en automatisch doorzoekbaar voor Chat, Taken en agents.</p>
      </div>

      <Panel
        title="Offline datasetkennis"
        actions={
          <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
            {loading ? <Loader2 className="spin" /> : <RefreshCcw />}Vernieuwen
          </Button>
        }
      >
        <div className="page-warning">
          <Brain />
          <span>
            <strong>Dit traint het framework, niet het model.</strong>
            <small>
              HADES bewaart de dataset lokaal en indexeert bruikbare chunks in de bestaande Knowledge Library. Gewone vragen doorzoeken die library al automatisch via lokale retrieval, reranking en contextbudgetten. Alleen relevante passages gaan naar het LLM; na materialisatie is Hugging Face niet meer nodig.
            </small>
          </span>
        </div>

        <section className="stat-grid four">
          <StatCard label="Offline bronnen" value={`${readyCount}/${datasets.length}`} note="Gereed voor automatische retrieval" icon={<Brain />} />
          <StatCard label="Brain chunks" value={chunkCount.toLocaleString("nl-NL")} note="FTS/Knowledge Library" icon={<Database />} />
          <StatCard label="Lokale snapshot" value={formatBytes(localBytes)} note="Onder HADES training/datasets" icon={<HardDrive />} />
          <StatCard label="Actieve imports" value={String(active.length)} note="Resumable achtergrondworkers" icon={<Loader2 className={active.length ? "spin" : ""} />} />
        </section>

        {datasets.some((dataset) => dataset.source_type === "huggingface") ? (
          <label className="prompt-field">
            <span>HF token <small>alleen voor gated/private bron tijdens eerste download of bronverversing; wordt niet opgeslagen</small></span>
            <Input type="password" autoComplete="off" value={hfToken} onChange={(event) => setHfToken(event.target.value)} placeholder="hf_…" />
          </label>
        ) : null}

        <div className="model-list">
          {datasets.map((dataset) => {
            const item = byDataset.get(dataset.id);
            const status = item?.status || "not_indexed";
            const activeJob = jobs.find(
              (job) => job.dataset_id === dataset.id && ["queued", "running", "cancelling"].includes(job.status),
            );
            return (
              <article className="model-row functional-model-row" key={`brain:${dataset.id}`}>
                <span className="radio-dot">{status === "ready" || activeJob ? <i /> : null}</span>
                <div className="model-name">
                  <strong>{dataset.name}</strong>
                  <small>
                    {Number(item?.materialized_rows || 0).toLocaleString("nl-NL")} rijen lokaal · {Number(item?.chunks_indexed || 0).toLocaleString("nl-NL")} chunks
                  </small>
                </div>
                <span>
                  <small>Offline opslag</small>
                  <strong>{formatBytes(item?.snapshot_size_bytes)}</strong>
                </span>
                <div className="model-status">
                  <StatusBadge tone={tone(status)}>{status}</StatusBadge>
                  {activeJob ? <StatusBadge tone="info">{Math.round(Math.max(0, Math.min(1, activeJob.progress || 0)) * 100)}%</StatusBadge> : null}
                  {item?.error ? <StatusBadge tone="danger">fout</StatusBadge> : null}
                </div>
                <div className="model-actions">
                  {activeJob ? (
                    <>
                      <Button variant="outline" size="sm" onClick={() => void openLog(activeJob.id)} disabled={busy === `log:${activeJob.id}`}>Log</Button>
                      <Button variant="outline" size="sm" onClick={() => void cancel(activeJob.id)} disabled={busy === `cancel:${activeJob.id}`}><Square />Stop</Button>
                    </>
                  ) : status === "ready" ? (
                    <>
                      <Button variant="outline" size="sm" onClick={() => void start(dataset, { rebuild_index: true })} disabled={busy === `index:${dataset.id}`}><RefreshCcw />Herindexeer</Button>
                      <Button variant="outline" size="sm" onClick={() => void start(dataset, { rebuild_index: true, rematerialize: true })} disabled={busy === `index:${dataset.id}`}><RotateCcw />Ververs bron</Button>
                      <Button variant="outline" size="sm" onClick={() => void remove(dataset)} disabled={busy === `remove:${dataset.id}`} aria-label={`${dataset.name} uit HADES Brain verwijderen`}><Trash2 /></Button>
                    </>
                  ) : (
                    <Button onClick={() => void start(dataset)} disabled={busy === `index:${dataset.id}`}>
                      {busy === `index:${dataset.id}` ? <Loader2 className="spin" /> : <Brain />}{status === "interrupted" ? "Hervatten" : "Offline maken + indexeren"}
                    </Button>
                  )}
                </div>
              </article>
            );
          })}
          {!datasets.length && !loading ? <div className="table-empty">Registreer hierboven eerst een lokale of Hugging Face dataset.</div> : null}
        </div>
      </Panel>

      {log ? (
        <Panel title={`Brain-log · ${log.id}`} actions={<Button variant="outline" size="sm" onClick={() => setLog(null)}>Sluiten</Button>}>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 420, overflow: "auto" }}>{log.content || "Nog geen logoutput."}</pre>
        </Panel>
      ) : null}
    </section>
  );
}
