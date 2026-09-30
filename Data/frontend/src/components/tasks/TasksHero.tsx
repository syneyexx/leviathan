import { media } from "../../assets/media";

export function TasksHero() {
  return (
    <section className="lv-v2-hero lv-v2-hero--tasks" aria-label="Taken">
      <div className="lv-v2-hero__media lv-v2-hero__media--tasks" aria-hidden="true">
        {media.hero ? <img src={media.hero} alt="" width={1600} height={440} /> : null}
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--tasks" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Taken</h2>
        <p className="lv-v2-hero__copy">
          Overzicht van alle lopende, geplande en voltooide taken in het systeem.
        </p>
        <p className="lv-v2-tasks-hero-sub">
          Monitor real-time voortgang, bekijk logs, beheer prioriteiten en controleer resource gebruik.
        </p>
      </div>
      <blockquote className="lv-v2-hero__quote">
        “Every task moves us closer to intelligence.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
