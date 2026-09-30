import { Button } from "../ui";
import { mediaControlCrops } from "../../assets/mediaControlAssets";

type Props = {
  onNewMission: () => void;
  onOpenRegistry: () => void;
  canLaunch: boolean;
};

export function AgentsHero({ onNewMission, onOpenRegistry, canLaunch }: Props) {
  const heroSrc = mediaControlCrops.agentsHeroWide || mediaControlCrops.agentsHeroArt;

  return (
    <section className="lv-v2-hero lv-v2-hero--agents" aria-label="Leviathan Agents">
      <div className="lv-v2-hero__media lv-v2-hero__media--agents" aria-hidden="true">
        {heroSrc ? (
          <img src={heroSrc} alt="" width={1600} height={360} />
        ) : (
          <AgentsHeroArt />
        )}
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--agents" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Leviathan Agents</h2>
        <p className="lv-v2-hero__copy">
          De orchestratie laag voor alle autonome agents, missies en toolchains. Coördineer, monitor
          en schaal gespecialiseerde AI agents voor research, trading, analyse, data, ontwikkeling
          en meer.
        </p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" onClick={onNewMission} disabled={!canLaunch} title={canLaunch ? undefined : "Geen launchable agent"}>
            + Nieuwe missie
          </Button>
          <Button variant="secondary" onClick={onOpenRegistry}>
            Registry openen
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        Specialized agents.
        <br />
        Unified intelligence.
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}

function AgentsHeroArt() {
  return (
    <svg className="lv-v2-agents-art" viewBox="0 0 480 220" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <radialGradient id="lv2-agents-glow" cx="65%" cy="40%" r="55%">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.45" />
          <stop offset="55%" stopColor="#6366f1" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#020617" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="300" cy="100" rx="160" ry="90" fill="url(#lv2-agents-glow)" />
      <path
        d="M180 140c40-70 120-90 200-40 20 14 38 40 42 68"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="1.6"
        opacity="0.7"
      />
      <circle cx="260" cy="90" r="18" fill="none" stroke="#818cf8" strokeWidth="1.3" opacity="0.65" />
      <circle cx="320" cy="75" r="10" fill="#67e8f9" opacity="0.85" />
      <circle cx="360" cy="120" r="7" fill="#3b82f6" opacity="0.8" />
    </svg>
  );
}
