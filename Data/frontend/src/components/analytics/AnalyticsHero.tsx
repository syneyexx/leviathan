import { media } from "../../assets/media";

export function AnalyticsHero() {
  return (
    <section className="lv-v2-hero lv-v2-hero--analytics lv-an-hero-v2" aria-label="Statistieken">
      <div className="lv-v2-hero__media lv-v2-hero__media--analytics" aria-hidden="true">
        {media.analyticsHero ? (
          <img src={media.analyticsHero} alt="" width={1400} height={220} />
        ) : null}
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--analytics" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Statistieken</h2>
        <p className="lv-v2-hero__copy">
          Realtime en historische statistieken van alle relevante Leviathan-systemen.
        </p>
        <p className="lv-v2-hero__copy lv-v2-hero__copy--secondary">
          Krijg inzicht in gebruik, groei, prestaties en trends.
        </p>
      </div>
      <blockquote className="lv-v2-hero__quote lv-an-hero-quote">
        “Data turns noise
        <br />
        into intelligence.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
