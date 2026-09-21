import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabInstrument, type LabRun } from "@/lib/hades-api";
import { LabEmpty, LabField, LabNotice, LabStatus, LabTable, num, shortTime, text, runAction } from "./shared";

const ORDER_TYPES = ["market", "limit", "stop_market", "stop_limit", "trailing_stop", "take_profit", "bracket"];
const TIME_IN_FORCE = ["GTC", "DAY", "IOC", "FOK", "GTD"];

type CapabilityMatrix = {
  instruments?: Array<Record<string, unknown>>;
  order_types?: Array<Record<string, unknown>>;
  time_in_force?: Record<string, unknown>;
  execution_mode?: string;
};

export function OrdersTab({ runId, onSelectRun }: { runId: string; onSelectRun: (id: string) => void }) {
  const [runs, setRuns] = useState<LabRun[]>([]);
  const [instruments, setInstruments] = useState<LabInstrument[]>([]);
  const [orders, setOrders] = useState<Array<Record<string, unknown>>>([]);
  const [fills, setFills] = useState<Array<Record<string, unknown>>>([]);
  const [matrix, setMatrix] = useState<CapabilityMatrix | null>(null);
  const [check, setCheck] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [ticket, setTicket] = useState({
    instrument_id: "",
    side: "buy",
    order_type: "limit",
    quantity: "1",
    limit_price: "100",
    stop_price: "",
    time_in_force: "GTC",
    reduce_only: false,
    post_only: false,
  });

  const refresh = useCallback(async () => {
    try {
      const [runList, instrumentList, capabilities] = await Promise.all([
        hadesApi.labRuns({ limit: 50 }),
        hadesApi.labInstruments(),
        hadesApi.labCapabilities(),
      ]);
      setRuns(runList.runs || []);
      setInstruments(instrumentList.instruments || []);
      setMatrix(capabilities as CapabilityMatrix);
      setTicket((current) => (current.instrument_id ? current : { ...current, instrument_id: instrumentList.instruments?.[0]?.instrument_id || "" }));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Uitvoeringsgegevens laden mislukt.");
    }
  }, []);

  const loadRun = useCallback(async (id: string) => {
    if (!id) {
      setOrders([]);
      setFills([]);
      return;
    }
    try {
      const [orderPayload, fillPayload] = await Promise.all([hadesApi.labRunOrders(id, 200), hadesApi.labRunFills(id, 200)]);
      setOrders(orderPayload.orders || []);
      setFills(fillPayload.fills || []);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Orders laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void loadRun(runId);
  }, [runId, loadRun]);

  const validate = async () => {
    if (!ticket.instrument_id) {
      toast.error("Kies een instrument.");
      return;
    }
    const result = await runAction(
      () => hadesApi.labOrderPreview({
        instrument_id: ticket.instrument_id,
        side: ticket.side,
        order_type: ticket.order_type,
        quantity: ticket.quantity,
        limit_price: ticket.limit_price || undefined,
        stop_price: ticket.stop_price || undefined,
        time_in_force: ticket.time_in_force,
        reduce_only: ticket.reduce_only,
        post_only: ticket.post_only,
      }),
      { busy: setBusy, failure: "Ordercontrole mislukt." },
    );
    if (result) setCheck(result);
  };

  return (
    <div className="lab-stack">
      <LabNotice tone="warning">
        {text(matrix?.execution_mode, "SIMULATIE/PAPER — geen brokersessie en geen pad naar echt geld")}. Vullingen komen
        uitsluitend van de exchangesimulator; het orderticket hieronder controleert of een combinatie überhaupt is toegestaan.
      </LabNotice>

      <div className="lab-grid-2">
        <Panel title="Ordercombinatie controleren">
          <div className="lab-form">
            <LabField label="Instrument">
              <select className="lab-select" value={ticket.instrument_id} onChange={(event) => setTicket({ ...ticket, instrument_id: event.target.value })}>
                <option value="">— kies —</option>
                {instruments.map((row) => <option key={row.instrument_id} value={row.instrument_id}>{row.instrument_id} ({row.family})</option>)}
              </select>
            </LabField>
            <div className="lab-form-row">
              <LabField label="Kant">
                <select className="lab-select" value={ticket.side} onChange={(event) => setTicket({ ...ticket, side: event.target.value })}>
                  {["buy", "sell"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Ordertype">
                <select className="lab-select" value={ticket.order_type} onChange={(event) => setTicket({ ...ticket, order_type: event.target.value })}>
                  {ORDER_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Geldigheid">
                <select className="lab-select" value={ticket.time_in_force} onChange={(event) => setTicket({ ...ticket, time_in_force: event.target.value })}>
                  {TIME_IN_FORCE.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
            </div>
            <div className="lab-form-row">
              <LabField label="Hoeveelheid"><Input value={ticket.quantity} onChange={(event) => setTicket({ ...ticket, quantity: event.target.value })} /></LabField>
              <LabField label="Limietprijs"><Input value={ticket.limit_price} onChange={(event) => setTicket({ ...ticket, limit_price: event.target.value })} /></LabField>
              <LabField label="Stopprijs"><Input value={ticket.stop_price} onChange={(event) => setTicket({ ...ticket, stop_price: event.target.value })} /></LabField>
            </div>
            <div className="lab-check-row">
              <label><input type="checkbox" checked={ticket.reduce_only} onChange={(event) => setTicket({ ...ticket, reduce_only: event.target.checked })} /> reduce-only</label>
              <label><input type="checkbox" checked={ticket.post_only} onChange={(event) => setTicket({ ...ticket, post_only: event.target.checked })} /> post-only</label>
            </div>
            <Button disabled={busy} onClick={() => void validate()}>Controleer tegen de capaciteitsmatrix</Button>
            {check ? (
              check.valid ? (
                <LabNotice tone="info">Toegestaan. Beschikbare dataniveaus: {(Array.isArray(check.available_data_levels) ? check.available_data_levels : []).join(", ")}</LabNotice>
              ) : (
                <LabNotice tone="danger">Geblokkeerd: {text(check.reason)}</LabNotice>
              )
            ) : null}
          </div>
        </Panel>

        <Panel title="Ondersteunde ordertypen">
          <LabTable
            rows={matrix?.order_types || []}
            keyOf={(row, index) => String(row.order_type ?? index)}
            empty={<LabEmpty title="Geen matrix" hint="De backend levert de capaciteitsmatrix." />}
            columns={[
              { header: "Type", cell: (row) => text(row.order_type) },
              { header: "Dataniveau", cell: (row) => <small>{text(row.required_data_level)}</small> },
              { header: "Implementatie", cell: (row) => <LabStatus value={String(row.implementation) === "implemented" ? "completed" : "draft"} /> },
              { header: "Verificatie", cell: (row) => <small>{text(row.verification)}</small> },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Uitvoering per run" actions={
        <select className="lab-select" value={runId} onChange={(event) => onSelectRun(event.target.value)}>
          <option value="">— kies run —</option>
          {runs.map((row) => <option key={row.run_id} value={row.run_id}>{text(row.label, row.run_id)}</option>)}
        </select>
      }>
        <LabTable
          rows={orders}
          keyOf={(row, index) => String(row.order_id ?? index)}
          empty={<LabEmpty title="Geen orders" hint="Kies een run die orders heeft geplaatst." />}
          columns={[
            { header: "Tijd", cell: (row) => <small>{shortTime(row.created_event_time)}</small> },
            { header: "Instrument", cell: (row) => <small>{text(row.instrument_id)}</small> },
            { header: "Kant", cell: (row) => <small>{text(row.side)}</small> },
            { header: "Type", cell: (row) => <small>{text(row.order_type)} · {text(row.time_in_force)}</small> },
            { header: "Hoeveelheid", align: "right", cell: (row) => num(row.quantity, 6) },
            { header: "Gevuld", align: "right", cell: (row) => num(row.filled_quantity, 6) },
            { header: "Status", cell: (row) => <LabStatus value={String(row.status ?? "")} /> },
            { header: "Reden", cell: (row) => <small>{text(row.reject_reason, "")}</small> },
          ]}
        />
      </Panel>

      <Panel title={`Vullingen (${fills.length})`}>
        <LabTable
          rows={fills.slice(0, 60)}
          keyOf={(row, index) => String(row.event_id ?? index)}
          empty={<LabEmpty title="Geen vullingen" hint="Vullingen ontstaan pas op een gebeurtenis ná de orderplaatsing." />}
          columns={[
            { header: "Tijd", cell: (row) => <small>{shortTime(row.event_time)}</small> },
            { header: "Instrument", cell: (row) => <small>{text(row.instrument_id)}</small> },
            { header: "Hoeveelheid", align: "right", cell: (row) => num(row.quantity, 6) },
            { header: "Prijs", align: "right", cell: (row) => num(row.price, 4) },
            { header: "Kosten", align: "right", cell: (row) => num(row.fee, 4) },
            { header: "Liquiditeit", cell: (row) => <small>{text(row.liquidity)}</small> },
            { header: "Slippage (bps)", align: "right", cell: (row) => num(row.modelled_slippage_bps, 2) },
            { header: "Intrabar", cell: (row) => <small>{row.intrabar_ambiguous ? "onzeker binnen bar" : "eenduidig"}</small> },
          ]}
        />
      </Panel>

      <Panel title="Instrumentfamilies en hun ordermogelijkheden">
        <LabTable
          rows={matrix?.instruments || []}
          keyOf={(row, index) => String(row.family ?? index)}
          empty={<LabEmpty title="Geen matrix" hint="De backend levert de capaciteitsmatrix." />}
          columns={[
            { header: "Familie", cell: (row) => text(row.family) },
            { header: "Ordertypen", cell: (row) => <small>{(Array.isArray(row.order_types) ? row.order_types : []).join(", ")}</small> },
            { header: "Short", cell: (row) => <small>{row.supports_short ? "ja" : "nee"}</small> },
            { header: "Boekhouding", cell: (row) => <small>{(Array.isArray(row.accounting_features) ? row.accounting_features : []).join(", ")}</small> },
            { header: "Ontbrekende externe data", cell: (row) => <small>{(Array.isArray(row.missing_external_data) ? row.missing_external_data : []).join(", ") || "—"}</small> },
          ]}
        />
      </Panel>
    </div>
  );
}
