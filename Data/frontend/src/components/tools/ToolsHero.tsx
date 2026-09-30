export function ToolsHero() {
  return (
    <section className="lv-v2-hero lv-v2-hero--tools" aria-label="Tools">
      <div className="lv-v2-hero__media lv-v2-hero__media--tools" aria-hidden="true">
        <img src="/assets/hero-tools.jpg" alt="" width={1600} height={360} />
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--tools" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Tools</h2>
        <p className="lv-v2-hero__copy">
          Ontdek, configureer en beheer alle tools die beschikbaar zijn voor agents en runtimes.
        </p>
        <p className="lv-v2-hero__subcopy">
          Tools kunnen lokaal, via plugins of via MCP servers worden geladen. Gebruik tools om agents
          uit te breiden met externe functionaliteit.
        </p>
      </div>
      <blockquote className="lv-v2-hero__quote">
        “Tools empower agents
        <br />
        to turn intelligence into action.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
