import type { DatasetMgmtStatus } from "../datasets/datasetManagementConstants";

export type { DatasetMgmtStatus };

/**
 * Map backend/canonical dataset status to NL UI labels.
 * Unknown / empty statuses must NOT default to success-like "Verwerkt".
 */
export function mapDatasetStatus(
  status: string,
  brainStatus?: string | null,
  canonicalState?: string | null,
): DatasetMgmtStatus {
  const canonical = (canonicalState || "").toUpperCase();
  if (canonical === "LEARNED" || canonical === "STALE_JOB") return "Klaar";
  if (canonical === "REBUILDING" || canonical === "INDEXING") return "Bezig";
  if (canonical === "INDEX_QUEUED") return "Wachtrij";
  if (canonical === "FAILED") return "Fout";
  const brain = (brainStatus || "").toLowerCase();
  if (brain === "learned") return "Klaar";
  if (brain === "indexing" || brain === "queued") return brain === "queued" ? "Wachtrij" : "Bezig";
  if (brain === "failed") return "Fout";
  const s = (status || "").toLowerCase().trim();
  if (!s || s === "unknown" || s === "unmeasured" || s === "unavailable") return "Onbekend";
  if (s === "ready" || s === "complete" || s === "completed") return "Verwerkt";
  if (s === "processed" || s === "materialized") return "Verwerkt";
  if (s === "raw" || s === "created") return "Wachtrij";
  if (s === "running" || s === "processing" || s === "importing") return "Bezig";
  if (s === "queued" || s === "pending") return "Wachtrij";
  if (s === "warning" || s === "degraded") return "Waarschuwing";
  if (s === "failed" || s === "error" || s === "cancelled") return "Fout";
  return "Onbekend";
}

export function toneForDatasetStatus(status: DatasetMgmtStatus): string {
  if (status === "Klaar") return "green";
  if (status === "Verwerkt" || status === "Bezig") return "cyan";
  if (status === "Wachtrij") return "gold";
  if (status === "Waarschuwing") return "orange";
  if (status === "Onbekend") return "muted";
  return "red";
}
