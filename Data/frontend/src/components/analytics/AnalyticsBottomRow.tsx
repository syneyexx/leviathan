import type { AnalyticsDashboard } from "../../types/api";

function bytesLabel(used: number | null, total: number | null): string | null {
  if (used == null || total == null) return null;
  const u = used / 1024 ** 3;
  const t = total / 1024 ** 3;
  return `${u.toFixed(1)}/${Math.round(t)} GB`;
}

function ResourceBar({
  label,
  pct,
  detail,
  status,
}: {
  label: string;
  pct: number | null;
  detail?: string | null;
  status: string;
}) {
  const unmeasured = status === "UNMEASURED" || pct == null;
  return (
    <div className="lv-an-resource">
      <div className="lv-an-resource-meta">
        <span>{label}</span>
        <strong>{unmeasured ? "UNMEASURED" : `${pct}%${detail ? ` · ${detail}` : ""}`}</strong>
      </div>
      <div className="lv-an-bar lv-an-bar--tall">
        <span style={{ width: `${unmeasured ? 0 : Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

function formatSeconds(v: number | null): string {
  if (v == null) return "—";
  return `${v}s`;
}

function formatTime(iso: string): string {
  const d = Date.parse(iso);
  if (Number.isNaN(d)) return iso;
  return new Date(d).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const KIND_ICON: Record<string, string> = {
  knowledge_added: "📄",
  dataset_processed: "📦",
  research_completed: "🔬",
  sync: "🔄",
  embeddings: "🧬",
  other: "•",
};

export function AnalyticsBottomRow({ dashboard }: { dashboard: AnalyticsDashboard | null }) {
  const res = dashboard?.resources;
  const proc = dashboard?.processing;
  const act = dashboard?.activity;

  return (
    <section className="lv-an-bottom-row" aria-label="Systeem en activiteit">
      <article id="lv-an-panel-resources" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">System Resource Gebruik</div>
        </div>
        <div className="lv-an-resources lv-an-resources--v2">
          <ResourceBar label="CPU" pct={res?.cpu.pct ?? null} status={res?.cpu.status ?? "UNMEASURED"} />
          <ResourceBar
            label="RAM"
            pct={res?.ram.pct ?? null}
            detail={bytesLabel(res?.ram.usedBytes ?? null, res?.ram.totalBytes ?? null)}
            status={res?.ram.status ?? "UNMEASURED"}
          />
          <ResourceBar label="GPU" pct={res?.gpu.pct ?? null} status={res?.gpu.status ?? "UNMEASURED"} />
          <ResourceBar
            label="Disk"
            pct={res?.disk.pct ?? null}
            detail={bytesLabel(res?.disk.usedBytes ?? null, res?.disk.totalBytes ?? null)}
            status={res?.disk.status ?? "UNMEASURED"}
          />
        </div>
        {res?.disk.metric ? (
          <p className="lv-muted lv-an-coverage">Disk metric: {res.disk.metric}</p>
        ) : null}
      </article>

      <article id="lv-an-panel-verwerkingstijden" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Verwerkingstijden</div>
        </div>
        {!proc?.tasks?.length ? (
          <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>
        ) : (
          <table className="lv-an-table">
            <thead>
              <tr>
                <th>Taak</th>
                <th>Gem. Tijd</th>
                <th>Min</th>
                <th>Max</th>
                <th>Aantal</th>
              </tr>
            </thead>
            <tbody>
              {proc.tasks.map((t) => (
                <tr key={t.key}>
                  <td>{t.label}</td>
                  <td>
                    {t.status === "UNMEASURED"
                      ? "UNMEASURED"
                      : t.count === 0
                        ? "—"
                        : formatSeconds(t.avgSeconds)}
                  </td>
                  <td>{formatSeconds(t.minSeconds)}</td>
                  <td>{formatSeconds(t.maxSeconds)}</td>
                  <td>{t.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </article>

      <article id="lv-an-panel-activiteit" className="lv-panel lv-an-card">
        <div className="lv-an-card-head">
          <div className="lv-section-label">Activiteit Log</div>
          <span className="lv-muted">Laatste {act?.limit ?? 10}</span>
        </div>
        {!act?.items?.length ? (
          <p className="lv-muted lv-an-empty">Geen gegevens in deze periode.</p>
        ) : (
          <ul className="lv-an-activity">
            {act.items.map((item, i) => (
              <li key={`${item.t}-${i}`}>
                <time>{formatTime(item.t)}</time>
                <span className="lv-an-activity-icon" aria-hidden="true">
                  {KIND_ICON[item.kind] ?? "•"}
                </span>
                <div>
                  <strong>{item.event}</strong>
                  <span className="lv-muted">{item.details}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </article>
    </section>
  );
}
