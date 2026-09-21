"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  useHadesFiles,
  type FilesFileRow,
  type FilesFolderNode,
} from "@/components/hades/features/files/hooks/useHadesFiles";
import { FbIcon } from "../icons";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };
type ViewMode = "list" | "grid";
type FilesTab = "Verkenner" | "Recente activiteit" | "Gedeeld met mij" | "Favorieten" | "Prullenbak";

const FILES_TABS: FilesTab[] = [
  "Verkenner",
  "Recente activiteit",
  "Gedeeld met mij",
  "Favorieten",
  "Prullenbak",
];

const FILES_QUOTE = "Data is de brandstof voor een slimmere morgen.";

const SELECTION_ACTIONS = [
  { id: "open", label: "Openen", tone: "outline" as const },
  { id: "download", label: "Downloaden", tone: "outline" as const },
  { id: "share", label: "Delen", tone: "outline" as const, chevron: true },
  { id: "move", label: "Verplaatsen", tone: "outline" as const },
  { id: "copy", label: "Kopiëren", tone: "outline" as const },
  { id: "delete", label: "Verwijderen", tone: "danger" as const },
];

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg className={`files-star${filled ? " on" : ""}`} viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path
        d="M12 3.6 14.6 9l5.9.5-4.5 3.8 1.4 5.7L12 16.8 6.6 19l1.4-5.7L3.5 9.5 9.4 9 12 3.6Z"
        fill={filled ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FileTypeIcon({ row }: { row: FilesFileRow }) {
  if (row.kind === "folder" || row.iconGlyph === "folder") {
    return (
      <span className={`files-type-ico folder ${row.iconTone}`}>
        <FbIcon name="folder" size={14} />
      </span>
    );
  }
  if (row.iconGlyph === "video") {
    return (
      <span className={`files-type-ico video ${row.iconTone}`}>
        <FbIcon name="play" size={12} />
      </span>
    );
  }
  if (row.iconGlyph === "model") {
    return (
      <span className={`files-type-ico model ${row.iconTone}`}>
        <FbIcon name="database" size={12} />
      </span>
    );
  }
  return <span className={`files-type-ico badge ${row.iconTone}`}>{row.typeLabel.slice(0, 4)}</span>;
}

function FolderIcon({ node }: { node: FilesFolderNode }) {
  if (node.icon === "trash") return <FbIcon name="trash" size={13} />;
  if (node.icon === "shared") return <FbIcon name="users" size={13} />;
  if (node.icon === "archive") return <FbIcon name="save" size={13} />;
  return <FbIcon name="folder" size={13} />;
}

function FolderTree({
  nodes,
  depth,
  selectedId,
  expanded,
  onSelect,
  onToggle,
}: {
  nodes: FilesFolderNode[];
  depth: number;
  selectedId: string;
  expanded: Set<string>;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
}) {
  return (
    <ul className="files-tree-list" style={{ ["--depth" as string]: depth }}>
      {nodes.map((node) => {
        const isOpen = expanded.has(node.id);
        const hasKids = Boolean(node.children?.length) || node.expandable;
        return (
          <li key={node.id}>
            <button
              type="button"
              className={`files-tree-row${selectedId === node.id ? " active" : ""}`}
              style={{ paddingLeft: 8 + depth * 14 }}
              onClick={() => onSelect(node.id)}
            >
              {hasKids ? (
                <span
                  className={`files-tree-chevron${isOpen ? " open" : ""}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onToggle(node.id);
                  }}
                  role="presentation"
                >
                  <FbIcon name="chevron" size={10} />
                </span>
              ) : (
                <span className="files-tree-chevron spacer" />
              )}
              <span className="files-tree-ico">
                <FolderIcon node={node} />
              </span>
              <span className="files-tree-label">{node.label}</span>
            </button>
            {hasKids && isOpen && node.children?.length ? (
              <FolderTree
                nodes={node.children}
                depth={depth + 1}
                selectedId={selectedId}
                expanded={expanded}
                onSelect={onSelect}
                onToggle={onToggle}
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function findFolderLabel(nodes: FilesFolderNode[], id: string): string | null {
  for (const node of nodes) {
    if (node.id === id) return node.label;
    if (node.children?.length) {
      const found = findFolderLabel(node.children, id);
      if (found) return found;
    }
  }
  return null;
}

export function FilesPage({ onNavigate }: Props) {
  const {
    scope,
    setScope,
    rows,
    folderTree,
    quickFilters,
    storage,
    knowledge,
    workspaces,
    loading,
    error,
    refresh,
    rescan,
    removeFile,
    upload,
  } = useHadesFiles("all");

  const [tab, setTab] = useState<FilesTab>("Verkenner");
  const [folderId, setFolderId] = useState("all");
  const [expanded, setExpanded] = useState(() => new Set(["root"]));
  const [query, setQuery] = useState("");
  const [view, setView] = useState<ViewMode>("list");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(() => new Set());
  const [favorites, setFavorites] = useState<Map<string, boolean>>(() => new Map());
  const [quickFilterId, setQuickFilterId] = useState("all");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!loading) setLastSyncedAt(new Date());
  }, [loading, rows.length, workspaces.length]);

  useEffect(() => {
    if (folderId === "root") {
      setFolderId("all");
      setScope("all");
      return;
    }
    if (folderId === "all" || folderId === "uploads" || workspaces.some((ws) => ws.id === folderId)) {
      setScope(folderId);
    }
  }, [folderId, setScope, workspaces]);

  const activeFilter = quickFilters.find((item) => item.id === quickFilterId) ?? quickFilters[0];

  const filtered = useMemo(() => {
    let list = rows;
    if (activeFilter && activeFilter.id !== "all") {
      list = list.filter(activeFilter.match);
    }
    if (tab === "Favorieten") {
      list = list.filter((row) => Boolean(favorites.get(row.id)));
    }
    if (tab === "Prullenbak" || tab === "Gedeeld met mij") {
      list = [];
    }
    if (tab === "Recente activiteit") {
      list = [...list].sort((a, b) => b.raw.mtime - a.raw.mtime).slice(0, 40);
    }
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (row) =>
        row.name.toLowerCase().includes(q) ||
        row.typeLabel.toLowerCase().includes(q) ||
        row.path.toLowerCase().includes(q) ||
        row.tags.some((tag) => tag.label.toLowerCase().includes(q)),
    );
  }, [rows, activeFilter, tab, favorites, query]);

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId(null);
      return;
    }
    setSelectedId((current) =>
      current && filtered.some((row) => row.id === current) ? current : filtered[0]!.id,
    );
  }, [filtered]);

  const selected = filtered.find((row) => row.id === selectedId) ?? filtered[0] ?? null;
  const checkedRows = filtered.filter((row) => checked.has(row.id));
  const selectionSize = checkedRows.length
    ? checkedRows.map((row) => row.size).filter((size) => size !== "—").join(" · ") || "—"
    : "";

  const folderLabel =
    findFolderLabel(folderTree, folderId) ||
    (folderId === "uploads" ? "Uploads" : folderId === "all" ? "Alle bestanden" : "Bestanden");

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleCheck = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleFavorite = (id: string) => {
    setFavorites((prev) => {
      const next = new Map(prev);
      next.set(id, !next.get(id));
      return next;
    });
  };

  const selectRow = (row: FilesFileRow) => {
    setSelectedId(row.id);
    setChecked(new Set([row.id]));
  };

  async function onUploadFiles(fileList: FileList | null) {
    if (!fileList?.length) return;
    setBusyAction("upload");
    try {
      for (const file of Array.from(fileList)) {
        await upload(file, true);
      }
      toast.success(`${fileList.length} bestand${fileList.length === 1 ? "" : "en"} geüpload.`);
      setScope("uploads");
      setFolderId("uploads");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload mislukt.");
    } finally {
      setBusyAction(null);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  }

  async function onRescan() {
    setBusyAction("rescan");
    try {
      if (scope !== "all" && scope !== "uploads") {
        const result = await rescan(scope);
        toast.success(
          `Herscan klaar: ${result.processed} verwerkt · ${result.ready} gereed · ${result.failed} fout.`,
        );
      } else {
        await refresh();
        toast.success("Bestandenlijst vernieuwd.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Herscannen mislukt.");
    } finally {
      setBusyAction(null);
    }
  }

  async function onDeleteSelection() {
    const ids = Array.from(checked);
    if (!ids.length) return;
    const ok = window.confirm(
      ids.length === 1
        ? "Dit geïndexeerde bestand verwijderen uit HADES?"
        : `${ids.length} geïndexeerde bestanden verwijderen uit HADES?`,
    );
    if (!ok) return;
    setBusyAction("delete");
    try {
      for (const id of ids) {
        await removeFile(id);
      }
      setChecked(new Set());
      toast.success("Verwijderd uit index.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Verwijderen mislukt.");
    } finally {
      setBusyAction(null);
    }
  }

  function onSelectionAction(actionId: string) {
    if (actionId === "delete") {
      void onDeleteSelection();
      return;
    }
    toast.message("Actie nog niet beschikbaar voor geïndexeerde bestanden.");
  }

  const body = (
    <div className="files-page" data-live="files">
      <div className="files-welcome">
        <div className="files-welcome-copy">
          <h1>Bestanden</h1>
          <p>Beheer, organiseer en deel je bestanden. Alles op één veilige plek binnen HADES.</p>
        </div>
        <div className="files-welcome-actions">
          <input
            ref={uploadRef}
            type="file"
            multiple
            hidden
            onChange={(event) => void onUploadFiles(event.target.files)}
          />
          <button
            type="button"
            className="btn btn-outline"
            disabled={busyAction === "upload"}
            onClick={() => uploadRef.current?.click()}
          >
            <FbIcon name="plus" size={12} />
            {busyAction === "upload" ? "Uploaden…" : "Uploaden"}
          </button>
          <button type="button" className="btn btn-outline" onClick={() => void onRescan()} disabled={Boolean(busyAction)}>
            {busyAction === "rescan" ? "Bezig…" : scope !== "all" && scope !== "uploads" ? "Herscannen" : "Vernieuwen"}
            <FbIcon name="refresh" size={11} className="files-chevron-down" />
          </button>
          <button
            type="button"
            className="btn btn-gold"
            onClick={() =>
              toast.message("Nieuwe map: voeg een workspace toe via pad in Lux Files, of upload bestanden hier.")
            }
          >
            <FbIcon name="plus" size={12} />
            Nieuwe map
          </button>
        </div>
      </div>

      {error ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Bestanden laden mislukt.</strong> {error.message}{" "}
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void refresh()}>
            Opnieuw
          </button>
        </div>
      ) : null}

      <div className="files-tabs tabs" role="tablist">
        {FILES_TABS.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={`tab${tab === item ? " active" : ""}`}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="files-dual">
        <aside className="files-tree card">
          <div className="files-tree-head">
            <h2>Mappen</h2>
            <button
              type="button"
              className="files-tree-add"
              aria-label="Vernieuwen"
              onClick={() => void refresh()}
            >
              <FbIcon name="refresh" size={12} />
            </button>
          </div>
          <div className="files-tree-body">
            {loading && !folderTree[0]?.children?.length ? (
              <p className="muted" style={{ padding: 8 }}>
                Workspaces laden…
              </p>
            ) : null}
            {!loading && !workspaces.length ? (
              <p className="muted" style={{ padding: 8 }}>
                Geen workspaces. Upload bestanden of voeg een workspace toe.
              </p>
            ) : null}
            <FolderTree
              nodes={folderTree}
              depth={0}
              selectedId={folderId}
              expanded={expanded}
              onSelect={setFolderId}
              onToggle={toggleExpand}
            />
          </div>
          <div className="files-filters">
            <h3>Snelle filters</h3>
            <ul>
              {quickFilters.map((filter) => (
                <li key={filter.id}>
                  <button
                    type="button"
                    className={`files-filter-row${quickFilterId === filter.id ? " active" : ""}`}
                    onClick={() => setQuickFilterId(filter.id)}
                  >
                    <FbIcon name={filter.icon} size={13} />
                    <span>{filter.label}</span>
                    <b>{filter.count}</b>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <section className="files-browser card">
          <div className="files-browser-toolbar">
            <label className="files-search">
              <FbIcon name="search" size={13} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Zoeken in bestanden..."
                aria-label="Zoeken in bestanden"
              />
            </label>
            <div className="files-view-toggle" role="group" aria-label="Weergave">
              <button
                type="button"
                className={view === "grid" ? "active" : undefined}
                aria-pressed={view === "grid"}
                onClick={() => setView("grid")}
              >
                <FbIcon name="grid" size={13} />
              </button>
              <button
                type="button"
                className={view === "list" ? "active" : undefined}
                aria-pressed={view === "list"}
                onClick={() => setView("list")}
              >
                <FbIcon name="list" size={13} />
              </button>
            </div>
            <button type="button" className="files-sort" disabled title="Sorteer op gewijzigd (actief)">
              Sorteren: Gewijzigd
              <FbIcon name="chevron" size={11} className="files-chevron-down" />
            </button>
            <button
              type="button"
              className="files-filter-btn"
              aria-label="Vernieuwen"
              onClick={() => void refresh()}
            >
              <FbIcon name="sliders" size={13} />
            </button>
          </div>

          <div className="files-breadcrumb">
            <FbIcon name="folder" size={12} />
            <span>HADES</span>
            <span className="sep">/</span>
            <strong>{folderLabel}</strong>
          </div>

          <div className={`files-table-wrap ${view}`}>
            <div className="files-table-head" aria-hidden="true">
              <span className="col-check" />
              <span className="col-name">Naam</span>
              <span className="col-type">Type</span>
              <span className="col-size">Grootte</span>
              <span className="col-modified">Gewijzigd</span>
              <span className="col-owner">Eigenaar</span>
              <span className="col-tags">Tags</span>
              <span className="col-star" />
              <span className="col-more" />
            </div>
            <div className="files-table-body">
              {loading && !rows.length ? (
                <p className="muted" style={{ padding: 16 }}>
                  Bestanden laden…
                </p>
              ) : null}
              {!loading && !filtered.length ? (
                <p className="muted" style={{ padding: 16 }}>
                  {tab === "Gedeeld met mij" || tab === "Prullenbak"
                    ? `${tab} is nog niet beschikbaar in deze build.`
                    : tab === "Favorieten"
                      ? "Geen favorieten gemarkeerd."
                      : query.trim()
                        ? "Geen bestanden matchen deze zoekopdracht."
                        : "Geen geïndexeerde bestanden in deze scope."}
                </p>
              ) : null}
              {filtered.map((row) => {
                const active = selected != null && row.id === selected.id;
                const isChecked = checked.has(row.id);
                const fav = Boolean(favorites.get(row.id));
                return (
                  <div
                    key={row.id}
                    className={`files-row${active ? " active" : ""}${isChecked ? " checked" : ""}`}
                    onClick={() => selectRow(row)}
                    role="row"
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectRow(row);
                      }
                    }}
                  >
                    <label className="col-check" onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggleCheck(row.id)}
                        aria-label={`Selecteer ${row.name}`}
                      />
                      <span />
                    </label>
                    <span className="col-name">
                      <FileTypeIcon row={row} />
                      <span className="files-row-name">{row.name}</span>
                    </span>
                    <span className="col-type">{row.typeLabel}</span>
                    <span className="col-size">{row.size}</span>
                    <span className="col-modified">{row.modified}</span>
                    <span className="col-owner">{row.owner}</span>
                    <span className="col-tags">
                      {row.tags.map((tag) => (
                        <span key={tag.label} className={`files-tag ${tag.tone}`}>
                          {tag.label}
                        </span>
                      ))}
                    </span>
                    <button
                      type="button"
                      className="col-star"
                      aria-label={fav ? "Favoriet verwijderen" : "Favoriet maken"}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggleFavorite(row.id);
                      }}
                    >
                      <StarIcon filled={fav} />
                    </button>
                    <button
                      type="button"
                      className="col-more"
                      aria-label="Meer acties"
                      onClick={(event) => {
                        event.stopPropagation();
                        toast.message(row.path || row.name);
                      }}
                    >
                      <FbIcon name="more" size={14} />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          {checked.size > 0 ? (
            <div className="files-selection-bar">
              <span className="files-selection-count">
                {checked.size} item{checked.size === 1 ? "" : "s"} geselecteerd
                {selectionSize ? ` (${checked.size === 1 ? checkedRows[0]?.size : selectionSize})` : ""}
              </span>
              <div className="files-selection-actions">
                {SELECTION_ACTIONS.map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    className={`btn btn-sm ${action.tone === "danger" ? "btn-danger" : "btn-outline"}`}
                    disabled={busyAction === "delete" && action.id === "delete"}
                    onClick={() => onSelectionAction(action.id)}
                  >
                    {action.label}
                    {"chevron" in action && action.chevron ? (
                      <FbIcon name="chevron" size={10} className="files-chevron-down" />
                    ) : null}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <section className="insp-section files-storage">
        <h3 className="insp-title">Opslagruimte</h3>
        <div className="insp-card">
          <div className="files-storage-top">
            <span>
              {storage.usedLabel} geïndexeerd · {storage.fileCount.toLocaleString("nl-NL")} bestanden
              {knowledge ? ` · ${knowledge.chunks} chunks` : ""}
            </span>
            <b>{storage.readyPercent}% ready</b>
          </div>
          <div className="files-storage-bar" aria-hidden="true">
            <i style={{ width: `${Math.max(storage.readyPercent, storage.fileCount ? 2 : 0)}%` }} />
          </div>
          <ul className="files-storage-legend">
            {storage.slices.map((slice) => (
              <li key={slice.id}>
                <i style={{ background: slice.color }} />
                <span>
                  {slice.label}
                  {slice.share ? ` (${slice.share}%)` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <p className="quote files-quote">“{FILES_QUOTE}”</p>

      <section className="insp-section files-preview">
        <h3 className="insp-title">Bestandsvoorbeeld</h3>
        <div className="insp-card">
          {selected ? (
            <>
              <div className="files-preview-head">
                <span className={`files-preview-ico ${selected.iconTone}`}>
                  {selected.kind === "folder" ? <FbIcon name="folder" size={22} /> : selected.typeLabel}
                </span>
                <div>
                  <strong>{selected.name}</strong>
                  <small>{selected.previewType ?? selected.typeLabel}</small>
                </div>
              </div>
              <div className="detail-row">
                <span className="k">Type</span>
                <span className="v">{selected.previewType ?? selected.typeLabel}</span>
              </div>
              <div className="detail-row">
                <span className="k">Grootte</span>
                <span className="v">{selected.size}</span>
              </div>
              <div className="detail-row">
                <span className="k">Status</span>
                <span className="v">{selected.status}</span>
              </div>
              <div className="detail-row">
                <span className="k">Gewijzigd</span>
                <span className="v">{selected.modified}</span>
              </div>
              <div className="detail-row">
                <span className="k">Eigenaar</span>
                <span className="v">{selected.owner}</span>
              </div>
              <div className="detail-row">
                <span className="k">Locatie</span>
                <span className="v">{selected.location ?? "—"}</span>
              </div>
              {selected.checksum ? (
                <div className="detail-row">
                  <span className="k">Checksum</span>
                  <span className="v mono">{selected.checksum}</span>
                </div>
              ) : null}
              <div className="detail-row">
                <span className="k">Pad</span>
                <span className="v mono">{selected.path || "—"}</span>
              </div>
            </>
          ) : (
            <p className="muted">Geen bestand geselecteerd.</p>
          )}
        </div>
      </section>

      <section className="insp-section files-insp-tags">
        <h3 className="insp-title">Tags</h3>
        <div className="insp-card">
          {selected?.tags.length ? (
            <div className="files-insp-tag-row">
              {selected.tags.map((tag) => (
                <span key={tag.label} className={`files-tag ${tag.tone}`}>
                  {tag.label}
                </span>
              ))}
            </div>
          ) : (
            <p className="muted">Geen tags voor dit item.</p>
          )}
        </div>
      </section>

      <section className="insp-section files-versions">
        <h3 className="insp-title">Versie geschiedenis</h3>
        <div className="insp-card">
          <p className="muted">Geen versiegeschiedenis beschikbaar voor geïndexeerde bestanden.</p>
        </div>
      </section>

      <section className="insp-section files-sync">
        <h3 className="insp-title">Synchronisatie</h3>
        <div className="insp-card files-sync-card">
          <div className="files-sync-status">
            <span className="files-sync-dot" />
            <div>
              <strong>{loading ? "Laden…" : error ? "Niet synchroon" : "Index bijgewerkt"}</strong>
              <small>
                {lastSyncedAt
                  ? `Laatste refresh: ${lastSyncedAt.toLocaleString("nl-NL")}`
                  : "Nog niet geladen"}
              </small>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline"
            disabled={Boolean(busyAction)}
            onClick={() => void onRescan()}
          >
            <FbIcon name="refresh" size={12} />
            {busyAction === "rescan" ? "Bezig…" : "Nu vernieuwen"}
          </button>
        </div>
      </section>
    </>
  );

  const footer = (
    <footer className="dash-footer files-footer">
      <span>HADES FINALBETA v0.9.0&nbsp;&nbsp;|&nbsp;&nbsp;Local AI Platform</span>
      <span className="motto">
        Build a smarter tomorrow. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="files"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="files-app"
      mainClassName="files-main"
      footer={footer}
    />
  );
}
