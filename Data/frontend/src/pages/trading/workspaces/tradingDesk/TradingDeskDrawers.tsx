/**
 * Trading Desk (WAVE 5/6) — ADVANCED drawers + create-portfolio / deploy modals
 * with working backend actions. No PaperTradingPage / PortefeuillePage /
 * BrokerTradingPage embedding — every tab talks to the api client directly.
 */
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../../../api/client";
import type { TradeOrchestra } from "../../../../types/api";
import { UNMEASURED } from "../commandHub/hubFormat";
import type { TradingDeskData } from "./useTradingDeskData";

function Drawer({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="lv-td-drawer-backdrop" role="presentation" onClick={onClose}>
      <div
        className={`lv-td-drawer${wide ? " lv-td-drawer--wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h3>{title}</h3>
          <button type="button" className="lv-td-btn lv-td-btn--ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="lv-td-drawer__body">{children}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------- create portfolio */

export function CreatePortfolioDrawer({
  data,
  onClose,
}: {
  data: TradingDeskData;
  onClose: () => void;
}) {
  const [name, setName] = useState("Paper Wallet");
  const [capital, setCapital] = useState("100000");
  const [orchestraId, setOrchestraId] = useState("");
  const [shorting, setShorting] = useState(false);
  const [brokerMode, setBrokerMode] = useState("simulated");

  async function submit() {
    await data.createPortfolio({
      name: name.trim() || "Paper Wallet",
      initialEquity: Math.max(1, Number(capital) || 100000),
      orchestraId: orchestraId || null,
      shortingEnabled: shorting,
      brokerMode,
    });
    onClose();
  }

  return (
    <Drawer title="Create paper wallet / portfolio" onClose={onClose}>
      <p className="lv-td-muted">
        Virtual / simulated capital only. Live broker trading remains blocked everywhere on the desk.
      </p>
      <div className="lv-td-form">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Initial paper capital (USD)
          <input value={capital} onChange={(e) => setCapital(e.target.value)} />
        </label>
        <label>
          Trade Orchestra
          <select value={orchestraId} onChange={(e) => setOrchestraId(e.target.value)}>
            <option value="">Manual-only (no orchestra)</option>
            {data.orchestras.map((o) => (
              <option key={o.orchestraId} value={o.orchestraId}>
                {o.name || o.orchestraId}
              </option>
            ))}
          </select>
        </label>
        <label>
          Broker mode
          <select value={brokerMode} onChange={(e) => setBrokerMode(e.target.value)}>
            <option value="simulated">Simulated</option>
            <option value="alpaca_paper">Alpaca paper</option>
          </select>
        </label>
        <label className="lv-td-form__checkbox">
          <input type="checkbox" checked={shorting} onChange={(e) => setShorting(e.target.checked)} />
          Enable paper shorting
        </label>
      </div>
      <footer className="lv-td-drawer__footer">
        <button type="button" className="lv-td-btn" onClick={onClose} disabled={!!data.busy}>
          Cancel
        </button>
        <button type="button" className="lv-td-btn lv-td-btn--primary" onClick={() => void submit()} disabled={!!data.busy || !name.trim()}>
          {data.busy === "create-portfolio" ? "Creating…" : "Create wallet"}
        </button>
      </footer>
    </Drawer>
  );
}

/* -------------------------------------------------------------- deploy paper */

export function DeployPaperDrawer({
  data,
  onClose,
}: {
  data: TradingDeskData;
  onClose: () => void;
}) {
  const [strategyId, setStrategyId] = useState("");
  const [symbol, setSymbol] = useState(data.market);
  const [mode, setMode] = useState<"shadow" | "autonomous_paper">("shadow");
  const [initialCash, setInitialCash] = useState(100_000);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!strategyId.trim()) {
      setError("Strategy ID is required (create/find one in Strategy Lab).");
      return;
    }
    setError(null);
    const res = await data.createPaperDeployment({
      strategyId: strategyId.trim(),
      symbol,
      universe: [symbol],
      mode,
      initialCash,
    });
    if (res) onClose();
  }

  return (
    <Drawer title="Deploy paper strategy" onClose={onClose}>
      <p className="lv-td-muted">
        Creates a real market_sim paper deployment (shadow observe or autonomous paper). Live money stays
        BLOCKED — this only ever touches paper capital.
      </p>
      {error ? <p className="lv-td-drawer__error">{error}</p> : null}
      <div className="lv-td-form">
        <label>
          Strategy ID
          <input value={strategyId} onChange={(e) => setStrategyId(e.target.value)} placeholder="strategy-id from Strategy Lab" />
        </label>
        <label>
          Symbol
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label>
          Mode
          <select value={mode} onChange={(e) => setMode(e.target.value as "shadow" | "autonomous_paper")}>
            <option value="shadow">Shadow observe</option>
            <option value="autonomous_paper">Autonomous paper</option>
          </select>
        </label>
        <label>
          Initial cash
          <input type="number" value={initialCash} onChange={(e) => setInitialCash(Number(e.target.value) || 100000)} />
        </label>
      </div>
      <footer className="lv-td-drawer__footer">
        <button type="button" className="lv-td-btn" onClick={onClose} disabled={!!data.busy}>
          Cancel
        </button>
        <button
          type="button"
          className="lv-td-btn lv-td-btn--primary"
          onClick={() => void submit()}
          disabled={!!data.busy}
        >
          {data.busy === "create-deployment" ? "Deploying…" : "Deploy"}
        </button>
      </footer>
    </Drawer>
  );
}

/* ---------------------------------------------------------------- advanced */

type AdvancedTab = "fleet" | "orchestra" | "deployments" | "rebalance" | "broker" | "calibration";

const ADVANCED_TABS: { id: AdvancedTab; label: string }[] = [
  { id: "fleet", label: "Agent fleet" },
  { id: "orchestra", label: "Orchestra config" },
  { id: "deployments", label: "Paper deployments" },
  { id: "rebalance", label: "Rebalance" },
  { id: "broker", label: "Broker boundary" },
  { id: "calibration", label: "Execution calibration" },
];

function FleetTab({ data }: { data: TradingDeskData }) {
  const [selectedOrchestraId, setSelectedOrchestraId] = useState<string>(data.orchestras[0]?.orchestraId ?? "");
  const [full, setFull] = useState<TradeOrchestra | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedOrchestraId) {
      setFull(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .getTradeOrchestra(selectedOrchestraId)
      .then((res) => {
        if (!cancelled) setFull(res.orchestra);
      })
      .catch(() => {
        if (!cancelled) setFull(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedOrchestraId]);

  return (
    <div>
      <p className="lv-td-muted">
        Per-member start/pause is not exposed by the orchestra API — health and enablement are read-only here.
        Trigger real fleet activity with a deliberation-round mission below.
      </p>
      <div className="lv-td-form__row">
        <label>
          Orchestra
          <select value={selectedOrchestraId} onChange={(e) => setSelectedOrchestraId(e.target.value)}>
            <option value="">—</option>
            {data.orchestras.map((o) => (
              <option key={o.orchestraId} value={o.orchestraId}>
                {o.name} · {o.autonomyLevel}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="lv-td-btn lv-td-btn--primary"
          disabled={!selectedOrchestraId || !!data.busy}
          onClick={() => void data.launchMission(selectedOrchestraId, "deliberation_round")}
        >
          {data.busy === `mission-${selectedOrchestraId}` ? "Launching…" : "Launch deliberation round"}
        </button>
      </div>
      {loading ? <p className="lv-td-muted">Loading members…</p> : null}
      {full ? (
        <table className="lv-td-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Role</th>
              <th>Health</th>
              <th>Enabled</th>
            </tr>
          </thead>
          <tbody>
            {(full.members || []).map((m) => (
              <tr key={m.agentId}>
                <td>{m.name}</td>
                <td>{m.canonicalRole || m.role}</td>
                <td>
                  <span className={`lv-td-pill lv-td-pill--${String(m.health).toLowerCase()}`}>{m.health}</span>
                </td>
                <td>{m.enabled ? "Yes" : "No"}</td>
              </tr>
            ))}
            {!full.members?.length ? (
              <tr>
                <td colSpan={4} className="lv-td-muted">
                  No members registered for this orchestra.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function OrchestraConfigTab({ data }: { data: TradingDeskData }) {
  const [selectedOrchestraId, setSelectedOrchestraId] = useState<string>(data.orchestras[0]?.orchestraId ?? "");
  const [level, setLevel] = useState("A2");
  const orchestra = data.orchestras.find((o) => o.orchestraId === selectedOrchestraId) ?? null;

  return (
    <div>
      <div className="lv-td-form__row">
        <label>
          Orchestra
          <select value={selectedOrchestraId} onChange={(e) => setSelectedOrchestraId(e.target.value)}>
            <option value="">—</option>
            {data.orchestras.map((o) => (
              <option key={o.orchestraId} value={o.orchestraId}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Target autonomy
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="A0">A0</option>
            <option value="A1">A1</option>
            <option value="A2">A2</option>
            <option value="A3">A3</option>
            <option value="A4">A4</option>
          </select>
        </label>
        <button
          type="button"
          className="lv-td-btn lv-td-btn--primary"
          disabled={!selectedOrchestraId || !!data.busy}
          onClick={() => void data.setAutonomy(selectedOrchestraId, level)}
        >
          Set autonomy
        </button>
      </div>
      {orchestra ? (
        <dl className="lv-td-drawer__list">
          <div>
            <dt>Current autonomy</dt>
            <dd>{orchestra.autonomyLevel}</dd>
          </div>
          <div>
            <dt>Readiness</dt>
            <dd>{orchestra.readiness.state}</dd>
          </div>
          <div>
            <dt>Live trading</dt>
            <dd className="is-bad">Cannot enable live (mandate.cannotEnableLive=true)</dd>
          </div>
          <div>
            <dt>Universe</dt>
            <dd>{orchestra.mandate.universe.join(", ") || UNMEASURED}</dd>
          </div>
          <div>
            <dt>Max gross exposure</dt>
            <dd>{orchestra.mandate.maxGrossExposurePct}%</dd>
          </div>
          <div>
            <dt>Max drawdown</dt>
            <dd>{orchestra.mandate.maxDrawdownPct}%</dd>
          </div>
        </dl>
      ) : (
        <p className="lv-td-muted">Select an orchestra to inspect its mandate.</p>
      )}
    </div>
  );
}

function DeploymentsTab({ data }: { data: TradingDeskData }) {
  const [targetLevel, setTargetLevel] = useState("A3");
  if (!data.deployments.length) {
    return <p className="lv-td-muted">No paper deployments yet — use Deploy paper in the hero.</p>;
  }
  return (
    <div>
      <div className="lv-td-form__row">
        <label>
          Target level (promote)
          <select value={targetLevel} onChange={(e) => setTargetLevel(e.target.value)}>
            <option value="A2">A2</option>
            <option value="A3">A3</option>
            <option value="A4">A4</option>
          </select>
        </label>
      </div>
      <table className="lv-td-table">
        <thead>
          <tr>
            <th>Deployment</th>
            <th>Mode</th>
            <th>Status</th>
            <th>Kill switch</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.deployments.map((d) => (
            <tr key={d.deployment_id}>
              <td>{d.deployment_id.slice(0, 14)}</td>
              <td>{d.mode}</td>
              <td>
                <span className="lv-td-pill">{d.status}</span>
              </td>
              <td>{d.kill_switch ? <span className="lv-td-pill lv-td-pill--armed">ARMED</span> : "off"}</td>
              <td className="lv-td-row-actions">
                <button
                  type="button"
                  className="lv-td-btn lv-td-btn--ghost"
                  disabled={!!data.busy}
                  onClick={() => void data.shadowObserve(d.deployment_id)}
                >
                  Shadow
                </button>
                <button
                  type="button"
                  className="lv-td-btn lv-td-btn--ghost"
                  disabled={!!data.busy}
                  onClick={() => void data.promoteDeployment(d.deployment_id, targetLevel)}
                >
                  Promote
                </button>
                <button
                  type="button"
                  className="lv-td-btn lv-td-btn--danger"
                  disabled={!!data.busy}
                  onClick={() => void data.deploymentKillSwitch(d.deployment_id, !d.kill_switch)}
                >
                  {d.kill_switch ? "Disarm" : "Kill"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RebalanceTab({ data }: { data: TradingDeskData }) {
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  async function runPreview() {
    setBusy(true);
    try {
      const res = await data.rebalancePreview();
      setPreview(res);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p className="lv-td-muted">
        Preview computes proposed paper orders without executing them; Execute submits real paper orders
        against the selected wallet.
      </p>
      <div className="lv-td-lifecycle">
        <button type="button" className="lv-td-btn" disabled={!data.selectedPortfolioId || busy} onClick={() => void runPreview()}>
          {busy ? "Loading…" : "Preview"}
        </button>
        <button
          type="button"
          className="lv-td-btn lv-td-btn--primary"
          disabled={!data.selectedPortfolioId || !!data.busy}
          onClick={() => void data.rebalanceExecute()}
        >
          Execute
        </button>
        <button type="button" className="lv-td-btn" onClick={() => void data.exportPortfolio("csv")}>
          Export CSV
        </button>
      </div>
      {preview ? <pre className="lv-td-drawer__raw">{JSON.stringify(preview, null, 2).slice(0, 4000)}</pre> : null}
    </div>
  );
}

function BrokerBoundaryTab({ data }: { data: TradingDeskData }) {
  const caps = data.capabilities;
  return (
    <div>
      <p className="lv-td-banner is-bad">
        LIVE_TRADING_AVAILABLE = <strong>{data.liveTrading}</strong>
      </p>
      <dl className="lv-td-drawer__list">
        <div>
          <dt>Human authorization required</dt>
          <dd>{String(true)}</dd>
        </div>
        <div>
          <dt>Force live blocked</dt>
          <dd>{String(caps.force_live_blocked)}</dd>
        </div>
        <div>
          <dt>Live credentials separated</dt>
          <dd>{String(caps.live_credentials_separated)}</dd>
        </div>
        <div>
          <dt>Alpaca paper secrets present</dt>
          <dd>{String(caps.alpaca_paper_secrets_present)}</dd>
        </div>
        <div>
          <dt>Binance public reachable</dt>
          <dd>{String(caps.binance_public_reachable)}</dd>
        </div>
      </dl>
      <p className="lv-td-muted">
        Real broker credentials and live order placement are intentionally unavailable in this build.
        Use paper wallets and paper deployments above for all execution testing.
      </p>
    </div>
  );
}

function CalibrationTab({ data }: { data: TradingDeskData }) {
  const [deploymentId, setDeploymentId] = useState(data.deployments[0]?.deployment_id ?? "");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function fetchCalibration() {
    if (!deploymentId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await data.getExecutionCalibration(deploymentId.trim());
      if (res == null) {
        setError("No execution calibration available for this deployment yet.");
        setResult(null);
      } else {
        setResult(res);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="lv-td-form__row">
        <label>
          Deployment ID
          <select value={deploymentId} onChange={(e) => setDeploymentId(e.target.value)}>
            <option value="">—</option>
            {data.deployments.map((d) => (
              <option key={d.deployment_id} value={d.deployment_id}>
                {d.deployment_id.slice(0, 18)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="lv-td-btn" disabled={!deploymentId.trim() || busy} onClick={() => void fetchCalibration()}>
          {busy ? "Loading…" : "Get calibration"}
        </button>
      </div>
      {error ? <p className="lv-td-drawer__error">{error}</p> : null}
      {result ? <pre className="lv-td-drawer__raw">{JSON.stringify(result, null, 2).slice(0, 4000)}</pre> : null}
    </div>
  );
}

export function AdvancedDrawer({ data, onClose }: { data: TradingDeskData; onClose: () => void }) {
  const [tab, setTab] = useState<AdvancedTab>("fleet");

  return (
    <Drawer title="Trading Desk · Advanced" onClose={onClose} wide>
      <div className="lv-td-advanced">
        <nav className="lv-td-advanced__nav">
          {ADVANCED_TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`lv-td-tab${tab === t.id ? " is-active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="lv-td-advanced__body">
          {tab === "fleet" ? <FleetTab data={data} /> : null}
          {tab === "orchestra" ? <OrchestraConfigTab data={data} /> : null}
          {tab === "deployments" ? <DeploymentsTab data={data} /> : null}
          {tab === "rebalance" ? <RebalanceTab data={data} /> : null}
          {tab === "broker" ? <BrokerBoundaryTab data={data} /> : null}
          {tab === "calibration" ? <CalibrationTab data={data} /> : null}
        </div>
      </div>
    </Drawer>
  );
}
