import type { DatasetOverview } from "../../types/api";

type Props = {
  overview: DatasetOverview | null;
  loading: boolean;
};

export function DatasetMgmtTags({ overview, loading }: Props) {
  const tags = overview?.tagCounts ?? [];
  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-tags" aria-label="Populaire tags">
      <h3 className="lv-v2-panel__title">Populaire tags</h3>
      {loading ? (
        <p className="lv-v2-dm-muted">Tags laden…</p>
      ) : tags.length === 0 ? (
        <p className="lv-v2-dm-muted">Geen tags in metadata</p>
      ) : (
        <div className="lv-v2-dm-tag-cloud">
          {tags.map((t) => (
            <span key={t.tag} className="lv-v2-dm-tag">
              {t.tag} ({t.count})
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
