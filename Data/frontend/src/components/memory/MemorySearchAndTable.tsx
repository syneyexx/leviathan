import { Button, EmptyState, Panel } from "../ui";
import type { MemoryWorkspace } from "../../hooks/useMemoryWorkspace";
import { memoryExcerpt } from "../../hooks/useMemoryWorkspace";

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("nl-NL", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function MemorySearchAndTable({ ws }: { ws: MemoryWorkspace }) {
  return (
    <div className="lv-v2-memory-main">
      <Panel
        className="lv-v2-memory-search"
        title="Geheugen Zoeken"
        action={
          ws.searchMeta?.mode ? (
            <span className="lv-v2-memory-mode">
              Mode: {ws.searchMeta.mode}
              {ws.searchMeta.degraded ? " (degraded)" : ""}
            </span>
          ) : null
        }
      >
        <form
          className="lv-v2-memory-search__form"
          onSubmit={(e) => {
            e.preventDefault();
            void ws.runSearch();
          }}
        >
          <input
            className="lv-v2-input" 
            value={ws.query}
            onChange={(e) => ws.setQuery(e.target.value)}
            placeholder="Stel je vraag of zoek in het geheugen..."
            aria-label="Zoek in geheugen"
          />
          <Button type="submit" variant="primary" loading={ws.searching}>
            Zoeken
          </Button>
          {ws.isSearchActive ? (
            <Button type="button" variant="secondary" onClick={ws.clearSearch}>
              Wissen
            </Button>
          ) : null}
        </form>

        <div className="lv-v2-memory-filters">
          <label>
            <span className="lv-v2-sr-only">Type</span>
            <select
              className="lv-v2-select"
              value={ws.kindFilter}
              onChange={(e) => ws.setKindFilter(e.target.value)}
            >
              <option value="">Alle types</option>
              {[
                "NOTE",
                "FACT",
                "EPISODIC",
                "PREFERENCE",
                "PROCEDURE",
                "DECISION",
                "SUMMARY",
                "CORRECTION",
                "PROJECT",
                "COMMITMENT",
                "RELATION",
                "RESIDUE",
              ].map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="lv-v2-sr-only">Bron</span>
            <select
              className="lv-v2-select"
              value={ws.sourceFilter}
              onChange={(e) => ws.setSourceFilter(e.target.value)}
            >
              <option value="">Alle bronnen</option>
              {["manual", "conversation", "agent", "research", "consolidation", "imported"].map(
                (s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            <span className="lv-v2-sr-only">Agent</span>
            <select
              className="lv-v2-select"
              value={ws.agentFilter}
              onChange={(e) => ws.setAgentFilter(e.target.value)}
            >
              <option value="">Alle agents</option>
              {ws.agentOptions.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="lv-v2-sr-only">Datum</span>
            <select
              className="lv-v2-select"
              value={ws.dateSort}
              onChange={(e) => ws.setDateSort(e.target.value as "newest" | "oldest")}
            >
              <option value="newest">Datum (nieuw → oud)</option>
              <option value="oldest">Datum (oud → nieuw)</option>
            </select>
          </label>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            aria-expanded={ws.advancedOpen}
            onClick={() => ws.setAdvancedOpen(!ws.advancedOpen)}
          >
            Geavanceerd
          </Button>
        </div>

        {ws.advancedOpen ? (
          <div className="lv-v2-memory-advanced" role="region" aria-label="Geavanceerde filters">
            <label>
              Status
              <select
                className="lv-v2-select"
                value={ws.statusFilter}
                onChange={(e) => ws.setStatusFilter(e.target.value as typeof ws.statusFilter)}
              >
                <option value="ACTIVE">ACTIVE</option>
                <option value="ARCHIVED">ARCHIVED</option>
                <option value="REVOKED">REVOKED</option>
                <option value="SUPERSEDED">SUPERSEDED</option>
              </select>
            </label>
            <label>
              Search mode
              <select
                className="lv-v2-select"
                value={ws.searchMode}
                onChange={(e) => ws.setSearchMode(e.target.value as typeof ws.searchMode)}
              >
                <option value="hybrid">Hybrid</option>
                <option value="lexical">Lexical (FTS)</option>
                <option value="semantic">Semantic</option>
              </select>
            </label>
            <label className="lv-v2-check">
              <input
                type="checkbox"
                checked={ws.pinnedOnly}
                onChange={(e) => ws.setPinnedOnly(e.target.checked)}
              />
              Alleen pinned
            </label>
            <label>
              Sort
              <select
                className="lv-v2-select"
                value={ws.sort}
                onChange={(e) => ws.setSort(e.target.value as typeof ws.sort)}
              >
                <option value="newest">Newest</option>
                <option value="oldest">Oldest</option>
                <option value="priority">Priority</option>
                <option value="kind">Kind</option>
                <option value="source">Source</option>
              </select>
            </label>
          </div>
        ) : null}
      </Panel>

      <Panel
        className="lv-v2-memory-table-panel"
        title="Geheugen Items"
        action={
          <span className="lv-v2-muted">
            {ws.isSearchActive ? "Zoekresultaten" : `${ws.items.length} geladen`}
          </span>
        }
      >
        {ws.listLoading && ws.items.length === 0 ? (
          <div className="lv-v2-skeleton lv-v2-memory-table-skel" aria-busy="true" />
        ) : ws.items.length === 0 ? (
          <EmptyState title="Geen memories gevonden." detail="Pas filters aan of maak een notitie." />
        ) : (
          <div className="lv-v2-table-wrap lv-v2-memory-table-wrap">
            <table className="lv-v2-table lv-v2-memory-table">
              <thead>
                <tr>
                  <th scope="col">Type</th>
                  <th scope="col">Titel / Inhoud</th>
                  <th scope="col">Bron</th>
                  <th scope="col">Agent</th>
                  <th scope="col">Datum</th>
                  <th scope="col">{ws.isSearchActive ? "Relevantie" : "Priority"}</th>
                  <th scope="col">
                    <span className="lv-v2-sr-only">Acties</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {ws.items.map((row) => {
                  const pinned = Boolean(row.pinned);
                  const relevance = row.scores?.relevance_pct;
                  const scoreLabel = ws.isSearchActive
                    ? relevance != null
                      ? `${Math.round(relevance)}%`
                      : "—"
                    : row.priority != null
                      ? `${Math.round(row.priority * 100)}%`
                      : "—";
                  return (
                    <tr
                      key={row.memory_id}
                      className={ws.selectedId === row.memory_id ? "is-selected" : undefined}
                      tabIndex={0}
                      onClick={() => void ws.openDetail(row.memory_id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          void ws.openDetail(row.memory_id);
                        }
                      }}
                    >
                      <td>
<span className={`lv-v2-badge lv-v2-badge--${
                          ["FACT", "PREFERENCE"].includes(row.kind)
                            ? "info"
                            : ["SUMMARY", "CORRECTION", "RELATION"].includes(row.kind)
                              ? "research"
                              : ["DECISION", "COMMITMENT", "PROJECT"].includes(row.kind)
                                ? "warning"
                                : ["PROCEDURE"].includes(row.kind)
                                  ? "success"
                                  : "system"
                        }`}>
                          {row.kind}
                        </span>
                      </td>
                      <td>
                        <div className="lv-v2-memory-title">
                          {pinned ? <span className="lv-v2-memory-pin" title="Pinned" aria-label="Pinned" /> : null}
                          <strong>{memoryExcerpt(row.content, 64)}</strong>
                        </div>
                      </td>
                      <td>{row.source_normalized || row.source || "—"}</td>
                      <td>{row.actor || "—"}</td>
                      <td>{formatWhen(row.updated_at || row.created_at)}</td>
                      <td>
                        <div className="lv-v2-memory-score">
                          <span
                            className="lv-v2-memory-score__bar"
                            style={{
                              width: `${Math.max(4, Math.min(100, Number(String(scoreLabel).replace("%", "")) || 0))}%`,
                            }}
                          />
                          <span>{scoreLabel}</span>
                        </div>
                      </td>
                      <td>
                        <details
                          className="lv-v2-memory-row-menu"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <summary aria-label="Acties">⋯</summary>
                          <div className="lv-v2-memory-row-menu__body">
                            <button type="button" onClick={() => void ws.openDetail(row.memory_id)}>
                              Open detail
                            </button>
                            <button type="button" onClick={() => void ws.togglePin(row.memory_id, pinned)}>
                              {pinned ? "Unpin" : "Pin"}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                void ws.openDetail(row.memory_id);
                                ws.setCorrectOpen(true);
                              }}
                            >
                              Correct
                            </button>
                            <button type="button" onClick={() => void ws.archive(row.memory_id)}>
                              Archive
                            </button>
                            <button type="button" onClick={() => void ws.revoke(row.memory_id)}>
                              Revoke
                            </button>
                            <a href={`/brain?types=memory&focus=${encodeURIComponent(row.memory_id)}`}>
                              Open Brain
                            </a>
                          </div>
                        </details>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {ws.nextCursor && !ws.isSearchActive ? (
          <div className="lv-v2-memory-pager">
            <Button variant="secondary" size="sm" loading={ws.listLoading} onClick={() => ws.loadMore()}>
              Meer laden
            </Button>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
