import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabInstrument, type LabRun } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabKeyValues, LabNotice, LabStatus, LabTable, num, pick, runAction, shortTime, text } from "./shared";

export function PortfolioRiskTab({ runId, onSelectRun }: { runId: string; onSelectRun: (id: string) => void }) {
  const [runs, setRuns] = useState<LabRun[]>([]);
  const [instruments, setInstruments] = useState<LabInstrument[]>([]);
  const [portfolio, setPortfolio] = useState<Record<string, unknown> | null>(null);
  const [ledger, setLedger] = useState<Record<string, unknown> | null>(null);
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ instrument_id: "", side: "buy", quantity: "1", order_type: "market", equity: "100000", limit_price: "", reduce_only: false });

  const refresh = useCallback(async () => {
    try {
      const [runList, instrumentList, settingsPayload] = await Promise.all([
        hadesApi.labRuns({ limit: 50 }),
        hadesApi.labInstruments(),
        hadesApi.labSettings(),
      ]);
      setRuns(runList.runs || []);
      setInstruments(instrumentList.instruments || []);
      setSettings(settingsPayload);
      setForm((current) => (current.instrument_id ? current : { ...current, instrument_id: instrumentList.instruments?.[0]?.instrument_id || "" }));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Portefeuille laden mislukt.");
    }
  }, []);

  const loadPortfolio = useCallback(async (id: string) => {
    try {
      setPortfolio(await hadesApi.labPortfolio(id || undefined));
      setLedger(id ? await hadesApi.labRunLedger(id, 200) : null);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Portefeuillestatus laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void loadPortfolio(runId);
  }, [runId, loadPortfolio]);

  const runRiskPreview = async () => {
    if (!form.instrument_id) {
      toast.error("Kies een instrument.");
      return;
    }
    const result = await runAction(
      () => hadesApi.labRiskPreview({
        instrument_id: form.instrument_id,
        side: form.side,
        quantity: form.quantity,
        order_type: form.order_type,
        limit_price: form.limit_price || undefined,
        reduce_only: form.reduce_only,
        equity: form.equity,
      }),
      { busy: setBusy, failure: "Risicotoets mislukt." },
    );
    if (result) setPreview(result);
  };

  const positions = Array.isArray(pick(portfolio, "snapshot.snapshot.positions")) ? (pick(portfolio, "snapshot.snapshot.positions") as Array<Record<string, unknown>>) : [];
  const cashByCurrency = Object.entries((pick(portfolio, "snapshot.snapshot.cash") || {}) as Record<string, unknown>);
  const ledgerTotals = Object.entries((ledger?.totals || {}) as Record<string, Record<string, string>>).flatMap(([account, balances]) =>
    Object.entries(balances || {}).map(([currency, amount]) => ({ account, currency, amount })),
  );
  const accounts = Array.isArray(portfolio?.accounts) ? (portfolio!.accounts as Array<Record<string, unknown>>) : [];
  const entries = Array.isArray(ledger?.entries) ? (ledger!.entries as Array<Record<string, unknown>>) : [];
  const stripped = Array.isArray(preview?.stripped_override_keys) ? (preview!.stripped_override_keys as string[]) : [];
  const limits = (settings?.risk_limits || {}) as Record<string, unknown>;

  return (
    <div className="lab-stack">
      <div className="lab-grid-2">
        <Panel title="Portefeuille" actions={
          <select className="lab-select" value={runId} onChange={(event) => onSelectRun(event.target.value)}>
            <option value="">Papieraccounts</option>
            {runs.map((row) => <option key={row.run_id} value={row.run_id}>{text(row.label, row.run_id)}</option>)}
          </select>
        }>
          {runId ? (
            <>
              <LabKeyValues
                rows={[
                  ["Simulatietijd", shortTime(pick(portfolio, "snapshot.event_time"))],
                  ["Eigen vermogen", num(pick(portfolio, "snapshot.equity"))],
                  ["Cash", cashByCurrency.map(([currency, amount]) => `${num(amount)} ${currency}`).join(" · ") || "—"],
                  ["Ongerealiseerde PnL", num(pick(portfolio, "snapshot.snapshot.unrealized_pnl"))],
                  ["Gerealiseerde PnL", num(pick(portfolio, "snapshot.snapshot.realized_pnl"))],
                  ["Kosten betaald", num(pick(portfolio, "snapshot.snapshot.fees_paid"))],
                  ["Bruto exposure", num(pick(portfolio, "snapshot.snapshot.gross_exposure"))],
                  ["Netto exposure", num(pick(portfolio, "snapshot.snapshot.net_exposure"))],
                  ["Marge in gebruik", num(pick(portfolio, "snapshot.snapshot.margin_used"))],
                ]}
              />
              <LabTable
                rows={positions}
                keyOf={(row, index) => String(row.instrument_id ?? index)}
                empty={<LabEmpty title="Geen open posities" hint="De laatste snapshot bevat geen posities." />}
                columns={[
                  { header: "Instrument", cell: (row) => <small>{text(row.instrument_id)}</small> },
                  { header: "Hoeveelheid", align: "right", cell: (row) => num(row.quantity, 6) },
                  { header: "Kant", cell: (row) => <small>{text(row.side)}</small> },
                  { header: "Gem. prijs", align: "right", cell: (row) => num(row.average_price, 4) },
                  { header: "Mark", align: "right", cell: (row) => num(row.mark_price, 4) },
                  { header: "Ongerealiseerd", align: "right", cell: (row) => num(row.unrealized_pnl) },
                ]}
              />
            </>
          ) : (
            <LabTable
              rows={accounts}
              keyOf={(row, index) => String(row.account_id ?? index)}
              empty={<LabEmpty title="Geen papieraccounts" hint="Papieraccounts ontstaan bij een paper-run." />}
              columns={[
                { header: "Account", cell: (row) => <small>{text(row.name ?? row.account_id)}</small> },
                { header: "Valuta", cell: (row) => <small>{text(row.base_currency)}</small> },
                { header: "Eigen vermogen", align: "right", cell: (row) => num(row.equity) },
              ]}
            />
          )}
          <small className="lab-hint">Modus: {text(pick(portfolio, "mode"), "SIMULATIE/PAPER")}</small>
        </Panel>

        <Panel title="Risicolimieten (deterministisch)">
          <LabKeyValues
            rows={[
              ["Max positienotional", num(limits.max_position_notional)],
              ["Max bruto exposure", num(limits.max_gross_exposure)],
              ["Max netto exposure", num(limits.max_net_exposure)],
              ["Max hefboom", num(limits.max_leverage)],
              ["Max ordernotional", num(limits.max_order_notional)],
              ["Max drawdownfractie", num(limits.max_drawdown_fraction)],
              ["Max volumeparticipatie", num(limits.max_participation)],
              ["Kill switch", <LabStatus key="k" value={limits.kill_switch_armed ? "running" : "completed"} />],
            ]}
          />
          <LabNotice tone="warning">
            De risicomotor is de enige plek die een order mag tegenhouden. Metadata uit een taalmodel die limieten probeert te
            verhogen wordt verwijderd en gelogd, niet gehonoreerd.
          </LabNotice>
          <LabJson value={limits} label="Alle limieten" />
        </Panel>
      </div>

      <div className="lab-grid-2">
        <Panel title="Risicotoets vooraf">
          <div className="lab-form">
            <LabField label="Instrument">
              <select className="lab-select" value={form.instrument_id} onChange={(event) => setForm({ ...form, instrument_id: event.target.value })}>
                <option value="">— kies —</option>
                {instruments.map((row) => <option key={row.instrument_id} value={row.instrument_id}>{row.instrument_id}</option>)}
              </select>
            </LabField>
            <div className="lab-form-row">
              <LabField label="Kant">
                <select className="lab-select" value={form.side} onChange={(event) => setForm({ ...form, side: event.target.value })}>
                  {["buy", "sell"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Hoeveelheid"><Input value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} /></LabField>
              <LabField label="Eigen vermogen"><Input value={form.equity} onChange={(event) => setForm({ ...form, equity: event.target.value })} /></LabField>
            </div>
            <Button disabled={busy} onClick={() => void runRiskPreview()}>Toets bij de risicomotor</Button>
            {preview ? (
              <>
                <LabKeyValues
                  rows={[
                    ["Beslissing", <LabStatus key="d" value={text(pick(preview, "decision.decision")) === "block" ? "failed" : "completed"} />],
                    ["Oordeel", text(pick(preview, "decision.decision"))],
                    ["Goedgekeurde omvang", num(pick(preview, "decision.approved_quantity"), 6)],
                    ["Laatste slotkoers", num(pick(preview, "latest_close.close"))],
                  ]}
                />
                <ul className="lab-bullets">
                  {(Array.isArray(pick(preview, "decision.reasons")) ? (pick(preview, "decision.reasons") as string[]) : []).map((item) => <li key={item}>{item}</li>)}
                </ul>
                {stripped.length > 0 ? (
                  <LabNotice tone="danger">Genegeerde overrideveldnamen uit modelinvoer: {stripped.join(", ")}</LabNotice>
                ) : null}
                <LabJson value={pick(preview, "decision.limit_snapshot")} label="Limietsnapshot" />
              </>
            ) : null}
          </div>
        </Panel>

        <Panel title="Grootboek">
          <LabTable
            rows={ledgerTotals}
            keyOf={(row) => `${row.account}-${row.currency}`}
            empty={<LabEmpty title="Geen saldi" hint="Het grootboek is leeg voor deze run." />}
            columns={[
              { header: "Rekening", cell: (row) => <small>{row.account}</small> },
              { header: "Valuta", cell: (row) => <small>{row.currency}</small> },
              { header: "Saldo", align: "right", cell: (row) => num(row.amount, 6) },
            ]}
          />
          <h3 className="lab-subhead">Laatste boekingen</h3>
          <LabTable
            rows={entries.slice(0, 40)}
            keyOf={(row, index) => String(row.entry_id ?? index)}
            empty={<LabEmpty title="Geen boekingen" hint="Kies een run met verwerkte orders." />}
            columns={[
              { header: "Tijd", cell: (row) => <small>{shortTime(row.event_time)}</small> },
              { header: "Soort", cell: (row) => <small>{text(row.kind)}</small> },
              { header: "Valuta", cell: (row) => <small>{text(row.currency)}</small> },
              { header: "Bedrag", align: "right", cell: (row) => num(row.amount, 6) },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
