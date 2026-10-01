/**
 * Shared Datasets view-model helpers (canonical `/datasets` + transitional DM).
 * Pure functions only.
 */

import type {
  DatasetPreviewRow,
  DatasetQualitySignal,
  DatasetRecord,
  DatasetVersion,
} from "../../types/api";

export function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export {
  formatBytes,
  formatCompactCount,
} from "./datasetsMapping";

export function displayNameForDataset(ds: DatasetRecord): string {
  return String(ds.displayName || ds.semanticProfile?.displayName || ds.name || ds.datasetId);
}

export function categoryForDataset(ds: DatasetRecord): string {
  return String(
    ds.primaryCategory ??
      ds.semanticProfile?.primaryCategory ??
      (ds.metadata as Record<string, unknown> | undefined)?.primaryCategory ??
      "",
  );
}

export function tagsForDataset(ds: DatasetRecord): string[] {
  const semanticTags = ds.semanticTags ?? ds.semanticProfile?.tags;
  if (Array.isArray(semanticTags) && semanticTags.length) {
    return semanticTags.map((t) => String(t)).filter(Boolean);
  }
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const raw = meta?.semanticTags ?? meta?.tags;
  if (Array.isArray(raw)) return raw.map((t) => String(t)).filter(Boolean);
  return [];
}

export function recoveryLabel(state: string | null | undefined): string {
  const s = (state || "").toUpperCase();
  if (s === "READY") return "Gereed";
  if (s === "METADATA_RESTORED") return "Metadata hersteld";
  if (s === "REINDEX_REQUIRED") return "Herindexeren vereist";
  if (s === "SOURCE_MISSING") return "Bron ontbreekt";
  if (s === "HASH_MISMATCH") return "Hash conflict";
  if (s === "CONFLICT") return "Conflict";
  if (s === "UNSUPPORTED") return "Niet ondersteund";
  return s || "—";
}

export function previewSampleText(rows: DatasetPreviewRow[]): string {
  if (rows.length === 0) return "Geen voorbeeldrijen.";
  const first = rows[0] as Record<string, unknown>;
  const text =
    first.text ??
    first.content ??
    first.body ??
    first.message ??
    first.prompt ??
    first.input;
  if (typeof text === "string") return text.slice(0, 2000);
  return JSON.stringify(first, null, 2).slice(0, 2000);
}

export function previewSampleTable(rows: DatasetPreviewRow[]): string {
  if (rows.length === 0) return "Geen voorbeeldrijen.";
  const cols = new Set<string>();
  for (const row of rows.slice(0, 5)) {
    Object.keys(row as object).forEach((k) => cols.add(k));
  }
  const headers = [...cols].slice(0, 6);
  const lines = [headers.join(" | ")];
  for (const row of rows.slice(0, 8)) {
    const r = row as Record<string, unknown>;
    lines.push(
      headers
        .map((h) => {
          const v = r[h];
          return dash(
            typeof v === "string" || typeof v === "number" ? v : v == null ? null : String(v),
          );
        })
        .join(" | "),
    );
  }
  return lines.join("\n");
}

export function pickUsableVersion(versions: DatasetVersion[]): DatasetVersion | null {
  const ready = versions.filter((v) => v.status === "ready");
  const order = ["materialized", "transformed", "split", "raw", "export"];
  for (const kind of order) {
    const hit = ready.find((v) => v.kind === kind);
    if (hit) return hit;
  }
  return ready[0] ?? versions[0] ?? null;
}

export function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function qualityLabel(quality: DatasetQualitySignal | null | undefined): string {
  if (!quality || !quality.measured || quality.score == null) return "Niet gemeten";
  return `${quality.label} (${quality.score})`;
}

export function redactSecretUri(uri: string | null | undefined): string {
  if (!uri) return "—";
  try {
    const u = new URL(uri);
    if (u.password) u.password = "***";
    if (u.username) u.username = "***";
    // Strip token-like query params
    for (const key of [...u.searchParams.keys()]) {
      if (/token|key|secret|password|auth/i.test(key)) {
        u.searchParams.set(key, "***");
      }
    }
    return u.toString();
  } catch {
    return uri.replace(/(token|key|secret|password)=([^&\s]+)/gi, "$1=***");
  }
}
