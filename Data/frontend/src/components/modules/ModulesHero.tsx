import { Button } from "../ui";
import { pluginRuntimeHeroes } from "../../assets/pluginRuntimeAssets";

type Props = {
  onInstallNew: () => void;
  onOpenManager: () => void;
};

export function ModulesHero({ onInstallNew, onOpenManager }: Props) {
  const heroSrc = pluginRuntimeHeroes.modules;

  return (
    <section className="lv-v2-hero lv-v2-hero--modules" aria-label="Modules">
      <div className="lv-v2-hero__media lv-v2-hero__media--modules" aria-hidden="true">
        {heroSrc ? <img src={heroSrc} alt="" width={1600} height={360} /> : null}
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--modules" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Modules</h2>
        <p className="lv-v2-hero__copy">
          Ontdek, installeer en beheer modules, agents, tools en externe capabilities. Breid
          Leviathan uit met krachtige functionaliteit voor research, trading en automatisering.
        </p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" size="sm" onClick={onInstallNew}>
            + Nieuwe module installeren
          </Button>
          <Button variant="secondary" size="sm" onClick={onOpenManager}>
            Module manager bekijken
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        Modulaire intelligentie.
        <br />
        One ecosystem. Infinite capabilities.
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
