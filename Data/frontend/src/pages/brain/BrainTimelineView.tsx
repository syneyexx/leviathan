import { useMemo, useState } from "react";
import { buildTimeline, type LiveBrainEdge, type LiveBrainNode } from "./brain-live";
import { Panel } from "./brain-shared";

export function BrainTimelineView({
  nodes,
}: {
  nodes: LiveBrainNode[];
  edges?: LiveBrainEdge[];
  onToast?: (msg: string) => void;
}) {
  const allEvents = useMemo(() => buildTimeline(nodes), [nodes]);
  const types = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of allEvents) counts.set(e.type, (counts.get(e.type) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [allEvents]);

  const [filter, setFilter] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [milestonesOnly, setMilestonesOnly] = useState(false);

  const events = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allEvents.filter((event) => {
      if (filter !== "all" && event.type !== filter) return false;
      if (milestonesOnly && !event.relevance) return false;
      if (!q) return true;
      return event.title.toLowerCase().includes(q) || event.body.toLowerCase().includes(q);
    });
  }, [allEvents, filter, milestonesOnly, query]);

  const selected = events.find((e) => e.id === selectedId) ?? events[0] ?? null;

  return (
    <div className="lv-btl">
      <div className="lv-btl-kpi">
        <article className="lv-btl-kpi-card">
          <div className="lv-btl-kpi-top">
            <span>Dated nodes</span>
          </div>
          <strong>{allEvents.length}</strong>
          <em>from created_at</em>
        </article>
        <article className="lv-btl-kpi-card">
          <div className="lv-btl-kpi-top">
            <span>Types</span>
          </div>
          <strong>{types.length}</strong>
          <em>in timeline</em>
        </article>
        <article className="lv-btl-kpi-card">
          <div className="lv-btl-kpi-top">
            <span>Visible</span>
          </div>
          <strong>{events.length}</strong>
          <em>after filters</em>
        </article>
      </div>

      <div className="lv-btl-grid">
        <Panel
          title="Timeline Filters"
          className="lv-btl-filters"
          action={
            <button
              type="button"
              className="lv-br-chip"
              onClick={() => {
                setFilter("all");
                setQuery("");
                setMilestonesOnly(false);
              }}
            >
              Reset
            </button>
          }
        >
          <input
            className="lv-br-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search events..."
            aria-label="Search events"
          />
          <ul className="lv-btl-filter-list">
            <li>
              <button
                type="button"
                className={`lv-btl-filter${filter === "all" ? " is-active" : ""}`}
                onClick={() => setFilter("all")}
              >
                <span className="lv-btl-dot" style={{ background: "#D4AF37" }} />
                <span>All</span>
                <em>{allEvents.length}</em>
              </button>
            </li>
            {types.map(([type, count]) => (
              <li key={type}>
                <button
                  type="button"
                  className={`lv-btl-filter${filter === type ? " is-active" : ""}`}
                  onClick={() => setFilter(type)}
                >
                  <span className="lv-btl-dot" style={{ background: allEvents.find((e) => e.type === type)?.color }} />
                  <span>{type}</span>
                  <em>{count}</em>
                </button>
              </li>
            ))}
          </ul>
          <label className="lv-br-field">
            <span>Ready / verified only</span>
            <input
              type="checkbox"
              checked={milestonesOnly}
              onChange={(e) => setMilestonesOnly(e.target.checked)}
            />
          </label>
        </Panel>

        <Panel title="Event Stream" className="lv-btl-stream">
          {events.length === 0 ? (
            <p className="lv-br-muted">No dated projection events.</p>
          ) : (
            <ol className="lv-btl-events">
              {events.map((event) => (
                <li key={event.id}>
                  <button
                    type="button"
                    className={`lv-btl-event${selected?.id === event.id ? " is-active" : ""}`}
                    onClick={() => setSelectedId(event.id)}
                  >
                    <span className="lv-btl-dot" style={{ background: event.color }} />
                    <div>
                      <strong>{event.title}</strong>
                      <small>
                        {event.at} · {event.type}
                      </small>
                      <p>{event.body}</p>
                    </div>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </Panel>

        <Panel title="Event Detail" className="lv-btl-detail">
          {!selected ? (
            <p className="lv-br-muted">Select an event.</p>
          ) : (
            <>
              <h3>{selected.title}</h3>
              <p className="lv-br-muted">{selected.body}</p>
              <dl className="lv-bt-meta">
                <div>
                  <dt>When</dt>
                  <dd>{selected.at}</dd>
                </div>
                <div>
                  <dt>Type</dt>
                  <dd>{selected.type}</dd>
                </div>
                <div>
                  <dt>Id</dt>
                  <dd style={{ fontSize: 11 }}>{selected.id}</dd>
                </div>
              </dl>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
