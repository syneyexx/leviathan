/**
 * Strategy Lab (WAVE 5) — ADVANCED drawers + modals with working backend actions.
 * Create lab run, pause/resume/cancel, explain candidate, strategy builder/versions,
 * simulation run controls, compare, and Q-gate / cost-pack diagnostics.
 */
import { useEffect, useState, type ReactNode } from "react";
import { UNMEASURED, asRec } from "../commandHub/hubFormat";
import type { DiscoveryRow, StrategyLabData } from "./useStrategyLabData";

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
    <div className="lv-sl-drawer-backdrop" role="presentation" onClick={onClose}>
      <div
        className={`lv-sl-drawer${wide ? " lv-sl-drawer--wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h3>{title}</h3>
          <button type="button" className="lv-sl-btn lv-sl-btn--ghost" onClick={onClose} aria-label="Sluiten">
            ✕
          </button>
        </header>
        <div className="lv-sl-drawer__body">{children}</div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------- create run modal */

export function CreateLabRunDrawer({
  data,
  onClose,
  onCreated,
}: {
  data: StrategyLabData;
  onClose: () => void;
  onCreated: (labId: string) => void;
}) {
  const [name, setName] = useState("Nieuwe zoekopdracht");
  const [sourceId, setSourceId] = useState(data.sources[0]?.source_id ?? "");
  const [strategyId, setStrategyId] = useState<string>("");
  const [runMode, setRunMode] = useState("SEED_EXISTING_STRATEGY");
  const [hypothesis, setHypothesis] = useState("");
  const [maxCandidates, setMaxCandidates] = useState(10);
  const [maxIterations, setMaxIterations] = useState(3);
  const [seed, setSeed] = useState(42);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!sourceId) {
      setError("Selecteer eerst een markt-databron (READY) — beheer via Market Data.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const lab = await data.createLabRun({
        name,
        sourceId,
        strategyId: strategyId || undefined,
        runMode,
        hypothesis,
        maxCandidates,
        maxIterations,
        seed,
      });
      onCreated(String(lab.lab_id ?? ""));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Aanmaken zoekopdracht mislukt");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer title="Nieuwe zoekopdracht" onClose={onClose}>
      {error ? <p className="lv-sl-drawer__error">{error}</p> : null}
      <div className="lv-sl-form">
        <label>
          Naam
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Databron (READY)
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">—</option>
            {data.sources
              .filter((s) => s.status === "READY")
              .map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.symbol} · {s.timeframe} · {s.bar_count} bars
                </option>
              ))}
          </select>
        </label>
        <label>
          Seed-strategie (optioneel)
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            <option value="">— autonome discovery —</option>
            {data.strategies.map((s) => (
              <option key={s.strategy_id} value={s.strategy_id}>
                {s.name} · v{s.current_version}
              </option>
            ))}
          </select>
        </label>
        <label>
          Run mode
          <select value={runMode} onChange={(e) => setRunMode(e.target.value)}>
            <option value="SEED_EXISTING_STRATEGY">Seed existing strategy</option>
            <option value="AUTONOMOUS_DISCOVERY">Autonomous discovery</option>
          </select>
        </label>
        <label>
          Hypothese
          <textarea
            value={hypothesis}
            onChange={(e) => setHypothesis(e.target.value)}
            placeholder="Bijv. volatility compression voorafgaand aan trend breakout"
          />
        </label>
        <div className="lv-sl-form__row">
          <label>
            Max candidates
            <input type="number" min={1} max={100} value={maxCandidates} onChange={(e) => setMaxCandidates(Number(e.target.value) || 10)} />
          </label>
          <label>
            Max iteraties
            <input type="number" min={1} max={50} value={maxIterations} onChange={(e) => setMaxIterations(Number(e.target.value) || 3)} />
          </label>
          <label>
            Seed
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 42)} />
          </label>
        </div>
      </div>
      <footer className="lv-sl-drawer__footer">
        <button type="button" className="lv-sl-btn" onClick={onClose} disabled={busy}>
          Annuleren
        </button>
        <button type="button" className="lv-sl-btn lv-sl-btn--primary" onClick={() => void submit()} disabled={busy}>
          {busy ? "Aanmaken…" : "Zoekopdracht starten"}
        </button>
      </footer>
    </Drawer>
  );
}

/* ------------------------------------------------------------- compare drawer */

export function CompareDrawer({
  rows,
  onClose,
  onClear,
}: {
  rows: DiscoveryRow[];
  onClose: () => void;
  onClear: () => void;
}) {
  return (
    <Drawer title="Strategieën vergelijken" onClose={onClose} wide>
      <div className="lv-sl-compare">
        <table className="lv-sl-table">
          <thead>
            <tr>
              <th>Metric</th>
              {rows.map((r) => (
                <th key={r.id}>{r.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Familie</td>
              {rows.map((r) => <td key={r.id}>{r.family}</td>)}
            </tr>
            <tr>
              <td>Markt</td>
              {rows.map((r) => <td key={r.id}>{r.market}</td>)}
            </tr>
            <tr>
              <td>Mode</td>
              {rows.map((r) => <td key={r.id}>{r.mode}</td>)}
            </tr>
            <tr>
              <td>Sharpe</td>
              {rows.map((r) => <td key={r.id}>{r.sharpe}</td>)}
            </tr>
            <tr>
              <td>Win rate</td>
              {rows.map((r) => <td key={r.id}>{r.winRate}</td>)}
            </tr>
            <tr>
              <td>Max DD</td>
              {rows.map((r) => <td key={r.id}>{r.maxDrawdown}</td>)}
            </tr>
            <tr>
              <td>Paper PnL</td>
              {rows.map((r) => <td key={r.id}>{r.paperPnl}</td>)}
            </tr>
            <tr>
              <td>Confidence</td>
              {rows.map((r) => <td key={r.id}>{r.confidence}</td>)}
            </tr>
            <tr>
              <td>Status</td>
              {rows.map((r) => <td key={r.id}>{r.status}</td>)}
            </tr>
          </tbody>
        </table>
      </div>
      <footer className="lv-sl-drawer__footer">
        <button type="button" className="lv-sl-btn" onClick={onClear}>
          Selectie wissen
        </button>
      </footer>
    </Drawer>
  );
}

/* ------------------------------------------------------------- advanced drawer */

type AdvancedTab =
  | "hypotheses"
  | "perception"
  | "generations"
  | "population"
  | "lineage"
  | "lessons"
  | "validation"
  | "costpack"
  | "simulation"
  | "builder";

const ADVANCED_TABS: { id: AdvancedTab; label: string }[] = [
  { id: "hypotheses", label: "Hypotheses" },
  { id: "perception", label: "Perception" },
  { id: "generations", label: "Generations" },
  { id: "population", label: "Population" },
  { id: "lineage", label: "Lineage" },
  { id: "lessons", label: "Lessons" },
  { id: "validation", label: "Validation / Q-gates" },
  { id: "costpack", label: "Cost pack" },
  { id: "simulation", label: "Simulation" },
  { id: "builder", label: "Strategy builder" },
];

function LabLifecycleBar({ data, labId }: { data: StrategyLabData; labId: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try {
      await fn();
      await data.loadLabDetail(labId, true);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="lv-sl-lifecycle">
      <button type="button" className="lv-sl-btn" disabled={!!busy} onClick={() => void act("pause", () => data.pauseLab(labId))}>
        {busy === "pause" ? "…" : "Pause"}
      </button>
      <button type="button" className="lv-sl-btn" disabled={!!busy} onClick={() => void act("resume", () => data.resumeLab(labId))}>
        {busy === "resume" ? "…" : "Resume"}
      </button>
      <button
        type="button"
        className="lv-sl-btn lv-sl-btn--danger"
        disabled={!!busy}
        onClick={() => void act("cancel", () => data.cancelLab(labId))}
      >
        {busy === "cancel" ? "…" : "Cancel"}
      </button>
    </div>
  );
}

function PopulationTab({ data, labId }: { data: StrategyLabData; labId: string }) {
  const detail = data.labDetails[labId];
  if (!detail) return <p className="lv-sl-muted">Laden…</p>;
  return (
    <div>
      <p className="lv-sl-muted">
        Qualified: <strong>{detail.qualifiedCandidate ?? "—"}</strong> · Best train:{" "}
        <strong>{detail.bestTrainCandidate ?? "—"}</strong> · Best validation:{" "}
        <strong>{detail.bestValidationCandidate ?? "—"}</strong>
      </p>
      <table className="lv-sl-table">
        <thead>
          <tr>
            <th>Candidate</th>
            <th>Gen</th>
            <th>Familie</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {detail.candidates.map((c) => {
            const cid = String((c as Record<string, unknown>).candidate_id ?? "");
            return (
              <tr key={cid}>
                <td>{cid.slice(0, 10)}</td>
                <td>{String((c as Record<string, unknown>).generation ?? "—")}</td>
                <td>{String((c as Record<string, unknown>).family ?? "—")}</td>
                <td>{String((c as Record<string, unknown>).status ?? "—")}</td>
                <td>
                  <button type="button" className="lv-sl-btn lv-sl-btn--ghost" onClick={() => void data.explainCandidate(labId, cid)}>
                    Explain
                  </button>
                </td>
              </tr>
            );
          })}
          {!detail.candidates.length ? (
            <tr>
              <td colSpan={5} className="lv-sl-muted">
                Nog geen candidates voor deze lab run.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {detail.explainCandidateId ? (
        <div className="lv-sl-explain">
          <h4>Explain · {detail.explainCandidateId.slice(0, 10)}</h4>
          {detail.explainError ? <p className="lv-sl-drawer__error">{detail.explainError}</p> : null}
          <pre>{JSON.stringify(detail.explain ?? {}, null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}

function LineageTab({ data, labId }: { data: StrategyLabData; labId: string }) {
  const detail = data.labDetails[labId];
  if (!detail) return <p className="lv-sl-muted">Laden…</p>;
  return (
    <ul className="lv-sl-lineage">
      {detail.candidates.map((c) => {
        const rec = c as Record<string, unknown>;
        const cid = String(rec.candidate_id ?? "");
        const parents = Array.isArray(rec.parent_refs) ? (rec.parent_refs as unknown[]) : [];
        const mutations = Array.isArray(rec.mutations) ? (rec.mutations as string[]) : [];
        return (
          <li key={cid}>
            <strong>{cid.slice(0, 10)}</strong>
            <span>method: {String(rec.proposal_method ?? "—")}</span>
            <span>parents: {parents.length ? parents.map((p) => String(asRec(p)?.candidate_id ?? p)).join(", ") : "—"}</span>
            <span>mutations: {mutations.length ? mutations.join(", ") : "—"}</span>
          </li>
        );
      })}
      {!detail.candidates.length ? <li className="lv-sl-muted">Geen lineage-data.</li> : null}
    </ul>
  );
}

function AdvancedDrawer({
  data,
  labId,
  strategyId,
  onClose,
}: {
  data: StrategyLabData;
  labId: string | null;
  strategyId: string | null;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<AdvancedTab>("hypotheses");

  useEffect(() => {
    if (labId) void data.loadLabDetail(labId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [labId]);

  const detail = labId ? data.labDetails[labId] : undefined;

  return (
    <Drawer title="Strategy Lab · Advanced" onClose={onClose} wide>
      <div className="lv-sl-advanced">
        <nav className="lv-sl-advanced__nav">
          {ADVANCED_TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`lv-sl-tab${tab === t.id ? " is-active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="lv-sl-advanced__body">
          {!labId && tab !== "simulation" && tab !== "builder" ? (
            <p className="lv-sl-muted">
              Selecteer een strategie/trial die aan een research sessie (lab run) is gekoppeld om deze tab te
              vullen.
            </p>
          ) : null}

          {labId && detail?.loading ? <p className="lv-sl-muted">Lab detail laden…</p> : null}
          {labId && detail?.error ? <p className="lv-sl-drawer__error">{detail.error}</p> : null}

          {labId ? (
            <div className="lv-sl-advanced__lab-head">
              <span>Lab: {labId.slice(0, 12)}</span>
              <LabLifecycleBar data={data} labId={labId} />
            </div>
          ) : null}

          {tab === "hypotheses" && labId && detail ? (
            <ul className="lv-sl-list">
              {detail.hypotheses.map((h, i) => (
                <li key={String((h as Record<string, unknown>).hypothesis_id ?? i)}>
                  {String((h as Record<string, unknown>).text ?? (h as Record<string, unknown>).hypothesis ?? JSON.stringify(h))}
                </li>
              ))}
              {!detail.hypotheses.length ? <li className="lv-sl-muted">Geen hypotheses geregistreerd.</li> : null}
            </ul>
          ) : null}

          {tab === "perception" && labId && detail ? (
            <div>
              <p className="lv-sl-muted">Status: {detail.perceptionStatus}</p>
              <pre>{JSON.stringify(detail.perception ?? {}, null, 2)}</pre>
            </div>
          ) : null}

          {tab === "generations" && labId && detail ? (
            <div>
              <p className="lv-sl-muted">Huidige generatie: {detail.currentGeneration ?? UNMEASURED}</p>
              <table className="lv-sl-table">
                <thead>
                  <tr>
                    <th>Generatie</th>
                    <th>Samenvatting</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.generations.map((g, i) => (
                    <tr key={i}>
                      <td>{String((g as Record<string, unknown>).generation ?? i)}</td>
                      <td>
                        <pre>{JSON.stringify(g, null, 0)}</pre>
                      </td>
                    </tr>
                  ))}
                  {!detail.generations.length ? (
                    <tr>
                      <td colSpan={2} className="lv-sl-muted">
                        Nog geen generaties.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
              <h4>Family probabilities</h4>
              <ul className="lv-sl-list">
                {Object.entries(detail.familyProbabilities).map(([fam, p]) => (
                  <li key={fam}>
                    {fam}: {(p * 100).toFixed(1)}%
                  </li>
                ))}
                {!Object.keys(detail.familyProbabilities).length ? (
                  <li className="lv-sl-muted">Geen family probabilities.</li>
                ) : null}
              </ul>
            </div>
          ) : null}

          {tab === "population" && labId ? <PopulationTab data={data} labId={labId} /> : null}
          {tab === "lineage" && labId ? <LineageTab data={data} labId={labId} /> : null}

          {tab === "lessons" && labId && detail ? (
            <ul className="lv-sl-list">
              {detail.lessons.map((l, i) => (
                <li key={i}>{JSON.stringify(l)}</li>
              ))}
              {!detail.lessons.length ? <li className="lv-sl-muted">Geen lessons geregistreerd.</li> : null}
            </ul>
          ) : null}

          {tab === "validation" ? <ValidationTab data={data} /> : null}
          {tab === "costpack" ? <CostPackTab data={data} labId={labId} /> : null}
          {tab === "simulation" ? <SimulationTab data={data} /> : null}
          {tab === "builder" ? <StrategyBuilderTab data={data} initialStrategyId={strategyId} /> : null}
        </div>
      </div>
    </Drawer>
  );
}

function ValidationTab({ data }: { data: StrategyLabData }) {
  const [qualId, setQualId] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [gates, setGates] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const overview = data.overview as { blockers?: unknown[] } | null;

  async function fetchBoth() {
    if (!qualId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const [run, g] = await Promise.all([
        data.getQualificationRun(qualId.trim()),
        data.getQualificationGates(qualId.trim()),
      ]);
      setResult(run);
      setGates(g);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Qualification run niet gevonden");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="lv-sl-qual-summary">
        <span>Qualification state (overview): <strong>{data.qualificationState}</strong></span>
        <span>Live trading: <strong className="is-bad">{data.liveTrading}</strong></span>
      </div>
      {overview?.blockers?.length ? (
        <ul className="lv-sl-list">
          {overview.blockers.slice(0, 10).map((b, i) => (
            <li key={i}>{String(b)}</li>
          ))}
        </ul>
      ) : (
        <p className="lv-sl-muted">Geen open blockers in de laatste overview-snapshot.</p>
      )}
      <div className="lv-sl-form__row">
        <label>
          Qualification run ID
          <input value={qualId} onChange={(e) => setQualId(e.target.value)} placeholder="qualification-run-id" />
        </label>
        <button type="button" className="lv-sl-btn" disabled={busy || !qualId.trim()} onClick={() => void fetchBoth()}>
          {busy ? "Laden…" : "Gates ophalen"}
        </button>
      </div>
      {error ? <p className="lv-sl-drawer__error">{error}</p> : null}
      {result ? (
        <div>
          <h4>Run</h4>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </div>
      ) : null}
      {gates ? (
        <div>
          <h4>Gates (Q01–Q11)</h4>
          <pre>{JSON.stringify(gates, null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}

function CostPackTab({ data, labId }: { data: StrategyLabData; labId: string | null }) {
  const [feeBps, setFeeBps] = useState(10);
  const [slippageBps, setSlippageBps] = useState(5);
  const [seed, setSeed] = useState(42);
  const detail = labId ? data.labDetails[labId] : undefined;

  return (
    <div>
      <div className="lv-sl-form__row">
        <label>
          Fee (bps)
          <input type="number" value={feeBps} onChange={(e) => setFeeBps(Number(e.target.value) || 0)} />
        </label>
        <label>
          Slippage (bps)
          <input type="number" value={slippageBps} onChange={(e) => setSlippageBps(Number(e.target.value) || 0)} />
        </label>
        <label>
          Seed
          <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 42)} />
        </label>
        <button
          type="button"
          className="lv-sl-btn"
          onClick={() => void data.loadCostPack(labId ?? "global", { feeBps, slippageBps, seed })}
        >
          Cost pack ophalen
        </button>
      </div>
      <pre>{JSON.stringify((labId ? detail?.costPack : null) ?? {}, null, 2)}</pre>
    </div>
  );
}

function SimulationTab({ data }: { data: StrategyLabData }) {
  const [sourceId, setSourceId] = useState(data.sources[0]?.source_id ?? "");
  const [strategyId, setStrategyId] = useState("");
  const [seed, setSeed] = useState(42);
  const [initialCash, setInitialCash] = useState(100_000);
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="lv-sl-form__row">
        <label>
          Databron
          <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">—</option>
            {data.sources.map((s) => (
              <option key={s.source_id} value={s.source_id}>
                {s.symbol} · {s.timeframe}
              </option>
            ))}
          </select>
        </label>
        <label>
          Strategie
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            <option value="">— default MA cross —</option>
            {data.strategies.map((s) => (
              <option key={s.strategy_id} value={s.strategy_id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Seed
          <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 42)} />
        </label>
        <label>
          Initial cash
          <input type="number" value={initialCash} onChange={(e) => setInitialCash(Number(e.target.value) || 100000)} />
        </label>
      </div>
      <div className="lv-sl-lifecycle">
        <button
          type="button"
          className="lv-sl-btn lv-sl-btn--primary"
          disabled={!!busy || !sourceId}
          onClick={() =>
            void run("create", () => data.createSimRun({ sourceId, strategyId: strategyId || undefined, seed, initialCash }))
          }
        >
          {busy === "create" ? "…" : "Nieuwe run"}
        </button>
        <button
          type="button"
          className="lv-sl-btn"
          disabled={!!busy || !data.selectedSimRunId}
          onClick={() => void run("start", () => data.startSimRun(data.selectedSimRunId as string))}
        >
          Start
        </button>
        <button
          type="button"
          className="lv-sl-btn"
          disabled={!!busy || !data.selectedSimRunId}
          onClick={() => void run("pause", () => data.pauseSimRun(data.selectedSimRunId as string))}
        >
          Pause
        </button>
        <button
          type="button"
          className="lv-sl-btn"
          disabled={!!busy || !data.selectedSimRunId}
          onClick={() => void run("step", () => data.stepSimRun(data.selectedSimRunId as string))}
        >
          Step
        </button>
        <button
          type="button"
          className="lv-sl-btn lv-sl-btn--danger"
          disabled={!!busy || !data.selectedSimRunId}
          onClick={() => void run("stop", () => data.stopSimRun(data.selectedSimRunId as string))}
        >
          Stop
        </button>
      </div>
      <table className="lv-sl-table">
        <thead>
          <tr>
            <th></th>
            <th>Run</th>
            <th>Status</th>
            <th>Equity</th>
            <th>Bar</th>
          </tr>
        </thead>
        <tbody>
          {data.simRuns.map((r) => (
            <tr
              key={r.run_id}
              className={data.selectedSimRunId === r.run_id ? "is-selected" : ""}
              onClick={() => data.setSelectedSimRunId(r.run_id)}
            >
              <td>
                <input type="radio" checked={data.selectedSimRunId === r.run_id} onChange={() => data.setSelectedSimRunId(r.run_id)} />
              </td>
              <td>{r.run_id.slice(0, 10)} · {r.symbol}</td>
              <td>{r.status}</td>
              <td>{r.equity}</td>
              <td>{r.bar_index}/{r.bar_count}</td>
            </tr>
          ))}
          {!data.simRuns.length ? (
            <tr>
              <td colSpan={5} className="lv-sl-muted">
                Nog geen simulatie runs.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {data.simLive ? (
        <p className="lv-sl-muted">
          Live: {data.simLive.fills.length} fills · {data.simLive.messages.length} messages · causality violations{" "}
          {data.simLive.run.causality_violations}
        </p>
      ) : null}
    </div>
  );
}

function StrategyBuilderTab({
  data,
  initialStrategyId,
}: {
  data: StrategyLabData;
  initialStrategyId: string | null;
}) {
  const [selected, setSelected] = useState<string | null>(initialStrategyId);
  const [name, setName] = useState("MA Cross");
  const [description, setDescription] = useState("Causal moving-average crossover");
  const [kind, setKind] = useState<"ma_cross" | "mean_reversion">("ma_cross");
  const [fastMa, setFastMa] = useState(10);
  const [slowMa, setSlowMa] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) return;
    void data.loadStrategyVersions(selected);
    const s = data.strategyById.get(selected);
    if (s) {
      setName(s.name);
      setDescription(s.description);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        name,
        description,
        tags: [kind, "paper"],
        parameters: { fast_ma: fastMa, slow_ma: slowMa, lookback: Math.max(slowMa, 20) },
        entryRules: { kind },
        exitRules: { kind },
        brainDependencies: ["knowledge", "memory", "neuro"],
        requiredTimeframes: ["1h"],
      };
      if (selected) {
        const updated = await data.versionStrategy(selected, { ...payload, changelog: `Updated ${kind} parameters` });
        setSelected(updated.strategy.strategy_id);
      } else {
        const created = await data.createStrategy(payload);
        setSelected(created.strategy.strategy_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Opslaan mislukt");
    } finally {
      setBusy(false);
    }
  }

  const versions = selected ? data.strategyVersions[selected] ?? [] : [];

  return (
    <div>
      {error ? <p className="lv-sl-drawer__error">{error}</p> : null}
      <div className="lv-sl-form__row">
        <label>
          Strategie
          <select value={selected ?? ""} onChange={(e) => setSelected(e.target.value || null)}>
            <option value="">— Nieuwe strategie —</option>
            {data.strategies.map((s) => (
              <option key={s.strategy_id} value={s.strategy_id}>
                {s.name} · v{s.current_version}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="lv-sl-form">
        <label>
          Naam
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Beschrijving
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="lv-sl-form__row">
          <label>
            Rule kind
            <select value={kind} onChange={(e) => setKind(e.target.value as "ma_cross" | "mean_reversion")}>
              <option value="ma_cross">MA cross</option>
              <option value="mean_reversion">Mean reversion</option>
            </select>
          </label>
          <label>
            Fast MA
            <input type="number" value={fastMa} onChange={(e) => setFastMa(Number(e.target.value) || 10)} />
          </label>
          <label>
            Slow MA
            <input type="number" value={slowMa} onChange={(e) => setSlowMa(Number(e.target.value) || 30)} />
          </label>
        </div>
      </div>
      <div className="lv-sl-lifecycle">
        <button type="button" className="lv-sl-btn lv-sl-btn--primary" disabled={busy} onClick={() => void save()}>
          {busy ? "Opslaan…" : selected ? "Save Version" : "Create Strategy"}
        </button>
      </div>
      <table className="lv-sl-table">
        <thead>
          <tr>
            <th>Versie</th>
            <th>Changelog</th>
            <th>Aangemaakt</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.version_id}>
              <td>v{v.version}</td>
              <td>{v.changelog || "—"}</td>
              <td>{v.created_at}</td>
            </tr>
          ))}
          {!versions.length ? (
            <tr>
              <td colSpan={3} className="lv-sl-muted">
                Selecteer een strategie om versies te zien.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

export { AdvancedDrawer };
