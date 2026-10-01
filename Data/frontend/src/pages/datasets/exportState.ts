/**
 * Export download state machine for Datasets workspace.
 * Toast "Download gestart" ONLY when blob download actually starts.
 */

export type ExportPhase =
  | "NO_EXPORT"
  | "ENQUEUED"
  | "RUNNING"
  | "READY"
  | "DOWNLOADING"
  | "FAILED";

export type ExportState = {
  phase: ExportPhase;
  datasetId: string | null;
  versionId: string | null;
  jobId: string | null;
  error?: string | null;
};

export function initialExportState(): ExportState {
  return {
    phase: "NO_EXPORT",
    datasetId: null,
    versionId: null,
    jobId: null,
    error: null,
  };
}

export function exportEnqueued(
  prev: ExportState,
  opts: { datasetId: string; jobId: string; versionId?: string | null },
): ExportState {
  return {
    ...prev,
    phase: "ENQUEUED",
    datasetId: opts.datasetId,
    jobId: opts.jobId,
    versionId: opts.versionId ?? prev.versionId,
    error: null,
  };
}

export function exportRunning(prev: ExportState): ExportState {
  if (prev.phase === "NO_EXPORT") return prev;
  return { ...prev, phase: "RUNNING", error: null };
}

export function exportReady(
  prev: ExportState,
  opts: { versionId: string; jobId?: string },
): ExportState {
  return {
    ...prev,
    phase: "READY",
    versionId: opts.versionId,
    jobId: opts.jobId ?? prev.jobId,
    error: null,
  };
}

export function exportDownloading(prev: ExportState): ExportState {
  return { ...prev, phase: "DOWNLOADING", error: null };
}

export function exportFailed(prev: ExportState, message: string): ExportState {
  return { ...prev, phase: "FAILED", error: message };
}

export function exportReset(): ExportState {
  return initialExportState();
}

export function canDownloadExport(state: ExportState): boolean {
  return (
    state.phase === "READY" &&
    Boolean(state.datasetId) &&
    Boolean(state.versionId)
  );
}

/** Label for UI — never claim download started while only enqueued. */
export function exportPhaseLabel(phase: ExportPhase): string {
  switch (phase) {
    case "NO_EXPORT":
      return "Geen export";
    case "ENQUEUED":
      return "Export job in wachtrij";
    case "RUNNING":
      return "Export bezig";
    case "READY":
      return "Export klaar — download beschikbaar";
    case "DOWNLOADING":
      return "Download gestart";
    case "FAILED":
      return "Export mislukt";
    default:
      return phase;
  }
}
