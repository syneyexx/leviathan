import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../../api/client";
import { marketSimLabApi } from "../../../../api/domains/marketSimLab";
import { researchCommandApi } from "../../../../api/domains/researchCommand";
import type { TradeOrchestra, PaperPortfolio } from "../../../../types/api";
import type { TradingContextState } from "../useTradingContext";
import { UNMEASURED, fmtHubDate, fmtHubTime } from "./hubFormat";
import type { HubAttentionRow, HubKpiCard, HubQueueRow, HubSessionRow } from "./hubTypes";
import { useCommandHubData } from "./useCommandHubData";

function Sparkline({ values, kind, tone }: { values: number[]; kind: "line" | "bars"; tone: string }) {
  if (!values.length) {
    return <div className="lv-hub-spark lv-hub-spark--empty" aria-hidden="true" />;
  }
  const w = 96;
  const h = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  if (kind === "bars") {
    const bw = w / values.length;
    return (
      <svg className={`lv-hub-spark lv-hub-spark--tone-${tone}`} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
        {values.map((v, i) => {
          const bh = Math.max(2, ((v - min) / span) * (h - 4) + 4);
          return (
            <rect key={i} x={i * bw + 1} y={h - bh} width={Math.max(1, bw - 2)} height={bh} rx={1} />
          );
        })}
      </svg>
    );
  }
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1 || 1)) * w;
      const y = h - ((v - min) / span) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className={`lv-hub-spark lv-hub-spark--tone-${tone}`} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts} fill="none" strokeWidth={1.6} />
    </svg>
  );
}

function KpiCard({ kpi, onOpenQueueDrawer }: { kpi: HubKpiCard; onOpenQueueDrawer: () => void }) {
  const body = (
    <>
      <p className="lv-hub-kpi__label">{kpi.label}</p>
      <p className="lv-hub-kpi__value">{kpi.value}</p>
      <div className="lv-hub-kpi__foot">
        <span className={`lv-hub-kpi__delta lv-hub-tone-${kpi.deltaTone}`}>{kpi.delta}</span>
        <Sparkline values={kpi.spark} kind={kpi.sparkKind} tone={kpi.tone} />
      </div>
    </>
  );
  if (kpi.href === "#control-room") {
    return (
      <button type="button" className={`lv-hub-kpi lv-hub-kpi--tone-${kpi.tone}`} onClick={onOpenQueueDrawer}>
        {body}
      </button>
    );
  }
  if (kpi.href) {
    return (
      <Link className={`lv-hub-kpi lv-hub-kpi--tone-${kpi.tone}`} to={kpi.href}>
        {body}
      </Link>
    );
  }
  return <article className={`lv-hub-kpi lv-hub-kpi--tone-${kpi.tone}`}>{body}</article>;
}

function SessionsTable({ rows, kind }: { rows: HubSessionRow[]; kind: "paper" | "research" }) {
  if (!rows.length) {
    return <p className="lv-hub-empty">Geen {kind === "paper" ? "paper sessies" : "research sessies"} gevonden.</p>;
  }
  return (
    <table className="lv-hub-table">
      <thead>
        <tr>
          <th>Naam</th>
          <th>Strategie</th>
          <th>{kind === "paper" ? "Wallet" : "Symbol"}</th>
          <th>Markt</th>
          <th>Huidige focus</th>
          <th>Pnl / Voortgang</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td>{r.name}</td>
            <td>{r.strategy}</td>
            <td>{r.wallet}</td>
            <td>{r.market}</td>
            <td>{r.focus}</td>
            <td>{r.progress != null ? `${r.progress}%` : r.result}</td>
            <td>
              <span className={`lv-hub-pill lv-hub-tone-${r.statusTone}`}>{r.status}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AttentionDrawer({
  row,
  onClose,
}: {
  row: HubAttentionRow | null;
  onClose: () => void;
}) {
  if (!row) return null;
  return (
    <div className="lv-hub-drawer" role="dialog" aria-label="Attention detail">
      <div className="lv-hub-drawer__panel">
        <header>
          <div>
            <p className="lv-hub-drawer__kicker">{row.type}</p>
            <h3>Attention detail</h3>
          </div>
          <button type="button" className="lv-hub-btn" onClick={onClose}>
            Sluiten
          </button>
        </header>
        <dl className="lv-hub-drawer__list">
          <div>
            <dt>Prioriteit</dt>
            <dd>{row.priority}</dd>
          </div>
          <div>
            <dt>Tijd</dt>
            <dd>{row.time}</dd>
          </div>
          <div>
            <dt>Bericht</dt>
            <dd>{row.message}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

function ControlRoomDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    marketSimLabApi
      .marketSimInstitutionalControlRoom()
      .then((res) => {
        if (!cancelled) setSnapshot(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load control room");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;
  const overallStatus = String((snapshot as { overallStatus?: string } | null)?.overallStatus ?? UNMEASURED);
  const liveTrading = (snapshot as { liveTrading?: Record<string, unknown> } | null)?.liveTrading;
  const notes = ((snapshot as { notes?: unknown[] } | null)?.notes || []) as string[];

  return (
    <div className="lv-hub-drawer" role="dialog" aria-label="Control room snapshot">
      <div className="lv-hub-drawer__panel">
        <header>
          <div>
            <p className="lv-hub-drawer__kicker">Institutional</p>
            <h3>Control Room snapshot</h3>
          </div>
          <button type="button" className="lv-hub-btn" onClick={onClose}>
            Sluiten
          </button>
        </header>
        {loading ? <p className="lv-hub-empty">Laden…</p> : null}
        {error ? <p className="lv-hub-drawer__error">{error}</p> : null}
        {!loading && !error ? (
          <>
            <dl className="lv-hub-drawer__list">
              <div>
                <dt>Overall status</dt>
                <dd>{overallStatus}</dd>
              </div>
              <div>
                <dt>Live trading</dt>
                <dd>{JSON.stringify(liveTrading ?? UNMEASURED)}</dd>
              </div>
            </dl>
            {notes.length ? (
              <ul className="lv-hub-drawer__notes">
                {notes.slice(0, 8).map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            ) : null}
            <pre className="lv-hub-drawer__raw">{JSON.stringify(snapshot, null, 2).slice(0, 4000)}</pre>
          </>
        ) : null}
      </div>
    </div>
  );
}

function NewResearchSessionModal({
  open,
  onClose,
  onStarted,
}: {
  open: boolean;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [orchestras, setOrchestras] = useState<TradeOrchestra[]>([]);
  const [portfolios, setPortfolios] = useState<PaperPortfolio[]>([]);
  const [orchestraId, setOrchestraId] = useState("");
  const [portfolioId, setPortfolioId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    Promise.all([
      api.listTradeOrchestras(false).catch(() => ({ orchestras: [] as TradeOrchestra[] })),
      api.listPortfolios(50).catch(() => ({ portfolios: [] as PaperPortfolio[] })),
    ]).then(([o, p]) => {
      setOrchestras(o.orchestras || []);
      setPortfolios(p.portfolios || []);
      setOrchestraId((o.orchestras || [])[0]?.orchestraId || "");
      setPortfolioId((p.portfolios || [])[0]?.portfolio_id || "");
    });
  }, [open]);

  if (!open) return null;

  const canStart = Boolean(orchestraId && portfolioId);

  return (
    <div className="lv-hub-drawer" role="dialog" aria-label="Nieuwe research sessie">
      <div className="lv-hub-drawer__panel lv-hub-drawer__panel--modal">
        <header>
          <div>
            <p className="lv-hub-drawer__kicker">Research Command</p>
            <h3>Nieuwe research sessie</h3>
          </div>
          <button type="button" className="lv-hub-btn" onClick={onClose}>
            Sluiten
          </button>
        </header>
        {!orchestras.length ? (
          <p className="lv-hub-empty">
            Geen orchestra's gevonden. Maak eerst een orchestra aan via Research Command.
          </p>
        ) : (
          <>
            <label className="lv-hub-field">
              <span>Orchestra</span>
              <select value={orchestraId} onChange={(e) => setOrchestraId(e.target.value)}>
                {orchestras.map((o) => (
                  <option key={o.orchestraId} value={o.orchestraId}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="lv-hub-field">
              <span>Portfolio</span>
              <select value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)}>
                {portfolios.map((p) => (
                  <option key={p.portfolio_id} value={p.portfolio_id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            {error ? <p className="lv-hub-drawer__error">{error}</p> : null}
            <div className="lv-hub-drawer__actions">
              <button
                type="button"
                className="lv-hub-btn lv-hub-btn--primary"
                disabled={!canStart || busy}
                onClick={() => {
                  setBusy(true);
                  setError(null);
                  researchCommandApi
                    .researchCommandStart({ orchestraId, portfolioId })
                    .then(() => {
                      onStarted();
                      onClose();
                    })
                    .catch((err) => setError(err instanceof Error ? err.message : "Failed to start session"))
                    .finally(() => setBusy(false));
                }}
              >
                {busy ? "Starten…" : "Start sessie"}
              </button>
              <Link className="lv-hub-btn" to="/trading/command-hub" onClick={onClose}>
                Annuleren
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function CommandHubView({ ctx }: { ctx: TradingContextState }) {
  const model = useCommandHubData(ctx.market, ctx.timeframe);
  const [sessTab, setSessTab] = useState<"paper" | "research">("paper");
  const [controlRoomOpen, setControlRoomOpen] = useState(false);
  const [newSessionOpen, setNewSessionOpen] = useState(false);
  const [attentionRow, setAttentionRow] = useState<HubAttentionRow | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const queueOpen = useCallback(() => setControlRoomOpen(true), []);

  const attnCount = model.attention.filter((a) => a.priority === "Hoog").length;
  const paperCount = model.paperSessions.length;
  const researchCount = model.researchSessions.length;

  return (
    <section className="lv-hub" aria-label="Command Hub" aria-busy={model.loading}>
      <div className="lv-hub__hero">
        <div className="lv-hub__hero-inner">
          <div className="lv-hub__hero-copy">
            <p className="lv-hub__kicker">Autonomous Trading Command Hub</p>
            <h2>Één centrale werkomgeving voor onderzoek, leren en simuleren</h2>
            <p className="lv-hub__hero-sub">
              Ontdek, onderzoek, leer en simuleer trading strategieën met autonome AI agents. Live geld blijft{" "}
              <strong>{model.liveTrading}</strong> — paper &amp; research only.
            </p>
            <div className="lv-hub__cta">
              <button type="button" className="lv-hub-btn lv-hub-btn--primary" onClick={() => setNewSessionOpen(true)}>
                + Nieuwe research sessie
              </button>
              <Link className="lv-hub-btn" to="/trading/trading-desk?surface=paper">
                Paper sessie openen
              </Link>
              <Link className="lv-hub-btn" to="/trading/strategy-lab?surface=lab">
                Strategy Lab
              </Link>
            </div>
            <div className="lv-hub__caps">
              {model.capabilities.map((c) => (
                <span key={c.id} className={`lv-hub-cap lv-hub-tone-${c.tone}${c.active ? "" : " is-inactive"}`}>
                  <strong>{c.label}</strong>
                  <small>{c.sub}</small>
                </span>
              ))}
            </div>
          </div>
          <div className="lv-hub__hero-clock" aria-hidden="true">
            <p>{fmtHubDate(now)}</p>
            <p className="lv-hub__hero-time">{fmtHubTime(now)}</p>
          </div>
        </div>
      </div>

      {model.error ? (
        <p className="lv-hub-error" role="alert">
          {model.error}
          <button type="button" className="lv-hub-btn" onClick={() => void model.refresh()}>
            Retry
          </button>
        </p>
      ) : null}

      <div className="lv-hub-kpis">
        {model.kpis.map((k) => (
          <KpiCard key={k.id} kpi={k} onOpenQueueDrawer={queueOpen} />
        ))}
      </div>

      <div className="lv-hub-grid">
        <section className="lv-hub-panel" aria-label="Active Operations">
          <header>
            <h3>Active Operations</h3>
            <Link to="/trading/strategy-lab?surface=lab">Alle agents bekijken</Link>
          </header>
          {model.agents.length ? (
            <table className="lv-hub-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Huidige taak</th>
                  <th>Markt / Symbool</th>
                  <th>Workload</th>
                </tr>
              </thead>
              <tbody>
                {model.agents.map((a) => (
                  <tr key={a.id}>
                    <td>{a.name}</td>
                    <td>
                      <span className={`lv-hub-pill lv-hub-tone-${a.statusTone}`}>{a.status}</span>
                    </td>
                    <td>{a.task}</td>
                    <td>{a.market}</td>
                    <td>
                      {a.workload != null ? (
                        <div className="lv-hub-workload">
                          <div className="lv-hub-workload__bar" style={{ width: `${a.workload}%` }} />
                        </div>
                      ) : (
                        <span className="lv-hub-empty-inline">{UNMEASURED}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="lv-hub-empty">Geen actieve agents gevonden voor de huidige sessie.</p>
          )}
        </section>

        <div className="lv-hub-side">
          <section className="lv-hub-panel" aria-label="Markt & Regime">
            <header>
              <h3>Markt &amp; Regime</h3>
              <span className="lv-hub-panel__badge">{ctx.timeframe}</span>
            </header>
            <div className="lv-hub-market">
              <div className="lv-hub-market__price">
                <p className="lv-hub-market__symbol">{model.market.symbol}</p>
                <p className="lv-hub-market__value">{model.market.price}</p>
                <span className={`lv-hub-tone-${model.market.changeTone}`}>{model.market.change}</span>
              </div>
              <Sparkline values={model.market.spark} kind="line" tone={model.market.changeTone} />
            </div>
            <dl className="lv-hub-market__stats">
              <div>
                <dt>Volatiliteit</dt>
                <dd className={`lv-hub-tone-${model.market.volatilityTone}`}>{model.market.volatility}</dd>
              </div>
              <div>
                <dt>Liquiditeit</dt>
                <dd>{model.market.liquidity}</dd>
              </div>
              <div>
                <dt>Funding Rate</dt>
                <dd>{model.market.funding}</dd>
              </div>
              <div>
                <dt>Regime</dt>
                <dd className={`lv-hub-tone-${model.market.regimeTone}`}>{model.market.regime}</dd>
              </div>
            </dl>
          </section>

          <section className="lv-hub-panel" aria-label="Databronnen">
            <header>
              <h3>Databronnen (Live)</h3>
              <span className="lv-hub-panel__badge">
                {model.sourcesOnline}/{model.sources.length}
              </span>
            </header>
            {model.sources.length ? (
              <ul className="lv-hub-sources">
                {model.sources.map((s) => (
                  <li key={s.id}>
                    <span>{s.name}</span>
                    <span
                      className={`lv-hub-dot ${s.online === true ? "is-on" : s.online === false ? "is-off" : "is-unknown"}`}
                    />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="lv-hub-empty">Geen databronnen geïndexeerd.</p>
            )}
          </section>
        </div>
      </div>

      <section className="lv-hub-panel" aria-label="Paper Sessions & Research">
        <header>
          <div className="lv-hub-tabs">
            <button
              type="button"
              className={sessTab === "paper" ? "is-active" : ""}
              onClick={() => setSessTab("paper")}
            >
              Paper Sessies ({paperCount})
            </button>
            <button
              type="button"
              className={sessTab === "research" ? "is-active" : ""}
              onClick={() => setSessTab("research")}
            >
              Research Sessies ({researchCount})
            </button>
          </div>
          <button type="button" className="lv-hub-btn" onClick={() => setNewSessionOpen(true)}>
            Nieuwe sessie
          </button>
        </header>
        <SessionsTable rows={sessTab === "paper" ? model.paperSessions : model.researchSessions} kind={sessTab} />
      </section>

      <div className="lv-hub-grid lv-hub-grid--lower">
        <section className="lv-hub-panel" aria-label="Wat kijken de agents nu?">
          <header>
            <h3>Wat kijken de agents nu?</h3>
            <span className="lv-hub-panel__badge">Live view</span>
          </header>
          {model.watching.length ? (
            <table className="lv-hub-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Focus / Symbool</th>
                  <th>Hypothese</th>
                  <th>Finding</th>
                  <th>Confidence</th>
                  <th>Activiteit</th>
                </tr>
              </thead>
              <tbody>
                {model.watching.map((w) => (
                  <tr key={w.id}>
                    <td>{w.agent}</td>
                    <td>{w.focus}</td>
                    <td>{w.hypothesis}</td>
                    <td>{w.finding}</td>
                    <td>{w.confidence != null ? `${Math.round(w.confidence)}%` : UNMEASURED}</td>
                    <td>{w.last}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="lv-hub-empty">Geen agent-activiteit beschikbaar.</p>
          )}
        </section>

        <div className="lv-hub-side">
          <section className="lv-hub-panel" aria-label="Attention / Decisions">
            <header>
              <h3>
                Attention / Decisions
                {attnCount ? <span className="lv-hub-badge-count">{attnCount}</span> : null}
              </h3>
              <button type="button" className="lv-hub-panel__link" onClick={queueOpen}>
                Alles bekijken
              </button>
            </header>
            <ul className="lv-hub-attn">
              {model.attention.map((a) => (
                <li key={a.id} data-priority={a.priority}>
                  <button type="button" onClick={() => setAttentionRow(a)}>
                    <span className="lv-hub-attn__time">{a.time}</span>
                    <span className="lv-hub-attn__type">{a.type}</span>
                    <span className="lv-hub-attn__msg">{a.message}</span>
                    <span className="lv-hub-attn__pri">{a.priority}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="lv-hub-panel" aria-label="Promotie & Control Queue">
            <header>
              <h3>Promotie &amp; Control Queue</h3>
              <button type="button" className="lv-hub-panel__link" onClick={queueOpen}>
                Open queue
              </button>
            </header>
            {model.queue.length ? (
              <table className="lv-hub-table lv-hub-table--compact">
                <thead>
                  <tr>
                    <th>Taak</th>
                    <th>Type</th>
                    <th>Agent</th>
                    <th>Prioriteit</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {model.queue.map((q: HubQueueRow) => (
                    <tr key={q.id}>
                      <td>{q.task}</td>
                      <td>{q.type}</td>
                      <td>{q.agent}</td>
                      <td>{q.priority}</td>
                      <td>
                        <span className={`lv-hub-pill lv-hub-tone-${q.statusTone}`}>{q.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="lv-hub-empty">Geen items in de promotie / control queue.</p>
            )}
          </section>
        </div>
      </div>

      <ControlRoomDrawer open={controlRoomOpen} onClose={() => setControlRoomOpen(false)} />
      <AttentionDrawer row={attentionRow} onClose={() => setAttentionRow(null)} />
      <NewResearchSessionModal
        open={newSessionOpen}
        onClose={() => setNewSessionOpen(false)}
        onStarted={() => void model.refresh()}
      />
    </section>
  );
}