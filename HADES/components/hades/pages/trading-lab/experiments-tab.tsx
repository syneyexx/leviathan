import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabDataset, type LabExperiment, type LabInstrument } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabKeyValues, LabNotice, LabStatus, LabTable, num, pct, pick, refusalOf, runAction, text } from "./shared";

const SEARCH_METHODS = ["single", "grid", "random", "sequential_refinement"];

export function ExperimentsTab() {
  const [experiments, setExperiments] = useState<LabExperiment[]>([]);
  const [instruments, setInstruments] = useState<LabInstrument[]>([]);
  const [datasets, setDatasets] = useState<LabDataset[]>([]);
  const [families, setFamilies] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    title: "",
    strategy_family: "trend_following",
    timeframe: "1h",
    split: "development",
    search_method: "grid",
    search_budget: "24",
    seed: "7",
    instruments: [] as string[],
    dataset_ids: [] as string[],
    objective: "",
    param_space: "",
  });

  const refresh = useCallback(async () => {
    try {
      const [experimentList, instrumentList, datasetList, familyList] = await Promise.all([
        hadesApi.labExperiments({ limit: 100 }),
        hadesApi.labInstruments(),
        hadesApi.labDatasets({ limit: 200 }),
        hadesApi.labStrategyFamilies(),
      ]);
      setExperiments(experimentList.experiments || []);
      setInstruments(instrumentList.instruments || []);
      setDatasets(datasetList.datasets || []);
      setFamilies((familyList.families || []).map((item) => String((item as Record<string, unknown>).family)));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Experimenten laden mislukt.");
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    setSelected(id);
    try {
      setDetail(await hadesApi.labExperiment(id));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Experimentdetail laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const running = experiments.some((item) => item.status === "running" || item.status === "queued");
    if (!running) return;
    const timer = window.setInterval(() => {
      void refresh();
      if (selected) void loadDetail(selected);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [experiments, refresh, selected, loadDetail]);

  const toggle = (key: "instruments" | "dataset_ids", value: string) => {
    setForm((current) => ({
      ...current,
      [key]: current[key].includes(value) ? current[key].filter((item) => item !== value) : [...current[key], value],
    }));
  };

  const create = async () => {
    if (!form.title.trim() || form.instruments.length === 0 || form.dataset_ids.length === 0) {
      toast.error("Geef een titel en kies minstens één instrument en één dataset.");
      return;
    }
    let paramSpace: Record<string, unknown> | undefined;
    if (form.param_space.trim()) {
      try {
        paramSpace = JSON.parse(form.param_space) as Record<string, unknown>;
      } catch {
        toast.error("Zoekruimte is geen geldige JSON.");
        return;
      }
    }
    const result = await runAction(
      () => hadesApi.createLabExperiment({
        title: form.title.trim(),
        strategy_family: form.strategy_family,
        instruments: form.instruments,
        dataset_ids: form.dataset_ids,
        timeframe: form.timeframe,
        split: form.split,
        search_method: form.search_method,
        search_budget: Number(form.search_budget) || 1,
        seed: Number(form.seed) || 7,
        objective: form.objective,
        ...(paramSpace ? { param_space: paramSpace } : {}),
      }),
      { busy: setBusy, failure: "Experiment aanmaken mislukt." },
    );
    if (!result) return;
    const refusal = refusalOf(result as unknown as Record<string, unknown>);
    if (refusal) {
      toast.message(`Geweigerd: ${refusal}`);
      return;
    }
    toast.success("Experiment preregistreerd. Alle trials worden vastgelegd, ook de mislukte.");
    await refresh();
    if (result.experiment_id) await loadDetail(result.experiment_id);
  };

  const start = async (experimentId: string) => {
    const result = await runAction(() => hadesApi.startLabExperiment(experimentId), { busy: setBusy, failure: "Starten mislukt." });
    const refusal = refusalOf(result);
    if (refusal) toast.message(refusal);
    else toast.success("Experiment in de wachtrij gezet.");
    await refresh();
    await loadDetail(experimentId);
  };

  const trials = Array.isArray(detail?.trials) ? (detail!.trials as Array<Record<string, unknown>>) : [];

  return (
    <div className="lab-stack">
      <LabNotice tone="warning">
        Zoeken is begrensd en preregistreerd: het aantal trials, de zoekruimte en de seed staan vast vóór de eerste run. Dat
        aantal telt later mee in de correctie voor meervoudig testen, zodat een toevalstreffer niet als vondst verschijnt.
      </LabNotice>

      <div className="lab-grid-2">
        <Panel title="Experiment preregistreren">
          <div className="lab-form">
            <LabField label="Titel"><Input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></LabField>
            <div className="lab-form-row">
              <LabField label="Strategiefamilie">
                <select className="lab-select" value={form.strategy_family} onChange={(event) => setForm({ ...form, strategy_family: event.target.value })}>
                  {families.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Resolutie"><Input value={form.timeframe} onChange={(event) => setForm({ ...form, timeframe: event.target.value })} /></LabField>
            </div>
            <div className="lab-form-row">
              <LabField label="Zoekmethode">
                <select className="lab-select" value={form.search_method} onChange={(event) => setForm({ ...form, search_method: event.target.value })}>
                  {SEARCH_METHODS.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Budget (trials)"><Input value={form.search_budget} onChange={(event) => setForm({ ...form, search_budget: event.target.value })} /></LabField>
              <LabField label="Seed"><Input value={form.seed} onChange={(event) => setForm({ ...form, seed: event.target.value })} /></LabField>
            </div>
            <LabField label="Split" hint="Zoeken gebeurt op ontwikkeling; validatie en sealed test blijven buiten bereik.">
              <select className="lab-select" value={form.split} onChange={(event) => setForm({ ...form, split: event.target.value })}>
                {["development", "validation"].map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </LabField>
            <LabField label="Instrumenten">
              <div className="lab-chip-row">
                {instruments.map((item) => (
                  <button key={item.instrument_id} type="button" className={`lab-chip${form.instruments.includes(item.instrument_id) ? " is-active" : ""}`} onClick={() => toggle("instruments", item.instrument_id)}>
                    {item.symbol}
                  </button>
                ))}
              </div>
            </LabField>
            <LabField label="Datasets">
              <div className="lab-chip-row">
                {datasets.map((item) => (
                  <button key={item.dataset_id} type="button" className={`lab-chip${form.dataset_ids.includes(item.dataset_id) ? " is-active" : ""}`} onClick={() => toggle("dataset_ids", item.dataset_id)}>
                    {item.instrument_id} {item.timeframe} v{item.revision}{item.is_synthetic ? " (syn)" : ""}
                  </button>
                ))}
              </div>
            </LabField>
            <LabField label="Zoekruimte (JSON, optioneel)" hint="Leeg laten gebruikt de standaardruimte van de familie.">
              <Textarea rows={4} value={form.param_space} onChange={(event) => setForm({ ...form, param_space: event.target.value })} placeholder={'{"fast": [10, 20], "slow": [50, 100]}'} />
            </LabField>
            <LabField label="Doel / vraag"><Input value={form.objective} onChange={(event) => setForm({ ...form, objective: event.target.value })} /></LabField>
            <Button disabled={busy} onClick={() => void create()}>Preregistreer</Button>
          </div>
        </Panel>

        <Panel title={`Experimenten (${experiments.length})`} actions={<Button size="sm" variant="outline" onClick={() => void refresh()}>Ververs</Button>}>
          <LabTable
            rows={experiments}
            keyOf={(row) => row.experiment_id}
            empty={<LabEmpty title="Nog geen experimenten" hint="Preregistreer er één links." />}
            columns={[
              { header: "Titel", cell: (row) => <button type="button" className={`lab-link${row.experiment_id === selected ? " is-active" : ""}`} onClick={() => void loadDetail(row.experiment_id)}>{row.title}</button> },
              { header: "Familie", cell: (row) => <small>{row.strategy_family}</small> },
              { header: "Zoek", cell: (row) => <small>{row.search_method} · {num(row.search_budget, 0)}</small> },
              { header: "Trials", align: "right", cell: (row) => `${num(row.trials_completed, 0)}/${num(row.search_budget, 0)}` },
              { header: "Status", cell: (row) => <LabStatus value={row.status} /> },
              { header: "", align: "right", cell: (row) => (row.status === "created" || row.status === "failed" ? <Button size="sm" variant="outline" disabled={busy} onClick={() => void start(row.experiment_id)}>Start</Button> : null) },
            ]}
          />
        </Panel>
      </div>

      {detail ? (
        <div className="lab-grid-2">
          <Panel title="Preregistratie">
            <LabKeyValues
              rows={[
                ["Status", <LabStatus key="s" value={text(pick(detail, "experiment.status"))} />],
                ["Mislukte trials", num(pick(detail, "experiment.trials_failed"), 0)],
                ["Seed", num(pick(detail, "experiment.seed"), 0)],
                ["Beste score", num(pick(detail, "experiment.result.best.score"))],
              ]}
            />
            <LabJson value={pick(detail, "experiment.preregistration")} label="Preregistratierecord" />
            <LabJson value={pick(detail, "experiment.result")} label="Uitkomst" />
          </Panel>
          <Panel title={`Trials (${trials.length})`}>
            <LabTable
              rows={trials}
              keyOf={(row, index) => String(row.trial_id ?? index)}
              empty={<LabEmpty title="Nog geen trials" hint="Start het experiment om de zoektocht uit te voeren." />}
              columns={[
                { header: "#", align: "right", cell: (row) => num(row.trial_index, 0) },
                { header: "Parameters", cell: (row) => <small className="lab-mono">{JSON.stringify(row.params ?? {})}</small> },
                { header: "Netto", align: "right", cell: (row) => pct(pick(row, "metrics.net_return")) },
                { header: "Sharpe", align: "right", cell: (row) => num(pick(row, "metrics.sharpe")) },
                { header: "Status", cell: (row) => <LabStatus value={String(row.status ?? "")} /> },
              ]}
            />
          </Panel>
        </div>
      ) : null}
    </div>
  );
}
