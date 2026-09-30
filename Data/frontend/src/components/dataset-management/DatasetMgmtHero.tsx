import { DM_PAGE_COPY } from "../../pages/dataset-management/constants";

type Props = {
  onAddDataset: () => void;
};

export function DatasetMgmtHero({ onAddDataset }: Props) {
  return (
    <section className="lv-v2-hero lv-v2-hero--dm" aria-label="Dataset Management">
      <div className="lv-v2-hero__shade lv-v2-hero__shade--dm" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">{DM_PAGE_COPY.title}</h2>
        <p className="lv-v2-dm-hero-pillars">{DM_PAGE_COPY.pillars.join(". ")}.</p>
        <p className="lv-v2-hero__copy">{DM_PAGE_COPY.subtitle}</p>
        <p className="lv-v2-hero__copy lv-v2-hero__copy--secondary">{DM_PAGE_COPY.intro}</p>
        <div className="lv-v2-hero__actions">
          <button type="button" className="lv-v2-button lv-v2-button--primary lv-v2-button--sm" onClick={onAddDataset}>
            + Dataset toevoegen
          </button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        “{DM_PAGE_COPY.quote}”
        <cite>{DM_PAGE_COPY.quoteAttribution}</cite>
      </blockquote>
    </section>
  );
}
