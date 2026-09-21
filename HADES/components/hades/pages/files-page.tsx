"use client";

import { ChangeEvent, DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Code2, File, FileCode2, FileText, FolderOpen, HardDrive, Loader2, Plus, RefreshCcw,
  Search, Trash2, Upload, XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, Panel, ProgressRow, StatusBadge } from "@/components/hades/ui";
import { ResultsPanel } from "@/components/hades/results-panel";
import { formatBytes, formatDate, hadesApi, IndexedFile, KnowledgeMatch, Workspace } from "@/lib/hades-api";

type Scope = "all" | "uploads" | string;

type KnowledgeChunk = {
  id: string;
  source_id: string;
  sequence: number;
  heading: string;
  content: string;
  token_estimate: number;
};

type SymbolHit = {
  name: string;
  kind: string;
  path: string;
  line: number;
  snippet?: string;
};

function FileIcon({ extension }: { extension: string }) {
  if ([".md", ".py", ".ts", ".tsx", ".js", ".json"].includes(extension)) return <FileCode2 />;
  if ([".pdf", ".docx", ".epub"].includes(extension)) return <FileText className="pdf-icon" />;
  return <File />;
}

function readFilesHashQuery(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  const hash = window.location.hash.replace(/^#/, "");
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  return new URLSearchParams(query);
}

function statusTone(status: string): "success" | "danger" | "warning" | "neutral" {
  if (status === "ready") return "success";
  if (status === "error") return "danger";
  if (status === "unsupported") return "warning";
  return "neutral";
}

function statusLabel(status: string): string {
  if (status === "ready") return "Gereed";
  if (status === "error") return "Fout";
  if (status === "unsupported") return "Niet ondersteund";
  return status;
}

export function FilesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [files, setFiles] = useState<IndexedFile[]>([]);
  const [scope, setScope] = useState<Scope>("all");
  const [selectedFileId, setSelectedFileId] = useState("");
  const [path, setPath] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "ready" | "error" | "unsupported">("all");
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [rescanning, setRescanning] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [busyDelete, setBusyDelete] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadsCount, setUploadsCount] = useState(0);
  const [knowledge, setKnowledge] = useState({ sources: 0, chunks: 0, token_estimate: 0, types: {} as Record<string, number> });
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksError, setChunksError] = useState<string | null>(null);
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [knowledgeHits, setKnowledgeHits] = useState<KnowledgeMatch[]>([]);
  const [knowledgeSearching, setKnowledgeSearching] = useState(false);
  const [knowledgeSearchError, setKnowledgeSearchError] = useState<string | null>(null);
  const [focusArtifactId, setFocusArtifactId] = useState("");
  const [symbolPath, setSymbolPath] = useState("");
  const [symbolQuery, setSymbolQuery] = useState("");
  const [symbolResults, setSymbolResults] = useState<SymbolHit[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolHit | null>(null);
  const [symbolMeta, setSymbolMeta] = useState<{ root: string; files_scanned: number; truncated: boolean } | null>(null);
  const [symbolLoading, setSymbolLoading] = useState(false);
  const [symbolError, setSymbolError] = useState<string | null>(null);
  const [definitionResults, setDefinitionResults] = useState<SymbolHit[]>([]);
  const [referenceResults, setReferenceResults] = useState<SymbolHit[]>([]);
  const [lspLoading, setLspLoading] = useState<"definition" | "references" | null>(null);
  const [lspNote, setLspNote] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const initializedHash = useRef(false);

  const selectedFile = useMemo(() => files.find((item) => item.id === selectedFileId), [files, selectedFileId]);
  const visibleFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return files.filter((item) => {
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (!needle) return true;
      return `${item.name} ${item.path}`.toLowerCase().includes(needle);
    });
  }, [files, query, statusFilter]);

  const refresh = useCallback(async (nextScope: Scope = scope) => {
    setLoading(true);
    try {
      const workspaceParam = nextScope === "all" ? "" : nextScope;
      const result = await hadesApi.files(workspaceParam);
      setWorkspaces(result.workspaces);
      setFiles(result.files);
      setKnowledge(result.knowledge);
      setUploadsCount(result.uploads_count ?? result.files.filter((item) => !item.workspace_id).length);
      setSelectedFileId((current) => (result.files.some((item) => item.id === current) ? current : result.files[0]?.id || ""));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Bestanden laden is mislukt.");
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    void refresh(scope);
  }, [scope]);  

  useEffect(() => {
    if (initializedHash.current) return;
    initializedHash.current = true;
    const params = readFilesHashQuery();
    const artifact = params.get("artifact") || "";
    const fileId = params.get("file") || "";
    const workspace = params.get("workspace") || "";
    const search = params.get("q") || "";
    if (artifact) setFocusArtifactId(artifact);
    if (workspace === "uploads" || workspace === "all") setScope(workspace);
    else if (workspace) setScope(workspace);
    if (fileId) setSelectedFileId(fileId);
    if (search) setKnowledgeQuery(search);
  }, []);

  useEffect(() => {
    if (!selectedFileId) {
      setChunks([]);
      setChunksError(null);
      return;
    }
    let cancelled = false;
    setChunksLoading(true);
    setChunksError(null);
    hadesApi.fileDetail(selectedFileId)
      .then((detail) => {
        if (cancelled) return;
        setChunks(detail.chunks || []);
      })
      .catch((reason) => {
        if (!cancelled) {
          setChunksError(reason instanceof Error ? reason.message : "Bestandsdetails laden mislukt.");
        }
      })
      .finally(() => {
        if (!cancelled) setChunksLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedFileId, files]);

  useEffect(() => {
    const needle = knowledgeQuery.trim();
    if (needle.length < 2) {
      setKnowledgeHits([]);
      setKnowledgeSearchError(null);
      return;
    }
    const timer = window.setTimeout(() => {
      setKnowledgeSearching(true);
      setKnowledgeSearchError(null);
      hadesApi.searchKnowledge(needle, 8)
        .then((result) => setKnowledgeHits(result.matches))
        .catch((reason) => {
          setKnowledgeSearchError(reason instanceof Error ? reason.message : "Zoeken in Knowledge is mislukt.");
        })
        .finally(() => setKnowledgeSearching(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [knowledgeQuery]);

  const addWorkspace = async () => {
    if (!path.trim()) return;
    setAdding(true);
    try {
      const result = await hadesApi.addWorkspace({ path: path.trim(), recursive: true, max_files: 10000, approved: true });
      setPath("");
      setScope(result.workspace.id);
      await refresh(result.workspace.id);
      const extra = result.limited ? " (limiet bereikt)" : "";
      const message = `${result.ready} gereed, ${result.unchanged} ongewijzigd, ${result.failed} fout, ${result.unsupported} niet ondersteund${extra}.`;
      const ready = Number(result.ready || 0);
      const failed = Number(result.failed || 0);
      const unsupported = Number(result.unsupported || 0);
      if (ready <= 0 && (failed > 0 || unsupported > 0)) {
        toast.error(`Map toegevoegd, maar niets geïndexeerd: ${message}`);
      } else if (ready <= 0) {
        toast.message(`Map toegevoegd zonder nieuwe indexering: ${message}`);
      } else {
        toast.success(message);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Map toevoegen is mislukt.");
    } finally {
      setAdding(false);
    }
  };

  const uploadFiles = async (picked: File[]) => {
    if (!picked.length) return;
    setUploading(true);
    let ready = 0;
    let failed = 0;
    for (const file of picked) {
      try {
        const result = await hadesApi.uploadFile(file, true);
        if (result.file.status === "ready") ready += 1;
        else failed += 1;
      } catch (reason) {
        failed += 1;
        toast.error(`${file.name}: ${reason instanceof Error ? reason.message : "upload mislukt"}`);
      }
    }
    setScope("uploads");
    await refresh("uploads");
    setUploading(false);
    if (ready) toast.success(`${ready} geüploade bestand(en) geïndexeerd.`);
    if (failed && !ready) toast.error("Geen uploads konden worden geïndexeerd.");
  };

  const onUploadInput = async (event: ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = "";
    await uploadFiles(picked);
  };

  const onDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragOver(false);
    const picked = Array.from(event.dataTransfer.files ?? []);
    await uploadFiles(picked);
  };

  const rescan = async () => {
    if (!scope || scope === "all" || scope === "uploads") return;
    setRescanning(true);
    try {
      const result = await hadesApi.rescanWorkspace(scope);
      await refresh(scope);
      const ready = Number(result.ready || 0);
      const failed = Number(result.failed || 0);
      const unchanged = Number(result.unchanged || 0);
      const message = `Herscan: ${ready} gereed, ${unchanged} ongewijzigd, ${failed} fout.`;
      if (ready > 0) {
        toast.success(message);
      } else if (failed > 0) {
        toast.error(message);
      } else {
        toast.message(message);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Herscannen mislukt.");
    } finally {
      setRescanning(false);
    }
  };

  const removeWorkspace = async () => {
    if (!scope || scope === "all" || scope === "uploads") return;
    const workspace = workspaces.find((item) => item.id === scope);
    if (!workspace) return;
    if (!window.confirm(`Workspace “${workspace.name}” en bijbehorende index/kennis verwijderen?`)) return;
    setBusyDelete(true);
    try {
      const result = await hadesApi.deleteWorkspace(scope);
      setScope("all");
      await refresh("all");
      toast.success(`Workspace verwijderd (${result.workspace.removed_files ?? 0} bestanden).`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Workspace verwijderen mislukt.");
    } finally {
      setBusyDelete(false);
    }
  };

  const reindexSelected = async () => {
    if (!selectedFile) return;
    setReindexing(true);
    try {
      const result = await hadesApi.reindexFile(selectedFile.id);
      await refresh(scope);
      setSelectedFileId(result.file.id);
      if (result.file.status === "ready") {
        const chunks = Number(result.chunks ?? 0);
        if (result.unchanged) {
          toast.message(chunks > 0 ? "Bestand was al up-to-date." : "Bestand up-to-date zonder chunks.");
        } else if (chunks > 0) {
          toast.success(`Opnieuw geïndexeerd (${chunks} chunks).`);
        } else {
          toast.error("Opnieuw indexeren leverde 0 chunks op.");
        }
      } else {
        toast.error(`Opnieuw indexeren mislukt (${result.file.status}${result.file.error ? `: ${result.file.error}` : ""}).`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Herindexeren mislukt.");
    } finally {
      setReindexing(false);
    }
  };

  const deleteSelected = async () => {
    if (!selectedFile) return;
    if (!window.confirm(`“${selectedFile.name}” uit de index en Knowledge Library verwijderen?`)) return;
    setBusyDelete(true);
    try {
      await hadesApi.deleteIndexedFile(selectedFile.id);
      await refresh(scope);
      toast.success("Bestand uit index verwijderd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Verwijderen mislukt.");
    } finally {
      setBusyDelete(false);
    }
  };

  const openKnowledgeHit = async (hit: KnowledgeMatch) => {
    const match = files.find((item) => item.source_id === hit.source_id)
      || (await hadesApi.files("")).files.find((item) => item.source_id === hit.source_id);
    if (match) {
      if (match.workspace_id) setScope(match.workspace_id);
      else setScope("uploads");
      setSelectedFileId(match.id);
      setQuery(match.name);
      return;
    }
    toast.message("Bron gevonden in Knowledge, maar geen geïndexeerd bestand gekoppeld.");
  };

  const workspace = workspaces.find((item) => item.id === scope);
  const symbolScopePath = useMemo(() => {
    if (symbolPath.trim()) return symbolPath.trim();
    if (selectedFile?.path) return selectedFile.path;
    if (workspace?.root_path) return workspace.root_path;
    return "";
  }, [symbolPath, selectedFile?.path, workspace?.root_path]);
  const symbolWorkspaceId = scope !== "all" && scope !== "uploads" ? scope : undefined;

  const searchWorkspaceSymbols = async () => {
    if (!symbolScopePath && !symbolWorkspaceId) {
      setSymbolError("Kies een workspace, selecteer een bestand of vul een pad in.");
      return;
    }
    setSymbolLoading(true);
    setSymbolError(null);
    setSelectedSymbol(null);
    setDefinitionResults([]);
    setReferenceResults([]);
    setLspNote(null);
    try {
      const payload = await hadesApi.searchSymbols({
        workspace_id: symbolWorkspaceId,
        path: symbolWorkspaceId ? undefined : symbolScopePath || undefined,
        query: symbolQuery.trim() || undefined,
      });
      setSymbolResults(payload.symbols ?? []);
      setSymbolMeta({
        root: payload.root,
        files_scanned: payload.files_scanned,
        truncated: payload.truncated,
      });
    } catch (reason) {
      setSymbolResults([]);
      setSymbolMeta(null);
      setSymbolError(reason instanceof Error ? reason.message : "Symbolen zoeken is mislukt.");
    } finally {
      setSymbolLoading(false);
    }
  };

  const loadSymbolDefinition = async (symbol: SymbolHit) => {
    setLspLoading("definition");
    setLspNote(null);
    try {
      const payload = await hadesApi.codeDefinition({
        workspace_id: symbolWorkspaceId,
        path: symbolWorkspaceId ? undefined : symbolScopePath || undefined,
        symbol: symbol.name,
      });
      setDefinitionResults(payload.definitions ?? []);
      setLspNote(payload.note ?? null);
    } catch (reason) {
      setDefinitionResults([]);
      setSymbolError(reason instanceof Error ? reason.message : "Definitie ophalen is mislukt.");
    } finally {
      setLspLoading(null);
    }
  };

  const loadSymbolReferences = async (symbol: SymbolHit) => {
    setLspLoading("references");
    setLspNote(null);
    try {
      const payload = await hadesApi.codeReferences({
        workspace_id: symbolWorkspaceId,
        path: symbolWorkspaceId ? undefined : symbolScopePath || undefined,
        symbol: symbol.name,
      });
      setReferenceResults(payload.references ?? []);
      setLspNote(payload.note ?? null);
    } catch (reason) {
      setReferenceResults([]);
      setSymbolError(reason instanceof Error ? reason.message : "Referenties ophalen is mislukt.");
    } finally {
      setLspLoading(null);
    }
  };

  const selectSymbol = (symbol: SymbolHit) => {
    setSelectedSymbol(symbol);
    setDefinitionResults([]);
    setReferenceResults([]);
    setLspNote(null);
    setSymbolError(null);
  };

  const readyCount = files.filter((item) => item.status === "ready").length;
  const errorCount = files.filter((item) => item.status === "error").length;
  const unsupportedCount = files.filter((item) => item.status === "unsupported").length;
  const totalBytes = files.reduce((sum, item) => sum + item.size_bytes, 0);
  const scopeLabel = scope === "all" ? "Alle bestanden" : scope === "uploads" ? "Uploads" : workspace?.name || "Workspace";

  return (
    <div className="page page-files">
      <PageHeader
        title="Bestanden"
        description="Koppel lokale mappen en uploads aan de Knowledge Library; alleen gewijzigde inhoud wordt opnieuw geïndexeerd."
        actions={(
          <>
            <input ref={uploadRef} className="visually-hidden" type="file" multiple onChange={(event) => void onUploadInput(event)} />
            <Button variant="outline" onClick={() => uploadRef.current?.click()} disabled={uploading}>
              {uploading ? <Loader2 className="spin" /> : <Upload />}Uploaden
            </Button>
            <Button variant="outline" onClick={() => void refresh()}><RefreshCcw />Vernieuwen</Button>
          </>
        )}
      />
      <div className="file-layout">
        <aside className="file-nav">
          <Panel title="Lokale map koppelen">
            <div className="form-stack">
              <label>
                <span>Volledig pad</span>
                <Input
                  value={path}
                  onChange={(event) => setPath(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void addWorkspace(); }}
                  placeholder={"D:\\Knowledge\\Documents"}
                />
              </label>
              <Button onClick={() => void addWorkspace()} disabled={!path.trim() || adding}>
                {adding ? <Loader2 className="spin" /> : <Plus />}Map indexeren
              </Button>
            </div>
          </Panel>
          <Panel title="Workspaces">
            <nav>
              <button type="button" className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>
                <HardDrive />Alle bestanden<small>{knowledge.sources} kennisbronnen</small>
              </button>
              <button type="button" className={scope === "uploads" ? "active" : ""} onClick={() => setScope("uploads")}>
                <Upload />Uploads<small>{uploadsCount} bestanden</small>
              </button>
              {workspaces.map((item) => (
                <button type="button" className={item.id === scope ? "active" : ""} key={item.id} onClick={() => setScope(item.id)}>
                  <FolderOpen />{item.name}<small>{item.root_path}</small>
                </button>
              ))}
              {!workspaces.length ? <span className="empty-copy">Nog geen gekoppelde mappen.</span> : null}
            </nav>
          </Panel>
          <Panel title="Lokale opslag">
            <ProgressRow label="Geïndexeerd" value={files.length ? Math.round(readyCount / files.length * 100) : 0} detail={`${readyCount} / ${files.length}`} />
            <div className="file-stats-mini">
              <span>{errorCount} fout</span>
              <span>{unsupportedCount} niet ondersteund</span>
              <span>{knowledge.chunks} chunks</span>
            </div>
            <code>{workspace?.root_path || (scope === "uploads" ? "data/uploads" : "Uploads + Knowledge Library")}</code>
            {scope !== "all" && scope !== "uploads" ? (
              <div className="button-stack tight">
                <Button variant="outline" onClick={() => void rescan()} disabled={rescanning}>
                  {rescanning ? <Loader2 className="spin" /> : <RefreshCcw />}Herscannen
                </Button>
                <Button variant="outline" onClick={() => void removeWorkspace()} disabled={busyDelete}>
                  <Trash2 />Workspace verwijderen
                </Button>
              </div>
            ) : null}
          </Panel>
        </aside>

        <Panel className="file-browser">
          <div
            className={dragOver ? "upload-zone drag-over" : "upload-zone"}
            onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => void onDrop(event)}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") uploadRef.current?.click(); }}
            onClick={() => uploadRef.current?.click()}
          >
            <Upload />
            <span>
              <strong>Sleep bestanden hierheen of klik om te uploaden</strong>
              <small>PDF, Office, Markdown, code en tekst → Knowledge Library</small>
            </span>
            {uploading ? <StatusBadge tone="warning"><Loader2 className="spin" />Bezig</StatusBadge> : <StatusBadge>Upload</StatusBadge>}
          </div>
          <div className="file-browser-head">
            <div className="breadcrumb"><HardDrive /><strong>{scopeLabel}</strong></div>
            <div className="file-browser-tools">
              <div className="inline-search"><Search /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Zoek in bestandsnaam of pad…" /></div>
              <select className="status-filter" aria-label="Filter op status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}>
                <option value="all">Alle statussen</option>
                <option value="ready">Gereed</option>
                <option value="error">Fout</option>
                <option value="unsupported">Niet ondersteund</option>
              </select>
            </div>
          </div>
          <div className="table-scroll">
            <table className="data-table file-table">
              <thead>
                <tr><th>Naam</th><th>Type</th><th>Grootte</th><th>Gewijzigd</th><th>Indexstatus</th></tr>
              </thead>
              <tbody>
                {visibleFiles.map((item) => (
                  <tr
                    className={item.id === selectedFileId ? "selected-row clickable-row" : "clickable-row"}
                    key={item.id}
                    onClick={() => setSelectedFileId(item.id)}
                  >
                    <td><span className="file-name"><FileIcon extension={item.extension} /><strong>{item.name}</strong></span></td>
                    <td>{item.extension || "—"}</td>
                    <td>{formatBytes(item.size_bytes)}</td>
                    <td>{formatDate(item.updated_at)}</td>
                    <td><StatusBadge tone={statusTone(item.status)}>{statusLabel(item.status)}</StatusBadge></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {loading ? <div className="table-empty"><Loader2 className="spin" />Bestanden laden…</div> : null}
            {!visibleFiles.length && !loading ? <div className="table-empty">Geen bestanden gevonden. Koppel een map of upload documenten.</div> : null}
          </div>
          <div className="table-footer">
            <span>{visibleFiles.length} items · {formatBytes(totalBytes)}</span>
            <span>{knowledge.sources} kennisbronnen · {knowledge.chunks} chunks · ~{knowledge.token_estimate} tokens</span>
          </div>
        </Panel>

        <aside className="file-details">
          <Panel
            title={selectedFile?.name || "Bestandsdetails"}
            actions={selectedFile ? <StatusBadge tone={statusTone(selectedFile.status)}>{statusLabel(selectedFile.status)}</StatusBadge> : undefined}
          >
            {selectedFile ? (
              <>
                <dl className="detail-list spaced">
                  <div><dt>Pad</dt><dd><code>{selectedFile.path}</code></dd></div>
                  <div><dt>Type</dt><dd>{selectedFile.extension || "—"}</dd></div>
                  <div><dt>Grootte</dt><dd>{formatBytes(selectedFile.size_bytes)}</dd></div>
                  <div><dt>Indexstatus</dt><dd>{statusLabel(selectedFile.status)}</dd></div>
                  <div><dt>Geïndexeerd</dt><dd>{selectedFile.indexed_at ? formatDate(selectedFile.indexed_at) : "—"}</dd></div>
                  <div><dt>SHA256</dt><dd><code>{selectedFile.content_hash?.slice(0, 18) || "—"}</code></dd></div>
                  <div><dt>Bron-ID</dt><dd><code>{selectedFile.source_id || "—"}</code></dd></div>
                </dl>
                {selectedFile.error ? <div className="inline-error"><XCircle />{selectedFile.error}</div> : null}
                <div className="button-stack">
                  <Button variant="outline" onClick={() => void reindexSelected()} disabled={reindexing}>
                    {reindexing ? <Loader2 className="spin" /> : <RefreshCcw />}Opnieuw indexeren
                  </Button>
                  <Button variant="outline" onClick={() => void deleteSelected()} disabled={busyDelete}>
                    <Trash2 />Uit index verwijderen
                  </Button>
                </div>
                <div className="chunk-preview">
                  <strong>Knowledge chunks</strong>
                  {chunksLoading ? <p className="empty-copy"><Loader2 className="spin" />Chunks laden…</p> : null}
                  {chunksError ? <p className="empty-copy inline-error">{chunksError}</p> : null}
                  {!chunksLoading && !chunksError && !chunks.length ? <p className="empty-copy">Geen chunks voor dit bestand.</p> : null}
                  <div className="chunk-list">
                    {chunks.slice(0, 8).map((chunk) => (
                      <article key={chunk.id} className="chunk-card">
                        <header>{chunk.heading || `Chunk ${chunk.sequence + 1}`} · ~{chunk.token_estimate} tokens</header>
                        <p>{chunk.content.slice(0, 280)}{chunk.content.length > 280 ? "…" : ""}</p>
                      </article>
                    ))}
                  </div>
                </div>
              </>
            ) : <p className="empty-copy">Selecteer een bestand om metadata, indexstatus en chunks te bekijken.</p>}
          </Panel>

          <Panel
            title="Symbolen / LSP-light"
            actions={
              <Button size="sm" variant="outline" onClick={() => void searchWorkspaceSymbols()} disabled={symbolLoading}>
                {symbolLoading ? <Loader2 className="spin" /> : <Search />}
                Zoeken
              </Button>
            }
          >
            <div className="form-stack">
              <label>
                <span>Pad of workspace</span>
                <Input
                  value={symbolPath}
                  onChange={(event) => setSymbolPath(event.target.value)}
                  placeholder={workspace?.root_path || selectedFile?.path || "D:\\Projects\\mijn-repo"}
                />
              </label>
              <label>
                <span>Query (optioneel)</span>
                <Input
                  value={symbolQuery}
                  onChange={(event) => setSymbolQuery(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void searchWorkspaceSymbols(); }}
                  placeholder="MyClass"
                />
              </label>
              {symbolMeta ? (
                <p className="empty-copy">
                  Root: <code>{symbolMeta.root}</code> · {symbolMeta.files_scanned} bestanden
                  {symbolMeta.truncated ? " · resultaten afgekapt" : ""}
                </p>
              ) : null}
              {symbolError ? <div className="inline-error"><XCircle />{symbolError}</div> : null}
              <div className="table-scroll symbol-results-scroll">
                <table className="data-table">
                  <thead>
                    <tr><th>Naam</th><th>Kind</th><th>Locatie</th></tr>
                  </thead>
                  <tbody>
                    {symbolResults.map((symbol) => (
                      <tr
                        key={`${symbol.path}:${symbol.line}:${symbol.name}`}
                        className={selectedSymbol?.name === symbol.name && selectedSymbol.path === symbol.path && selectedSymbol.line === symbol.line ? "selected-row clickable-row" : "clickable-row"}
                        onClick={() => selectSymbol(symbol)}
                      >
                        <td><strong>{symbol.name}</strong></td>
                        <td>{symbol.kind}</td>
                        <td><code>{symbol.path}:{symbol.line}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!symbolResults.length && !symbolLoading ? (
                  <p className="empty-copy">Geen symbolen — zoek in een gekoppelde workspace of pad.</p>
                ) : null}
              </div>
              {selectedSymbol ? (
                <div className="button-row">
                  <StatusBadge tone="info"><Code2 />{selectedSymbol.name}</StatusBadge>
                  <Button size="sm" variant="outline" disabled={lspLoading === "definition"} onClick={() => void loadSymbolDefinition(selectedSymbol)}>
                    {lspLoading === "definition" ? <Loader2 className="spin" /> : <Code2 />}
                    Definitie
                  </Button>
                  <Button size="sm" variant="outline" disabled={lspLoading === "references"} onClick={() => void loadSymbolReferences(selectedSymbol)}>
                    {lspLoading === "references" ? <Loader2 className="spin" /> : <Search />}
                    Referenties
                  </Button>
                </div>
              ) : null}
              {lspNote ? <p className="empty-copy">{lspNote}</p> : null}
              {definitionResults.length ? (
                <div className="symbol-lsp-results">
                  <strong>Definities</strong>
                  <ul>
                    {definitionResults.map((item) => (
                      <li key={`def-${item.path}:${item.line}:${item.name}`}><code>{item.path}:{item.line}</code> · {item.kind} · {item.name}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {referenceResults.length ? (
                <div className="symbol-lsp-results">
                  <strong>Referenties</strong>
                  <ul>
                    {referenceResults.map((item) => (
                      <li key={`ref-${item.path}:${item.line}:${item.name}`}>
                        <code>{item.path}:{item.line}</code> · {item.name}
                        {item.snippet ? <span> — {item.snippet.slice(0, 120)}{item.snippet.length > 120 ? "…" : ""}</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </Panel>

          <Panel title="Zoek in Knowledge">
            <div className="inline-search"><Search /><Input value={knowledgeQuery} onChange={(event) => setKnowledgeQuery(event.target.value)} placeholder="Zoek in geïndexeerde inhoud…" /></div>
              {knowledgeSearching ? <p className="empty-copy"><Loader2 className="spin" />Zoeken…</p> : null}
              {knowledgeSearchError ? <p className="empty-copy inline-error">{knowledgeSearchError}</p> : null}
            <div className="knowledge-hit-list">
              {knowledgeHits.map((hit) => (
                <button type="button" className="knowledge-hit" key={hit.chunk_id} onClick={() => void openKnowledgeHit(hit)}>
                  <strong>{hit.title}</strong>
                  <small>{hit.heading || hit.source_type} · {hit.uri}</small>
                  <span>{hit.content.slice(0, 160)}{hit.content.length > 160 ? "…" : ""}</span>
                </button>
              ))}
              {!knowledgeHits.length && knowledgeQuery.trim().length >= 2 && !knowledgeSearching && !knowledgeSearchError ? (
                <p className="empty-copy">Geen treffers in de Knowledge Library.</p>
              ) : null}
            </div>
          </Panel>

          <ResultsPanel title="Beheerde resultaten" focusArtifactId={focusArtifactId} />
        </aside>
      </div>
    </div>
  );
}
