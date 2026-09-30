import { Button } from "../ui";
import { onderzoekHeroes } from "../../assets/onderzoekKennisAssets";

type Props = {
  onNewNote: () => void;
  onBrain: () => void;
};

export function MemoryHero({ onNewNote, onBrain }: Props) {
  const heroSrc = onderzoekHeroes.geheugen;

  return (
    <section className="lv-v2-hero lv-v2-hero--memory" aria-label="Leviathan Geheugen">
      <div className="lv-v2-hero__media lv-v2-hero__media--memory" aria-hidden="true">
        {heroSrc ? <img src={heroSrc} alt="" width={1600} height={440} /> : null}
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--memory" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Geheugen</h2>
        <p className="lv-v2-hero__copy">
          Centrale geheugenslaag voor duurzame context, voorkeuren, beslissingen, ervaringen en
          afgeleide herinneringen van Leviathan.
        </p>
        <p className="lv-v2-hero__copy lv-v2-hero__copy--secondary">
          Zoek, beheer, verrijk en analyseer gecontroleerde memories met scope-veilige retrieval en
          AI-gestuurde verwerking.
        </p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" size="sm" onClick={onNewNote}>
            + Nieuwe notitie
          </Button>
          <Button variant="secondary" size="sm" onClick={onBrain}>
            Open Brain
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        “Memory turns information
        <br />
        into intelligence.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
