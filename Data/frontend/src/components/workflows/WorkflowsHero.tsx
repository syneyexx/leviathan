import { Button } from "../ui";
import { tradingHeroes } from "../../assets/tradingAssets";

type Props = {
  onNewWorkflow: () => void;
  onOpenTemplates: () => void;
};

export function WorkflowsHero({ onNewWorkflow, onOpenTemplates }: Props) {
  const heroSrc = tradingHeroes.workflows;

  return (
    <section className="lv-v2-hero lv-v2-hero--workflows" aria-label="Workflows">
      <div className="lv-v2-hero__media lv-v2-hero__media--workflows" aria-hidden="true">
        {heroSrc ? <img src={heroSrc} alt="" width={1600} height={360} /> : null}
        <WorkflowsHeroArt />
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--workflows" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Workflows</h2>
        <p className="lv-v2-hero__copy">
          Visualiseer, bouw en beheer geavanceerde workflows. Combineer agents, tools, MCP servers en
          externe systemen in krachtige automatiseringen.
        </p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" size="sm" onClick={onNewWorkflow}>
            + Nieuwe workflow
          </Button>
          <Button variant="secondary" size="sm" onClick={onOpenTemplates}>
            Templates
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        Van losse tools naar
        <br />
        intelligente workflows.
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}

function WorkflowsHeroArt() {
  return (
    <svg
      className="lv-v2-workflows-art"
      viewBox="0 0 520 220"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <radialGradient id="lv2-wf-glow" cx="60%" cy="45%" r="55%">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.4" />
          <stop offset="60%" stopColor="#2563eb" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#020617" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="300" cy="110" rx="180" ry="95" fill="url(#lv2-wf-glow)" />
      <path
        d="M90 120 C160 60, 220 50, 280 90 S380 150, 450 100"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="1.5"
        opacity="0.75"
      />
      <path
        d="M120 150 C200 130, 260 160, 340 120 S420 80, 480 130"
        fill="none"
        stroke="#60a5fa"
        strokeWidth="1.2"
        opacity="0.45"
      />
      <g>
        <rect x="70" y="95" width="78" height="36" rx="8" fill="#0b1220" stroke="#38bdf8" strokeWidth="1.2" />
        <text x="109" y="117" textAnchor="middle" fill="#e2e8f0" fontSize="11" fontFamily="system-ui">
          Agents
        </text>
      </g>
      <g>
        <rect x="220" y="55" width="72" height="36" rx="8" fill="#0b1220" stroke="#818cf8" strokeWidth="1.2" />
        <text x="256" y="77" textAnchor="middle" fill="#e2e8f0" fontSize="11" fontFamily="system-ui">
          Tools
        </text>
      </g>
      <g>
        <rect x="380" y="110" width="72" height="36" rx="8" fill="#0b1220" stroke="#22d3ee" strokeWidth="1.2" />
        <text x="416" y="132" textAnchor="middle" fill="#e2e8f0" fontSize="11" fontFamily="system-ui">
          APIs
        </text>
      </g>
      <circle cx="200" cy="100" r="4" fill="#67e8f9" />
      <circle cx="310" cy="80" r="4" fill="#818cf8" />
      <circle cx="350" cy="140" r="3.5" fill="#38bdf8" />
    </svg>
  );
}
