import { Link } from "react-router-dom";
import { Panel } from "../ui";
import type { ConsoleOverviewResponse } from "../../types/api";
import { formatCompactCount, formatConsoleTime } from "../../pages/console/consoleFormat";

type Props = {
  overview: ConsoleOverviewResponse | null;
  onFocusError: (sequence: number) => void;
};

export function ConsoleBottomAnalytics({ overview, onFocusError }: Props) {
  const stats = overview?.stats;
  const buckets = stats?.buckets ?? [];
  const totals = stats?.totals;
  const top = stats?.top_components ?? [];
  const errors = stats?.recent_errors ?? [];
  const maxBucket = Math.max(1, ...buckets.map((b) => b.total || 0));

  return (
    <section className="lv-v2-console-analytics" aria-label="Console analytics">
      <Panel
        className="lv-v2-console-analytics__stats"
        title="Log Statistieken (Laatste 24 uur)"
        meta={
          totals
            ? `${formatCompactCount(totals.events)} events`
            : "UNMEASURED"
        }
      >
        <div className="lv-v2-console-bars" role="img" aria-label="Log volume per bucket">
          {buckets.length === 0 ? (
            <p className="lv-v2-muted">Geen chart data — UNMEASURED</p>
          ) : (
            buckets.map((b) => {
              const h = Math.max(6, Math.round(((b.total || 0) / maxBucket) * 100));
              return (
                <div
                  key={b.bucket_index}
                  className="lv-v2-console-bars__col"
                  title={`${b.total} · ${formatConsoleTime(b.bucket_start_ms, true)}`}
                >
                  <div className="lv-v2-console-bars__stack" style={{ height: `${h}%` }}>
                    <i className="is-info" style={{ flex: b.info || 0.001 }} />
                    <i className="is-ok" style={{ flex: b.success || 0 }} />
                    <i className="is-warn" style={{ flex: b.warning || 0 }} />
                    <i className="is-bad" style={{ flex: b.error || 0 }} />
                  </div>
                </div>
              );
            })
          )}
        </div>
        <div className="lv-v2-console-bars__legend">
          <span>
            <i className="is-info" /> Info ({totals?.info ?? "—"})
          </span>
          <span>
            <i className="is-ok" /> Success ({totals?.success ?? "—"})
          </span>
          <span>
            <i className="is-warn" /> Warning ({totals?.warning ?? "—"})
          </span>
          <span>
            <i className="is-bad" /> Error ({totals?.error ?? "—"})
          </span>
        </div>
      </Panel>

      <Panel
        className="lv-v2-console-analytics__top"
        title="Meest Actieve Componenten"
        meta="aandeel / totaal events"
      >
        <ol className="lv-v2-console-top-list">
          {top.length === 0 ? (
            <li className="lv-v2-muted">Geen data — UNMEASURED</li>
          ) : (
            top.map((item) => (
              <li key={`${item.rank}-${item.component}`}>
                <span className="rank">{item.rank}</span>
                <span className="name">{item.component}</span>
                <span className="bar">
                  <i
                    style={{
                      width: `${Math.round((item.share ?? 0) * 100)}%`,
                    }}
                  />
                </span>
                <span className="pct">
                  {item.share == null ? "—" : `${Math.round(item.share * 100)}%`}
                </span>
              </li>
            ))
          )}
        </ol>
      </Panel>

      <Panel
        className="lv-v2-console-analytics__errors"
        title="Recente Fouten"
        action={
          <button
            type="button"
            className="lv-v2-console-link"
            onClick={() => {
              if (errors[0]) onFocusError(errors[0].sequence);
            }}
          >
            Alles bekijken
          </button>
        }
      >
        <ul className="lv-v2-console-errors">
          {errors.length === 0 ? (
            <li className="lv-v2-muted">Geen recente fouten in venster</li>
          ) : (
            errors.map((e) => (
              <li key={e.event_id}>
                <button type="button" onClick={() => onFocusError(e.sequence)}>
                  <span className="time">{formatConsoleTime(e.created_at_ms)}</span>
                  <span className="src">{e.subsystem || e.category || e.source}</span>
                  <span className="msg">{e.message}</span>
                </button>
              </li>
            ))
          )}
        </ul>
        <p className="lv-v2-muted lv-v2-console-errors__foot">
          <Link to="/performance">Performance</Link> · product-truth components
        </p>
      </Panel>
    </section>
  );
}
