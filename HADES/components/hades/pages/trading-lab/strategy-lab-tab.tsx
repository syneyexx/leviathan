import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabInstrument, type LabStrategy } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabKeyValues, LabNotice, LabStatus, LabTable, num, pick, refusalOf, runAction, shortTime, text } from "./shared";

type Family = { family: string; param_space?: Record<string, unknown>; required_data_level?: string; min_instruments?: number };

const HORIZONS = ["scalping", "intraday", "swing", "position"];
const DIRECTIONS = ["long_only", "short_only", "long_short"];
const ORDER_TYPES = ["market", "limit", "stop_market", "stop_limit", "trailing_stop", "take_profit", "bracket"];
const SIZING_MODES = ["equity_fraction", "fixed_notional", "fixed_quantity", "risk_per_trade"];

export function StrategyLabTab({ strategyId, onSelectStrategy }: { strategyId: string; onSelectStrategy: (id: string) => void }) {
  const [families, setFamilies] = useState<Family[]>([]);
  const [instruments, setInstruments] = useState<LabInstrument[]>([]);
  const [strategies, setStrategies] = useState<LabStrategy[]>([]);
  const [evidence, setEvidence] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [paramsText, setParamsText] = useState("{}");
  const [form, setForm] = useState({
    name: "",
    family: "trend_following",
    timeframe: "1h",
    instruments: [] as string[],
    order_type: "market",
    time_in_force: "GTC",
    sizing_mode: "equity_fraction",
    sizing_value: "0.1",
    scope_note: "",
    economic_rationale: "",
    horizon: "swing",
    direction: "long_only",
    plausible_regimes: "",
    implausible_regimes: "",
    falsification: "",
    no_trade_conditions: "",
    expected_costs: "",
  });
  const [promotion, setPromotion] = useState({ target_state: "validated", evaluation_report_id: "", justification: "", requested_by: "operator" });

  const refresh = useCallback(async () => {
    try {
      const [familyList, instrumentList, strategyList] = await Promise.all([
        hadesApi.labStrategyFamilies(),
        hadesApi.labInstruments(),
        hadesApi.labStrategies({ limit: 200 }),
      ]);
      setFamilies((familyList.families || []) as Family[]);
      setInstruments(instrumentList.instruments || []);
      setStrategies(strategyList.strategies || []);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Strategieën laden mislukt.");
    }
  }, []);

  const loadEvidence = useCallback(async (id: string) => {
    if (!id) {
      setEvidence(null);
      return;
    }
    try {
      setEvidence(await hadesApi.labStrategy(id));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Strategiedetail laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void loadEvidence(strategyId);
  }, [strategyId, loadEvidence]);

  const selectedFamily = useMemo(() => families.find((item) => item.family === form.family) || null, [families, form.family]);

  useEffect(() => {
    if (!selectedFamily?.param_space) return;
    const defaults: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(selectedFamily.param_space)) {
      defaults[key] = Array.isArray(value) ? value[Math.floor(value.length / 2)] : value;
    }
    setParamsText(JSON.stringify(defaults, null, 2));
  }, [selectedFamily]);

  const toggleInstrument = (instrumentId: string) => {
    setForm((current) => ({
      ...current,
      instruments: current.instruments.includes(instrumentId)
        ? current.instruments.filter((item) => item !== instrumentId)
        : [...current.instruments, instrumentId],
    }));
  };

  const buildPayload = (): Record<string, unknown> | null => {
    let params: Record<string, unknown>;
    try {
      params = JSON.parse(paramsText || "{}") as Record<string, unknown>;
    } catch {
      toast.error("Parameters zijn geen geldige JSON.");
      return null;
    }
    if (!form.name.trim() || form.instruments.length === 0) {
      toast.error("Geef een naam en kies minstens één instrument.");
      return null;
    }
    return {
      name: form.name.trim(),
      family: form.family,
      timeframe: form.timeframe,
      instruments: form.instruments,
      params,
      order_type: form.order_type,
      time_in_force: form.time_in_force,
      sizing: { mode: form.sizing_mode, value: form.sizing_value },
      scope_note: form.scope_note,
      hypothesis: {
        economic_rationale: form.economic_rationale,
        horizon: form.horizon,
        direction: form.direction,
        plausible_regimes: form.plausible_regimes,
        implausible_regimes: form.implausible_regimes,
        expected_costs: form.expected_costs,
        falsification_criteria: form.falsification.split("\n").map((item) => item.trim()).filter(Boolean),
        no_trade_conditions: form.no_trade_conditions.split("\n").map((item) => item.trim()).filter(Boolean),
      },
    };
  };

  const create = async () => {
    const payload = buildPayload();
    if (!payload) return;
    const result = await runAction(() => hadesApi.createLabStrategy(payload), { busy: setBusy, failure: "Strategie registreren mislukt." });
    if (!result) return;
    const refusal = refusalOf(result as unknown as Record<string, unknown>);
    if (refusal) {
      toast.message(`Geweigerd: ${refusal}`);
      return;
    }
    toast.success("Strategie geregistreerd als draft.");
    if (result.strategy?.strategy_id) onSelectStrategy(result.strategy.strategy_id);
    await refresh();
  };

  const addVersion = async () => {
    if (!strategyId) return;
    const payload = buildPayload();
    if (!payload) return;
    const result = await runAction(() => hadesApi.addLabStrategyVersion(strategyId, payload), {
      busy: setBusy,
      failure: "Nieuwe versie opslaan mislukt.",
    });
    if (!result) return;
    const refusal = refusalOf(result as unknown as Record<string, unknown>);
    if (refusal) {
      toast.message(`Geweigerd: ${refusal}`);
      return;
    }
    toast.success(`Versie ${result.version ?? "?"} opgeslagen; bewijs van de vorige versie vervalt.`);
    await refresh();
    await loadEvidence(strategyId);
  };

  const promote = async () => {
    if (!strategyId) return;
    const strategy = strategies.find((item) => item.strategy_id === strategyId);
    const result = await runAction(
      () => hadesApi.promoteLabStrategy({
        strategy_id: strategyId,
        version: strategy?.current_version || 1,
        target_state: promotion.target_state,
        requested_by: promotion.requested_by,
        evaluation_report_id: promotion.evaluation_report_id || null,
        justification: promotion.justification,
      }),
      { busy: setBusy, failure: "Promotie mislukt." },
    );
    if (!result) return;
    const refusal = refusalOf(result as unknown as Record<string, unknown>);
    if (refusal) {
      toast.message(`Promotie geweigerd: ${refusal}`);
    } else {
      toast.success(`Strategie verplaatst naar ${promotion.target_state}.`);
    }
    await refresh();
    await loadEvidence(strategyId);
  };

  return (
    <div className="lab-stack">
      <LabNotice tone="info">
        Een strategie bestaat pas als er een economische hypothese, een verwacht kostenbeeld en minstens één
        falsificatiecriterium ligt. Zonder dat is een backtestresultaat niet te interpreteren.
      </LabNotice>

      <div className="lab-grid-2">
        <Panel title="Strategie registreren">
          <div className="lab-form">
            <LabField label="Naam"><Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></LabField>
            <div className="lab-form-row">
              <LabField label="Familie">
                <select className="lab-select" value={form.family} onChange={(event) => setForm({ ...form, family: event.target.value })}>
                  {families.map((item) => <option key={item.family} value={item.family}>{item.family}</option>)}
                </select>
              </LabField>
              <LabField label="Resolutie"><Input value={form.timeframe} onChange={(event) => setForm({ ...form, timeframe: event.target.value })} /></LabField>
            </div>
            {selectedFamily ? (
              <small className="lab-hint">
                Vereist dataniveau: {text(selectedFamily.required_data_level)} · minimaal {num(selectedFamily.min_instruments, 0)} instrument(en)
              </small>
            ) : null}
            <LabField label="Instrumenten">
              <div className="lab-chip-row">
                {instruments.length === 0 ? <small>Nog geen instrumenten geregistreerd.</small> : null}
                {instruments.map((item) => (
                  <button
                    key={item.instrument_id}
                    type="button"
                    className={`lab-chip${form.instruments.includes(item.instrument_id) ? " is-active" : ""}`}
                    onClick={() => toggleInstrument(item.instrument_id)}
                  >
                    {item.symbol}
                  </button>
                ))}
              </div>
            </LabField>
            <LabField label="Parameters (JSON)" hint="Voorgevuld met het midden van de zoekruimte van deze familie.">
              <Textarea rows={5} value={paramsText} onChange={(event) => setParamsText(event.target.value)} />
            </LabField>
            <div className="lab-form-row">
              <LabField label="Ordertype">
                <select className="lab-select" value={form.order_type} onChange={(event) => setForm({ ...form, order_type: event.target.value })}>
                  {ORDER_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Sizing">
                <select className="lab-select" value={form.sizing_mode} onChange={(event) => setForm({ ...form, sizing_mode: event.target.value })}>
                  {SIZING_MODES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Waarde"><Input value={form.sizing_value} onChange={(event) => setForm({ ...form, sizing_value: event.target.value })} /></LabField>
            </div>
          </div>
        </Panel>

        <Panel title="Hypothese en falsificatie">
          <div className="lab-form">
            <LabField label="Economische onderbouwing" hint="Minimaal 20 tekens: waarom zou deze inefficiëntie bestaan?">
              <Textarea rows={4} value={form.economic_rationale} onChange={(event) => setForm({ ...form, economic_rationale: event.target.value })} />
            </LabField>
            <div className="lab-form-row">
              <LabField label="Horizon">
                <select className="lab-select" value={form.horizon} onChange={(event) => setForm({ ...form, horizon: event.target.value })}>
                  {HORIZONS.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Richting">
                <select className="lab-select" value={form.direction} onChange={(event) => setForm({ ...form, direction: event.target.value })}>
                  {DIRECTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
            </div>
            <div className="lab-form-row">
              <LabField label="Plausibele regimes"><Input value={form.plausible_regimes} onChange={(event) => setForm({ ...form, plausible_regimes: event.target.value })} /></LabField>
              <LabField label="Implausibele regimes"><Input value={form.implausible_regimes} onChange={(event) => setForm({ ...form, implausible_regimes: event.target.value })} /></LabField>
            </div>
            <LabField label="Verwachte kosten"><Input value={form.expected_costs} onChange={(event) => setForm({ ...form, expected_costs: event.target.value })} /></LabField>
            <LabField label="Falsificatiecriteria" hint="Eén per regel. Wanneer verklaar je de strategie mislukt?">
              <Textarea rows={3} value={form.falsification} onChange={(event) => setForm({ ...form, falsification: event.target.value })} />
            </LabField>
            <LabField label="Niet-handelen-condities" hint="Eén per regel.">
              <Textarea rows={2} value={form.no_trade_conditions} onChange={(event) => setForm({ ...form, no_trade_conditions: event.target.value })} />
            </LabField>
            <div className="lab-button-row">
              <Button disabled={busy} onClick={() => void create()}>Registreer strategie</Button>
              <Button variant="outline" disabled={busy || !strategyId} onClick={() => void addVersion()}>
                Opslaan als nieuwe versie
              </Button>
            </div>
            <small className="lab-hint">
              Een nieuwe versie van de geselecteerde strategie zet de status terug naar draft: bewijs van de vorige
              versie geldt niet voor een gewijzigde definitie.
            </small>
          </div>
        </Panel>
      </div>

      <Panel title={`Strategieën (${strategies.length})`} actions={<Button size="sm" variant="outline" onClick={() => void refresh()}>Ververs</Button>}>
        <LabTable
          rows={strategies}
          keyOf={(row) => row.strategy_id}
          empty={<LabEmpty title="Nog geen strategieën" hint="Registreer er één hierboven." />}
          columns={[
            { header: "Naam", cell: (row) => <button type="button" className={`lab-link${row.strategy_id === strategyId ? " is-active" : ""}`} onClick={() => onSelectStrategy(row.strategy_id)}>{row.name}</button> },
            { header: "Familie", cell: (row) => <small>{row.family}</small> },
            { header: "Versie", align: "right", cell: (row) => `v${row.current_version}` },
            { header: "Status", cell: (row) => <LabStatus value={row.status} /> },
            { header: "Bijgewerkt", cell: (row) => <small>{shortTime(row.updated_at)}</small> },
          ]}
        />
      </Panel>

      {evidence ? (
        <div className="lab-grid-2">
          <Panel title="Bewijsdossier">
            <LabKeyValues
              rows={[
                ["Status", <LabStatus key="s" value={text(pick(evidence, "strategy.status"))} />],
                ["Sterkste bewijs", text(pick(evidence, "strongest_evidence"))],
                ["Aanwezige bewijsklassen", (Array.isArray(evidence.evidence_classes_present) ? evidence.evidence_classes_present : []).join(", ") || "—"],
                ["Volgende stap", text(pick(evidence, "next_step"))],
                ["Sealed test gebruikt", Array.isArray(evidence.holdout_usage) ? String(evidence.holdout_usage.length) : "0"],
              ]}
            />
            <LabJson value={pick(evidence, "strategy.hypothesis")} label="Hypothese" />
            <LabTable
              rows={Array.isArray(evidence.evaluations) ? (evidence.evaluations as Array<Record<string, unknown>>) : []}
              keyOf={(row, index) => String(row.report_id ?? index)}
              empty={<LabEmpty title="Nog geen evaluaties" hint="Zonder onafhankelijke evaluatie is promotie uitgesloten." />}
              columns={[
                { header: "Rapport", cell: (row) => <span className="lab-mono">{String(row.report_id).slice(0, 12)}</span> },
                { header: "Split", cell: (row) => <small>{text(row.protocol)}</small> },
                { header: "Oordeel", cell: (row) => <LabStatus value={String(row.verdict)} /> },
                { header: "Deflated Sharpe", align: "right", cell: (row) => num(row.deflated_sharpe) },
              ]}
            />
          </Panel>

          <Panel title="Promotie aanvragen">
            <div className="lab-form">
              <LabField label="Doelstatus">
                <select className="lab-select" value={promotion.target_state} onChange={(event) => setPromotion({ ...promotion, target_state: event.target.value })}>
                  {["researched", "validated", "paper", "retired"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Evaluatierapport-id" hint="Verplicht voor 'validated'; moet van een onafhankelijke validator komen.">
                <Input value={promotion.evaluation_report_id} onChange={(event) => setPromotion({ ...promotion, evaluation_report_id: event.target.value })} />
              </LabField>
              <LabField label="Aanvrager"><Input value={promotion.requested_by} onChange={(event) => setPromotion({ ...promotion, requested_by: event.target.value })} /></LabField>
              <LabField label="Onderbouwing"><Textarea rows={3} value={promotion.justification} onChange={(event) => setPromotion({ ...promotion, justification: event.target.value })} /></LabField>
              <Button disabled={busy || !strategyId} onClick={() => void promote()}>Vraag promotie aan</Button>
              <small className="lab-hint">
                De registry weigert promotie zonder passend rapport, bij een andere versie, bij een ander oordeel dan pass, of
                wanneer de evaluator dezelfde actor is als de auteur.
              </small>
            </div>
          </Panel>
        </div>
      ) : null}
    </div>
  );
}
