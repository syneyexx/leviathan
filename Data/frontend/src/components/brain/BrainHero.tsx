import { useNavigate } from "react-router-dom";
import { Button } from "../ui";

type BrainHeroProps = {
  onOpenGraph: () => void;
};

/** Screen 1 hero — Leviathan Brain. Art is an inline SVG abstraction (no exact raster asset in repo). */
export function BrainHero({ onOpenGraph }: BrainHeroProps) {
  const navigate = useNavigate();

  return (
    <section className="lv-v2-hero lv-v2-hero--brain" aria-label="Leviathan Brain">
      <div className="lv-v2-hero__media lv-v2-hero__media--brain" aria-hidden="true">
        <BrainHeroArt />
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--brain" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Leviathan Brain</h2>
        <p className="lv-v2-hero__copy">
          Een geïntegreerd kennisnetwerk dat informatie begrijpt, onthoudt en redeneert. Verbindt data,
          documenten, ervaringen en real-time inzichten tot één levende kennisbasis voor al je AI agents.
        </p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" onClick={() => navigate("/knowledge")}>
            + Nieuwe kennis bron
          </Button>
          <Button variant="secondary" onClick={onOpenGraph}>
            Kennis grafiek openen
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        “Kennis is de fundering
        <br />
        van intelligente actie.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}

/** Replaceable hero art — stylized neural brain (cyan wireframe). */
function BrainHeroArt() {
  return (
    <svg className="lv-v2-brain-art" viewBox="0 0 480 220" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <radialGradient id="lv2-brain-glow" cx="55%" cy="45%" r="45%">
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.45" />
          <stop offset="55%" stopColor="#3b82f6" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#020617" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="lv2-brain-stroke" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#67e8f9" />
          <stop offset="100%" stopColor="#3b82f6" />
        </linearGradient>
      </defs>
      <ellipse cx="260" cy="110" rx="160" ry="90" fill="url(#lv2-brain-glow)" />
      <path
        d="M180 120c-8-40 18-72 58-78 22-28 70-28 92 2 38 2 62 28 58 64-2 22-14 40-34 50 4 18-6 36-28 40-18 22-54 22-72 2-24 6-48-6-56-28-20-4-32-22-18-52z"
        fill="none"
        stroke="url(#lv2-brain-stroke)"
        strokeWidth="1.6"
        opacity="0.9"
      />
      <path d="M210 70c20-18 48-22 72-10M200 100c28-8 56-6 80 8M210 140c24 10 52 12 78 2M250 55c6 30 8 60 2 92M280 58c4 28 6 56 0 88M310 68c-2 26 0 52 6 78"
        fill="none" stroke="#22d3ee" strokeWidth="1" opacity="0.55" />
      {[
        [220, 78], [248, 64], [278, 70], [308, 82], [330, 108],
        [318, 136], [290, 152], [258, 158], [228, 146], [210, 118],
        [240, 100], [270, 112], [300, 120], [255, 128],
      ].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 3.2 : 2.2} fill={i % 4 === 0 ? "#67e8f9" : "#3b82f6"} opacity="0.85" />
      ))}
      <g opacity="0.35" stroke="#22d3ee" strokeWidth="0.8">
        <line x1="140" y1="40" x2="200" y2="70" />
        <line x1="360" y1="40" x2="320" y2="75" />
        <line x1="380" y1="160" x2="330" y2="140" />
        <line x1="130" y1="160" x2="200" y2="140" />
      </g>
    </svg>
  );
}
