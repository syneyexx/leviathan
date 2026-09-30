import type { DatasetOverview } from "../../types/api";
import { formatBytes } from "../../pages/dataset-management/viewModels";

type Props = {
  overview: DatasetOverview | null;
  loading: boolean;
};

export function DatasetMgmtStorage({ overview, loading }: Props) {
  const pct =
    overview?.capacityBytes && overview.capacityBytes > 0 && overview.usedBytes != null
      ? Math.min(100, Math.round((overview.usedBytes / overview.capacityBytes) * 100))
      : null;

  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-storage" aria-label="Opslag">
      <h3 className="lv-v2-panel__title">Opslag</h3>
      {loading ? (
        <p className="lv-v2-dm-muted">Opslag laden…</p>
      ) : (
        <>
          <p className="lv-v2-dm-storage-summary">
            {formatBytes(overview?.attributableBytes ?? null)}
            {overview?.capacityBytes ? ` van ${formatBytes(overview.capacityBytes)}` : ""} gebruikt
          </p>
          <div className="lv-v2-dm-progress">
            <i style={{ width: `${pct ?? 0}%` }} />
          </div>
          <p className="lv-v2-dm-muted">
            {pct != null ? `${pct}% bezet` : "Schijfcapaciteit niet beschikbaar op deze host"}
          </p>
          {overview?.storageBreakdown && overview.storageBreakdown.length > 0 ? (
            <ul className="lv-v2-dm-storage-breakdown">
              {overview.storageBreakdown.map((row) => (
                <li key={row.id}>
                  <span>{row.label}</span>
                  <span className="lv-v2-dm-muted">{formatBytes(row.bytes)} ({row.pct}%)</span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
}
