import type { ServiceCardModel } from "../types/backend";
import { ServiceIcon } from "./icons";

export function ServiceHealthStrip({ cards }: { cards: ServiceCardModel[] }) {
  return (
    <section className="health" aria-label="Service health">
      <header className="health-head">
        <h2>SERVICE HEALTH</h2>
        <span>Core components and runtimes.</span>
      </header>
      <div className="health-row" style={{ gridTemplateColumns: `repeat(${Math.max(cards.length, 1)}, minmax(0, 1fr))` }}>
        {cards.map((card) => (
          <article key={card.id}>
            <div className="name"><ServiceIcon id={card.id} /><span>{card.name}</span></div>
            <div className={`state tone-${card.tone}`}>{card.state}</div>
            <div className="detail" title={card.detail}>{card.detail}</div>
          </article>
        ))}
      </div>
    </section>
  );
}
