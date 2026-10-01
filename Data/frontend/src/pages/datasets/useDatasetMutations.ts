/**
 * Dataset mutations for canonical `/datasets` workspace.
 * Truthful MutationOutcome toasts — no placebo success messages.
 */

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { useAppToast } from "../../state/useAppToast";
import type { DatasetJob, DatasetRecord, DatasetVersion } from "../../types/api";
import { isCompletedJob } from "./datasetActivity";
import {
  emptyCreateForm,
  emptyHfImportForm,
  emptyLocalImportForm,
  emptyUploadForm,
  type CreateDatasetForm,
  type HfImportForm,
  type LocalImportForm,
  type UploadDatasetForm,
} from "./datasetForms";
import {
  blocked,
  completed,
  failed,
  mutationToastKind,
  mutationToastMessage,
  noop,
  outcomeFromBulk,
  startedJob,
  type MutationOutcome,
} from "./mutationOutcomes";
import {
  canDownloadExport,
  exportDownloading,
  exportEnqueued,
  exportFailed,
  exportReady,
  exportReset,
  exportRunning,
  initialExportState,
  type ExportState,
} from "./exportState";
import { addTag, normalizeTag, removeTag, resolveTagsToSave } from "./tagEdit";
import { DS_BULK_MAX } from "./constants";
import { triggerBlobDownload } from "./viewModels";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export type ModalKind =
  | "create"
  | "import"
  | "hf"
  | "activity"
  | "health"
  | "delete"
  | null;

export function useDatasetMutations(opts: {
  activeId: string | null;
  selectedIds: Set<string>;
  selectedVersionId: string | null;
  selectedVersion: DatasetVersion | null;
  activeRecord: DatasetRecord | null;
  tagChips: string[];
  setTagChips: (tags: string[]) => void;
  tagInput: string;
  setTagInput: (v: string) => void;
  editDisplayName: string;
  editCategory: string;
  setSemanticEditing: (v: boolean) => void;
  setActiveId: (id: string | null) => void;
  setSelectedIds: React.Dispatch<React.SetStateAction<Set<string>>>;
  setMenuFor: (id: string | null) => void;
  setPreferredJobId: (id: string | null) => void;
  loadDatasets: (opts?: { quiet?: boolean; offset?: number }) => Promise<void>;
  loadOverview: (opts?: { quiet?: boolean }) => Promise<void>;
  loadJobs: () => Promise<DatasetJob[]>;
  bumpDetail: () => void;
  jobs: DatasetJob[];
}) {
  const toast = useAppToast();
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<ModalKind>(null);
  const [createForm, setCreateForm] = useState<CreateDatasetForm>(emptyCreateForm);
  const [uploadForm, setUploadForm] = useState<UploadDatasetForm>(emptyUploadForm);
  const [localImportForm, setLocalImportForm] = useState<LocalImportForm>(emptyLocalImportForm);
  const [hfImportForm, setHfImportForm] = useState<HfImportForm>(emptyHfImportForm);
  const [exportState, setExportState] = useState<ExportState>(initialExportState);
  const exportWatchRef = useRef<string | null>(null);
  const prevExportJobsRef = useRef<Map<string, DatasetJob>>(new Map());

  const resetCreateForm = () => setCreateForm(emptyCreateForm());
  const resetUploadForm = () => setUploadForm(emptyUploadForm());
  const resetLocalImportForm = () => setLocalImportForm(emptyLocalImportForm());
  const resetHfImportForm = () => setHfImportForm(emptyHfImportForm());

  function closeModal() {
    setModal(null);
    resetCreateForm();
    resetUploadForm();
    resetLocalImportForm();
    resetHfImportForm();
  }

  function applyOutcome(outcome: MutationOutcome) {
    const kind = mutationToastKind(outcome);
    const msg = mutationToastMessage(outcome);
    if (!msg || kind === "none") return;
    // Single-string toast bus — severity encoded in message phrasing only.
    toast(msg);
  }

  async function runMutation(fn: () => Promise<MutationOutcome>): Promise<MutationOutcome | null> {
    if (busy) return null;
    setBusy(true);
    try {
      const outcome = await fn();
      applyOutcome(outcome);
      return outcome;
    } catch (err) {
      const outcome = failed(errMsg(err, "Actie mislukt"));
      applyOutcome(outcome);
      return outcome;
    } finally {
      setBusy(false);
    }
  }

  // Watch export jobs → READY when completed.
  useEffect(() => {
    const prev = prevExportJobsRef.current;
    for (const job of opts.jobs) {
      if (job.jobType !== "export") continue;
      const old = prev.get(job.jobId);
      if (old && old.status === job.status) continue;
      if (isCompletedJob(job)) {
        const exportVersionId =
          typeof job.result?.versionId === "string" ? job.result.versionId : null;
        const datasetId = job.datasetId;
        if (exportVersionId && datasetId) {
          setExportState((s) =>
            exportReady(s.jobId === job.jobId || exportWatchRef.current === job.jobId ? s : {
              ...s,
              datasetId,
              jobId: job.jobId,
            }, { versionId: exportVersionId, jobId: job.jobId }),
          );
          if (exportWatchRef.current === job.jobId) {
            toast("Export klaar — download beschikbaar");
          }
        }
      } else if (
        (job.status === "running" || job.status === "queued") &&
        exportWatchRef.current === job.jobId
      ) {
        setExportState((s) => (s.jobId === job.jobId ? exportRunning(s) : s));
      }
    }
    prevExportJobsRef.current = new Map(opts.jobs.map((j) => [j.jobId, j]));
  }, [opts.jobs, toast]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onCreate() {
    if (!createForm.name.trim()) {
      applyOutcome(blocked("Naam is verplicht"));
      return;
    }
    await runMutation(async () => {
      await api.createDataset({
        name: createForm.name.trim(),
        description: createForm.description,
        license: createForm.license.trim() || null,
      });
      closeModal();
      await opts.loadDatasets({ offset: 0 });
      await opts.loadOverview({ quiet: true });
      return completed("Dataset aangemaakt");
    });
  }

  async function onUpload() {
    if (!uploadForm.file) {
      applyOutcome(blocked("Kies eerst een bestand"));
      return;
    }
    await runMutation(async () => {
      const form = new FormData();
      form.append("file", uploadForm.file!);
      if (uploadForm.name.trim()) form.append("name", uploadForm.name.trim());
      if (uploadForm.description) form.append("description", uploadForm.description);
      form.append("materialize", "true");
      const res = await api.uploadDataset(form);
      opts.setPreferredJobId(res.job.jobId);
      closeModal();
      await opts.loadDatasets({ quiet: true, offset: 0 });
      await opts.loadJobs();
      await opts.loadOverview({ quiet: true });
      return startedJob("Upload in wachtrij", res.job.jobId);
    });
  }

  async function onImportLocal() {
    if (!localImportForm.path.trim()) {
      applyOutcome(blocked("Lokaal pad is verplicht"));
      return;
    }
    await runMutation(async () => {
      try {
        await api.inspectDatasetPath(localImportForm.path.trim());
      } catch (err) {
        return failed(errMsg(err, "Padinspectie mislukt"));
      }
      const res = await api.importDatasetLocal({
        path: localImportForm.path.trim(),
        name: localImportForm.name.trim() || undefined,
        description: localImportForm.description || undefined,
        materialize: true,
      });
      opts.setPreferredJobId(res.job.jobId);
      closeModal();
      await opts.loadJobs();
      await opts.loadDatasets({ quiet: true, offset: 0 });
      await opts.loadOverview({ quiet: true });
      return startedJob("Lokale import in wachtrij", res.job.jobId);
    });
  }

  async function onImportHf() {
    if (!hfImportForm.repositoryId.trim()) {
      applyOutcome(blocked("Repository id is verplicht"));
      return;
    }
    await runMutation(async () => {
      const token = hfImportForm.token.trim() || null;
      const res = await api.importDatasetHuggingFace({
        repositoryId: hfImportForm.repositoryId.trim(),
        filename: hfImportForm.filename.trim() || null,
        revision: hfImportForm.revision.trim() || "main",
        name: hfImportForm.name.trim() || undefined,
        description: hfImportForm.description || undefined,
        token,
        materialize: true,
      });
      opts.setPreferredJobId(res.job.jobId);
      closeModal();
      await opts.loadJobs();
      await opts.loadDatasets({ quiet: true, offset: 0 });
      await opts.loadOverview({ quiet: true });
      return startedJob("Hugging Face import in wachtrij", res.job.jobId);
    });
  }

  async function onCancelDatasetJob(jobId: string) {
    await runMutation(async () => {
      await api.cancelDatasetJob(jobId);
      await opts.loadJobs();
      return { kind: "cancelled" as const, message: "Annulering aangevraagd" };
    });
  }

  async function onRetryDatasetJob(jobId: string) {
    await runMutation(async () => {
      const res = await api.retryDatasetJob(jobId, true);
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Job opnieuw in wachtrij", res.job.jobId);
    });
  }

  async function onDelete(id: string) {
    await runMutation(async () => {
      await api.deleteDataset(id);
      setModal(null);
      opts.setMenuFor(null);
      opts.setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      if (opts.activeId === id) opts.setActiveId(null);
      setExportState((s) => (s.datasetId === id ? exportReset() : s));
      await opts.loadDatasets({ offset: 0 });
      await opts.loadOverview({ quiet: true });
      return completed("Dataset verwijderd");
    });
  }

  async function onIndex(id: string) {
    await runMutation(async () => {
      const detail = await api.getDataset(id);
      const version =
        detail.versions.find((v) => v.status === "ready") ?? detail.versions[0] ?? null;
      if (!version) {
        return blocked("Geen versie beschikbaar om te indexeren");
      }
      const res = await api.indexDatasetVersion(id, version.versionId);
      opts.setMenuFor(null);
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Index in wachtrij", res.job.jobId);
    });
  }

  async function onBulkProcess() {
    const ids = [...opts.selectedIds].slice(0, DS_BULK_MAX);
    if (ids.length === 0) {
      applyOutcome(blocked("Selecteer datasets om te verwerken — wachtrij wordt niet leeggedraineerd"));
      return;
    }
    await runMutation(async () => {
      const res = await api.bulkMaterializeDatasets({ datasetIds: ids });
      if (res.results.find((r) => r.ok && r.jobId)) {
        opts.setPreferredJobId(res.results.find((r) => r.ok && r.jobId)!.jobId!);
      }
      await opts.loadJobs();
      await opts.loadDatasets({ quiet: true });
      return outcomeFromBulk({
        succeeded: res.succeeded,
        failed: res.failed,
        message: `Verwerken: ${res.succeeded} ok, ${res.failed} mislukt`,
      });
    });
  }

  async function onBulkIndex() {
    const ids =
      opts.selectedIds.size > 0
        ? [...opts.selectedIds].slice(0, DS_BULK_MAX)
        : opts.activeId
          ? [opts.activeId]
          : [];
    if (ids.length === 0) {
      applyOutcome(blocked("Selecteer datasets of een actieve rij om te indexeren"));
      return;
    }
    await runMutation(async () => {
      const res = await api.bulkIndexDatasets({ datasetIds: ids });
      if (res.results.find((r) => r.ok && r.jobId)) {
        opts.setPreferredJobId(res.results.find((r) => r.ok && r.jobId)!.jobId!);
      }
      await opts.loadJobs();
      return outcomeFromBulk({
        succeeded: res.succeeded,
        failed: res.failed,
        message: `Indexeren: ${res.succeeded} ok, ${res.failed} mislukt`,
      });
    });
  }

  async function onEnqueueExport(id: string) {
    await runMutation(async () => {
      const detail = await api.getDataset(id);
      const ready =
        detail.versions.find((v) => v.status === "ready" && (v.kind === "export" || v.kind === "materialized")) ??
        detail.versions.find((v) => v.status === "ready") ??
        detail.versions[0] ??
        null;
      if (!ready) return blocked("Geen exporteerbare versie");
      if (ready.kind === "export") {
        setExportState(
          exportReady(initialExportState(), {
            versionId: ready.versionId,
            jobId: undefined,
          }),
        );
        setExportState((s) => ({ ...s, datasetId: id, phase: "READY", versionId: ready.versionId }));
        return completed("Export klaar — download beschikbaar");
      }
      const job = await api.exportDatasetVersion(id, ready.versionId);
      exportWatchRef.current = job.job.jobId;
      setExportState(exportEnqueued(initialExportState(), { datasetId: id, jobId: job.job.jobId }));
      opts.setPreferredJobId(job.job.jobId);
      await opts.loadJobs();
      return startedJob("Export job gestart", job.job.jobId);
    });
  }

  async function onDownloadExport() {
    if (!canDownloadExport(exportState) || !exportState.datasetId || !exportState.versionId) {
      // Fallback: try enqueue path for active selection
      if (opts.activeId) {
        await onEnqueueExport(opts.activeId);
        return;
      }
      applyOutcome(blocked("Geen exportartifact beschikbaar"));
      return;
    }
    await runMutation(async () => {
      setExportState((s) => exportDownloading(s));
      try {
        const blob = await api.downloadDatasetExport(exportState.datasetId!, exportState.versionId!);
        triggerBlobDownload(blob, `export-${exportState.versionId}.jsonl`);
        return completed("Download gestart");
      } catch (err) {
        setExportState((s) => exportFailed(s, errMsg(err, "Download mislukt")));
        throw err;
      }
    });
  }

  /** Combined: enqueue if needed, download only when blob starts. */
  async function onExportDownload(id: string) {
    await runMutation(async () => {
      const detail = await api.getDataset(id);
      const exportVer = detail.versions.find((v) => v.status === "ready" && v.kind === "export");
      if (exportVer) {
        setExportState({
          phase: "DOWNLOADING",
          datasetId: id,
          versionId: exportVer.versionId,
          jobId: null,
        });
        const blob = await api.downloadDatasetExport(id, exportVer.versionId);
        triggerBlobDownload(blob, `export-${exportVer.versionId}.jsonl`);
        setExportState(
          exportReady({ phase: "READY", datasetId: id, versionId: exportVer.versionId, jobId: null }, {
            versionId: exportVer.versionId,
          }),
        );
        return completed("Download gestart");
      }
      const ready =
        detail.versions.find((v) => v.status === "ready") ?? detail.versions[0] ?? null;
      if (!ready) return blocked("Geen exporteerbare versie");
      const job = await api.exportDatasetVersion(id, ready.versionId);
      exportWatchRef.current = job.job.jobId;
      setExportState(exportEnqueued(initialExportState(), { datasetId: id, jobId: job.job.jobId }));
      opts.setPreferredJobId(job.job.jobId);
      await opts.loadJobs();
      return startedJob("Export job gestart", job.job.jobId);
    });
  }

  async function onSaveTags() {
    if (!opts.activeId) return;
    const resolved = resolveTagsToSave(
      // Prefer chips; if tagInput pending, merge
      [...opts.tagChips, ...(opts.tagInput.trim() ? [opts.tagInput] : [])].join(","),
      opts.tagChips,
    );
    if (resolved.kind === "blocked") {
      applyOutcome(blocked(resolved.message));
      return;
    }
    if (resolved.kind === "noop") {
      applyOutcome(noop(resolved.message));
      return;
    }
    await runMutation(async () => {
      await api.patchDatasetSemantic(opts.activeId!, { tags: resolved.tags });
      opts.setTagChips(resolved.tags);
      opts.setTagInput("");
      await opts.loadDatasets({ quiet: true });
      opts.bumpDetail();
      return completed("Tags opgeslagen");
    });
  }

  function onAddTagChip() {
    const next = normalizeTag(opts.tagInput);
    if (!next) return;
    opts.setTagChips(addTag(opts.tagChips, next));
    opts.setTagInput("");
  }

  function onRemoveTagChip(tag: string) {
    opts.setTagChips(removeTag(opts.tagChips, tag));
  }

  async function onSemanticAnalyze(id: string, sync = false) {
    await runMutation(async () => {
      const res = await api.analyzeDatasetSemantic(id, {
        versionId: opts.selectedVersionId,
        enqueue: !sync,
        syncArtifacts: sync,
      });
      if (res.job?.jobId) {
        opts.setPreferredJobId(res.job.jobId);
        await opts.loadJobs();
        await opts.loadDatasets({ quiet: true });
        return startedJob("Semantic analyse in wachtrij", res.job.jobId);
      }
      opts.bumpDetail();
      await opts.loadDatasets({ quiet: true });
      return completed("Semantische analyse voltooid");
    });
  }

  async function onSaveSemantic() {
    if (!opts.activeId) return;
    await runMutation(async () => {
      await api.patchDatasetSemantic(opts.activeId!, {
        displayName: opts.editDisplayName.trim() || undefined,
        primaryCategory: opts.editCategory || undefined,
        tags: opts.tagChips,
        versionId: opts.selectedVersionId,
      });
      opts.setSemanticEditing(false);
      opts.bumpDetail();
      await opts.loadDatasets({ quiet: true });
      return completed("Metagegevens opgeslagen");
    });
  }

  async function onValidate() {
    if (!opts.activeId || !opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.validateDatasetVersion(opts.activeId!, opts.selectedVersionId!);
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Validatie in wachtrij gezet", res.job.jobId);
    });
  }

  async function onDedupe() {
    if (!opts.activeId || !opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.dedupeDatasetVersion(opts.activeId!, opts.selectedVersionId!);
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Deduplicatie in wachtrij gezet", res.job.jobId);
    });
  }

  async function onTransform() {
    if (!opts.activeId || !opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.transformDatasetVersion(opts.activeId!, opts.selectedVersionId!, []);
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Transform in wachtrij gezet", res.job.jobId);
    });
  }

  async function onSplit() {
    if (!opts.activeId || !opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.splitDatasetVersion(opts.activeId!, opts.selectedVersionId!, {
        seed: 42,
        trainRatio: 0.8,
        valRatio: 0.1,
        testRatio: 0.1,
      });
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Split in wachtrij gezet", res.job.jobId);
    });
  }

  async function onTokenize() {
    if (!opts.activeId || !opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.tokenizeStatsDatasetVersion(opts.activeId!, opts.selectedVersionId!);
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Tokenize stats in wachtrij gezet", res.job.jobId);
    });
  }

  async function onScanPii() {
    if (!opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.scanDatasetPii(opts.selectedVersionId!);
      const findings = res.pii;
      const count =
        typeof findings?.findingCount === "number"
          ? findings.findingCount
          : Array.isArray(findings?.findings)
            ? findings.findings.length
            : null;
      opts.bumpDetail();
      return completed(
        count == null
          ? "PII-scan voltooid (samenvatting beschikbaar)"
          : `PII-scan: ${count} bevinding(en) — gevoelige matches niet in UI getoond`,
      );
    });
  }

  async function onContaminationScan() {
    if (!opts.activeId || !opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.contaminationScanDatasetVersion(opts.activeId!, opts.selectedVersionId!, {
        sealedCases: [],
      });
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Contaminatiescan in wachtrij gezet", res.job.jobId);
    });
  }

  async function onMaterialize() {
    if (!opts.activeId) {
      applyOutcome(blocked("Selecteer eerst een dataset"));
      return;
    }
    await runMutation(async () => {
      const res = await api.materializeDataset(opts.activeId!);
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      return startedJob("Materialisatie in wachtrij", res.job.jobId);
    });
  }

  async function onLearn(optsLearn?: { rebuild?: boolean }) {
    if (!opts.activeId) {
      applyOutcome(blocked("Selecteer eerst een dataset"));
      return;
    }
    const ds = opts.activeRecord;
    const brain = ds?.brainStatus ?? ds?.brain?.brainStatus;
    if (!optsLearn?.rebuild && brain === "learned") {
      applyOutcome(blocked("Al geleerd — gebruik rebuild om opnieuw te leren"));
      return;
    }
    if (brain === "indexing" || brain === "queued") {
      applyOutcome(blocked("Kennis leren is al bezig"));
      return;
    }
    if (ds?.sourceMissing || ds?.brain?.sourceMissing) {
      applyOutcome(blocked("Bronbestand ontbreekt op schijf"));
      return;
    }
    await runMutation(async () => {
      const res = await api.learnDataset(opts.activeId!, {
        versionId: opts.selectedVersionId,
        rebuild: optsLearn?.rebuild ?? false,
        offlineOnly: true,
      });
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      await opts.loadDatasets({ quiet: true });
      return startedJob(
        optsLearn?.rebuild ? "Opnieuw leren in wachtrij" : "Kennis leren in wachtrij",
        res.job.jobId,
      );
    });
  }

  async function onDuplicate() {
    if (!opts.activeId) {
      applyOutcome(blocked("Selecteer eerst een dataset"));
      return;
    }
    await runMutation(async () => {
      const res = await api.duplicateDataset(opts.activeId!, {
        versionId: opts.selectedVersionId,
      });
      opts.setPreferredJobId(res.job.jobId);
      await opts.loadJobs();
      await opts.loadDatasets({ quiet: true });
      await opts.loadOverview({ quiet: true });
      return startedJob("Duplicatie in wachtrij", res.job.jobId);
    });
  }

  async function onRefreshLibrary() {
    await runMutation(async () => {
      const res = await api.refreshDatasetLibrary();
      await opts.loadDatasets({ quiet: true, offset: 0 });
      await opts.loadOverview({ quiet: true });
      return completed(
        `Scan klaar: ${res.created} nieuw, ${res.updated} bijgewerkt, ${res.discovered} bronnen`,
      );
    });
  }

  async function onPreflight() {
    if (!opts.activeId || !opts.selectedVersionId) {
      applyOutcome(blocked("Selecteer eerst een datasetversie"));
      return;
    }
    await runMutation(async () => {
      const res = await api.offlineBrainPreflight({
        datasetId: opts.activeId!,
        versionId: opts.selectedVersionId!,
        offlineOnly: true,
      });
      const ok = Boolean((res.preflight as { ok?: boolean })?.ok);
      return ok
        ? completed("Preflight OK — klaar voor Brain index")
        : blocked(
            `Preflight geblokkeerd: ${JSON.stringify((res.preflight as { blockers?: unknown })?.blockers ?? res.preflight).slice(0, 200)}`,
          );
    });
  }

  const canProcess = opts.selectedIds.size > 0;

  return {
    busy,
    modal,
    setModal,
    closeModal,
    createForm,
    setCreateForm,
    uploadForm,
    setUploadForm,
    localImportForm,
    setLocalImportForm,
    hfImportForm,
    setHfImportForm,
    exportState,
    setExportState,
    canProcess,
    onCreate,
    onUpload,
    onImportLocal,
    onImportHf,
    onCancelDatasetJob,
    onRetryDatasetJob,
    onDelete,
    onIndex,
    onBulkProcess,
    onBulkIndex,
    onExportDownload,
    onDownloadExport,
    onEnqueueExport,
    onSaveTags,
    onAddTagChip,
    onRemoveTagChip,
    onSemanticAnalyze,
    onSaveSemantic,
    onValidate,
    onDedupe,
    onTransform,
    onSplit,
    onTokenize,
    onScanPii,
    onContaminationScan,
    onMaterialize,
    onLearn,
    onDuplicate,
    onRefreshLibrary,
    onPreflight,
  };
}

export type DatasetMutations = ReturnType<typeof useDatasetMutations>;
