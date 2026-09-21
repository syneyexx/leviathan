/** Shared FINALBETA placeholder page for new HOOFDMENU submenu entries. */
import type { FinalBetaPageRender } from "../types";

export function makePlaceholderPage(opts: {
  title: string;
  subtitle: string;
  inspectorTitle?: string;
  blurb?: string;
}): () => FinalBetaPageRender {
  const {
    title,
    subtitle,
    inspectorTitle = "Detail",
    blurb = "Prototype-pagina in FINALBETA. Functionaliteit volgt later pagina voor pagina.",
  } = opts;

  return function PlaceholderPage(): FinalBetaPageRender {
    const body = (
      <>
        <div className="page-head">
          <div>
            <h1 className="page-title">{title}</h1>
            <p className="page-sub">{subtitle}</p>
          </div>
          <div className="page-actions">
            <button type="button" className="btn btn-gold" data-toast="Demoactie">
              Openen
            </button>
          </div>
        </div>
        <section className="card card-pad" style={{ maxWidth: 720 }}>
          <p className="muted" style={{ margin: 0, lineHeight: 1.55 }}>
            {blurb}
          </p>
        </section>
      </>
    );

    const inspector = (
      <>
        <p className="quote">
          “Sovereign AI. Local power.
          <br />
          Infinite possibilities.”
        </p>
        <section className="insp-section">
          <h3 className="insp-title">{inspectorTitle}</h3>
          <div className="insp-card">
            <div className="detail-row">
              <span className="k">Pagina</span>
              <span className="v">{title}</span>
            </div>
            <div className="detail-row">
              <span className="k">Status</span>
              <span className="v">Mock / prototype</span>
            </div>
          </div>
        </section>
        <section className="insp-section">
          <h3 className="insp-title">Snelacties</h3>
          <div className="insp-card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <button type="button" className="btn btn-sm btn-outline btn-block" data-toast="Demo">
              Refresh
            </button>
          </div>
        </section>
      </>
    );

    return { body, inspector };
  };
}
