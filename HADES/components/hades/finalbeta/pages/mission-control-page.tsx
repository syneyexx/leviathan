/** FINALBETA — v2 mockup UI (mock/prototype content). */
import type { FinalBetaPageRender } from "../types";

export function MissionControlPage(): FinalBetaPageRender {
  const body = (
    <>
      <div className="page-head">
                <div>
                  <h1 className="page-title">Mission Control</h1>
                  <p className="page-sub">Bewaak lopende missies, goedkeuringen en uitvoeringsstatus.</p>
                </div>
                <div className="page-actions"><button className="btn btn-gold" type="button" data-toast="Demo">Nieuwe missie</button></div>
              </div>
              <div className="stat-grid-3" style={{marginBottom: 12}}>
                <div className="card card-pad"><div className="muted">Actief</div><div style={{fontSize: 22, fontWeight: 700}}>2</div></div>
                <div className="card card-pad"><div className="muted">Wacht op goedkeuring</div><div style={{fontSize: 22, fontWeight: 700, color: "var(--gold)"}}>1</div></div>
                <div className="card card-pad"><div className="muted">Voltooid (24u)</div><div style={{fontSize: 22, fontWeight: 700, color: "var(--success)"}}>5</div></div>
              </div>
              <section className="card list-card">
                <div className="list-row"><div className="grow"><strong>Ship Training Control UI</strong><div className="muted" style={{fontSize: 11}}>Criteria: pixel parity · tests groen</div></div><span className="tag gold">Active</span><button className="btn btn-outline" type="button" data-toast="Demo">Open</button></div>
                <div className="list-row"><div className="grow"><strong>ATME benchmark gate</strong><div className="muted" style={{fontSize: 11}}>Wacht op accept score ≥ 9.0</div></div><span className="tag warn">Approval</span><button className="btn btn-outline" type="button" data-toast="Demo">Review</button></div>
                <div className="list-row"><div className="grow"><strong>Evidence vault ingest</strong><div className="muted" style={{fontSize: 11}}>14 docs · voltooid</div></div><span className="tag green">Done</span><button className="btn btn-outline" type="button" data-toast="Demo">Log</button></div>
              </section>
    </>
  );
  const inspector = (
    <>
      <p className="quote">“Sovereign AI. Local power.<br />Infinite possibilities.”</p>
              <div style={{marginBottom: 10}}><span className="badge-outline">ONTWERPVOORBEELD</span></div>
              <section className="insp-section">
                <h3 className="insp-title">Inspector</h3>
                <div className="insp-card">
                  <div className="detail-row"><span className="k">Status</span><span className="v green">● Online</span></div>
                  <div className="detail-row"><span className="k">Host</span><span className="v">DESKTOP-HADES</span></div>
                  <div className="detail-row"><span className="k">Modus</span><span className="v">Lokaal / Offline-first</span></div>
                  <div className="detail-row"><span className="k">UI</span><span className="v">FINALBETA v2 mockup</span></div>
                </div>
              </section>
              <section className="insp-section">
                <h3 className="insp-title">Snelacties</h3>
                <div className="insp-card" style={{display: "flex", flexDirection: "column", gap: 8}}>
                  <button className="btn btn-sm btn-outline btn-block" type="button" data-toast="Demo">Refresh</button>
                  <button className="btn btn-sm btn-gold btn-block" type="button" data-toast="Demo">Open Work Runtime</button>
                </div>
              </section>
    </>
  );
  return { body, inspector };
}
