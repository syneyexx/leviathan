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
                <strong>{b.bytes == null ? "—" : formatBytes(b.bytes)}</strong>
              </li>
            ))}
          </ul>
        ) : null}

        <h4 className="lv-v2-dm-storage__tags-title">Populaire tags</h4>
        <div className="lv-v2-dm-tag-cloud">
          {ws.tagCloud.length === 0 ? (
            <span className="lv-v2-dm-pill">Geen tags</span>
          ) : (
            ws.tagCloud.map((t) => (
              <span key={t.tag} className="lv-v2-dm-pill is-tag">
                {t.tag} ({t.count})
              </span>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
