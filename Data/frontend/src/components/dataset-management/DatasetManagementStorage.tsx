import { formatBytes } from "../../pages/datasets/datasetManagementFormat";
import type { DatasetManagementWorkspace } from "../../hooks/useDatasetManagementWorkspace";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetManagementStorage({ ws }: Props) {
  const storage = ws.overview?.storage;
  const used = storage?.usedBytes ?? ws.overview?.totalKnownBytes ?? 0;
  const capacity = storage?.capacityBytes;
  const pct = storage?.usedPercent ?? null;
  const breakdown = storage?.breakdown ?? [];

  return (
    <section className="lv-v2-panel lv-v2-dm-storage" aria-label="Opslag">
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">Opslag</h3>
        <span className="lv-v2-panel__meta">
          {formatBytes(used)}
          {capacity != null ? ` / ${formatBytes(capacity)}` : ""}
        </span>
      </div>
      <div className="lv-v2-panel__body">
        {pct != null ? (
          <div className="lv-v2-dm-storage__bar" aria-label={`${pct}% bezet`}>
            <i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
          </div>
        ) : (
          <p className="lv-v2-dm-empty">Capaciteit ongemeten</p>
        )}

        {breakdown.length > 0 ? (
          <ul className="lv-v2-dm-storage__breakdown">
            {breakdown.map((b) => (
              <li key={b.id}>
                <span>{b.label}</span>
                <strong>
                  {b.bytes == null
                    ? b.provenance === "UNMEASURED"
                      ? "UNMEASURED"
                      : "—"
                    : formatBytes(b.bytes)}
                </strong>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="lv-v2-dm-storage__tags-head">
          <h4 className="lv-v2-dm-storage__tags-title">Populaire tags</h4>
          {ws.tagFilter ? (
            <button
              type="button"
              className="lv-v2-dm-pill is-tag is-active"
              onClick={() => ws.setTagFilter(null)}
            >
              Wis filter: {ws.tagFilter}
            </button>
          ) : null}
        </div>
        <div className="lv-v2-dm-tag-cloud">
          {ws.tagCloud.length === 0 ? (
            <span className="lv-v2-dm-pill">Geen tags</span>
          ) : (
            ws.tagCloud.map((t) => (
              <button
                key={t.tag}
                type="button"
                className={`lv-v2-dm-pill is-tag${ws.tagFilter === t.tag ? " is-active" : ""}`}
                onClick={() => ws.setTagFilter(ws.tagFilter === t.tag ? null : t.tag)}
              >
                {t.tag} ({t.count})
              </button>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
