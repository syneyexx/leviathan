/**
 * Leviathan V2 Dataset Management — view-model formatters and derivations.
 *
 * Pure functions only; no fixture data, no API calls. Mirrors the formatting
 * previously embedded in DatasetManagementPixelPage.tsx so behavior stays
 * consistent between Pixel and V2 surfaces.
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

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${(bytes / 1024 ** 4).toFixed(2)} TB`;
}

export function formatCompactCount(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function mapSourceLabel(sourceType: string): string {
  const s = (sourceType || "").toLowerCase();
  if (s.includes("hugging") || s === "hf") return "Hugging Face";
  if (s.includes("local") || s === "path") return "Lokaal";
  if (s.includes("upload") || s === "file") return "Lokaal";
  if (s.includes("derived")) return "Afgeleid";
  if (s.includes("synthetic")) return "Synthetic";
  if (s.includes("open")) return "Open Data";
  return sourceType || "—";
}

export function sourceMatchesFilter(sourceType: string, filter: string): boolean {
  if (filter === "Alle bronnen") return true;
  return mapSourceLabel(sourceType) === filter;
}

export function mapTypeLabel(ds: DatasetRecord): string {
  const fmt = (ds.detectedFormat ?? "").toLowerCase();
  if (fmt.includes("pdf")) return "PDF";
  if (fmt.includes("log")) return "Logs";
  if (fmt.includes("chat") || fmt.includes("dialog")) return "Chat";
  if (fmt.includes("code") || fmt.includes("py") || fmt.includes("js")) return "Code";
  if (fmt) return "Tekst";
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const task = String(meta?.taskType ?? meta?.task ?? "").toLowerCase();
  if (task.includes("chat")) return "Chat";
  if (task.includes("code")) return "Code";
  return "Tekst";
}

export function typeToneForLabel(type: string): "cyan" | "gold" | "green" | "purple" | "blue" {
  if (type === "Code") return "gold";
  if (type === "Chat") return "purple";
  if (type === "PDF") return "blue";
  if (type === "Logs") return "green";
  return "cyan";
}

export function categoryForDataset(ds: DatasetRecord): string {
  return String(
    ds.primaryCategory
      ?? ds.semanticProfile?.primaryCategory
      ?? (ds.metadata as Record<string, unknown> | undefined)?.primaryCategory
      ?? "",
  );
}

export function displayNameForDataset(ds: DatasetRecord): string {
  return String(ds.displayName || ds.semanticProfile?.displayName || ds.name || ds.datasetId);
}

export function tagsForDataset(ds: DatasetRecord): string[] {
  const semanticTags = ds.semanticTags ?? ds.semanticProfile?.tags;
  if (Array.isArray(semanticTags) && semanticTags.length) {
    return semanticTags.map((t) => String(t)).filter(Boolean).slice(0, 6);
  }
  const meta = ds.metadata as Record<string, unknown> | undefined;
  const raw = meta?.semanticTags ?? meta?.tags;
  if (Array.isArray(raw)) return raw.map((t) => String(t)).filter(Boolean).slice(0, 6);
  const lang = meta?.language ?? meta?.lang;
  if (typeof lang === "string" && lang) return [lang];
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

export function splitLabelFromVersion(v: DatasetVersion | null | undefined): string {
  if (!v?.split || typeof v.split !== "object") return "—";
  const keys = Object.keys(v.split);
  if (keys.length === 0) return "—";
  return keys[0];
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

export function fileSuffix(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
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

/** Quality display — Niet gemeten when the version has no validation evidence. */
export function qualityLabel(quality: DatasetQualitySignal | null | undefined): string {
  if (!quality || !quality.measured || quality.score == null) return "Niet gemeten";
  return `${quality.label} (${quality.score})`;
}

export function qualityTone(quality: DatasetQualitySignal | null | undefined): string {
  if (!quality || !quality.measured) return "muted";
  switch (quality.tone) {
    case "good":
      return "green";
    case "fair":
      return "gold";
    case "poor":
      return "orange";
    case "critical":
      return "red";
    default:
      return "muted";
  }
}

export function serviceStateTone(state: string): "green" | "cyan" | "gold" | "red" | "muted" {
  const s = (state || "").toLowerCase();
  if (s === "running" || s === "ready") return "green";
  if (s === "busy") return "cyan";
  if (s === "offline" || s === "unavailable") return "red";
  if (s === "unmeasured") return "muted";
  return "gold";
}
