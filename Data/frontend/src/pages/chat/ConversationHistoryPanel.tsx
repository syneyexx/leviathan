import { useMemo, useState, type RefObject } from "react";
import { EmptyState, LoadingState } from "../../components/ui";
import type { Conversation } from "../../types/api";
import {
  formatConversationTime,
  groupConversationsByDate,
} from "./chatHelpers";

export type ConversationHistoryPanelProps = {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  bootstrapped?: boolean;
  creating?: boolean;
  searchQuery?: string;
  onSearchChange?: (query: string) => void;
  /** Mobile drawer open — adds is-drawer-open for CSS. */
  drawerOpen?: boolean;
  searchInputRef?: RefObject<HTMLInputElement | null>;
};

export function ConversationHistoryPanel({
  conversations,
  activeId,
  onSelect,
  onCreate,
  bootstrapped = true,
  creating = false,
  searchQuery,
  onSearchChange,
  drawerOpen = false,
  searchInputRef,
}: ConversationHistoryPanelProps) {
  const [localQuery, setLocalQuery] = useState("");
  const query = searchQuery ?? localQuery;
  const setQuery = onSearchChange ?? setLocalQuery;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((item) => item.title.toLowerCase().includes(q));
  }, [conversations, query]);

  const groups = useMemo(() => groupConversationsByDate(filtered), [filtered]);

  return (
    <aside
      className={`lv-v2-chat-col lv-v2-chat-col--history${drawerOpen ? " is-drawer-open" : ""}`}
      aria-label="Gesprekshistorie"
    >
      <div className="lv-v2-chat-col__head">
        <h2 className="lv-v2-chat-col__title">Gesprekshistorie</h2>
      </div>

      <div className="lv-v2-chat-search-row">
        <label className="lv-v2-chat-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <span className="lv-v2-sr-only">Zoek gesprekken</span>
          <input
            ref={searchInputRef}
            type="search"
            placeholder="Zoek gesprekken..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={!bootstrapped}
          />
        </label>
        <button
          type="button"
          className="lv-v2-icon-btn"
          aria-label="Nieuw gesprek"
          title="Nieuw gesprek"
          disabled={creating || !bootstrapped}
          onClick={onCreate}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </div>

      <div className="lv-v2-chat-history">
        {!bootstrapped ? (
          <LoadingState label="Gesprekken laden…" />
        ) : groups.length === 0 ? (
          <EmptyState
            title={query.trim() ? "Geen matches" : "Nog geen gesprekken"}
            detail={
              query.trim()
                ? "Pas je zoekopdracht aan of start een nieuw gesprek."
                : "Start een nieuw gesprek met de + knop."
            }
          />
        ) : (
          groups.map((group) => (
            <div key={group.id} className="lv-v2-chat-group">
              <div className="lv-v2-chat-group__label">{group.label}</div>
              {group.items.map((item) => {
                const active = item.id === activeId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`lv-v2-thread${active ? " is-active" : ""}`}
                    aria-current={active ? "true" : undefined}
                    onClick={() => onSelect(item.id)}
                  >
                    <span className="lv-v2-thread__icon" aria-hidden="true">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M5 6h14v9H9l-4 4V6z" />
                      </svg>
                    </span>
                    <span>
                      <span className="lv-v2-thread__title">{item.title || "Zonder titel"}</span>
                    </span>
                    <span className="lv-v2-thread__time">
                      {formatConversationTime(item.updated_at || item.created_at)}
                    </span>
                  </button>
                );
              })}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
