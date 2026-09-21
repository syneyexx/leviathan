import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabRun, type LabStrategy } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabKeyValues, LabNotice, LabStatus, LabTable, num, pct, pick, refusalOf, runAction, shortTime, text } from "./shared";

const SPLITS = ["development", "validation", "sealed_test"];

function EquityCurve({ points, benchmark }: { points: Array<[string, number]>; benchmark: Array<[string, number]> }) {
  const width = 720;
  const height = 220;
  const pad = 18;
  if (points.length < 2) {
    return <LabEmpty title="Nog geen equitycurve" hint="De curve verschijnt zodra de simulatie observaties heeft verwerkt." />;
  }
  const all = [...points.map((item) => item[1]), ...benchmark.map((item) => item[1])];
  const max = Math.max(...all);
  const min = Math.min(...all);
  const span = Math.max(max - min, 1e-9);
  const path = (series: Array<[string, number]>) =>
    series
      .map((item, index) => {
        const x = pad + (index / Math.max(series.length - 1, 1)) * (width - pad * 2);
        const y = pad + ((max - item[1]) / span) * (height - pad * 2);
        return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  return (
    <svg className="lab-curve" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Equitycurve van de simulatie">
      {[0.25, 0.5, 0.75].map((ratio) => {
        const y = pad + ratio * (height - pad * 2);
        return <line key={ratio} className="chart-grid-line" x1={pad} x2={width - pad} y1={y} y2={y} />;
      })}
      {benchmark.length > 1 ? <path className="lab-curve-benchmark" d={path(benchmark)} /> : null}
      <path className="lab-curve-equity" d={path(points)} />
    </svg>
  );
}

export function SimulatorTab({ runId, onSelectRun }: { runId: string; onSelectRun: (runId: string) => void }) {
  const [runs, setRuns] = useState<LabRun[]>([]);
  const [strategies, setStrategies] = useState<LabStrategy[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [decisions, setDecisions] = useState<Array<Record<string, unknown>>>([]);
  const [snapshots, setSnapshots] = useState<Array<Record<string, unknown>>>([]);
  const [busy, setBusy] = useState(false);
  const [compareWith, setCompareWith] = useState("");
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [rewindAt, setRewindAt] = useState("");
  const [form, setForm] = useState({ strategy_id: "", split: "development", starting_cash: "100000", base_currency: "USD", seed: "7", lookback: "300", speed: "1" });

  const refreshRuns = useCallback(async () => {
    try {
      const [runList, strategyList] = await Promise.all([hadesApi.labRuns({ limit: 50 }), hadesApi.labStrategies({ limit: 200 })]);
      setRuns(runList.runs || []);
      setStrategies(strategyList.strategies || []);
      setForm((current) => (current.strategy_id ? current : { ...current, strategy_id: strategyList.strategies?.[0]?.strategy_id || "" }));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Runs laden mislukt.");
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    if (!id) return;
    try {
      const [detailPayload, decisionPayload, snapshotPayload] = await Promise.all([
        hadesApi.labRun(id),
        hadesApi.labRunDecisions(id, 60),
        hadesApi.labRunSnapshots(id, 200),
      ]);
      setDetail(detailPayload);
      setDecisions(decisionPayload.decisions || []);
      setSnapshots(snapshotPayload.snapshots || []);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Rundetail laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    void loadDetail(runId);
  }, [runId, loadDetail]);

  const run = (detail?.run as LabRun | undefined) ?? null;
  const active = run ? run.status === "running" || run.status === "queued" : false;

  useEffect(() => {
    if (!active || !runId) return;
    const timer = window.setInterval(() => {
      void loadDetail(runId);
      void refreshRuns();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [active, runId, loadDetail, refreshRuns]);

  const equity = useMemo(() => (Array.isArray(detail?.equity_curve) ? (detail!.equity_curve as Array<[string, number]>) : []), [detail]);
  const benchmark = useMemo(() => (Array.isArray(detail?.benchmark_curve) ? (detail!.benchmark_curve as Array<[string, number]>) : []), [detail]);
  const metrics = (pick(run?.result, "metrics") as Record<string, unknown> | undefined) || {};
  const jobStatus = text(pick(detail, "job.status"), "—");

  const start = async () => {
    if (!form.strategy_id) {
      toast.error("Kies eerst een strategie in Strategy Lab.");
      return;
    }
    const result = await runAction(
      () => hadesApi.startLabRun({
        strategy_id: form.strategy_id,
        split: form.split,
        starting_cash: form.starting_cash,
        base_currency: form.base_currency,
        seed: Number(form.seed) || 7,
        lookback: Number(form.lookback) || 300,
      }),
      { busy: setBusy, failure: "Simulatie starten mislukt." },
    );
    if (!result) return;
    const refusal = refusalOf(result as Record<string, unknown>);
    if (refusal) {
      toast.message(`Geweigerd: ${refusal}`);
      return;
    }
    toast.success("Simulatie in de wachtrij gezet.");
    if (result.run_id) onSelectRun(result.run_id);
    await refreshRuns();
  };

  const control = async (action: string, value?: number) => {
    if (!runId) return;
    const result = await runAction(() => hadesApi.controlLabRun(runId, action, value), { busy: setBusy, failure: "Besturing mislukt." });
    const refusal = refusalOf(result as Record<string, unknown> | null);
    if (refusal) toast.message(refusal);
    else toast.success(`Klokopdracht '${action}' verwerkt.`);
    await loadDetail(runId);
  };

  const rewind = async () => {
    if (!runId || !rewindAt.trim()) {
      toast.error("Geef een simulatietijdstip om naar terug te spoelen.");
      return;
    }
    const result = await runAction(() => hadesApi.rewindLabRun(runId, rewindAt.trim()), { busy: setBusy, failure: "Terugspoelen mislukt." });
    if (!result) return;
    const refusal = refusalOf(result as Record<string, unknown>);
    if (refusal) {
      toast.message(refusal);
      return;
    }
    toast.success("Nieuwe runtak aangemaakt; de oorspronkelijke run blijft ongewijzigd.");
    if (result.run_id) onSelectRun(String(result.run_id));
    await refreshRuns();
  };

  const compare = async () => {
    if (!runId || !compareWith) return;
    const result = await runAction(() => hadesApi.labCompareRuns(runId, compareWith), { busy: setBusy, failure: "Vergelijken mislukt." });
    if (result) setComparison(result);
  };

  return (
    <div className="lab-stack">
      <div className="lab-grid-2">
        <Panel title="Nieuwe simulatie">
          <div className="lab-form">
            <LabField label="Strategie">
              <select className="lab-select" value={form.strategy_id} onChange={(event) => setForm({ ...form, strategy_id: event.target.value })}>
                <option value="">— kies —</option>
                {strategies.map((row) => <option key={row.strategy_id} value={row.strategy_id}>{row.name} (v{row.current_version}, {row.status})</option>)}
              </select>
            </LabField>
            <div className="lab-form-row">
              <LabField label="Split" hint="sealed_test is eenmalig per strategieversie.">
                <select className="lab-select" value={form.split} onChange={(event) => setForm({ ...form, split: event.target.value })}>
                  {SPLITS.map((split) => <option key={split} value={split}>{split}</option>)}
                </select>
              </LabField>
              <LabField label="Startkapitaal"><Input value={form.starting_cash} onChange={(event) => setForm({ ...form, starting_cash: event.target.value })} /></LabField>
            </div>
            <div className="lab-form-row">
              <LabField label="Basisvaluta"><Input value={form.base_currency} onChange={(event) => setForm({ ...form, base_currency: event.target.value })} /></LabField>
              <LabField label="Seed"><Input value={form.seed} onChange={(event) => setForm({ ...form, seed: event.target.value })} /></LabField>
              <LabField label="Lookback"><Input value={form.lookback} onChange={(event) => setForm({ ...form, lookback: event.target.value })} /></LabField>
            </div>
            <Button disabled={busy} onClick={() => void start()}>Start simulatie</Button>
            <small className="lab-hint">
              De simulatie loopt op één virtuele klok. Een order wordt pas gevuld op een gebeurtenis ná de observatie waarop
              het besluit is genomen.
            </small>
          </div>
        </Panel>

        <Panel title="Klokbesturing" actions={<LabStatus value={run?.status} />}>
          {run ? (
            <div className="lab-form">
              <LabKeyValues
                rows={[
                  ["Run", <span key="r" className="lab-mono">{run.run_id}</span>],
                  ["Simulatietijd", shortTime(run.simulation_time)],
                  ["Venster", `${shortTime(run.first_event_time)} → ${shortTime(run.last_event_time)}`],
                  ["Verwerkte events", num(run.events_processed, 0)],
                  ["Wachtrijstatus", jobStatus],
                ]}
              />
              <Progress value={Number(run.progress) || 0} />
              <div className="lab-button-row">
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void control("resume")}>Speel</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void control("pause")}>Pauzeer</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void control("step", 1)}>Stap</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void control("step", 100)}>100 stappen</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void control("cancel")}>Annuleer</Button>
              </div>
              <div className="lab-form-row">
                <LabField label="Snelheid"><Input value={form.speed} onChange={(event) => setForm({ ...form, speed: event.target.value })} /></LabField>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void control("speed", Number(form.speed) || 1)}>Pas snelheid toe</Button>
              </div>
              <div className="lab-form-row">
                <LabField label="Terugspoelen naar" hint="Maakt een nieuwe tak; de oude run blijft intact."><Input value={rewindAt} placeholder="2021-06-01T00:00:00+00:00" onChange={(event) => setRewindAt(event.target.value)} /></LabField>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void rewind()}>Tak aanmaken</Button>
              </div>
            </div>
          ) : (
            <LabEmpty title="Geen run geselecteerd" hint="Kies een run uit de lijst of start een nieuwe simulatie." />
          )}
        </Panel>
      </div>

      <Panel title="Runs" actions={<Button size="sm" variant="outline" onClick={() => void refreshRuns()}>Ververs</Button>}>
        <LabTable
          rows={runs}
          keyOf={(row) => row.run_id}
          empty={<LabEmpty title="Nog geen runs" hint="Start hierboven een simulatie." />}
          columns={[
            { header: "Run", cell: (row) => <button type="button" className={`lab-link${row.run_id === runId ? " is-active" : ""}`} onClick={() => onSelectRun(row.run_id)}>{text(row.label, row.run_id)}</button> },
            { header: "Split", cell: (row) => <small>{text(row.split)}</small> },
            { header: "Status", cell: (row) => <LabStatus value={row.status} /> },
            { header: "Voortgang", align: "right", cell: (row) => `${num(row.progress, 0)}%` },
            { header: "Tak van", cell: (row) => <small>{text(row.branch_of_run_id, "—")}</small> },
            { header: "Rendement", align: "right", cell: (row) => pct(pick(row.result, "metrics.total_return")) },
          ]}
        />
      </Panel>

      {run ? (
        <>
          <Panel title="Equity en benchmark">
            <EquityCurve points={equity} benchmark={benchmark} />
            <div className="lab-inline-facts">
              <span>Totaalrendement: {pct(metrics.total_return)}</span>
              <span>Sharpe: {num(metrics.sharpe)}</span>
              <span>Max drawdown: {pct(metrics.max_drawdown)}</span>
              <span>Trades: {num(metrics.trades, 0)}</span>
              <span>Kosten betaald: {num(metrics.fees_paid)}</span>
            </div>
            {run.error ? <LabNotice tone="danger">{run.error}</LabNotice> : null}
          </Panel>

          <div className="lab-grid-2">
            <Panel title="Besluitlog">
              <LabTable
                rows={decisions}
                keyOf={(row, index) => String(row.decision_id ?? index)}
                empty={<LabEmpty title="Geen besluiten" hint="Elke actie of bewuste niet-actie wordt hier vastgelegd." />}
                columns={[
                  { header: "Tijd", cell: (row) => <small>{shortTime(row.event_time)}</small> },
                  { header: "Instrument", cell: (row) => <small>{text(row.instrument_id)}</small> },
                  { header: "Signaal", cell: (row) => <small>{text(row.signal)}{row.in_scope === false ? " · buiten scope" : ""}</small> },
                  { header: "Actie", cell: (row) => text(row.action) },
                  { header: "Reden", cell: (row) => <small>{text(row.action_reason)}</small> },
                  { header: "Kosten", cell: (row) => <small>{text(row.cost_assessment)}</small> },
                ]}
              />
            </Panel>
            <Panel title="Reproduceerbaarheid">
              <LabKeyValues
                rows={[
                  ["Basiscommit", <span key="c" className="lab-mono">{text(pick(detail, "reproducibility.base_commit"))}</span>],
                  ["Engine", text(pick(detail, "reproducibility.engine_version"))],
                  ["Strategiehash", <span key="s" className="lab-mono">{text(pick(detail, "reproducibility.strategy_hash"))}</span>],
                  ["Datasethash", <span key="d" className="lab-mono">{text(pick(detail, "reproducibility.dataset_hash"))}</span>],
                  ["Seeds", text(JSON.stringify(pick(detail, "reproducibility.seeds") ?? {}))],
                  ["Split", text(pick(detail, "reproducibility.split"))],
                ]}
              />
              <LabJson value={pick(detail, "reproducibility")} label="Volledig reproductierecord" />
              <div className="lab-form-row">
                <LabField label="Vergelijk met run">
                  <select className="lab-select" value={compareWith} onChange={(event) => setCompareWith(event.target.value)}>
                    <option value="">— kies —</option>
                    {runs.filter((item) => item.run_id !== runId).map((item) => <option key={item.run_id} value={item.run_id}>{text(item.label, item.run_id)}</option>)}
                  </select>
                </LabField>
                <Button size="sm" variant="outline" disabled={busy || !compareWith} onClick={() => void compare()}>Vergelijk</Button>
              </div>
              {comparison ? <LabJson value={pick(comparison, "comparison")} label="Verschilrapport" /> : null}
            </Panel>
          </div>

          <Panel title={`Checkpoints (${snapshots.length})`}>
            <LabTable
              rows={snapshots.slice(-40).reverse()}
              keyOf={(row, index) => String(row.event_time ?? index)}
              empty={<LabEmpty title="Nog geen checkpoints" hint="De engine legt periodiek een herstelpunt vast tijdens de run." />}
              columns={[
                { header: "Simulatietijd", cell: (row) => <small className="lab-mono">{text(row.event_time)}</small> },
                { header: "Equity", align: "right", cell: (row) => num(row.equity) },
                { header: "Posities", align: "right", cell: (row) => num((pick(row, "snapshot.positions") as unknown[] | undefined)?.length ?? 0, 0) },
                { header: "Enginecheckpoint", cell: (row) => <small>{row.has_engine_checkpoint ? "ja" : "nee"}</small> },
                {
                  header: "",
                  align: "right",
                  cell: (row) => (
                    <Button size="sm" variant="outline" disabled={busy || !row.has_engine_checkpoint} onClick={() => setRewindAt(String(row.event_time))}>
                      Kies voor terugspoelen
                    </Button>
                  ),
                },
              ]}
            />
            <small className="lab-hint">
              Terugspoelen verplaatst de klok niet terug: het maakt vanaf dit herstelpunt een nieuwe runtak
              die tot het oorspronkelijke einde doorloopt. De oorspronkelijke run blijft als bewijs intact.
              Alleen rijen met een enginecheckpoint kunnen als takpunt dienen.
            </small>
          </Panel>
        </>
      ) : null}
    </div>
  );
}
