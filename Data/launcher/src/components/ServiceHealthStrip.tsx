import type { ServiceCardModel } from "../types/backend";

const marks: Record<string, string> = {
  api: "▷",
  workers: "⬡",
  native: "▣",
  python: "π",
  control: "◆",
  knowledge: "◈",
  market: "◇",
  model: "◎",
  queue: "☰",
};

export function ServiceHealthStrip({ cards }: { cards: ServiceCardModel[] }) {
  return (
    <section className="health" aria-label="Service health">
      {cards.map((card) => (
        <article key={card.id}>
          <div className="name"><span className="mark" aria-hidden="true">{marks[card.id] || "•"}</span>{card.name}</div>
          <div className={`state tone-${card.tone}`}>{card.state}</div>
          <div className="detail" title={card.detail}>{card.detail}</div>
        </article>
      ))}
    </section>
  );
}
