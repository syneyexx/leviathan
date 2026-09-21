import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabEvaluation, type LabStrategy } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabKeyValues, LabNotice, LabStatus, LabTable, num, pct, pick, refusalOf, runAction, shortTime, text } from "./shared";

export function ValidationTab({ strategyId }: { strategyId: string }) {
  const [strategies, setStrategies] = useState<LabStrategy[]>([]);
  const [evaluations, setEvaluations] = useState<LabEvaluation[]>([]);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ strategy_id: strategyId, split: "validation", folds: "4", scheme: "expanding", evaluated_by: "independent_validator", seed: "7" });

  const refresh = useCallback(async () => {
    try {
      const [strategyList, evaluationList] = await Promise.all([hadesApi.labStrategies({ limit: 200 }), hadesApi.labEvaluations({ limit: 100 })]);
      setStrategies(strategyList.strategies || []);
      setEvaluations(evaluationList.evaluations || []);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Evaluaties laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (strategyId) setForm((current) => ({ ...current, strategy_id: strategyId }));
  }, [strategyId]);

  const startEvaluation = async () => {
    if (!form.strategy_id) {
      toast.error("Kies een strategie.");
      return;
    }
    const result = await runAction(
      () => hadesApi.startLabEvaluation({
        strategy_id: form.strategy_id,
        split: form.split,
        folds: Number(form.folds) || 4,
        scheme: form.scheme,
        evaluated_by: form.evaluated_by,
        seed: Number(form.seed) || 7,
      }),
      { busy: setBusy, failure: "Evaluatie starten mislukt." },
    );
    if (!result) return;
    const refusal = refusalOf(result as unknown as Record<string, unknown>);
    if (refusal) {
      toast.message(`Geweigerd: ${refusal}`);
      return;
    }
    toast.success("Onafhankelijke evaluatie in de wachtrij gezet.");
    window.setTimeout(() => void refresh(), 1500);
  };

  const open = async (reportId: string) => {
    try {
      setReport(await hadesApi.labEvaluation(reportId));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Rapport laden mislukt.");
    }
  };

  const folds = Array.isArray(pick(report, "report.folds")) ? (pick(report, "report.folds") as Array<Record<string, unknown>>) : [];
  const stress = Array.isArray(pick(report, "report.stress")) ? (pick(report, "report.stress") as Array<Record<string, unknown>>) : [];
  const reasons = Array.isArray(pick(report, "report.verdict_reasons")) ? (pick(report, "report.verdict_reasons") as string[]) : [];

  return (
    <div className="lab-stack">
      <LabNotice tone="info">
        Evaluatie is gescheiden van onderzoek. De validator draait walk-forward op ongebruikte perioden, corrigeert voor het
        aantal geprobeerde varianten en geeft onzekerheidsintervallen. Een sealed test is per strategieversie eenmalig.
      </LabNotice>

      <div className="lab-grid-2">
        <Panel title="Evaluatie starten">
          <div className="lab-form">
            <LabField label="Strategie">
              <select className="lab-select" value={form.strategy_id} onChange={(event) => setForm({ ...form, strategy_id: event.target.value })}>
                <option value="">— kies —</option>
                {strategies.map((row) => <option key={row.strategy_id} value={row.strategy_id}>{row.name} (v{row.current_version}, {row.status})</option>)}
              </select>
            </LabField>
            <div className="lab-form-row">
              <LabField label="Split">
                <select className="lab-select" value={form.split} onChange={(event) => setForm({ ...form, split: event.target.value })}>
                  {["validation", "sealed_test"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Folds"><Input value={form.folds} onChange={(event) => setForm({ ...form, folds: event.target.value })} /></LabField>
              <LabField label="Schema">
                <select className="lab-select" value={form.scheme} onChange={(event) => setForm({ ...form, scheme: event.target.value })}>
                  {["expanding", "rolling"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
            </div>
            <LabField label="Evaluator" hint="Mag niet dezelfde actor zijn als de auteur van de strategie.">
              <Input value={form.evaluated_by} onChange={(event) => setForm({ ...form, evaluated_by: event.target.value })} />
            </LabField>
            <Button disabled={busy} onClick={() => void startEvaluation()}>Start onafhankelijke evaluatie</Button>
            {form.split === "sealed_test" ? (
              <LabNotice tone="warning">De sealed test wordt hierdoor verbruikt voor deze versie en is daarna niet meer beschikbaar.</LabNotice>
            ) : null}
          </div>
        </Panel>

        <Panel title={`Rapporten (${evaluations.length})`} actions={<Button size="sm" variant="outline" onClick={() => void refresh()}>Ververs</Button>}>
          <LabTable
            rows={evaluations}
            keyOf={(row) => row.report_id}
            empty={<LabEmpty title="Nog geen rapporten" hint="Zonder rapport blijft een strategie draft." />}
            columns={[
              { header: "Rapport", cell: (row) => <button type="button" className="lab-link" onClick={() => void open(row.report_id)}>{row.report_id.slice(0, 14)}</button> },
              { header: "Strategie", cell: (row) => <small>{row.strategy_id} v{row.strategy_version}</small> },
              { header: "Oordeel", cell: (row) => <LabStatus value={row.verdict} /> },
              { header: "Bewijsklasse", cell: (row) => <small>{row.evidence_class}</small> },
              { header: "Trials", align: "right", cell: (row) => num(row.search_trials_considered, 0) },
              { header: "Deflated Sharpe", align: "right", cell: (row) => num(row.deflated_sharpe) },
            ]}
          />
        </Panel>
      </div>

      {report ? (
        <>
          <Panel title="Rapportdetail" actions={<LabStatus value={text(pick(report, "verdict"))} />}>
            <LabKeyValues
              rows={[
                ["Protocol", text(pick(report, "report.protocol"))],
                ["Benchmark", text(pick(report, "report.benchmark"))],
                ["Splits gebruikt", (Array.isArray(report.splits_used) ? report.splits_used : []).join(", ") || "—"],
                ["Netto rendement", pct(pick(report, "report.aggregate.net_return"))],
                ["Kosten betaald", num(pick(report, "report.aggregate.costs_paid"))],
                ["Sharpe", num(pick(report, "report.aggregate.sharpe"))],
                ["Max drawdown", pct(pick(report, "report.aggregate.max_drawdown"))],
                ["Benchmark netto", pct(pick(report, "report.aggregate.benchmark_net_return"))],
                ["Correctie meervoudig testen", text(pick(report, "report.multiple_testing_note"))],
                ["Datakwaliteit", text(pick(report, "report.data_quality_note"))],
              ]}
            />
            {reasons.length > 0 ? (
              <>
                <h3 className="lab-subhead">Onderbouwing van het oordeel</h3>
                <ul className="lab-bullets">{reasons.map((item) => <li key={item}>{item}</li>)}</ul>
              </>
            ) : null}
          </Panel>

          <div className="lab-grid-2">
            <Panel title="Walk-forward folds">
              <LabTable
                rows={folds}
                keyOf={(row, index) => String(row.label ?? index)}
                empty={<LabEmpty title="Geen folds" hint="Het rapport bevat geen deelperioden." />}
                columns={[
                  { header: "Fold", cell: (row) => text(row.label) },
                  { header: "Periode", cell: (row) => <small>{shortTime(row.first_event_time)} → {shortTime(row.last_event_time)}</small> },
                  { header: "Netto", align: "right", cell: (row) => pct(row.net_return) },
                  { header: "Sharpe", align: "right", cell: (row) => num(row.sharpe) },
                  { header: "Trades", align: "right", cell: (row) => num(row.trades, 0) },
                ]}
              />
            </Panel>
            <Panel title="Stress en onzekerheid">
              <LabTable
                rows={stress}
                keyOf={(row, index) => String(row.scenario ?? index)}
                empty={<LabEmpty title="Geen stressscenario's" hint="Stress staat uit voor dit rapport." />}
                columns={[
                  { header: "Scenario", cell: (row) => text(row.scenario) },
                  { header: "Netto", align: "right", cell: (row) => pct(row.net_return) },
                  { header: "Max drawdown", align: "right", cell: (row) => pct(row.max_drawdown) },
                  { header: "Geweigerde orders", align: "right", cell: (row) => num(row.rejected_orders, 0) },
                  { header: "Toelichting", cell: (row) => <small>{text(row.note ?? row.description)}</small> },
                ]}
              />
              <LabJson value={pick(report, "report.confidence_intervals")} label="Betrouwbaarheidsintervallen" />
              <LabJson value={pick(report, "report.parameter_sensitivity")} label="Parametergevoeligheid" />
              <LabJson value={pick(report, "report.simulator_limitations")} label="Grenzen van de simulator" />
            </Panel>
          </div>
        </>
      ) : null}
    </div>
  );
}
