"use client";

import { useCallback, useMemo, useState } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import {
  formatBytes,
  formatDate,
  hadesApi,
  type IndexedFile,
  type KnowledgeStats,
  type Workspace,
} from "@/lib/hades-api";

const KEY = "hades:files";

export type FilesScope = "all" | "uploads" | string;

export type FileKind = "folder" | "file";
export type FileTagTone = "gold" | "green" | "blue" | "cyan" | "purple" | "orange" | "gray" | "teal";

export type FilesFileTag = {
  label: string;
  tone: FileTagTone;
};

export type FilesFileRow = {
  id: string;
  name: string;
  kind: FileKind;
  typeLabel: string;
  size: string;
  sizeBytes: number;
  modified: string;
  owner: string;
  tags: FilesFileTag[];
  favorite: boolean;
  iconTone: "gold" | "red" | "blue" | "green" | "cyan" | "gray" | "purple" | "orange";
  iconGlyph: string;
  location?: string;
  checksum?: string;
  previewType?: string;
  status: string;
  workspaceId: string | null;
  path: string;
  extension: string;
  raw: IndexedFile;
};

export type FilesFolderNode = {
  id: string;
  label: string;
  icon?: "folder" | "shared" | "archive" | "trash";
  expandable?: boolean;
  children?: FilesFolderNode[];
};

export type FilesQuickFilter = {
  id: string;
  label: string;
  count: string;
  icon: string;
  match: (row: FilesFileRow) => boolean;
};

export type FilesStorageSlice = {
  id: string;
  label: string;
  color: string;
  share: number;
  bytes: number;
};

export type FilesStorageSummary = {
  usedLabel: string;
  totalBytes: number;
  fileCount: number;
  readyCount: number;
  readyPercent: number;
  slices: FilesStorageSlice[];
};

const IMAGE_EXT = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"]);
const DOC_EXT = new Set([".pdf", ".md", ".txt", ".docx", ".doc", ".rtf", ".epub", ".odt", ".xlsx", ".xls", ".csv", ".pptx"]);
const VIDEO_EXT = new Set([".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"]);
const ARCHIVE_EXT = new Set([".zip", ".tar", ".gz", ".tgz", ".rar", ".7z", ".bz2"]);
const CODE_EXT = new Set([
  ".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp",
  ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".sql", ".sh", ".bat", ".ps1", ".json",
  ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".scss",
]);

function formatCount(n: number): string {
  return n.toLocaleString("nl-NL");
}

function formatModified(file: IndexedFile): string {
  if (file.indexed_at) return formatDate(file.indexed_at);
  if (file.updated_at) return formatDate(file.updated_at);
  if (file.mtime > 0) {
    try {
      return new Intl.DateTimeFormat("nl-NL", { dateStyle: "short", timeStyle: "short" }).format(
        new Date(file.mtime * (file.mtime < 1e12 ? 1000 : 1)),
      );
    } catch {
      return "—";
    }
  }
  return formatDate(file.created_at);
}

function statusTag(status: string): FilesFileTag {
  const s = String(status || "").toLowerCase();
  if (s === "ready") return { label: "ready", tone: "green" };
  if (s === "error") return { label: "fout", tone: "orange" };
  if (s === "unsupported") return { label: "niet ondersteund", tone: "gray" };
  return { label: s || "onbekend", tone: "gray" };
}

function iconForExtension(ext: string): { glyph: string; tone: FilesFileRow["iconTone"]; preview: string } {
  const e = ext.toLowerCase();
  if (e === ".pdf") return { glyph: "pdf", tone: "red", preview: "PDF Document" };
  if (e === ".mp4" || VIDEO_EXT.has(e)) return { glyph: "video", tone: "red", preview: "Video" };
  if (e === ".json") return { glyph: "json", tone: "blue", preview: "JSON" };
  if (e === ".csv") return { glyph: "csv", tone: "green", preview: "CSV" };
  if (e === ".md") return { glyph: "md", tone: "gray", preview: "Markdown" };
  if (e === ".yaml" || e === ".yml") return { glyph: "yaml", tone: "gray", preview: "YAML" };
  if (e === ".safetensors" || e === ".gguf" || e === ".bin" || e === ".pt" || e === ".onnx") {
    return { glyph: "model", tone: "purple", preview: "Modelgewicht" };
  }
  if (IMAGE_EXT.has(e)) return { glyph: "image", tone: "cyan", preview: "Afbeelding" };
  if (CODE_EXT.has(e)) return { glyph: "code", tone: "blue", preview: "Broncode" };
  if (ARCHIVE_EXT.has(e)) return { glyph: "archive", tone: "orange", preview: "Archief" };
  if (DOC_EXT.has(e)) return { glyph: "doc", tone: "gold", preview: "Document" };
  return { glyph: "file", tone: "gray", preview: e ? e.slice(1).toUpperCase() : "Bestand" };
}

function locationOf(file: IndexedFile, workspaces: Workspace[]): string {
  if (!file.workspace_id) return "Uploads";
  const ws = workspaces.find((item) => item.id === file.workspace_id);
  if (ws?.name) return ws.name;
  const parts = file.path.replace(/\\/g, "/").split("/");
  if (parts.length > 1) return parts.slice(0, -1).join("/") || "/";
  return file.path || "—";
}

export function mapIndexedFileToRow(file: IndexedFile, workspaces: Workspace[] = []): FilesFileRow {
  const ext = (file.extension || "").toLowerCase();
  const typeLabel = ext ? ext.replace(/^\./, "").toUpperCase() : "BESTAND";
  const icon = iconForExtension(ext);
  const hash = file.content_hash?.trim();
  return {
    id: file.id,
    name: file.name || file.path || file.id,
    kind: "file",
    typeLabel,
    size: formatBytes(file.size_bytes || 0),
    sizeBytes: file.size_bytes || 0,
    modified: formatModified(file),
    owner: "lokaal",
    tags: [statusTag(file.status)],
    favorite: false,
    iconTone: icon.tone,
    iconGlyph: icon.glyph,
    location: locationOf(file, workspaces),
    checksum: hash ? (hash.length > 12 ? `${hash.slice(0, 6)}…${hash.slice(-4)}` : hash) : undefined,
    previewType: icon.preview,
    status: file.status,
    workspaceId: file.workspace_id,
    path: file.path,
    extension: ext,
    raw: file,
  };
}

export function mapWorkspacesToFolderTree(
  workspaces: Workspace[],
  uploadsCount: number,
): FilesFolderNode[] {
  const children: FilesFolderNode[] = [
    { id: "all", label: "Alle bestanden" },
    ...workspaces.map((ws) => ({
      id: ws.id,
      label: ws.name || ws.root_path || ws.id,
      expandable: false as const,
    })),
    { id: "uploads", label: uploadsCount ? `Uploads (${formatCount(uploadsCount)})` : "Uploads" },
  ];
  return [
    {
      id: "root",
      label: "HADES",
      expandable: true,
      children,
    },
  ];
}

function categoryOf(row: FilesFileRow): string {
  const e = row.extension;
  if (IMAGE_EXT.has(e)) return "images";
  if (VIDEO_EXT.has(e)) return "video";
  if (ARCHIVE_EXT.has(e)) return "archives";
  if (CODE_EXT.has(e)) return "code";
  if (DOC_EXT.has(e) || e === ".pdf") return "docs";
  if (row.iconGlyph === "model") return "models";
  return "other";
}

export function buildQuickFilters(rows: FilesFileRow[]): FilesQuickFilter[] {
  const defs: Array<Omit<FilesQuickFilter, "count"> & { countNum: number }> = [
    { id: "all", label: "Alle bestanden", icon: "file", match: () => true, countNum: rows.length },
    {
      id: "images",
      label: "Afbeeldingen",
      icon: "image",
      match: (row) => categoryOf(row) === "images",
      countNum: 0,
    },
    {
      id: "docs",
      label: "Documenten",
      icon: "file",
      match: (row) => categoryOf(row) === "docs",
      countNum: 0,
    },
    {
      id: "video",
      label: "Video's",
      icon: "play",
      match: (row) => categoryOf(row) === "video",
      countNum: 0,
    },
    {
      id: "archives",
      label: "Archieven",
      icon: "folder",
      match: (row) => categoryOf(row) === "archives",
      countNum: 0,
    },
    {
      id: "code",
      label: "Code",
      icon: "code",
      match: (row) => categoryOf(row) === "code",
      countNum: 0,
    },
    {
      id: "ready",
      label: "Gereed",
      icon: "bolt",
      match: (row) => row.status === "ready",
      countNum: 0,
    },
    {
      id: "error",
      label: "Fouten",
      icon: "shield",
      match: (row) => row.status === "error",
      countNum: 0,
    },
  ];
  for (const def of defs) {
    if (def.id === "all") continue;
    def.countNum = rows.filter(def.match).length;
  }
  return defs.map(({ countNum, ...rest }) => ({ ...rest, count: formatCount(countNum) }));
}

export function buildStorageSummary(rows: FilesFileRow[]): FilesStorageSummary {
  const totalBytes = rows.reduce((sum, row) => sum + (row.sizeBytes || 0), 0);
  const readyCount = rows.filter((row) => row.status === "ready").length;
  const buckets: Record<string, { label: string; color: string; bytes: number }> = {
    models: { label: "Modellen", color: "#38bdf8", bytes: 0 },
    docs: { label: "Documenten", color: "#eab94f", bytes: 0 },
    code: { label: "Code", color: "#7dd3fc", bytes: 0 },
    media: { label: "Media", color: "#a78bfa", bytes: 0 },
    other: { label: "Overig", color: "#64748b", bytes: 0 },
  };
  for (const row of rows) {
    const cat = categoryOf(row);
    if (cat === "models") buckets.models.bytes += row.sizeBytes;
    else if (cat === "docs") buckets.docs.bytes += row.sizeBytes;
    else if (cat === "code") buckets.code.bytes += row.sizeBytes;
    else if (cat === "images" || cat === "video") buckets.media.bytes += row.sizeBytes;
    else buckets.other.bytes += row.sizeBytes;
  }
  const slices: FilesStorageSlice[] = Object.entries(buckets)
    .filter(([, b]) => b.bytes > 0 || totalBytes === 0)
    .map(([id, b]) => ({
      id,
      label: b.label,
      color: b.color,
      bytes: b.bytes,
      share: totalBytes > 0 ? Math.round((b.bytes / totalBytes) * 100) : 0,
    }))
    .filter((s) => totalBytes === 0 || s.bytes > 0)
    .slice(0, 4);
  if (!slices.length) {
    slices.push({ id: "other", label: "Overig", color: "#64748b", share: 0, bytes: 0 });
  }
  return {
    usedLabel: formatBytes(totalBytes),
    totalBytes,
    fileCount: rows.length,
    readyCount,
    readyPercent: rows.length ? Math.round((readyCount / rows.length) * 100) : 0,
    slices,
  };
}

export function useHadesFiles(initialScope: FilesScope = "all") {
  const [scope, setScope] = useState<FilesScope>(initialScope);

  const workspaceParam = scope === "all" ? "" : scope;

  const query = useHadesQuery(
    `${KEY}:${workspaceParam || "all"}`,
    async () => hadesApi.files(workspaceParam),
    { staleTime: 5_000, refetchInterval: 15_000 },
  );

  const workspaces: Workspace[] = query.data?.workspaces ?? [];
  const files: IndexedFile[] = query.data?.files ?? [];
  const knowledge: KnowledgeStats | null = query.data?.knowledge ?? null;
  const uploadsCount =
    query.data?.uploads_count ?? files.filter((item) => !item.workspace_id).length;

  const rows = useMemo(
    () => files.map((file) => mapIndexedFileToRow(file, workspaces)),
    [files, workspaces],
  );

  const folderTree = useMemo(
    () => mapWorkspacesToFolderTree(workspaces, uploadsCount),
    [workspaces, uploadsCount],
  );

  const quickFilters = useMemo(() => buildQuickFilters(rows), [rows]);
  const storage = useMemo(() => buildStorageSummary(rows), [rows]);

  const refresh = useCallback(async () => {
    invalidateHadesQuery(`${KEY}:${workspaceParam || "all"}`);
    // Also invalidate sibling scopes so switching folders stays fresh.
    invalidateHadesQuery(`${KEY}:all`);
    return query.refetch();
  }, [query, workspaceParam]);

  const rescan = useCallback(
    async (workspaceId?: string) => {
      const id = workspaceId || (scope !== "all" && scope !== "uploads" ? scope : "");
      if (!id) throw new Error("Selecteer eerst een workspace om te herscannen.");
      const result = await hadesApi.rescanWorkspace(id);
      await refresh();
      return result;
    },
    [refresh, scope],
  );

  const removeFile = useCallback(
    async (fileId: string) => {
      const result = await hadesApi.deleteIndexedFile(fileId);
      await refresh();
      return result;
    },
    [refresh],
  );

  const upload = useCallback(
    async (file: File, approved = true) => {
      const result = await hadesApi.uploadFile(file, approved);
      await refresh();
      return result;
    },
    [refresh],
  );

  return {
    scope,
    setScope,
    workspaces,
    files,
    rows,
    folderTree,
    quickFilters,
    storage,
    knowledge,
    uploadsCount,
    loading: query.status === "loading" && !query.data,
    error: query.error,
    refresh,
    rescan,
    removeFile,
    upload,
  };
}
