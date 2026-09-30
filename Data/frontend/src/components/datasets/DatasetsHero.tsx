import { DH_PAGE_COPY } from "../../mocks/datasets-dashboard";

export function DatasetsHero() {
  return (
    <section className="lv-v2-hero lv-v2-hero--datasets" aria-label="Datasets">
      <div className="lv-v2-hero__media lv-v2-hero__media--datasets" aria-hidden="true">
        <img src="/assets/hero-datasets.jpg" alt="" width={1600} height={440} />
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--datasets" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">{DH_PAGE_COPY.title}</h2>
        <p className="lv-v2-hero__copy">{DH_PAGE_COPY.subtitle}</p>
        <p className="lv-v2-ds-hero-sub">{DH_PAGE_COPY.description}</p>
      </div>
      <blockquote className="lv-v2-hero__quote">{DH_PAGE_COPY.quote}</blockquote>
    </section>
  );
}
