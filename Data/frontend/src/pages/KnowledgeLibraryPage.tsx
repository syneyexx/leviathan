/**
 * Leviathan V2 Knowledge Library — canonical `/knowledge`
 * (Onderzoek & Kennis → Knowledge Library).
 *
 * Visual layout follows the Knowledge Library reference; truth comes from
 * KnowledgeStore + SourceIngestionService. No page-local CSS file.
 */

import { useRef } from "react";
import {
  KnowledgeIngestionPanels,
  KnowledgeSelectedPanel,
} from "../components/knowledge/KnowledgeDetailPanels";
import {
  KnowledgeKpis,
  KnowledgeLibraryTable,
  KnowledgeNav,
  KnowledgeTypeSidebar,
} from "../components/knowledge/KnowledgeLibraryCore";
import { ErrorState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
import { KL_SORT_OPTIONS } from "./knowledge/constants";
import { useKnowledgeLibraryWorkspace } from "./knowledge/useKnowledgeLibraryWorkspace";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function TopbarSearch({
  value,
  onChange,
  inputRef,
}: {
  value: string;
  onChange: (v: string) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  return (
    <form
      className="lv-v2-topbar-search lv-v2-kl-topbar-search"
      role="search"
      onSubmit={(e) => e.preventDefault()}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.5-3.5" />
      </svg>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Zoek in knowledge library..."
        aria-label="Zoek in knowledge library"
      />
      <kbd>Ctrl + K</kbd>
    </form>
  );
}

export function KnowledgeLibraryPage() {
  const ws = useKnowledgeLibraryWorkspace();
  const frozen = visualFixtureNow();
  const uploadRef = useRef<HTMLInputElement | null>(null);

  return (
    <AppShell
      variant="v2"
      v2Title="Knowledge Library"
      v2Subtitle="Beheer, doorzoek en analyseer alle kennis, datasets, documenten en bronnen binnen Leviathan."
      v2Online={ws.online}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.refresh({ quiet: true });
      }}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={
        <TopbarSearch value={ws.q} onChange={ws.setQ} inputRef={ws.searchInputRef} />
      }
    >
      <main className="lv-v2-page lv-v2-page--knowledge">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            STALE — laatste succesvolle update{" "}
            {ws.lastUpdated ? new Date(ws.lastUpdated).toLocaleString("nl-NL") : "—"}.
            Behouden waarden na refresh-fout.
          </p>
        ) : null}

        {ws.error && ws.items.length === 0 ? (
          <div className="lv-v2-kl-error-block">
            <ErrorState title="Knowledge Library unavailable" detail={ws.error} />
            <button type="button" className="lv-v2-button lv-v2-button--primary lv-v2-button--sm" onClick={() => void ws.refresh()}>
              Opnieuw proberen
            </button>
          </div>
        ) : null}

        <KnowledgeKpis ws={ws} />
        <KnowledgeNav ws={ws} />

        {ws.view === "vector" ? (
          <section className="lv-v2-kl-vector" aria-label="Vector Search">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void ws.onVectorSearch();
              }}
            >
              <input
                value={ws.vectorQ}
                onChange={(e) => ws.setVectorQ(e.target.value)}
                placeholder="Semantische query over chunks…"
                aria-label="Vector search query"
              />
              <button type="submit" disabled={ws.busy}>
                Zoeken
              </button>
            </form>
            {ws.vectorError ? <p className="lv-v2-kl-warn">{ws.vectorError}</p> : null}
            <ul>
              {ws.vectorHits.map((h) => (
                <li key={`${h.document_id}:${h.chunk_id || h.chunk_index}`}>
                  <button type="button" onClick={() => ws.setSelectedId(h.document_id)}>
                    <strong>{h.title}</strong>
                    <span>{h.content.slice(0, 180)}</span>
                    <em>
                      {h.modality || "hybrid"}
                      {h.score != null ? ` · score ${h.score.toFixed(3)}` : ""}
                    </em>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {ws.view === "ingestie" ? (
          <section className="lv-v2-kl-ingest-view" aria-label="Ingestie">
            <input
              ref={uploadRef}
              type="file"
              multiple
              hidden
              onChange={(e) => void ws.onUploadFiles(e.target.files)}
            />
            <button
              type="button"
              className="lv-v2-button lv-v2-button--primary"
              disabled={ws.busy}
              onClick={() => uploadRef.current?.click()}
            >
              Bestand uploaden
            </button>
            <p className="lv-v2-kl-muted">
              Uploads gaan via SourceIngestionService (gestreamd). ZIP/archieven worden door de
              source_ingestion worker verwerkt — niet in de browser.
            </p>
            <KnowledgeIngestionPanels ws={ws} />
          </section>
        ) : null}

        {ws.view === "analyses" ? (
          <section className="lv-v2-kl-analyses" aria-label="Analyses">
            <h3>Knowledge analyses</h3>
            <p className="lv-v2-kl-muted">Server-side aggregaties uit library overview.</p>
            <ul>
              <li>Bronnen: {ws.overview?.total_sources ?? "—"}</li>
              <li>Types: {ws.overview?.source_type_count ?? "—"}</li>
              <li>
                Embedding: {ws.overview?.embedding?.coverage_percent ?? "—"}% (
                {ws.overview?.embedding?.status ?? "—"})
              </li>
              <li>Tag vocabulary: {ws.overview?.tag_vocabulary_size ?? "—"}</li>
            </ul>
          </section>
        ) : null}

        {ws.view === "bibliotheek" || ws.view === "bronnen" ? (
          <>
            <div className="lv-v2-kl-toolbar">
              <input
                value={ws.q}
                onChange={(e) => ws.setQ(e.target.value)}
                placeholder="Zoek in bronnen..."
                aria-label="Zoek in bronnen"
              />
              <select
                value={ws.typeFilter}
                onChange={(e) => ws.setTypeFilter(e.target.value)}
                aria-label="Alle types"
              >
                <option value="">Alle types</option>
                {(ws.overview?.source_type_counts ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
              <select
                value={ws.tagFilter}
                onChange={(e) => ws.setTagFilter(e.target.value)}
                aria-label="Alle tags"
              >
                <option value="">Alle tags</option>
                {(ws.overview?.top_tags ?? []).map((t) => (
                  <option key={t.tag} value={t.tag}>
                    #{t.tag}
                  </option>
                ))}
              </select>
              <select value={ws.sort} onChange={(e) => ws.setSort(e.target.value)} aria-label="Sortering">
                {KL_SORT_OPTIONS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <div className="lv-v2-kl-view-toggle">
                <button
                  type="button"
                  className={ws.viewMode === "list" ? "is-active" : undefined}
                  onClick={() => ws.setViewMode("list")}
                >
                  List
                </button>
                <button
                  type="button"
                  className={ws.viewMode === "grid" ? "is-active" : undefined}
                  onClick={() => ws.setViewMode("grid")}
                >
                  Grid
                </button>
              </div>
              {ws.checked.size ? (
                <div className="lv-v2-kl-bulk">
                  <span>{ws.checked.size} geselecteerd</span>
                  <button type="button" onClick={() => void ws.onBulkTag()}>
                    Tags toevoegen
                  </button>
                  <button type="button" onClick={() => void ws.onBulkDelete()}>
                    Verwijderen
                  </button>
                </div>
              ) : null}
            </div>

            <section className="lv-v2-kl-workspace" aria-label="Knowledge workspace">
              <KnowledgeTypeSidebar ws={ws} />
              <div className="lv-v2-kl-center">
                <KnowledgeLibraryTable ws={ws} />
                <KnowledgeIngestionPanels ws={ws} />
              </div>
              <KnowledgeSelectedPanel ws={ws} />
            </section>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}
