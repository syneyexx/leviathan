/**
 * Leviathan V2 Knowledge Library — canonical `/knowledge`
 * (Onderzoek & Kennis → Knowledge Library).
 *
 * Visual layout follows the Knowledge Library reference; truth comes from
 * KnowledgeStore + SourceIngestionService. No page-local CSS file.
 */

import { useRef } from "react";
import { IngestionProgress } from "../components/knowledge/IngestionProgress";
import { KnowledgeLibraryKpis } from "../components/knowledge/KnowledgeLibraryKpis";
import { KnowledgeLibraryNav } from "../components/knowledge/KnowledgeLibraryNav";
import { LibraryTable } from "../components/knowledge/LibraryTable";
import { LibraryToolbar } from "../components/knowledge/LibraryToolbar";
import { RecentIngestions } from "../components/knowledge/RecentIngestions";
import { SelectedSourcePanel } from "../components/knowledge/SelectedSourcePanel";
import { SourceTypeSidebar } from "../components/knowledge/SourceTypeSidebar";
import { TagSidebar } from "../components/knowledge/TagSidebar";
import { ErrorState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
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
      v2Actions={<TopbarSearch value={ws.q} onChange={ws.setQ} inputRef={ws.searchInputRef} />}
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
            <button
              type="button"
              className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
              onClick={() => void ws.refresh()}
            >
              Opnieuw proberen
            </button>
          </div>
        ) : null}

        <KnowledgeLibraryKpis ws={ws} />
        <KnowledgeLibraryNav ws={ws} />

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
            <section className="lv-v2-kl-bottom" aria-label="Ingestie">
              <IngestionProgress ws={ws} />
              <RecentIngestions ws={ws} />
            </section>
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
          <section className="lv-v2-kl-workspace" aria-label="Knowledge workspace">
            <aside className="lv-v2-kl-side" aria-label="Bron filters">
              <SourceTypeSidebar ws={ws} />
              <TagSidebar ws={ws} />
            </aside>
            <div className="lv-v2-kl-center">
              <LibraryToolbar ws={ws} />
              <LibraryTable ws={ws} showSource={ws.view === "bronnen"} />
              <section className="lv-v2-kl-bottom" aria-label="Ingestie">
                <IngestionProgress ws={ws} />
                <RecentIngestions ws={ws} />
              </section>
            </div>
            <SelectedSourcePanel ws={ws} />
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
