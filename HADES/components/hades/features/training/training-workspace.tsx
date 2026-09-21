"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cloud, Cpu, Database, HardDrive, Loader2, Play, RefreshCcw, Square, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Panel, StatCard, StatusBadge } from "@/components/hades/ui";
import {
  hadesTrainingApi,
  HuggingFacePreview,
  HuggingFaceSplit,
  MemoryStrategy,
  TrainingCapabilities,
  TrainingDataset,
  TrainingExecutionPlan,
  TrainingJob,
} from "@/lib/hades-training-api";
import { invalidateHadesQuery, useHadesQuery } from "@/hooks/use-hades-query";

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "remote";
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

function strategyLabel(strategy: string): string {
  switch (strategy) {
    case "auto":
      return "Auto — aanbevolen";
    case "gpu_resident":
      return "GPU only";
    case "gpu_resident_4bit":
      return "Save VRAM (4-bit)";
    case "cpu_offload":
      return "CPU offload";
    case "ram_layer_streaming":
      return "Experimental layer streaming (RAM)";
    case "nvme_layer_streaming":
      return "Experimental layer streaming (NVMe)";
    default:
      return strategy;
  }
}

function jobTone(status: string): "success" | "warning" | "info" | "danger" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  if (status === "queued" || status === "cancelling") return "warning";
  return "neutral";
}

function splitKey(split: HuggingFaceSplit): string {
  return `${split.config}\u0000${split.split}`;
}

function parseSplitKey(value: string): HuggingFaceSplit | null {
  const index = value.indexOf("\u0000");
  if (index < 0) return null;
  return { config: value.slice(0, index), split: value.slice(index + 1) };
}

const ACTIVE_JOB_STATUSES = new Set([
  "queued",
  "planning",
  "profiling",
  "waiting_for_model",
  "allocating",
  "warming_up",
  "running",
  "checkpointing",
  "cancelling",
]);

export function TrainingWorkspace() {
  const capabilitiesQuery = useHadesQuery<TrainingCapabilities>(
    "training-capabilities",
    () => hadesTrainingApi.capabilities(),
    { staleTime: 120_000, refetchOnVisibility: true },
  );
  const datasetsQuery = useHadesQuery<TrainingDataset[]>(
    "training-datasets",
    () => hadesTrainingApi.datasets(),
    { staleTime: 60_000, refetchOnVisibility: true },
  );
  const jobsQuery = useHadesQuery<TrainingJob[]>(
    "training-jobs",
    () => hadesTrainingApi.jobs(),
    { staleTime: 2_000, refetchOnVisibility: true },
  );

  const capabilities = capabilitiesQuery.error ? null : capabilitiesQuery.data ?? null;
  const datasets = datasetsQuery.error ? [] : datasetsQuery.data ?? [];
  const jobs = jobsQuery.error ? [] : jobsQuery.data ?? [];
  const loading = capabilitiesQuery.isLoading || datasetsQuery.isLoading || jobsQuery.isLoading;

  const [busy, setBusy] = useState<string | null>(null);

  const [localPath, setLocalPath] = useState("");
  const [localName, setLocalName] = useState("");
  const [localTextField, setLocalTextField] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  const [hfDatasetId, setHfDatasetId] = useState("");
  const [hfToken, setHfToken] = useState("");
  const [hfSplits, setHfSplits] = useState<HuggingFaceSplit[]>([]);
  const [hfSelectedSplit, setHfSelectedSplit] = useState("");
  const [hfPreview, setHfPreview] = useState<HuggingFacePreview | null>(null);
  const [hfTextField, setHfTextField] = useState("");

  const [jobDatasetId, setJobDatasetId] = useState("");
  const [baseModel, setBaseModel] = useState("");
  const [maxSteps, setMaxSteps] = useState(200);
  const [learningRate, setLearningRate] = useState(0.0002);
  const [sequenceLength, setSequenceLength] = useState(1024);
  const [batchSize, setBatchSize] = useState(1);
  const [gradientAccumulation, setGradientAccumulation] = useState(8);
  const [loraR, setLoraR] = useState(16);
  const [loraAlpha, setLoraAlpha] = useState(32);
  const [loadIn4Bit, setLoadIn4Bit] = useState(false);
  const [memoryStrategy, setMemoryStrategy] = useState<MemoryStrategy>("auto");
  const [experimentalStreaming, setExperimentalStreaming] = useState(false);
  const [showAdvancedAtme, setShowAdvancedAtme] = useState(false);
  const [activationCheckpointing, setActivationCheckpointing] = useState<"auto" | "enabled" | "disabled">("auto");
  const [streamBufferCount, setStreamBufferCount] = useState<number | "auto">("auto");
  const [planPreview, setPlanPreview] = useState<TrainingExecutionPlan | null>(null);
  const [planWarnings, setPlanWarnings] = useState<string[]>([]);
  const [selectedLog, setSelectedLog] = useState<{ id: string; content: string } | null>(null);

  const activeJobs = useMemo(() => jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status)), [jobs]);

  const simpleStrategy = memoryStrategy === "auto" || memoryStrategy === "gpu_resident" || memoryStrategy === "gpu_resident_4bit"
    ? memoryStrategy === "gpu_resident_4bit"
      ? "save_vram"
      : memoryStrategy === "gpu_resident"
        ? "gpu_only"
        : "auto"
    : "streaming";

  const refreshJobs = useCallback(async () => {
    try {
      await jobsQuery.refetch(true);
    } catch {
      // Job polling errors are surfaced on the next manual refresh.
    }
  }, [jobsQuery]);

  const refreshAll = useCallback(async () => {
    try {
      await Promise.all([
        capabilitiesQuery.refetch(true),
        datasetsQuery.refetch(true),
        jobsQuery.refetch(true),
      ]);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "TRAINEN-status laden is mislukt.");
    }
  }, [capabilitiesQuery, datasetsQuery, jobsQuery]);

  const invalidateCatalog = useCallback(() => {
    invalidateHadesQuery("training-capabilities");
    invalidateHadesQuery("training-datasets");
  }, []);

  useEffect(() => {
    if (!datasets.length) return;
    setJobDatasetId((current) => current || datasets[0]?.id || "");
  }, [datasets]);

  useEffect(() => {
    if (!activeJobs.length) return undefined;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void refreshJobs();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeJobs.length, refreshJobs]);

  const registerLocal = async () => {
    if (!localPath.trim()) return;
    setBusy("local");
    try {
      const created = await hadesTrainingApi.registerLocal({
        path: localPath.trim(),
        name: localName.trim(),
        text_field: localTextField.trim(),
        approved_file_read: true,
      });
      toast.success(`Dataset '${created.name}' geregistreerd zonder bronbestand te kopiëren.`);
      setLocalPath("");
      setLocalName("");
      invalidateCatalog();
      await datasetsQuery.refetch(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Lokale dataset registreren mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const upload = async () => {
    if (!uploadFile) return;
    setBusy("upload");
    try {
      const created = await hadesTrainingApi.upload(uploadFile, { text_field: localTextField.trim() });
      toast.success(`Upload '${created.name}' geregistreerd.`);
      setUploadFile(null);
      invalidateCatalog();
      await datasetsQuery.refetch(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Dataset uploaden mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const inspectHuggingFace = async () => {
    if (!hfDatasetId.trim()) return;
    setBusy("hf-inspect");
    setHfPreview(null);
    try {
      const inspected = await hadesTrainingApi.inspectHuggingFace({
        dataset_id: hfDatasetId.trim(),
        token: hfToken || undefined,
        approved_network: true,
      });
      setHfSplits(inspected.splits);
      const first = inspected.splits[0];
      if (!first) {
        setHfSelectedSplit("");
        toast.warning("Deze dataset rapporteert geen bruikbare config/split via de Dataset Viewer API.");
        return;
      }
      const key = splitKey(first);
      setHfSelectedSplit(key);
      const preview = await hadesTrainingApi.previewHuggingFace({
        dataset_id: hfDatasetId.trim(),
        config: first.config,
        split: first.split,
        token: hfToken || undefined,
        approved_network: true,
        rows: 20,
      });
      setHfPreview(preview);
      toast.success(`${inspected.splits.length} Hugging Face split(s) gevonden.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Hugging Face inspectie mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const previewSelectedSplit = async (value: string) => {
    setHfSelectedSplit(value);
    const selected = parseSplitKey(value);
    if (!selected || !hfDatasetId.trim()) return;
    setBusy("hf-preview");
    try {
      const preview = await hadesTrainingApi.previewHuggingFace({
        dataset_id: hfDatasetId.trim(),
        config: selected.config,
        split: selected.split,
        token: hfToken || undefined,
        approved_network: true,
        rows: 20,
      });
      setHfPreview(preview);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Split-preview laden mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const registerHuggingFace = async () => {
    const selected = parseSplitKey(hfSelectedSplit);
    if (!selected || !hfDatasetId.trim()) return;
    setBusy("hf-register");
    try {
      const created = await hadesTrainingApi.registerHuggingFace({
        dataset_id: hfDatasetId.trim(),
        config: selected.config,
        split: selected.split,
        token: hfToken || undefined,
        text_field: hfTextField.trim(),
        approved_network: true,
      });
      toast.success(`Hugging Face dataset '${created.name}' geregistreerd.`);
      invalidateCatalog();
      await datasetsQuery.refetch(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Hugging Face dataset registreren mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const deleteDataset = async (datasetId: string) => {
    setBusy(`delete:${datasetId}`);
    try {
      await hadesTrainingApi.deleteDataset(datasetId);
      setJobDatasetId((current) => (current === datasetId ? "" : current));
      invalidateCatalog();
      await datasetsQuery.refetch(true);
      toast.success("Datasetregistratie verwijderd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Dataset verwijderen mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const previewPlan = async () => {
    if (!baseModel.trim()) {
      toast.error("Vul eerst een basismodel in voor een ATME-planpreview.");
      return;
    }
    setBusy("plan");
    try {
      const response = await hadesTrainingApi.createPlan({
        dataset_id: jobDatasetId || undefined,
        base_model: baseModel.trim(),
        max_steps: maxSteps,
        learning_rate: learningRate,
        sequence_length: sequenceLength,
        batch_size: batchSize,
        gradient_accumulation_steps: gradientAccumulation,
        lora_r: loraR,
        lora_alpha: loraAlpha,
        lora_dropout: 0.05,
        load_in_4bit: loadIn4Bit || memoryStrategy === "gpu_resident_4bit",
        memory_strategy: memoryStrategy,
        activation_checkpointing: activationCheckpointing,
        stream_buffer_count: streamBufferCount,
        experimental_streaming_allowed: experimentalStreaming,
        approved_network: true,
      });
      setPlanPreview(response.selected);
      const warnings = [
        ...(response.selected?.warnings || []),
        ...response.candidates.filter((item) => !item.feasible).map((item) => `${item.strategy}: ${item.rejection_reason || "afgewezen"}`),
      ];
      setPlanWarnings(warnings.slice(0, 8));
      if (!response.selected?.feasible) {
        toast.warning(response.selected?.rejection_reason || "Geen haalbaar ATME-plan voor deze configuratie.");
      } else {
        toast.success(`Plan: ${strategyLabel(String(response.selected.strategy))}`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "ATME-plan maken mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const startTraining = async () => {
    if (!jobDatasetId || !baseModel.trim()) {
      toast.error("Kies een dataset en vul een trainbaar basismodel in.");
      return;
    }
    setBusy("train");
    try {
      const job = await hadesTrainingApi.startJob({
        dataset_id: jobDatasetId,
        base_model: baseModel.trim(),
        max_steps: maxSteps,
        learning_rate: learningRate,
        sequence_length: sequenceLength,
        batch_size: batchSize,
        gradient_accumulation_steps: gradientAccumulation,
        lora_r: loraR,
        lora_alpha: loraAlpha,
        lora_dropout: 0.05,
        load_in_4bit: loadIn4Bit || memoryStrategy === "gpu_resident_4bit",
        memory_strategy: memoryStrategy,
        activation_checkpointing: activationCheckpointing,
        stream_buffer_count: streamBufferCount,
        experimental_streaming_allowed: experimentalStreaming,
        hf_token: hfToken || undefined,
        approved_network: true,
        approved_subprocess: true,
      });
      invalidateHadesQuery("training-jobs");
      await jobsQuery.refetch(true);
      setPlanPreview(job.resolved_execution_plan || null);
      toast.success(`Trainingstaak ${job.id} gestart in een apart proces.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Training starten mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const cancelJob = async (jobId: string) => {
    setBusy(`cancel:${jobId}`);
    try {
      await hadesTrainingApi.cancelJob(jobId);
      await jobsQuery.refetch(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Training annuleren mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const openLog = async (jobId: string) => {
    setBusy(`log:${jobId}`);
    try {
      const result = await hadesTrainingApi.jobLog(jobId);
      setSelectedLog({ id: jobId, content: result.content });
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Trainingslog laden mislukt.");
    } finally {
      setBusy(null);
    }
  };

  const missingPackages = capabilities
    ? capabilities.required_packages.filter((name) => !capabilities.packages[name]?.available)
    : [];

  return (
    <section id="trainen" className="details-stack" aria-labelledby="training-title">
      <div>
        <h2 id="training-title">TRAINEN</h2>
        <p className="panel-copy">Datasetbeheer en geïsoleerde LoRA-finetuning. Bestaande Chat, LM Studio en agent-runtimes blijven buiten dit trainingsproces.</p>
      </div>

      <section className="stat-grid four">
        <StatCard label="Trainer" value={capabilities?.trainer_ready ? "Gereed" : "Optioneel"} note={capabilities?.trainer_ready ? "LoRA worker beschikbaar" : `${missingPackages.length} package(s) ontbreken`} icon={<Cpu />} />
        <StatCard label="Datasets" value={String(datasets.length)} note="Lokaal + Hugging Face" icon={<Database />} />
        <StatCard label="Actieve jobs" value={String(activeJobs.length)} note="Apart Python-proces" icon={<Play />} />
        <StatCard label="Uploadlimiet" value={capabilities ? formatBytes(capabilities.upload_limit_bytes) : "—"} note="Groot: lokaal pad gebruiken" icon={<Upload />} />
      </section>

      {!capabilities?.trainer_ready && capabilities ? (
        <div className="page-warning">
          <Cpu />
          <span>
            <strong>Trainingsstack is niet geïnstalleerd.</strong>
            <small>Ontbreekt: {missingPackages.join(", ") || "onbekend"}. Installeer bewust via <code>python -m pip install -r backend/requirements-training.txt</code>. Normaal HADES blijft zonder deze zware packages werken.</small>
          </span>
        </div>
      ) : null}

      <Panel title="Dataset toevoegen" actions={<Button variant="outline" onClick={() => void refreshAll()} disabled={loading}>{loading ? <Loader2 className="spin" /> : <RefreshCcw />}Vernieuwen</Button>}>
        <div className="form-grid two">
          <div className="form-stack">
            <div className="policy-row"><HardDrive /><span><strong>Grote lokale dataset · zero-copy</strong><small>JSONL, JSON, CSV, TSV of Parquet. HADES registreert het pad; het bronbestand wordt niet gedupliceerd.</small></span></div>
            <label><span>Bestandspad</span><Input value={localPath} onChange={(event) => setLocalPath(event.target.value)} placeholder="D:\\datasets\\train.jsonl" /></label>
            <label><span>Naam <small>optioneel</small></span><Input value={localName} onChange={(event) => setLocalName(event.target.value)} placeholder="Mijn trainingsset" /></label>
            <label><span>Tekstkolom <small>optioneel; auto-detect ondersteunt o.a. messages, instruction/output en prompt/completion</small></span><Input value={localTextField} onChange={(event) => setLocalTextField(event.target.value)} placeholder="text" /></label>
            <div className="button-row end"><Button onClick={() => void registerLocal()} disabled={!localPath.trim() || busy === "local"}>{busy === "local" ? <Loader2 className="spin" /> : <HardDrive />}Pad registreren</Button></div>
            <label>
              <span>Kleine dataset uploaden <small>max. 512 MB</small></span>
              <Input type="file" accept=".jsonl,.ndjson,.json,.csv,.tsv,.parquet" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} />
            </label>
            <div className="button-row end"><Button variant="outline" onClick={() => void upload()} disabled={!uploadFile || busy === "upload"}>{busy === "upload" ? <Loader2 className="spin" /> : <Upload />}Upload registreren</Button></div>
          </div>

          <div className="form-stack">
            <div className="policy-row"><Cloud /><span><strong>Hugging Face Dataset</strong><small>Inspectie gebruikt de Dataset Viewer API; training streamt de gekozen split. Token blijft alleen in deze sessie/in het trainerproces.</small></span></div>
            <label><span>Dataset-ID</span><Input value={hfDatasetId} onChange={(event) => setHfDatasetId(event.target.value)} placeholder="organisatie/dataset" /></label>
            <label><span>HF token <small>alleen nodig voor gated/private bronnen</small></span><Input type="password" autoComplete="off" value={hfToken} onChange={(event) => setHfToken(event.target.value)} placeholder="hf_…" /></label>
            <div className="button-row end"><Button variant="outline" onClick={() => void inspectHuggingFace()} disabled={!hfDatasetId.trim() || busy === "hf-inspect"}>{busy === "hf-inspect" ? <Loader2 className="spin" /> : <Cloud />}Splits inspecteren</Button></div>
            {hfSplits.length ? (
              <label>
                <span>Config / split</span>
                <select value={hfSelectedSplit} onChange={(event) => void previewSelectedSplit(event.target.value)}>
                  {hfSplits.map((item) => <option key={splitKey(item)} value={splitKey(item)}>{item.config} / {item.split}</option>)}
                </select>
              </label>
            ) : null}
            {hfPreview ? <small>Preview: {hfPreview.columns.join(", ") || "geen kolommen"}{hfPreview.row_count !== null ? ` · ${hfPreview.row_count.toLocaleString("nl-NL")} rijen` : ""}</small> : null}
            <label><span>Tekstkolom <small>optioneel</small></span><Input value={hfTextField} onChange={(event) => setHfTextField(event.target.value)} placeholder="text" /></label>
            <div className="button-row end"><Button onClick={() => void registerHuggingFace()} disabled={!hfSelectedSplit || busy === "hf-register"}>{busy === "hf-register" ? <Loader2 className="spin" /> : <Database />}HF dataset registreren</Button></div>
          </div>
        </div>
      </Panel>

      <Panel title="Geregistreerde datasets" actions={<StatusBadge tone={datasets.length ? "success" : "neutral"}>{datasets.length} bron(nen)</StatusBadge>}>
        <div className="model-list">
          {datasets.map((dataset) => (
            <article className="model-row functional-model-row" key={dataset.id}>
              <span className="radio-dot"><i /></span>
              <div className="model-name"><strong>{dataset.name}</strong><small>{dataset.source_type === "huggingface" ? String(dataset.source.dataset_id || "Hugging Face") : dataset.path || "Managed upload"}</small></div>
              <span><small>Formaat</small><strong>{dataset.format}</strong></span>
              <span><small>Omvang</small><strong>{formatBytes(dataset.size_bytes)}</strong></span>
              <div className="model-status"><StatusBadge tone="success">{dataset.status}</StatusBadge><StatusBadge>{dataset.row_count !== null ? `${dataset.row_count.toLocaleString("nl-NL")} rijen` : "streaming"}</StatusBadge></div>
              <div className="model-actions"><Button variant="outline" size="sm" onClick={() => void deleteDataset(dataset.id)} disabled={busy === `delete:${dataset.id}`} aria-label={`${dataset.name} verwijderen`}>{busy === `delete:${dataset.id}` ? <Loader2 className="spin" /> : <Trash2 />}</Button></div>
            </article>
          ))}
          {!datasets.length && !loading ? <div className="table-empty">Nog geen trainingsdatasets geregistreerd.</div> : null}
        </div>
      </Panel>

      <Panel title="Nieuwe LoRA-training" actions={<StatusBadge tone={capabilities?.trainer_ready ? "success" : "warning"}>{capabilities?.trainer_ready ? "Worker gereed" : "Dependencies nodig"}</StatusBadge>}>
        <div className="form-stack">
          <div className="page-warning"><Cpu /><span><strong>Basismodel is niet hetzelfde als het geladen LM Studio-model.</strong><small>Gebruik een Hugging Face model-ID (bijv. organisatie/model) of een lokale Transformers-modelmap. Een los GGUF-bestand wordt bewust geweigerd.</small></span></div>
          <div className="form-grid two">
            <label><span>Dataset</span><select value={jobDatasetId} onChange={(event) => setJobDatasetId(event.target.value)}><option value="">Kies dataset</option>{datasets.map((dataset) => <option value={dataset.id} key={dataset.id}>{dataset.name}</option>)}</select></label>
            <label><span>Basismodel</span><Input value={baseModel} onChange={(event) => setBaseModel(event.target.value)} placeholder="Qwen/Qwen3-0.6B of D:\\models\\hf-model" /></label>
            <label><span>Max. stappen</span><Input type="number" min={1} value={maxSteps} onChange={(event) => setMaxSteps(Math.max(1, Number(event.target.value) || 1))} /></label>
            <label><span>Sequence length</span><Input type="number" min={64} value={sequenceLength} onChange={(event) => setSequenceLength(Math.max(64, Number(event.target.value) || 64))} /></label>
            <label><span>Learning rate</span><Input type="number" min={0.00000001} step={0.00001} value={learningRate} onChange={(event) => setLearningRate(Number(event.target.value) || 0.0002)} /></label>
            <label><span>Batch size</span><Input type="number" min={1} value={batchSize} onChange={(event) => setBatchSize(Math.max(1, Number(event.target.value) || 1))} /></label>
            <label><span>Gradient accumulation</span><Input type="number" min={1} value={gradientAccumulation} onChange={(event) => setGradientAccumulation(Math.max(1, Number(event.target.value) || 1))} /></label>
            <label><span>LoRA rank (r)</span><Input type="number" min={1} value={loraR} onChange={(event) => setLoraR(Math.max(1, Number(event.target.value) || 1))} /></label>
            <label><span>LoRA alpha</span><Input type="number" min={1} value={loraAlpha} onChange={(event) => setLoraAlpha(Math.max(1, Number(event.target.value) || 1))} /></label>
            <label className="policy-row"><Cpu /><span><strong>4-bit QLoRA</strong><small>Legacy schakelaar; voorkeur via geheugenstrategie hieronder.</small></span><Switch checked={loadIn4Bit || memoryStrategy === "gpu_resident_4bit"} onCheckedChange={(value) => { setLoadIn4Bit(value); if (value) setMemoryStrategy("gpu_resident_4bit"); }} /></label>
          </div>

          <div className="form-stack" style={{ marginTop: 12 }}>
            <strong>Geheugenstrategie (ATME)</strong>
            <small>HADES kiest de snelste gevalideerde strategie die veilig op deze machine past. Streaming is nooit sneller dan resident wanneer resident past.</small>
            <div className="form-grid two">
              <label className="policy-row">
                <input
                  type="radio"
                  name="atme-strategy"
                  checked={simpleStrategy === "auto"}
                  onChange={() => { setMemoryStrategy("auto"); setLoadIn4Bit(false); }}
                />
                <span><strong>Auto — aanbevolen</strong><small>Snelste haalbare strategie met veiligheidsmarge.</small></span>
              </label>
              <label className="policy-row">
                <input
                  type="radio"
                  name="atme-strategy"
                  checked={simpleStrategy === "gpu_only"}
                  onChange={() => { setMemoryStrategy("gpu_resident"); setLoadIn4Bit(false); }}
                />
                <span><strong>GPU only</strong><small>Volledige resident LoRA-training.</small></span>
              </label>
              <label className="policy-row">
                <input
                  type="radio"
                  name="atme-strategy"
                  checked={simpleStrategy === "save_vram"}
                  onChange={() => { setMemoryStrategy("gpu_resident_4bit"); setLoadIn4Bit(true); }}
                />
                <span><strong>Save VRAM</strong><small>4-bit / QLoRA wanneer bitsandbytes + CUDA beschikbaar zijn.</small></span>
              </label>
              <label className="policy-row">
                <input
                  type="radio"
                  name="atme-strategy"
                  checked={simpleStrategy === "streaming"}
                  onChange={() => { setMemoryStrategy("ram_layer_streaming"); setLoadIn4Bit(false); setExperimentalStreaming(true); }}
                />
                <span><strong>Experimental layer streaming</strong><small>RAM-laagstreaming voor allowlisted Llama/Qwen/Mistral-achtige modellen.</small></span>
              </label>
            </div>
            <label className="policy-row">
              <Switch checked={experimentalStreaming} onCheckedChange={setExperimentalStreaming} />
              <span><strong>Experimentele streaming toestaan</strong><small>Vereist voor NVMe-streaming en low-confidence plannen.</small></span>
            </label>
            <label className="policy-row">
              <Switch checked={showAdvancedAtme} onCheckedChange={setShowAdvancedAtme} />
              <span><strong>Geavanceerde ATME-opties</strong></span>
            </label>
            {showAdvancedAtme ? (
              <div className="form-grid two">
                <label>
                  <span>Activation checkpointing</span>
                  <select value={activationCheckpointing} onChange={(event) => setActivationCheckpointing(event.target.value as "auto" | "enabled" | "disabled")}>
                    <option value="auto">auto</option>
                    <option value="enabled">enabled</option>
                    <option value="disabled">disabled</option>
                  </select>
                </label>
                <label>
                  <span>Stream buffers</span>
                  <select
                    value={String(streamBufferCount)}
                    onChange={(event) => {
                      const value = event.target.value;
                      setStreamBufferCount(value === "auto" ? "auto" : Math.max(1, Number(value) || 1));
                    }}
                  >
                    <option value="auto">auto</option>
                    <option value="1">1 (correctness baseline)</option>
                    <option value="2">2 (double buffer)</option>
                  </select>
                </label>
                <label>
                  <span>Expliciete strategie</span>
                  <select value={memoryStrategy} onChange={(event) => setMemoryStrategy(event.target.value as MemoryStrategy)}>
                    <option value="auto">auto</option>
                    <option value="gpu_resident">gpu_resident</option>
                    <option value="gpu_resident_4bit">gpu_resident_4bit</option>
                    <option value="cpu_offload">cpu_offload</option>
                    <option value="ram_layer_streaming">ram_layer_streaming</option>
                    <option value="nvme_layer_streaming" disabled={!experimentalStreaming}>nvme_layer_streaming</option>
                  </select>
                </label>
              </div>
            ) : null}
            {planPreview ? (
              <div className="page-warning">
                <Cpu />
                <span>
                  <strong>Uitvoeringsplan · {strategyLabel(String(planPreview.strategy))}</strong>
                  <small>
                    VRAM≈{formatBytes(planPreview.estimated_vram_peak_bytes)} · reserve {formatBytes(planPreview.safety_margin_vram_bytes)} · RAM≈{formatBytes(planPreview.estimated_ram_peak_bytes)} · bottleneck {planPreview.expected_bottleneck || "unknown"} · confidence {planPreview.confidence || "?"}
                    {planPreview.selection_reason ? ` · ${planPreview.selection_reason}` : ""}
                  </small>
                  {planWarnings.length ? <small>{planWarnings.join(" · ")}</small> : null}
                </span>
              </div>
            ) : null}
          </div>

          <div className="button-row end">
            <Button variant="outline" onClick={() => void previewPlan()} disabled={!baseModel.trim() || busy === "plan"}>{busy === "plan" ? <Loader2 className="spin" /> : <Cpu />}Plan preview</Button>
            <Button onClick={() => void startTraining()} disabled={!capabilities?.trainer_ready || !jobDatasetId || !baseModel.trim() || busy === "train"}>{busy === "train" ? <Loader2 className="spin" /> : <Play />}Training starten</Button>
          </div>
        </div>
      </Panel>

      <Panel title="Trainingstaken" actions={<StatusBadge tone={activeJobs.length ? "info" : "neutral"}>{activeJobs.length} actief</StatusBadge>}>
        <div className="model-list">
          {jobs.map((job) => (
            <article className="model-row functional-model-row" key={job.id}>
              <span className="radio-dot">{job.status === "running" ? <i /> : null}</span>
              <div className="model-name"><strong>{job.dataset_name || job.dataset_id}</strong><small>{job.base_model}{job.resolved_execution_plan?.strategy ? ` · ${job.resolved_execution_plan.strategy}` : ""}</small></div>
              <span><small>Voortgang</small><strong>{Math.round(Math.max(0, Math.min(1, job.progress || 0)) * 100)}% · {job.step}/{job.max_steps}</strong></span>
              <div className="model-status"><StatusBadge tone={jobTone(job.status)}>{job.status}</StatusBadge>{job.observed_bottleneck ? <StatusBadge>{job.observed_bottleneck}</StatusBadge> : null}{job.error ? <StatusBadge tone="danger">fout</StatusBadge> : null}</div>
              <div className="model-actions">
                <Button variant="outline" size="sm" onClick={() => void openLog(job.id)} disabled={busy === `log:${job.id}`}>{busy === `log:${job.id}` ? <Loader2 className="spin" /> : "Log"}</Button>
                {ACTIVE_JOB_STATUSES.has(job.status) ? <Button variant="outline" size="sm" onClick={() => void cancelJob(job.id)} disabled={busy === `cancel:${job.id}`}><Square />Stop</Button> : null}
              </div>
            </article>
          ))}
          {!jobs.length && !loading ? <div className="table-empty">Nog geen trainingstaken.</div> : null}
        </div>
      </Panel>

      {selectedLog ? (
        <Panel title={`Trainingslog · ${selectedLog.id}`} actions={<Button variant="outline" size="sm" onClick={() => setSelectedLog(null)}>Sluiten</Button>}>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 420, overflow: "auto" }}>{selectedLog.content || "Nog geen logoutput."}</pre>
        </Panel>
      ) : null}
    </section>
  );
}
