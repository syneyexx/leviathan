import { Button } from "../ui";
import { DM_PAGE_COPY } from "../../pages/datasets/datasetManagementConstants";
import trainingHero from "../../assets/training-hero.jpg";

type Props = {
  onAddDataset: () => void;
  onOpenLibrary?: () => void;
};

export function DatasetManagementHero({ onAddDataset, onOpenLibrary }: Props) {
  return (
    <section className="lv-v2-hero lv-v2-hero--dataset-mgmt" aria-label="Dataset Management">
      <div className="lv-v2-hero__media lv-v2-hero__media--dataset-mgmt" aria-hidden="true">
        <img src={trainingHero} alt="" width={1600} height={360} />
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--dataset-mgmt" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">{DM_PAGE_COPY.title}</h2>
        <p className="lv-v2-hero__kicker">{DM_PAGE_COPY.subtitle}</p>
        <p className="lv-v2-hero__copy">{DM_PAGE_COPY.body}</p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" size="sm" onClick={onAddDataset}>
            + Dataset toevoegen
          </Button>
          {onOpenLibrary ? (
            <Button variant="secondary" size="sm" onClick={onOpenLibrary}>
              Bibliotheek bekijken
            </Button>
          ) : null}
        </div>
        <ul className="lv-v2-dm-pillars" aria-label="Pijlers">
          {DM_PAGE_COPY.pillars.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </div>
      <blockquote className="lv-v2-hero__quote">
        {DM_PAGE_COPY.quote.split("\n").map((line) => (
          <span key={line}>
            {line}
            <br />
          </span>
        ))}
        <cite>{DM_PAGE_COPY.quoteAttribution}</cite>
      </blockquote>
    </section>
  );
}
