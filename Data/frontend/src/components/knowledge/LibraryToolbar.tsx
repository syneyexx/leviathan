import { KL_SORT_OPTIONS } from "../../pages/knowledge/constants";
import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/**
 * Library search + type/tag/date/sort filters + list/grid toggle + bulk actions.
 * Bulk tag/delete operate on `ws.checked` against bounded APIs only.
 */
export function LibraryToolbar({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  return (
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
      <select value={ws.tagFilter} onChange={(e) => ws.setTagFilter(e.target.value)} aria-label="Alle tags">
        <option value="">Alle tags</option>
        {(ws.overview?.top_tags ?? []).map((t) => (
          <option key={t.tag} value={t.tag}>
            #{t.tag}
          </option>
        ))}
      </select>
      <select
        value={ws.datePreset}
        onChange={(e) => ws.setDatePreset(e.target.value)}
        aria-label="Alle datums"
      >
        <option value="">Alle datums</option>
        <option value="7d">Laatste 7 dagen</option>
        <option value="30d">Laatste 30 dagen</option>
        <option value="90d">Laatste 90 dagen</option>
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
          aria-label="Lijstweergave"
        >
          List
        </button>
        <button
          type="button"
          className={ws.viewMode === "grid" ? "is-active" : undefined}
          onClick={() => ws.setViewMode("grid")}
          aria-label="Rasterweergave"
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
  );
}
