import { DS_PAGE_COPY } from "../../pages/datasets/constants";

/**
 * Optional hero for non-primary surfaces. `/datasets` primary composition
 * uses AppTopbarV2 as page header (reference has no hero between topbar and KPIs).
 * Preserve this component for any secondary/demo usage.
 */
export function DatasetsHero() {
  return (
    <section className="lv-v2-hero lv-v2-hero--datasets" aria-label="Datasets">
      <div className="lv-v2-hero__media lv-v2-hero__media--datasets" aria-hidden="true">
        <img src="/assets/hero-datasets.jpg" alt="" width={1600} height={440} />
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--datasets" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">{DS_PAGE_COPY.title}</h2>
        <p className="lv-v2-hero__copy">{DS_PAGE_COPY.subtitle}</p>
      </div>
    </section>
  );
}
