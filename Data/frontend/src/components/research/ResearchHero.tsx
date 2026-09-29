import { Button } from "../ui";
import { mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { RD_HERO } from "../../config/research";

type Props = {
  onNewResearch: () => void;
  onTemplates: () => void;
};

export function ResearchHero({ onNewResearch, onTemplates }: Props) {
  const heroSrc = mediaPageHeroes.research;

  return (
    <section className="lv-v2-hero lv-v2-hero--research" aria-label="Leviathan Research">
      <div className="lv-v2-hero__media lv-v2-hero__media--research" aria-hidden="true">
        {heroSrc ? (
          <img src={heroSrc} alt="" width={1600} height={440} />
        ) : (
          <ResearchHeroArt />
        )}
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--research" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">{RD_HERO.title}</h2>
        <p className="lv-v2-hero__copy">{RD_HERO.description}</p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" onClick={onNewResearch}>
            + Nieuw Onderzoek
          </Button>
          <Button variant="secondary" onClick={onTemplates}>
            Voorbeeld templates
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        {RD_HERO.quoteLines[0]}
        <br />
        {RD_HERO.quoteLines[1]}
        <cite>{RD_HERO.cite}</cite>
      </blockquote>
    </section>
  );
}

function ResearchHeroArt() {
  return (
    <svg className="lv-v2-research-art" viewBox="0 0 480 220" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <radialGradient id="lv2-research-glow" cx="60%" cy="45%" r="50%">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.4" />
          <stop offset="55%" stopColor="#3b82f6" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#020617" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="280" cy="110" rx="150" ry="85" fill="url(#lv2-research-glow)" />
      <circle cx="280" cy="110" r="48" fill="none" stroke="#38bdf8" strokeWidth="1.4" opacity="0.7" />
      <circle cx="280" cy="110" r="28" fill="none" stroke="#818cf8" strokeWidth="1.2" opacity="0.55" />
      <circle cx="280" cy="110" r="8" fill="#67e8f9" opacity="0.9" />
      {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => {
        const r = (deg * Math.PI) / 180;
        const x = 280 + Math.cos(r) * 70;
        const y = 110 + Math.sin(r) * 55;
        return <circle key={deg} cx={x} cy={y} r="2.5" fill="#3b82f6" opacity="0.8" />;
      })}
    </svg>
  );
}
