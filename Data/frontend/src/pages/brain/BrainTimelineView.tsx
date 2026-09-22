import { useMemo, useState } from "react";
import {
  TIMELINE_DETAIL,
  TIMELINE_EVENTS,
  TIMELINE_FILTERS,
  TIMELINE_KPI,
  TIMELINE_TREND,
  type TimelineType,
} from "./brain-mock";
import { LineChart, Panel, Spark } from "./brain-shared";

export function BrainTimelineView({ onToast }: { onToast: (msg: string) => void }) {
  const [filter, setFilter] = useState<TimelineType>("all");
  const [selectedId, setSelectedId] = useState("e2");
  const [query, setQuery] = useState("");
  const [milestonesOnly, setMilestonesOnly] = useState(false);

  const events = useMemo(() => {
    const q = query.trim().toLowerCase();
    return TIMELINE_EVENTS.filter((event) => {
      if (filter !== "all" && event.type !== filter) return false;
      if (milestonesOnly && !event.relevance) return false;
      if (!q) return true;
      return event.title.toLowerCase().includes(q) || event.body.toLowerCase().includes(q);
    });
  }, [filter, milestonesOnly, query]);

  const selected = events.find((e) => e.id === selectedId) ?? events[0] ?? TIMELINE_EVENTS[1];

  return (
    <div className="lv-btl">
      <div className="lv-btl-kpi">
        {TIMELINE_KPI.map((kpi) => (
          <article key={kpi.label} className="lv-btl-kpi-card">
            <div className="lv-btl-kpi-top">
              <span>{kpi.label}</span>
              <Spark points={kpi.spark} color={kpi.color} />
            </div>
            <strong>{kpi.value}</strong>
            <em style={{ color: kpi.color }}>{kpi.delta}</em>
          </article>
        ))}
      </div>

      <div className="lv-btl-grid">
        <Panel title="Timeline Filters" className="lv-btl-filters" action={<button type="button" className="lv-br-chip" onClick={() => { setFilter("all"); setQuery(""); }}>Reset</button>}>
          <input
            className="lv-br-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search events..."
            aria-label="Search events"
          />
          <ul className="lv-btl-filter-list">
            {TIMELINE_FILTERS.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className={`lv-btl-filter${filter === item.id ? " is-active" : ""}`}
                  onClick={() => setFilter(item.id)}
                >
                  <span className="lv-btl-dot" style={{ background: item.color }} />
                  <span>{item.label}</span>
                  <em>{item.count.toLocaleString()}</em>
                </button>
              </li>
            ))}
          </ul>
          <label className="lv-br-field">
            <span>Knowledge Domains</span>
            <select className="lv-br-select" defaultValue="all">
              <option value="all">All Domains</option>
              <option value="agents">Agents</option>
              <option value="research">Research</option>
            </select>
          </label>
          <label className="lv-br-field">
            <span>Agents</span>
            <select className="lv-br-select" defaultValue="all">
              <option value="all">All Agents</option>
              <option value="research">Research Agent</option>
            </select>
          </label>
          <button
            type="button"
            className={`lv-br-toggle${milestonesOnly ? " is-on" : ""}`}
            onClick={() => setMilestonesOnly((v) => !v)}
          >
            <span />
            Show Milestones Only
          </button>
        </Panel>

        <Panel
          title="Timeline"
          className="lv-btl-feed"
          action={
            <div className="lv-btl-feed-tools">
              <button type="button" className="lv-br-chip is-active">
                List View
              </button>
              <button type="button" className="lv-br-chip">
                Chronological
              </button>
            </div>
          }
        >
          <ol className="lv-btl-events">
            {events.map((event) => {
              const tone = TIMELINE_FILTERS.find((f) => f.id === event.type)?.color ?? "#D4AF37";
              return (
                <li key={event.id}>
                  <button
                    type="button"
                    className={`lv-btl-event${selected?.id === event.id ? " is-active" : ""}`}
                    onClick={() => setSelectedId(event.id)}
                  >
                    <span className="lv-btl-rail" style={{ background: tone }} />
                    <div className="lv-btl-event-body">
                      <time>{event.time}</time>
                      <h4>{event.title}</h4>
                      <p>{event.body}</p>
                      <div className="lv-br-tags">
                        {event.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                    </div>
                    <div className="lv-btl-event-meta">
                      <strong>{event.meta}</strong>
                      {event.relevance ? <em>{event.relevance}</em> : null}
                    </div>
                  </button>
                </li>
              );
            })}
          </ol>
        </Panel>

        <div className="lv-btl-right">
          <Panel title="Events Trend" action={<span className="lv-br-muted">Last 30 Days</span>}>
            <LineChart series={[...TIMELINE_TREND.series]} labels={[...TIMELINE_TREND.labels]} height={140} />
          </Panel>
          <Panel title="Event Details">
            <div className="lv-btl-detail-head">
              <h3>{selected?.title ?? TIMELINE_DETAIL.title}</h3>
              <time>{selected?.time}</time>
            </div>
            <dl className="lv-br-meta is-dense">
              <div>
                <dt>Type</dt>
                <dd>{TIMELINE_DETAIL.type}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{TIMELINE_DETAIL.source}</dd>
              </div>
              <div>
                <dt>Title</dt>
                <dd>{TIMELINE_DETAIL.title}</dd>
              </div>
              <div>
                <dt>Size</dt>
                <dd>{TIMELINE_DETAIL.size}</dd>
              </div>
              <div>
                <dt>Nodes Created</dt>
                <dd>{TIMELINE_DETAIL.nodes}</dd>
              </div>
              <div>
                <dt>Clusters</dt>
                <dd>{TIMELINE_DETAIL.clusters}</dd>
              </div>
              <div>
                <dt>Domain</dt>
                <dd>{TIMELINE_DETAIL.domain}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd className="is-ok">{TIMELINE_DETAIL.status}</dd>
              </div>
            </dl>
            <p className="lv-br-desc">{TIMELINE_DETAIL.description}</p>
            <div className="lv-btl-detail-actions">
              <button type="button" className="lv-br-btn" onClick={() => onToast("View Source")}>
                View Source
              </button>
              <button type="button" className="lv-br-btn" onClick={() => onToast("View Nodes")}>
                View Nodes ({TIMELINE_DETAIL.nodes})
              </button>
            </div>
            <div className="lv-btl-related">
              <div className="lv-br-panel-title">Related Events</div>
              {TIMELINE_DETAIL.related.map((item) => (
                <button key={item.title} type="button" onClick={() => onToast(item.title)}>
                  <strong>{item.title}</strong>
                  <span>{item.when}</span>
                </button>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
