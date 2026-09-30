import { Link } from "react-router-dom";
import { Button, Panel, ProgressBar, StatusDot } from "../ui";
import type { MemoryWorkspace } from "../../hooks/useMemoryWorkspace";

function Donut({ byKind }: { byKind: Record<string, number> }) {
  const entries = Object.entries(byKind).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
  const top = entries.slice(0, 5);
  const rest = entries.slice(5).reduce((s, [, n]) => s + n, 0);
  const slices = rest > 0 ? [...top, ["Overig", rest] as [string, number]] : top;
  let acc = 0;
  const stops = slices.map(([label, n], i) => {
    const start = (acc / total) * 100;
    acc += n;
    const end = (acc / total) * 100;
    const colors = ["#a78bfa", "#38bdf8", "#34d399", "#fbbf24", "#f97316", "#64748b"];
    return { label, n, start, end, color: colors[i % colors.length] };
  });
  const gradient = stops.map((s) => `${s.color} ${s.start}% ${s.end}%`).join(", ");

  return (
    <div className="lv-v2-memory-donut">
      <div
        className="lv-v2-memory-donut__chart"
        style={{ background: `conic-gradient(${gradient || "#1e293b 0 100%"})` }}
        role="img"
        aria-label={stops.map((s) => `${s.label} ${Math.round((s.n / total) * 100)}%`).join(", ")}
      />
      <ul className="lv-v2-memory-donut__legend">
        {stops.map((s) => (
          <li key={s.label}>
            <span style={{ background: s.color }} />
            {s.label} {Math.round((s.n / total) * 100)}%
          </li>
        ))}
      </ul>
    </div>
  );
}

function AnalyticsChart({ ws }: { ws: MemoryWorkspace }) {
  const series = ws.analytics?.series;
  const ranges = ["24h", "7d", "30d", "90d"] as const;
  const all = [
    ...(series?.new_items.map((d) => d.count) || []),
    ...(series?.searches.map((d) => d.count) || []),
    ...(series?.embeddings.map((d) => d.count) || []),
  ];
  const max = Math.max(...all, 1);
  const n = series?.new_items.length || 0;

  return (
    <Panel
      title="Geheugen Analytics"
      action={
        <div className="lv-v2-segmented" role="group" aria-label="Periode">
          {ranges.map((r) => (
            <button
              key={r}
              type="button"
              className={ws.analyticsRange === r ? "is-active" : undefined}
              aria-pressed={ws.analyticsRange === r}
              onClick={() => ws.setAnalyticsRange(r)}
            >
              {r === "24h" ? "24u" : r}
            </button>
          ))}
        </div>
      }
    >
      {!series || n === 0 ? (
        <p className="lv-v2-muted">Geen tijdreeks beschikbaar.</p>
      ) : (
        <div className="lv-v2-memory-chart" role="img" aria-label="Analytics lijndiagram">
          <svg viewBox="0 0 320 120" preserveAspectRatio="none">
            {(["new_items", "searches", "embeddings"] as const).map((key, idx) => {
              const data = series[key];
              const color = ["#34d399", "#38bdf8", "#a78bfa"][idx];
              const pts = data
                .map((d, i) => {
                  const x = n <= 1 ? 0 : (i / (n - 1)) * 320;
                  const y = 110 - (d.count / max) * 100;
                  return `${x},${y}`;
                })
                .join(" ");
              return (
                <polyline
                  key={key}
                  fill="none"
                  stroke={color}
                  strokeWidth="2"
                  points={pts}
                />
              );
            })}
          </svg>
          <ul className="lv-v2-memory-chart__legend">
            <li>
              <span style={{ background: "#34d399" }} /> Nieuwe items
            </li>
            <li>
              <span style={{ background: "#38bdf8" }} /> Zoekopdrachten
            </li>
            <li>
              <span style={{ background: "#a78bfa" }} /> Embeddings
            </li>
          </ul>
        </div>
      )}
    </Panel>
  );
}

export function MemoryRightColumn({ ws }: { ws: MemoryWorkspace }) {
  const sem = ws.semanticIndex;
  const status = String(sem?.status || "UNKNOWN").toUpperCase();
  const tone =
    status === "HEALTHY"
      ? ("success" as const)
      : status === "EMPTY" || status === "NON_SEMANTIC_PROVIDER"
        ? ("warning" as const)
        : status === "UNAVAILABLE"
          ? ("danger" as const)
          : ("muted" as const);

  const proc = ws.processing;

  return (
    <div className="lv-v2-memory-right">
      <AnalyticsChart ws={ws} />

      <Panel
        title="Semantic Index"
        action={
          <Button variant="secondary" size="sm" loading={ws.busy} onClick={() => void ws.optimizeIndex()}>
            Index optimaliseren
          </Button>
        }
      >
        <dl className="lv-v2-memory-kv">
          <div>
            <dt>Backend</dt>
            <dd>{sem?.backend || "sqlite_control_memory_embeddings"}</dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd>{sem?.provider_id || "—"}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{sem?.model_id || "—"}</dd>
          </div>
          <div>
            <dt>Dimensie</dt>
            <dd>{sem?.dimensions ?? "—"}</dd>
          </div>
          <div>
            <dt>Geïndexeerd</dt>
            <dd>{sem?.indexed_count ?? 0}</dd>
          </div>
          <div>
            <dt>Stale</dt>
            <dd>{sem?.stale_count ?? 0}</dd>
          </div>
          <div>
            <dt>Index grootte</dt>
            <dd>
              {sem?.bytes_provenance === "MEASURED" && sem.bytes != null
                ? ws.formatBytes(sem.bytes)
                : "UNMEASURED"}
            </dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd className="lv-v2-memory-status">
              <StatusDot tone={tone} title={status} />
              {status}
              {sem?.is_semantic === false ? " · niet-semantisch" : null}
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel title="Geheugen Types">
        <Donut byKind={ws.overview?.by_kind || ws.analytics?.by_kind || {}} />
      </Panel>

      <Panel title="Geheugen Beheer">
        <div className="lv-v2-memory-manage">
          <Button variant="secondary" onClick={() => ws.setCreateOpen(true)}>
            Nieuwe notitie
          </Button>
          <Link className="lv-v2-button lv-v2-button--secondary" to="/knowledge">
            Document uploaden
          </Link>
          <Link className="lv-v2-button lv-v2-button--secondary" to="/research">
            Web content opslaan
          </Link>
          <Button
            variant="secondary"
            onClick={() => {
              void ws.loadConversations();
              ws.setConversationOpen(true);
            }}
          >
            Van gesprek opslaan
          </Button>
        </div>
        <p className="lv-v2-muted lv-v2-memory-manage-note">
          Documenten horen in Knowledge Library; web-acquisitie via Research. Memory bewaart alleen
          expliciete afgeleide herinneringen.
        </p>
      </Panel>

      <Panel
        title="Automatische Verwerking"
        action={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => ws.setProcessingSettingsOpen(true)}
          >
            Verwerkingsinstellingen
          </Button>
        }
      >
        {!proc ? (
          <p className="lv-v2-muted">Settings laden…</p>
        ) : (
          <ul className="lv-v2-memory-processing">
            {(
              [
                ["embeddings_enabled", "Embeddings genereren"],
                ["summarization_enabled", "Content samenvatten"],
                ["entity_extraction_enabled", "Entiteiten extraheren"],
                ["brain_projection_enabled", "Brain graph updaten"],
                ["duplicate_detection_enabled", "Duplicaat detectie"],
              ] as const
            ).map(([key, label]) => (
              <li key={key}>
                <label className="lv-v2-switch-row">
                  <span>{label}</span>
                  <input
                    type="checkbox"
                    role="switch"
                    aria-checked={Boolean(proc[key])}
                    checked={Boolean(proc[key])}
                    disabled={ws.busy}
                    onChange={(e) => void ws.patchProcessing({ [key]: e.target.checked })}
                  />
                </label>
              </li>
            ))}
          </ul>
        )}
        {sem?.status === "UNAVAILABLE" && proc?.embeddings_enabled ? (
          <p className="lv-v2-warn">Embeddings enabled, maar provider UNAVAILABLE.</p>
        ) : null}
      </Panel>
    </div>
  );
}

export function MemoryBottomRow({ ws }: { ws: MemoryWorkspace }) {
  return (
    <section className="lv-v2-memory-bottom" aria-label="Activiteit en bronnen">
      <Panel title="Recente Activiteit">
        <ul className="lv-v2-memory-activity">
          {(ws.activity || []).slice(0, 8).map((ev) => (
            <li key={ev.event_id}>
              <time>{new Date(ev.created_at).toLocaleTimeString("nl-NL")}</time>
              <span>{ev.event_type.replace(/^memory\./, "")}</span>
              <em>{ev.actor || "System"}</em>
            </li>
          ))}
          {ws.activity.length === 0 ? <li className="lv-v2-muted">Nog geen activiteit.</li> : null}
        </ul>
      </Panel>

      <Panel title="Top Bronnen">
        <table className="lv-v2-table lv-v2-table--compact">
          <thead>
            <tr>
              <th>Source</th>
              <th>Items</th>
              <th>Opslag</th>
            </tr>
          </thead>
          <tbody>
            {(ws.analytics?.top_sources || []).slice(0, 6).map((s) => (
              <tr key={s.source}>
                <td>{s.source}</td>
                <td>{s.items}</td>
                <td>
                  {s.bytes_provenance === "MEASURED" ? ws.formatBytes(s.bytes) : "UNMEASURED"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Meest Gezochte Topics">
        <table className="lv-v2-table lv-v2-table--compact">
          <thead>
            <tr>
              <th>Topic</th>
              <th>Queries</th>
              <th>Trend</th>
            </tr>
          </thead>
          <tbody>
            {(ws.analytics?.topics || []).slice(0, 6).map((t) => (
              <tr key={t.topic}>
                <td>{t.topic}</td>
                <td>{t.queries}</td>
                <td>{t.trend_pct == null ? "—" : `${t.trend_pct > 0 ? "+" : ""}${t.trend_pct}%`}</td>
              </tr>
            ))}
            {(ws.analytics?.topics || []).length === 0 ? (
              <tr>
                <td colSpan={3} className="lv-v2-muted">
                  Nog geen veilige topic-telemetrie.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </Panel>

      <Panel title="Recent Toegevoegde">
        <ul className="lv-v2-memory-recent">
          {ws.recentAdded.map((m) => (
            <li key={m.memory_id}>
              <button type="button" onClick={() => void ws.openDetail(m.memory_id)}>
                <strong>{m.content.slice(0, 48)}</strong>
                <span>{m.kind}</span>
                <time>{new Date(m.created_at).toLocaleTimeString("nl-NL")}</time>
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      {ws.overview ? (
        <div className="lv-v2-memory-lifecycle" aria-label="Lifecycle counts">
          <span>Active {ws.overview.active}</span>
          <ProgressBar value={ws.overview.total ? (ws.overview.active / ws.overview.total) * 100 : 0} />
          <span>Archived {ws.overview.archived}</span>
          <span>Revoked {ws.overview.revoked}</span>
          <span>Superseded {ws.overview.superseded}</span>
        </div>
      ) : null}
    </section>
  );
}
