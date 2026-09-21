import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LmModel } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabNotice, LabStatus, LabTable, num, text } from "./shared";

const COST_FIELDS: Array<[string, string]> = [
  ["taker_fee_bps", "Taker fee (bps)"],
  ["maker_fee_bps", "Maker fee (bps)"],
  ["half_spread_bps", "Halve spread (bps)"],
  ["slippage_bps", "Slippage (bps)"],
  ["min_fee", "Minimumkosten"],
  ["latency_events", "Latency (events)"],
  ["max_volume_participation", "Max volumeparticipatie"],
  ["reject_probability", "Kans op afwijzing"],
  ["funding_multiplier", "Fundingmultiplier"],
];

const RISK_FIELDS: Array<[string, string]> = [
  ["max_position_notional", "Max positienotional"],
  ["max_gross_exposure", "Max bruto exposure"],
  ["max_net_exposure", "Max netto exposure"],
  ["max_leverage", "Max hefboom"],
  ["max_order_notional", "Max ordernotional"],
  ["max_daily_loss", "Max dagverlies"],
  ["max_drawdown_fraction", "Max drawdownfractie"],
  ["max_participation", "Max participatie"],
  ["max_open_orders", "Max open orders"],
  ["max_instrument_concentration", "Max concentratie per instrument"],
];

export function SettingsTab() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [models, setModels] = useState<LmModel[]>([]);
  const [jobs, setJobs] = useState<Record<string, unknown> | null>(null);
  const [cost, setCost] = useState<Record<string, string>>({});
  const [risk, setRisk] = useState<Record<string, string>>({});
  const [killSwitch, setKillSwitch] = useState(false);
  const [allowNetwork, setAllowNetwork] = useState(false);
  const [defaultModel, setDefaultModel] = useState("");
  const [autonomy, setAutonomy] = useState("off");
  const [maxWorkers, setMaxWorkers] = useState("2");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [settingsPayload, jobsPayload] = await Promise.all([hadesApi.labSettings(), hadesApi.labJobs()]);
      setSettings(settingsPayload);
      setJobs(jobsPayload as unknown as Record<string, unknown>);
      const costModel = (settingsPayload.cost_model || {}) as Record<string, unknown>;
      const riskLimits = (settingsPayload.risk_limits || {}) as Record<string, unknown>;
      setCost(Object.fromEntries(COST_FIELDS.map(([key]) => [key, String(costModel[key] ?? "")])));
      setRisk(Object.fromEntries(RISK_FIELDS.map(([key]) => [key, String(riskLimits[key] ?? "")])));
      setKillSwitch(Boolean(riskLimits.kill_switch_armed));
      setAllowNetwork(Boolean((settingsPayload.providers as Record<string, unknown> | undefined)?.allow_network));
      setDefaultModel(String((settingsPayload.agent_models as Record<string, unknown> | undefined)?.default ?? ""));
      setAutonomy(String((settingsPayload.learning as Record<string, unknown> | undefined)?.autonomy_level ?? "off"));
      setMaxWorkers(String((settingsPayload.resources as Record<string, unknown> | undefined)?.max_workers ?? 2));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Instellingen laden mislukt.");
    }
    try {
      const modelPayload = await hadesApi.models();
      setModels(modelPayload.models || []);
    } catch {
      setModels([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      const costModel = Object.fromEntries(Object.entries(cost).filter(([, value]) => value !== ""));
      const riskLimits = Object.fromEntries(Object.entries(risk).filter(([, value]) => value !== ""));
      const updated = await hadesApi.saveLabSettings({
        cost_model: { ...(settings?.cost_model as Record<string, unknown>), ...costModel },
        risk_limits: { ...(settings?.risk_limits as Record<string, unknown>), ...riskLimits, kill_switch_armed: killSwitch },
        providers: { ...(settings?.providers as Record<string, unknown>), allow_network: allowNetwork },
        resources: { ...(settings?.resources as Record<string, unknown>), max_workers: Number(maxWorkers) || 2 },
        agent_models: defaultModel ? { ...(settings?.agent_models as Record<string, unknown>), default: defaultModel } : (settings?.agent_models as Record<string, unknown>) || {},
        learning: { ...((settings?.learning as Record<string, unknown>) || {}), autonomy_level: autonomy },
      });
      setSettings(updated);
      toast.success("Instellingen opgeslagen en gevalideerd door de backend.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Opslaan mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const jobRows = Array.isArray(jobs?.jobs) ? (jobs!.jobs as Array<Record<string, unknown>>) : [];
  const queue = (jobs?.queue || {}) as Record<string, unknown>;

  return (
    <div className="lab-stack">
      <div className="lab-grid-2">
        <Panel title="Kostenmodel">
          <div className="lab-form">
            {COST_FIELDS.map(([key, label]) => (
              <LabField key={key} label={label}>
                <Input value={cost[key] ?? ""} onChange={(event) => setCost({ ...cost, [key]: event.target.value })} />
              </LabField>
            ))}
            <small className="lab-hint">
              Kosten worden uitsluitend door de uitvoeringslaag toegepast. Een strategie kan haar eigen kosten niet omzeilen.
            </small>
          </div>
        </Panel>

        <Panel title="Risicolimieten">
          <div className="lab-form">
            {RISK_FIELDS.map(([key, label]) => (
              <LabField key={key} label={label}>
                <Input value={risk[key] ?? ""} onChange={(event) => setRisk({ ...risk, [key]: event.target.value })} />
              </LabField>
            ))}
            <div className="lab-toggle-row">
              <span>Kill switch geactiveerd</span>
              <Switch checked={killSwitch} onCheckedChange={setKillSwitch} />
            </div>
            <small className="lab-hint">Met een actieve kill switch zijn alleen risicoverlagende orders nog toegestaan.</small>
          </div>
        </Panel>
      </div>

      <div className="lab-grid-2">
        <Panel title="Bronnen en netwerk">
          <div className="lab-form">
            <div className="lab-toggle-row">
              <span>Netwerktoegang voor publieke bronnen</span>
              <Switch checked={allowNetwork} onCheckedChange={setAllowNetwork} />
            </div>
            <LabNotice tone="info">
              Uit staat is de standaard. Met netwerk aan gebruikt het lab alleen gratis publieke eindpunten; ontbreekt een
              licentie of sleutel, dan meldt de bron dat en levert hij niets.
            </LabNotice>
            <LabField label="Maximum aantal workers" hint="Begrenst gelijktijdige backtests, experimenten en trainingen.">
              <Input value={maxWorkers} onChange={(event) => setMaxWorkers(event.target.value)} />
            </LabField>
          </div>
        </Panel>

        <Panel title="Modellen voor agentrollen">
          <div className="lab-form">
            <LabField label="Gedeeld model" hint="Wordt live uit LM Studio gelezen; er is geen vast model in de code.">
              <select className="lab-select" value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)}>
                <option value="">— geen model gekozen —</option>
                {models.map((model) => <option key={model.id} value={model.id}>{model.id}</option>)}
              </select>
            </LabField>
            {models.length === 0 ? <LabNotice tone="warning">Geen modellen gevonden. Start LM Studio en laad een model.</LabNotice> : null}
            <LabField label="Leerautonomie" hint="Standaard OFF. Nooit stilzwijgend omhoog. AUTO_RESEARCH consumeert nooit sealed holdout.">
              <select className="lab-select" value={autonomy} onChange={(event) => setAutonomy(event.target.value)}>
                <option value="off">OFF — handmatig</option>
                <option value="learn_only">LEARN_ONLY — experiences en beliefs</option>
                <option value="propose">PROPOSE — kandidaten, geen experimenten</option>
                <option value="research">RESEARCH — development-experimenten</option>
                <option value="auto_research">AUTO_RESEARCH — + validatie, geen sealed holdout</option>
              </select>
            </LabField>
            <Button disabled={busy} onClick={() => void save()}>Sla instellingen op</Button>
          </div>
        </Panel>
      </div>

      <Panel title="Werkwachtrij" actions={<Button size="sm" variant="outline" onClick={() => void load()}>Ververs</Button>}>
        <div className="lab-inline-facts">
          <span>Actief: {num(queue.running, 0)}</span>
          <span>Wachtend: {num(queue.queued, 0)}</span>
          <span>Workers: {num(queue.max_workers, 0)}</span>
        </div>
        <LabTable
          rows={jobRows}
          keyOf={(row, index) => String(row.job_id ?? index)}
          empty={<LabEmpty title="Geen taken" hint="Backtests, experimenten en trainingen verschijnen hier." />}
          columns={[
            { header: "Soort", cell: (row) => text(row.kind) },
            { header: "Referentie", cell: (row) => <small className="lab-mono">{text(row.ref_id)}</small> },
            { header: "Status", cell: (row) => <LabStatus value={String(row.status ?? "")} /> },
            { header: "Voortgang", align: "right", cell: (row) => `${num(row.progress, 0)}%` },
            { header: "Fout", cell: (row) => <small>{text(row.error, "")}</small> },
          ]}
        />
      </Panel>

      <Panel title="Actieve backendinstellingen">
        <LabJson value={settings} label="Volledige instellingen zoals de backend ze teruggeeft" />
      </Panel>
    </div>
  );
}
