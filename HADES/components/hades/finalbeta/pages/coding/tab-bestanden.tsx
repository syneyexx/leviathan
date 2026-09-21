"use client";

import { useEffect } from "react";
import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";
import { FbIcon } from "../../icons";

type Props = { coding: HadesCodingRuntime };

export function CodingTabBestanden({ coding }: Props) {
  useEffect(() => {
    if (coding.workspacePath) void coding.loadWorkspaceTree("");
  }, [coding.workspacePath, coding.loadWorkspaceTree]);

  const previewLines = (coding.fsPreview?.content || "").split("\n").slice(0, 200);

  return (
    <div className="coding-files-tab">
      <div className="coding-tab-grid coding-tab-grid--files">
        <article className="coding-panel">
          <div className="coding-panel-head">
            <strong>Workspace</strong>
            <div className="coding-panel-actions">
              <button type="button" className="coding-icon-btn" aria-label="Omhoog" onClick={() => void coding.loadWorkspaceTree(coding.fsRelative.split("/").slice(0, -1).join("/"))}>
                <FbIcon name="chevron" size={12} />
              </button>
              <button type="button" className="coding-icon-btn" aria-label="Vernieuwen" onClick={() => void coding.loadWorkspaceTree(coding.fsRelative)}>
                <FbIcon name="refresh" size={12} />
              </button>
            </div>
          </div>
          <label className="coding-field">
            <span>Pad</span>
            <input
              value={coding.symbolsPath || coding.sourceRepo}
              onChange={(e) => {
                coding.setSymbolsPath(e.target.value);
                coding.setSourceRepo(e.target.value);
              }}
              placeholder="Workspace root"
            />
          </label>
          <label className="coding-field">
            <span>Filter</span>
            <input value={coding.fsFilter} onChange={(e) => coding.setFsFilter(e.target.value)} placeholder="Zoek bestanden…" />
          </label>
          <button type="button" className="btn btn-outline btn-sm btn-block" disabled={coding.fsLoading} onClick={() => void coding.loadWorkspaceTree(coding.fsRelative)}>
            {coding.fsLoading ? "Laden…" : "Tree laden"}
          </button>
          <div className="coding-tree">
            {coding.fsEntries.length === 0 ? (
              <div className="coding-empty">Geen entries. Laad een workspace.</div>
            ) : (
              coding.fsEntries.map((entry) => (
                <button
                  key={entry.path}
                  type="button"
                  className="coding-tree-row"
                  onClick={() => void coding.openFsEntry(entry)}
                >
                  <FbIcon name={entry.kind === "dir" ? "folder" : "file"} size={12} />
                  <span>{entry.name}</span>
                  {entry.dirty ? <em>dirty</em> : null}
                </button>
              ))
            )}
          </div>
          {coding.fsMeta?.truncated ? <div className="coding-hint">Resultaat afgekapt door backend-limiet.</div> : null}
        </article>

        <article className="coding-panel coding-editor-panel">
          <div className="coding-panel-head">
            <strong>{coding.fsPreview?.path || "Preview"}</strong>
            <div className="coding-panel-actions">
              <button type="button" className="coding-icon-btn" aria-label="Open in editor" onClick={() => void coding.openInEditor(coding.fsPreview?.path)}>
                <FbIcon name="external" size={12} />
              </button>
              <button
                type="button"
                className="coding-icon-btn"
                aria-label="Kopiëren"
                onClick={() => void navigator.clipboard?.writeText(coding.fsPreview?.content || "")}
              >
                <FbIcon name="copy" size={12} />
              </button>
            </div>
          </div>
          <div className="coding-editor-body">
            {coding.fsPreviewLoading ? (
              <div className="coding-empty">Preview laden…</div>
            ) : !coding.fsPreview ? (
              <div className="coding-empty">Selecteer een bestand in de tree.</div>
            ) : (
              previewLines.map((line, index) => (
                <div key={index} className="coding-line ctx">
                  <span className="coding-ln">{index + 1}</span>
                  <code>{line || " "}</code>
                </div>
              ))
            )}
          </div>
          {coding.fsPreview?.truncated ? <div className="coding-hint">Preview afgekapt.</div> : null}
        </article>

        <aside className="coding-panel">
          <div className="coding-panel-head">
            <strong>Symbolen</strong>
          </div>
          <label className="coding-field">
            <span>Zoek</span>
            <input value={coding.symbolsQuery} onChange={(e) => coding.setSymbolsQuery(e.target.value)} placeholder="symbol…" />
          </label>
          <div className="coding-tab-b-actions">
            <button type="button" className="btn btn-outline btn-sm" disabled={coding.symbolsLoading} onClick={() => void coding.searchSymbols(false)}>
              Zoek
            </button>
            <button type="button" className="btn btn-outline btn-sm" disabled={coding.symbolsRefreshing} onClick={() => void coding.refreshSymbolIndex()}>
              Refresh index
            </button>
          </div>
          {coding.symbolsMeta ? (
            <div className="coding-hint">
              {coding.symbolsMeta.files_scanned} files
              {coding.symbolsMeta.from_cache ? " · cache" : ""}
              {coding.symbolsMeta.embeddings === false ? " · lexical fallback" : ""}
              {coding.symbolsMeta.embeddings_note ? ` · ${coding.symbolsMeta.embeddings_note}` : ""}
            </div>
          ) : null}
          <ul className="coding-symbol-list">
            {coding.symbols.slice(0, 40).map((sym) => (
              <li key={`${sym.path}:${sym.line}:${sym.name}`}>
                <button type="button" onClick={() => void coding.loadSymbolDefinition(sym)}>
                  <strong>{sym.name}</strong>
                  <small>
                    {sym.kind} · {sym.path}:{sym.line}
                  </small>
                </button>
                <div className="coding-symbol-actions">
                  <button type="button" className="coding-mini" onClick={() => void coding.loadSymbolDefinition(sym)}>
                    Def
                  </button>
                  <button type="button" className="coding-mini" onClick={() => void coding.loadSymbolReferences(sym)}>
                    Refs
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {coding.definitionHits.length ? (
            <div className="coding-hint">
              Definitions: {coding.definitionHits.map((d) => `${d.path}:${d.line}`).join(", ")}
            </div>
          ) : null}
          {coding.referenceHits.length ? (
            <div className="coding-hint">
              References: {coding.referenceHits.length} hit(s)
            </div>
          ) : null}
          <button type="button" className="btn btn-sm btn-outline btn-block" onClick={() => void coding.loadCodeOutline()}>
            Outline geselecteerd pad
          </button>
        </aside>
      </div>
    </div>
  );
}
