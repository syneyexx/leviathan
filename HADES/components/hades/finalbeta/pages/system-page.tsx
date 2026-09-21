/** FINALBETA — v2 mockup UI (mock/prototype content). */
import type { FinalBetaPageRender } from "../types";

export function SystemPage(): FinalBetaPageRender {
  const body = (
    <>
      <div className="page-head">
                <div>
                  <h1 className="page-title">Systeem</h1>
                  <p className="page-sub">Diagnostics, logs en systeemstatus.</p>
                </div>
                <div className="page-actions"><button className="btn btn-gold" type="button" data-toast="Demo">Export diagnostics</button></div>
              </div>
              <div className="page-grid-2">
                <section className="card card-pad">
                  <h2 className="section-title">Build</h2>
                  <div className="kv"><span>App</span><span>HADES FINALBETA</span></div>
                  <div className="kv"><span>UI revision</span><span>v2 mockup</span></div>
                  <div className="kv"><span>Node</span><span>local</span></div>
                  <div className="kv"><span>OS</span><span>Windows 10</span></div>
                </section>
                <section className="card card-pad">
                  <h2 className="section-title">Health checks</h2>
                  <div className="list-row"><div className="grow">API reachability</div><span className="tag green">OK</span></div>
                  <div className="list-row"><div className="grow">LM Studio</div><span className="tag green">OK</span></div>
                  <div className="list-row"><div className="grow">Persistence</div><span className="tag green">OK</span></div>
                  <div className="list-row"><div className="grow">Network (optional)</div><span className="tag">Skipped</span></div>
                </section>
              </div>
              <section className="card card-pad" style={{marginTop: 12}}>
                <h2 className="section-title">Recente logs</h2>
                <pre style={{margin: "8px 0 0", fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted)", lineHeight: 1.5, whiteSpace: "pre-wrap"}}>[14:22:01] training.worker job=run-20241114-1422 started
      [14:22:08] atme.planner strategy=adaptive confidence=0.92
      [14:28:16] training.worker step=2480 loss=0.842 vram=13.6</pre>
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
