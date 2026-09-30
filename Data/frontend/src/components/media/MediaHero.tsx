import { useNavigate } from "react-router-dom";
import { mediaControlCrops } from "../../assets/mediaControlAssets";
import { Button } from "../ui";

export function MediaHero() {
  const navigate = useNavigate();
  const heroSrc = mediaControlCrops.mediaHeroWide || mediaControlCrops.mediaHero;

  return (
    <section className="lv-v2-hero lv-v2-hero--media" aria-label="Media Control">
      <div className="lv-v2-hero__media lv-v2-hero__media--media" aria-hidden="true">
        {heroSrc ? <img src={heroSrc} alt="" width={1600} height={440} /> : null}
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--media" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Media Control</h2>
        <p className="lv-v2-hero__copy">
          Complete controle over je media workflow. Genereer, bewerk, organiseer en distribueer
          AI-gegenereerde content.
        </p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" onClick={() => navigate("/media/genereren")}>
            + Nieuwe media genereren
          </Button>
          <Button variant="secondary" onClick={() => navigate("/media/library")}>
            Media bibliotheek
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        “Content is intelligence
        <br />
        in een andere vorm.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
