import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/** Left sidebar "Tags" filter — top tags from the library overview (bounded, top 40 server-side). */
export function TagSidebar({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  const allTags = ws.overview?.top_tags ?? [];
  const visibleTags = ws.tagsExpanded ? allTags : allTags.slice(0, 10);
  return (
    <div className="lv-v2-kl-side-block">
      <h3>
        Tags
        <button
          type="button"
          className="lv-v2-kl-icon-btn"
          aria-label="Tag toevoegen aan selectie"
          onClick={() => void ws.onBulkTag()}
          disabled={!ws.checked.size}
        >
          +
        </button>
      </h3>
      {visibleTags.map((t, idx) => (
        <button
          key={t.tag}
          type="button"
          className={`lv-v2-kl-tag-row lv-v2-kl-tag-row--${idx % 8}${ws.tagFilter === t.tag ? " is-active" : ""}`}
          onClick={() => ws.setTagFilter(ws.tagFilter === t.tag ? "" : t.tag)}
        >
          <span>#{t.tag}</span>
          <em>{t.count.toLocaleString("nl-NL")}</em>
        </button>
      ))}
      {(ws.overview?.tag_vocabulary_size ?? 0) > 10 ? (
        <button type="button" className="lv-v2-kl-more" onClick={() => ws.setTagsExpanded((v) => !v)}>
          {ws.tagsExpanded ? "Toon minder" : "Toon meer"}
        </button>
      ) : null}
      {ws.overview && !ws.overview.top_tags?.length ? <p className="lv-v2-kl-muted">Geen tags</p> : null}
    </div>
  );
}
