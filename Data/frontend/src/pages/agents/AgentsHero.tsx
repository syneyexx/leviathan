import { mediaControlCrops } from "../../assets/mediaControlAssets";

export function AgentsHero() {
  return (
    <section className="lv-ag-hero" aria-label="Agents">
      <div className="lv-ag-hero-media">
        <img src={mediaControlCrops.agentsHeroWide} alt="" width={1600} height={320} />
      </div>
      <div className="lv-ag-hero-shade" />
      <div className="lv-ag-hero-content">
        <div className="lv-ag-hero-line">
          <h1 className="lv-ag-hero-title">AGENTS</h1>
          <p className="lv-ag-hero-sub">
            ORCHESTRATION, WORKERS, ARCHITECTURE &amp; AUTONOMOUS EXECUTION
          </p>
        </div>
        <p className="lv-ag-hero-quote">“Coordinate. Delegate. Verify. Evolve.”</p>
      </div>
    </section>
  );
}
