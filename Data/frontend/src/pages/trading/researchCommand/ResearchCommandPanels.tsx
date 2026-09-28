import type { ReactNode } from "react";
import type { Measured, PositionRow, ResearchCommandSnapshot, WatchRow } from "../../../types/researchCommand";
import {
  formatUptime,
  generationLabel,
  measuredText,
  modeLabel,
  moneyText,
  percentText,
  safetyClass,
  signedClass,
  whyText,
} from "./viewModels";

type Snap = ResearchCommandSnapshot;

export function Card({
  title,
  className,
  action,
  children,
}: {
  title: string;
  className?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={`lv-rc-card ${className ?? ""}`}>
      <header className="lv-rc-card-head">
        <h2>{title}</h2>
        {action}
      </header>
      <div className="lv-rc-card-body">{children}</div>
    </section>
  );
}

function Pill({ text, className }: { text: string; className?: string }) {
  return <span className={`lv-rc-pill ${className ?? ""}`}>{text}</span>;
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return <span className="lv-rc-muted">UNMEASURED</span>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const d = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 72;
      const y = 18 - ((value - min) / span) * 14;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg className="lv-rc-spark" viewBox="0 0 72 20" width="72" height="20" aria-hidden="true">
      <path d={d} fill="none" stroke={up ? "#3dbea0" : "#d46464"} strokeWidth="1.4" />
    </svg>
  );
}

function Allocation({ label, field }: { label: string; field: Measured }) {
  const measured = field.measurement === "MEASURED" && field.value != null;
  const width = measured ? Math.max(0, Math.min(100, Number(field.value))) : 0;
  return (
    <div className="lv-rc-alloc">
      <span>{label}</span>
      <div className="lv-rc-alloc-track">
        {measured ? <i style={{ width: `${width}%` }} /> : null}
      </div>
      <em>{percentText(field)}</em>
    </div>
  );
}

export function SessionCard({
  snap,
  orchestraId,
  portfolioId,
  labId,
  missionKind,
  missionAsOf,
  createName,
  createUniverse,
  createCapital,
  busy,
  onOrchestra,
  onPortfolio,
  onLab,
  onMissionKind,
  onMissionAsOf,
  onCreateName,
  onCreateUniverse,
  onCreateCapital,
  onCreate,
  onLaunch,
}: {
  snap: Snap | null;
  orchestraId: string;
  portfolioId: string;
  labId: string;
  missionKind: string;
  missionAsOf: string;
  createName: string;
  createUniverse: string;
  createCapital: string;
  busy: string | null;
  onOrchestra: (value: string) => void;
  onPortfolio: (value: string) => void;
  onLab: (value: string) => void;
  onMissionKind: (value: string) => void;
  onMissionAsOf: (value: string) => void;
  onCreateName: (value: string) => void;
  onCreateUniverse: (value: string) => void;
  onCreateCapital: (value: string) => void;
  onCreate: () => void;
  onLaunch: () => void;
}) {
  const session = snap?.session;
  const launch = snap?.actions.launchMission;
  return (
    <Card title="Active Research Session" className="lv-rc-session">
      <div className="lv-rc-pills">
        <Pill text={session?.state ?? "NO SESSION"} className={session?.state === "RUNNING" ? "is-safe" : "is-muted"} />
        <Pill text={modeLabel(session?.mode)} className={session?.mode === "PAPER" ? "is-paper" : "is-muted"} />
        <Pill text={session?.safety ?? "UNMEASURED"} className={safetyClass(session?.safety)} />
      </div>
      <p className="lv-rc-session-name">{session?.name || "No research session"}</p>
      <dl className="lv-rc-kv">
        <div>
          <dt>Started</dt>
          <dd>{session?.startedAt || "EMPTY"}</dd>
        </div>
        <div>
          <dt>Uptime</dt>
          <dd>{formatUptime(session?.uptime)}</dd>
        </div>
        <div>
          <dt>Wallet</dt>
          <dd>{snap?.portfolio.name || "NO PAPER WALLET"}</dd>
        </div>
        <div>
          <dt>Universe</dt>
          <dd>{session?.universe?.length ? session.universe.join(", ") : "EMPTY"}</dd>
        </div>
      </dl>
      <div className="lv-rc-selects">
        <select aria-label="Trade orchestra" value={orchestraId} onChange={(e) => onOrchestra(e.target.value)}>
          <option value="">No orchestra</option>
          {(snap?.catalogs.orchestras ?? []).map((row) => (
            <option key={row.orchestraId} value={row.orchestraId}>
              {row.name}
            </option>
          ))}
        </select>
        <select aria-label="Paper portfolio" value={portfolioId} onChange={(e) => onPortfolio(e.target.value)}>
          <option value="">No paper wallet</option>
          {(snap?.catalogs.portfolios ?? []).map((row) => (
            <option key={row.portfolioId} value={row.portfolioId}>
              {row.name}
            </option>
          ))}
        </select>
        <select aria-label="Research lab run" value={labId} onChange={(e) => onLab(e.target.value)}>
          <option value="">No evolution run</option>
          {(snap?.catalogs.labs ?? []).map((row) => (
            <option key={row.labId} value={row.labId}>
              {row.name || row.labId} · {row.status}
            </option>
          ))}
        </select>
      </div>
      <div className="lv-rc-inline">
        <select aria-label="Mission kind" value={missionKind} onChange={(e) => onMissionKind(e.target.value)}>
          <option value="deliberation_round">Deliberation round</option>
          <option value="news_digest">News digest</option>
          <option value="post_mortem">Post-mortem</option>
        </select>
        <input
          aria-label="Mission as of"
          placeholder="mission as_of"
          value={missionAsOf}
          onChange={(e) => onMissionAsOf(e.target.value)}
        />
        <button type="button" disabled={!launch?.enabled || busy === "mission"} title={launch?.reason || ""} onClick={onLaunch}>
          Launch mission
        </button>
      </div>
      <details className="lv-rc-details">
        <summary>New orchestra</summary>
        <div className="lv-rc-inline">
          <input aria-label="Orchestra name" placeholder="Name" value={createName} onChange={(e) => onCreateName(e.target.value)} />
          <input aria-label="Universe" placeholder="BTCUSD, ETHUSD" value={createUniverse} onChange={(e) => onCreateUniverse(e.target.value)} />
          <input aria-label="Paper capital" placeholder="Paper capital" value={createCapital} onChange={(e) => onCreateCapital(e.target.value)} />
          <button type="button" disabled={!createName.trim() || busy === "create-orchestra"} onClick={onCreate}>
            Create
          </button>
        </div>
      </details>
    </Card>
  );
}

export function TeamCard({
  snap,
  onOpenAgent,
}: {
  snap: Snap | null;
  onOpenAgent: (agentId: string) => void;
}) {
  const members = snap?.team.members ?? [];
  return (
    <Card title="Standard Agent Team" className="lv-rc-team" action={<span className="lv-rc-muted">telemetry UNMEASURED</span>}>
      {members.length === 0 ? (
        <p className="lv-rc-empty">No orchestra members. Create or select a trade orchestra.</p>
      ) : (
        <ul className="lv-rc-team-list">
          {members.map((member) => (
            <li key={member.agentId || member.name}>
              <button
                type="button"
                className="lv-rc-agent"
                disabled={!member.agentId}
                onClick={() => member.agentId && onOpenAgent(member.agentId)}
              >
                <strong>{member.name || "UNMEASURED"}</strong>
                <span>{member.role || member.kind || "UNMEASURED"}</span>
              </button>
              <em className={member.state === "ACTIVE" ? "is-safe" : "is-warn"}>{member.enabled ? member.state : "IDLE"}</em>
              <span className="lv-rc-muted">
                {member.activityMeasurement === "MEASURED" && member.activity ? member.activity : "UNMEASURED"}
              </span>
            </li>
          ))}
        </ul>
      )}
      {snap?.runtime.modelAvailable === false ? <p className="lv-rc-muted">Model UNAVAILABLE</p> : null}
      {snap?.runtime.worker === "BLOCKED" ? <p className="lv-rc-warn">Worker BLOCKED</p> : null}
      {snap?.runtime.paperEngine === "UNAVAILABLE" ? <p className="lv-rc-warn">Paper engine UNAVAILABLE</p> : null}
    </Card>
  );
}

export function PortfolioCard({
  snap,
  portfolioId,
  onPortfolio,
}: {
  snap: Snap | null;
  portfolioId: string;
  onPortfolio: (value: string) => void;
}) {
  const book = snap?.portfolio;
  const currency = book?.currency;
  return (
    <Card
      title="Wallet & Portfolio"
      className="lv-rc-wallet"
      action={<Pill text="PAPER" className="is-paper" />}
    >
      <select aria-label="Selected paper wallet" value={portfolioId} onChange={(e) => onPortfolio(e.target.value)}>
        <option value="">No paper wallet</option>
        {(snap?.catalogs.portfolios ?? []).map((row) => (
          <option key={row.portfolioId} value={row.portfolioId}>
            {row.name}
          </option>
        ))}
      </select>
      {!book?.bound ? <p className="lv-rc-empty">No paper wallet selected. Live capital is not connected.</p> : null}
      <div className="lv-rc-equity">
        <strong className={signedClass(book?.dailyPnl)}>{moneyText(book?.equity, currency)}</strong>
        <span>Total value · {book?.marks === "MEASURED" ? "marks measured" : book?.marks || "UNMEASURED"}</span>
      </div>
      <dl className="lv-rc-metrics">
        <div>
          <dt>Cash</dt>
          <dd>{moneyText(book?.cash, currency)}</dd>
        </div>
        <div>
          <dt>Allocated</dt>
          <dd>{moneyText(book?.allocated, currency)}</dd>
        </div>
        <div>
          <dt>Buying power</dt>
          <dd>{moneyText(book?.buyingPower, currency)}</dd>
        </div>
        <div>
          <dt>Leverage</dt>
          <dd>{measuredText(book?.leverage)}</dd>
        </div>
        <div>
          <dt>Daily PnL</dt>
          <dd className={signedClass(book?.dailyPnl)}>{moneyText(book?.dailyPnl, currency)}</dd>
        </div>
        <div>
          <dt>Session PnL</dt>
          <dd>{moneyText(book?.sessionPnl, currency)}</dd>
        </div>
      </dl>
      <Allocation label="Cash" field={book?.allocations.cash ?? { value: null, measurement: "UNMEASURED" }} />
      <Allocation label="Positions" field={book?.allocations.positions ?? { value: null, measurement: "UNMEASURED" }} />
      <Allocation label="Risk" field={book?.allocations.risk ?? { value: null, measurement: "UNMEASURED" }} />
    </Card>
  );
}

function WatchRows({ rows }: { rows: WatchRow[] }) {
  if (rows.length === 0) return <p className="lv-rc-empty">EMPTY</p>;
  return (
    <table className="lv-rc-table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Last</th>
          <th>24h</th>
          <th>7d</th>
          <th>Trend</th>
          <th>Vol</th>
          <th>Why watching</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.symbol}>
            <td>{row.symbol}</td>
            <td>{measuredText(row.last)}</td>
            <td className={signedClass(row.change24h)}>{percentText(row.change24h)}</td>
            <td className={signedClass(row.change7d)}>{percentText(row.change7d)}</td>
            <td>
              <Sparkline points={row.spark} />
            </td>
            <td>{measuredText(row.volatility)}</td>
            <td title={row.whySource || ""}>{whyText(row.why)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function WatchCard({
  snap,
  tab,
  asOf,
  watchSymbol,
  watchReason,
  busy,
  onTab,
  onAsOf,
  onSymbol,
  onReason,
  onAddWatch,
  onManageFeeds,
}: {
  snap: Snap | null;
  tab: "watchlist" | "opportunities" | "volatility" | "news";
  asOf: string;
  watchSymbol: string;
  watchReason: string;
  busy: string | null;
  onTab: (tab: "watchlist" | "opportunities" | "volatility" | "news") => void;
  onAsOf: (value: string) => void;
  onSymbol: (value: string) => void;
  onReason: (value: string) => void;
  onAddWatch: () => void;
  onManageFeeds: () => void;
}) {
  const watching = snap?.watching;
  return (
    <Card
      title="What They're Watching"
      className="lv-rc-watch"
      action={
        <div className="lv-rc-tabs">
          {(
            [
              ["watchlist", "Watchlist"],
              ["opportunities", "Opportunities"],
              ["volatility", "High Volatility"],
              ["news", "News"],
            ] as const
          ).map(([id, label]) => (
            <button key={id} type="button" className={tab === id ? "is-on" : ""} onClick={() => onTab(id)}>
              {label}
            </button>
          ))}
        </div>
      }
    >
      {tab === "watchlist" ? (
        <>
          <WatchRows rows={watching?.watchlist ?? []} />
          <div className="lv-rc-inline">
            <input aria-label="Watch symbol" placeholder="Symbol" value={watchSymbol} onChange={(e) => onSymbol(e.target.value)} />
            <input
              aria-label="Watch reason"
              placeholder="Explicit reason"
              value={watchReason}
              onChange={(e) => onReason(e.target.value)}
            />
            <button
              type="button"
              disabled={!snap?.selection.sessionId || !watchSymbol.trim() || !watchReason.trim() || busy === "watch"}
              onClick={onAddWatch}
            >
              Add watch
            </button>
          </div>
        </>
      ) : null}
      {tab === "opportunities" ? (
        (watching?.opportunities.length ?? 0) === 0 ? (
          <p className="lv-rc-empty">No recorded proposals.</p>
        ) : (
          <ul className="lv-rc-feed">
            {watching?.opportunities.map((row) => (
              <li key={row.decisionId || row.symbol}>
                <strong>{row.symbol || "—"}</strong> · {row.direction}
                <p>{whyText(row.why)}</p>
              </li>
            ))}
          </ul>
        )
      ) : null}
      {tab === "volatility" ? (
        <>
          <p className="lv-rc-muted">{watching?.highVolatility.note || "No measured volatility."}</p>
          <WatchRows rows={watching?.highVolatility.rows ?? []} />
        </>
      ) : null}
      {tab === "news" ? (
        <>
          <div className="lv-rc-inline">
            <input
              aria-label="Causal as of"
              placeholder="as_of (empty = session as_of or now)"
              value={asOf}
              onChange={(e) => onAsOf(e.target.value)}
            />
            <button type="button" onClick={onManageFeeds}>
              Manage feeds
            </button>
          </div>
          <p className="lv-rc-muted">Signals are data, not execution authority. Visibility uses available_at / as_of.</p>
          {(watching?.news.length ?? 0) === 0 ? <p className="lv-rc-empty">No news visible at this as_of.</p> : null}
          <ul className="lv-rc-feed">
            {(watching?.news ?? []).map((item) => (
              <li key={item.itemId}>
                <strong>{item.title}</strong>
                <p>
                  {item.source || "—"} · available {item.availableAt || "UNMEASURED"} · published {item.publishedAt || "unknown"} ·{" "}
                  {item.licenseState || "UNKNOWN"}
                </p>
              </li>
            ))}
          </ul>
          <h3 className="lv-rc-subhead">News signals</h3>
          {(watching?.signals.length ?? 0) === 0 ? <p className="lv-rc-empty">No signals.</p> : null}
          <ul className="lv-rc-feed">
            {(watching?.signals ?? []).map((signal) => (
              <li key={signal.signalId}>
                {signal.direction} · {signal.eventType} · {signal.instruments.join(", ") || "—"} · magnitude{" "}
                {signal.magnitude} · agent estimate {signal.confidence} · {signal.horizon} · as_of {signal.asOf}
                <p>{signal.rationale || "NOT AVAILABLE"}</p>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Card>
  );
}

export function StreamCard({ snap }: { snap: Snap | null }) {
  const events = snap?.publicEvents ?? [];
  return (
    <Card
      title="Live Thinking / Reasoning Stream"
      className="lv-rc-stream"
      action={<span className="lv-rc-muted">public agent rationale & decision events</span>}
    >
      {events.length === 0 ? <p className="lv-rc-empty">No public decision or mission events.</p> : null}
      <ol className="lv-rc-stream-list">
        {events.map((event) => (
          <li key={`${event.kind}-${event.id}`}>
            <time>{event.at || "UNMEASURED"}</time>
            <span className="lv-rc-stage">{event.stage || event.kind}</span>
            <p>{event.summary}</p>
            <em>
              {event.role || "—"} · {event.source}
            </em>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function ThesisCard({ snap }: { snap: Snap | null }) {
  const thesis = snap?.thesis;
  return (
    <Card title="Thesis & Why" className="lv-rc-thesis">
      {!thesis?.present ? <p className="lv-rc-empty">EMPTY — no recorded thesis or proposal.</p> : null}
      {thesis?.present ? (
        <>
          <p className="lv-rc-thesis-text">{thesis.primary || "NOT AVAILABLE"}</p>
          <p className="lv-rc-muted">
            Source {thesis.source} · {thesis.instruments.filter(Boolean).join(", ") || "no instrument"} · {thesis.direction || "—"}
          </p>
          <dl className="lv-rc-kv">
            <div>
              <dt>Horizon</dt>
              <dd>{measuredText(thesis.horizon)}</dd>
            </div>
            <div>
              <dt>Expected edge</dt>
              <dd>{measuredText(thesis.expectedEdge)}</dd>
            </div>
            <div>
              <dt>Invalidation</dt>
              <dd>{measuredText(thesis.invalidation)}</dd>
            </div>
            <div>
              <dt>Catalysts</dt>
              <dd>{measuredText(thesis.catalysts)}</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{measuredText(thesis.confidence)}</dd>
            </div>
            <div>
              <dt>Measured validation</dt>
              <dd>{measuredText(thesis.measuredValidation)}</dd>
            </div>
          </dl>
        </>
      ) : null}
    </Card>
  );
}

export function IntentCard({ snap }: { snap: Snap | null }) {
  const intent = snap?.intent;
  return (
    <Card title="Positioning & Intent" className="lv-rc-intent" action={<Pill text="PROPOSAL · PAPER" className="is-paper" />}>
      {!intent?.present ? <p className="lv-rc-empty">EMPTY — no paper intent or risk decision.</p> : null}
      {intent?.present ? (
        <dl className="lv-rc-kv">
          <div>
            <dt>Market</dt>
            <dd>{intent.instrument || "NOT AVAILABLE"}</dd>
          </div>
          <div>
            <dt>Direction</dt>
            <dd>{intent.direction || "UNMEASURED"}</dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd>{measuredText(intent.size)}</dd>
          </div>
          <div>
            <dt>Max risk</dt>
            <dd>{measuredText(intent.maxRisk)}</dd>
          </div>
          <div>
            <dt>Stop</dt>
            <dd>{measuredText(intent.stop)}</dd>
          </div>
          <div>
            <dt>Target</dt>
            <dd>{measuredText(intent.target)}</dd>
          </div>
          <div>
            <dt>Rationale</dt>
            <dd>{intent.rationale || "NOT AVAILABLE"}</dd>
          </div>
          <div>
            <dt>Sizing rationale</dt>
            <dd>{measuredText(intent.sizingRationale)}</dd>
          </div>
        </dl>
      ) : null}
      <p className="lv-rc-muted">Live order submission remains blocked. Intent is not execution authority.</p>
    </Card>
  );
}

function PositionTable({ rows }: { rows: PositionRow[] }) {
  if (rows.length === 0) return <p className="lv-rc-empty">EMPTY</p>;
  return (
    <table className="lv-rc-table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Side</th>
          <th>Size</th>
          <th>Entry</th>
          <th>Mark</th>
          <th>PnL</th>
          <th>%</th>
          <th>State</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.positionId || `${row.symbol}-${row.at}`}>
            <td>
              {row.symbol || "—"} {row.paper ? <em className="lv-rc-paper-tag">PAPER</em> : null}
            </td>
            <td>{row.side || "—"}</td>
            <td>{measuredText(row.size)}</td>
            <td>{measuredText(row.entry)}</td>
            <td>{measuredText(row.mark)}</td>
            <td className={signedClass(row.pnl)}>{measuredText(row.pnl)}</td>
            <td>{percentText(row.pnlPct)}</td>
            <td>{row.state}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PositionsCard({
  snap,
  tab,
  onTab,
}: {
  snap: Snap | null;
  tab: "open" | "closed";
  onTab: (tab: "open" | "closed") => void;
}) {
  const currency = snap?.portfolio.currency;
  return (
    <Card
      title="Open Positions & PnL"
      className="lv-rc-positions"
      action={
        <div className="lv-rc-tabs">
          <button type="button" className={tab === "open" ? "is-on" : ""} onClick={() => onTab("open")}>
            Open Positions
          </button>
          <button type="button" className={tab === "closed" ? "is-on" : ""} onClick={() => onTab("closed")}>
            Closed Positions
          </button>
        </div>
      }
    >
      <div className="lv-rc-pnl-head">
        <span>
          Unrealized <strong className={signedClass(snap?.positions.unrealizedPnl)}>{moneyText(snap?.positions.unrealizedPnl, currency)}</strong>
        </span>
        <span>
          Realized <strong>{moneyText(snap?.positions.realizedPnl, currency)}</strong>
        </span>
      </div>
      <PositionTable rows={tab === "open" ? snap?.positions.open ?? [] : snap?.positions.closed ?? []} />
    </Card>
  );
}

export function EvolutionCard({
  snap,
  busy,
  onEvolve,
}: {
  snap: Snap | null;
  busy: string | null;
  onEvolve: () => void;
}) {
  const evo = snap?.strategyEvolution;
  const action = snap?.actions.evolve;
  const rows = evo?.rows ?? [];
  return (
    <Card
      title="Strategy Evolution"
      className="lv-rc-evolution"
      action={
        <button type="button" disabled={!action?.enabled || busy === "evolve"} title={action?.reason || ""} onClick={onEvolve}>
          {evo?.status === "PAUSED" ? "Resume Evolution Run" : "Start Evolution Run"}
        </button>
      }
    >
      <p className="lv-rc-muted">
        {evo?.bound ? `${evo.name || evo.labId} · ${evo.status || "UNMEASURED"}` : "No research lab run selected."} · owner {evo?.owner || "Research Lab"} · generation{" "}
        {generationLabel(evo?.currentGeneration.value, evo?.currentGeneration.measurement)}
      </p>
      {rows.length === 0 ? <p className="lv-rc-empty">No strategy generation recorded.</p> : null}
      {rows.length > 0 ? (
        <table className="lv-rc-table">
          <thead>
            <tr>
              <th>Gen</th>
              <th>Variant</th>
              <th>Status</th>
              <th>Validation</th>
              <th>Paper PnL</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.generation}-${row.variant}`}>
                <td>{generationLabel(row.generation, row.generation == null ? "UNMEASURED" : "MEASURED")}</td>
                <td>
                  {row.variant || "NOT AVAILABLE"}
                  {row.strategyVersion != null ? ` v${row.strategyVersion}` : ""}
                </td>
                <td>{row.status}</td>
                <td>{measuredText(row.validationScore)}</td>
                <td>{measuredText(row.paperPnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Card>
  );
}

export function GuardrailsCard({
  snap,
  busy,
  onKill,
}: {
  snap: Snap | null;
  busy: string | null;
  onKill: () => void;
}) {
  const gate = snap?.guardrails;
  const kill = snap?.actions.killSwitch;
  return (
    <Card title="Execution Guardrails" className="lv-rc-guard">
      <ul className="lv-rc-guards">
        <li>
          <span>Paper trading only</span>
          <strong className="is-safe">{gate?.paperTradingOnly ? "ON" : "UNMEASURED"}</strong>
        </li>
        <li>
          <span>Live trading</span>
          <strong className="is-bad">{gate?.liveTrading ?? "BLOCKED"}</strong>
        </li>
        <li>
          <span>Risk guard</span>
          <strong className={gate?.riskGuard === "ENABLED" ? "is-safe" : "is-bad"}>{gate?.riskGuard ?? "UNAVAILABLE"}</strong>
        </li>
        <li>
          <span>Max symbol exposure</span>
          <strong>{percentText(gate?.maxSymbolExposurePct)}</strong>
        </li>
        <li>
          <span>Max gross exposure</span>
          <strong>{percentText(gate?.maxGrossExposurePct)}</strong>
        </li>
        <li>
          <span>Per-trade risk</span>
          <strong>{percentText(gate?.perTradeRiskPct)}</strong>
        </li>
        <li>
          <span>Orders / day</span>
          <strong>{measuredText(gate?.maxOrdersPerDay)}</strong>
        </li>
        <li>
          <span>Max drawdown</span>
          <strong>{percentText(gate?.maxDrawdownPct)}</strong>
        </li>
        <li>
          <span>Daily loss limit</span>
          <strong>{percentText(gate?.dailyLossLimitPct)}</strong>
        </li>
        <li>
          <span>Kill switch</span>
          <strong className={gate?.killSwitch === "ARMED" ? "is-bad" : "is-warn"}>{gate?.killSwitch ?? "UNMEASURED"}</strong>
        </li>
      </ul>
      <button
        type="button"
        className="lv-rc-kill"
        disabled={!kill?.enabled || busy === "kill" || !snap?.selection.sessionId}
        title={kill?.reason || "Arming stops new paper exposure and pauses the session. It does not flatten."}
        onClick={onKill}
      >
        Arm kill switch
      </button>
      <p className="lv-rc-muted">Mandate {gate?.mandateFingerprint || "UNMEASURED"}. Live enablement stays blocked.</p>
    </Card>
  );
}
