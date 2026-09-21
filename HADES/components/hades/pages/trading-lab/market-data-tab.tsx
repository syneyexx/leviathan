import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabDataset, type LabInstrument } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabKeyValues, LabNotice, LabStatus, LabTable, num, pct, pick, refusalOf, runAction, shortTime, text } from "./shared";
import { toast } from "sonner";

const FAMILIES = ["crypto_spot", "crypto_perpetual", "equity", "etf", "forex", "future", "option", "cfd", "bond"];
const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

export function MarketDataTab() {
  const [instruments, setInstruments] = useState<LabInstrument[]>([]);
  const [datasets, setDatasets] = useState<LabDataset[]>([]);
  const [providers, setProviders] = useState<Array<Record<string, unknown>>>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [gaps, setGaps] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const [instrumentForm, setInstrumentForm] = useState({
    family: "crypto_spot",
    venue: "binance",
    symbol: "BTCUSDT",
    base_currency: "BTC",
    quote_currency: "USDT",
    tick_size: "0.01",
    lot_size: "0.00001",
    calendar: "24x7",
  });
  const [importForm, setImportForm] = useState({ instrument_id: "", timeframe: "1h", text: "", licence: "operator supplied", availability_delay_seconds: "0" });
  const [syntheticForm, setSyntheticForm] = useState({ instrument_id: "", timeframe: "1h", start: "2018-01-01", end: "2024-12-31", seed: "20240101", regime: "mixed", start_price: "100" });
  const [downloadForm, setDownloadForm] = useState({ provider_id: "", instrument_id: "", timeframe: "1h", start: "", end: "", limit: "5000" });
  const [splitForm, setSplitForm] = useState({ development: "0.6", validation: "0.2", embargo_seconds: "0" });
  const [actionsText, setActionsText] = useState("[]");

  const refresh = useCallback(async () => {
    try {
      const [instrumentList, datasetList, providerList] = await Promise.all([
        hadesApi.labInstruments(),
        hadesApi.labDatasets({ limit: 200 }),
        hadesApi.labProviders(),
      ]);
      setInstruments(instrumentList.instruments || []);
      setDatasets(datasetList.datasets || []);
      setProviders(Array.isArray(providerList.providers) ? (providerList.providers as Array<Record<string, unknown>>) : []);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Marktdata laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const first = instruments[0]?.instrument_id || "";
    setImportForm((current) => (current.instrument_id ? current : { ...current, instrument_id: first }));
    setSyntheticForm((current) => (current.instrument_id ? current : { ...current, instrument_id: first }));
    setDownloadForm((current) => (current.instrument_id ? current : { ...current, instrument_id: first }));
  }, [instruments]);

  useEffect(() => {
    const usable = providers.find((item) => item.usable);
    const fallback = String(usable?.provider_id ?? providers[0]?.provider_id ?? "");
    setDownloadForm((current) => (current.provider_id ? current : { ...current, provider_id: fallback }));
  }, [providers]);

  const loadDetail = useCallback(async (datasetId: string) => {
    setSelected(datasetId);
    setDetail(null);
    setGaps(null);
    setPreview(null);
    try {
      const [detailPayload, gapPayload, previewPayload] = await Promise.all([
        hadesApi.labDataset(datasetId),
        hadesApi.labDatasetGaps(datasetId),
        hadesApi.labDatasetPreview(datasetId, 200),
      ]);
      setDetail(detailPayload);
      setGaps(gapPayload);
      setPreview(previewPayload);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Datasetdetail laden mislukt.");
    }
  }, []);

  const previewRows = useMemo(() => (Array.isArray(preview?.rows) ? (preview!.rows as Array<Record<string, unknown>>) : []), [preview]);

  const createInstrument = async () => {
    const result = await runAction(() => hadesApi.createLabInstrument({ ...instrumentForm }), {
      busy: setBusy,
      success: (row) => `Instrument ${row.instrument_id} geregistreerd.`,
      failure: "Instrument registreren mislukt.",
    });
    if (result) await refresh();
  };

  const importCsv = async () => {
    if (!importForm.instrument_id || !importForm.text.trim()) {
      toast.error("Kies een instrument en plak CSV-inhoud.");
      return;
    }
    const result = await runAction(
      () => hadesApi.labImportDataset({ ...importForm, availability_delay_seconds: Number(importForm.availability_delay_seconds) || 0 }),
      { busy: setBusy, failure: "Import mislukt." },
    );
    if (!result) return;
    const rows = Number(pick(result, "dataset.row_count") ?? 0);
    if (result.accepted && rows > 0) {
      toast.success(
        `${rows} rijen geïmporteerd (revisie ${text(pick(result, "dataset.revision"))}, ${num(pick(result, "quality.rows_rejected"), 0)} afgewezen).`,
      );
      setImportForm((current) => ({ ...current, text: "" }));
    } else {
      toast.message(`Niet geaccepteerd: ${text(result.reason, "zie kwaliteitsrapport")}`);
    }
    await refresh();
  };

  const generateSynthetic = async () => {
    const result = await runAction(
      () => hadesApi.labSyntheticDataset({ ...syntheticForm, seed: Number(syntheticForm.seed) || 0, start_price: Number(syntheticForm.start_price) || 100 }),
      { busy: setBusy, failure: "Synthetische reeks genereren mislukt." },
    );
    if (result) {
      toast.success(`Synthetische dataset aangemaakt (${num(pick(result, "dataset.row_count"), 0)} rijen). Gemarkeerd als SYNTHETIC.`);
      await refresh();
    }
  };

  const download = async () => {
    const result = await runAction(
      () => hadesApi.labDownloadDataset({ ...downloadForm, limit: Number(downloadForm.limit) || 5000, start: downloadForm.start || null, end: downloadForm.end || null }),
      { busy: setBusy, failure: "Download mislukt." },
    );
    if (!result) return;
    const reason = typeof result.reason === "string" ? result.reason : null;
    if (reason) toast.message(reason);
    else toast.success(`${num(pick(result, "dataset.row_count"), 0)} rijen opgehaald.`);
    await refresh();
  };

  const freeze = async (datasetId: string) => {
    const result = await runAction(() => hadesApi.labFreezeDataset(datasetId), { busy: setBusy, failure: "Bevriezen mislukt." });
    if (result) {
      toast.success("Dataset bevroren: de inhoud kan niet meer wijzigen zonder nieuwe revisie.");
      await refresh();
      await loadDetail(datasetId);
    }
  };

  const applySplits = async () => {
    if (!selected) return;
    const result = await runAction(
      () => hadesApi.labSetDatasetSplits(selected, {
        development: Number(splitForm.development),
        validation: Number(splitForm.validation),
        embargo_seconds: Number(splitForm.embargo_seconds) || 0,
      }),
      { busy: setBusy, failure: "Splits opslaan mislukt." },
    );
    if (result) {
      toast.success("Chronologische splits opgeslagen.");
      await loadDetail(selected);
    }
  };

  const importCorporateActions = async () => {
    if (!selected) return;
    let actions: Array<Record<string, unknown>>;
    try {
      const parsed = JSON.parse(actionsText || "[]");
      actions = Array.isArray(parsed) ? (parsed as Array<Record<string, unknown>>) : [];
    } catch {
      toast.error("Corporate actions zijn geen geldige JSON.");
      return;
    }
    if (actions.length === 0) {
      toast.error("Geef minstens één corporate action.");
      return;
    }
    const result = await runAction(() => hadesApi.labImportCorporateActions(selected, actions), {
      busy: setBusy,
      failure: "Corporate actions importeren mislukt.",
    });
    if (!result) return;
    toast.success(`${num(result.added, 0)} corporate action(s) toegevoegd.`);
    await loadDetail(selected);
  };

  const removeInstrument = async (instrumentId: string) => {
    const result = await runAction(() => hadesApi.deleteLabInstrument(instrumentId), { busy: setBusy, failure: "Verwijderen mislukt." });
    const refusal = refusalOf(result as Record<string, unknown> | null);
    if (refusal) toast.message(refusal);
    else if (result) toast.success("Instrument verwijderd.");
    await refresh();
  };

  return (
    <div className="lab-stack">
      <LabNotice tone="info">
        HADES levert geen koershistorie mee. Elke dataset komt van een eigen import, een gratis publieke bron of een expliciet
        als SYNTHETIC gemarkeerde generator. Herkomst, licentie en checksum staan bij elke revisie.
      </LabNotice>

      <div className="lab-grid-2">
        <Panel title="Instrument registreren">
          <div className="lab-form">
            <LabField label="Familie">
              <select className="lab-select" value={instrumentForm.family} onChange={(event) => setInstrumentForm({ ...instrumentForm, family: event.target.value })}>
                {FAMILIES.map((family) => <option key={family} value={family}>{family}</option>)}
              </select>
            </LabField>
            <LabField label="Beurs / venue"><Input value={instrumentForm.venue} onChange={(event) => setInstrumentForm({ ...instrumentForm, venue: event.target.value })} /></LabField>
            <LabField label="Symbool"><Input value={instrumentForm.symbol} onChange={(event) => setInstrumentForm({ ...instrumentForm, symbol: event.target.value })} /></LabField>
            <div className="lab-form-row">
              <LabField label="Basisvaluta"><Input value={instrumentForm.base_currency} onChange={(event) => setInstrumentForm({ ...instrumentForm, base_currency: event.target.value })} /></LabField>
              <LabField label="Notering"><Input value={instrumentForm.quote_currency} onChange={(event) => setInstrumentForm({ ...instrumentForm, quote_currency: event.target.value })} /></LabField>
            </div>
            <div className="lab-form-row">
              <LabField label="Tickgrootte"><Input value={instrumentForm.tick_size} onChange={(event) => setInstrumentForm({ ...instrumentForm, tick_size: event.target.value })} /></LabField>
              <LabField label="Lotgrootte"><Input value={instrumentForm.lot_size} onChange={(event) => setInstrumentForm({ ...instrumentForm, lot_size: event.target.value })} /></LabField>
            </div>
            <LabField label="Kalender" hint="24x7, nyse, xetra, cme_equity_index of forex_24x5">
              <Input value={instrumentForm.calendar} onChange={(event) => setInstrumentForm({ ...instrumentForm, calendar: event.target.value })} />
            </LabField>
            <Button disabled={busy} onClick={() => void createInstrument()}>Registreer instrument</Button>
          </div>
        </Panel>

        <Panel title={`Instrumenten (${instruments.length})`}>
          <LabTable
            rows={instruments}
            keyOf={(row) => row.instrument_id}
            empty={<LabEmpty title="Nog geen instrumenten" hint="Registreer er één; datasets hangen aan een instrument." />}
            columns={[
              { header: "Instrument", cell: (row) => <span className="lab-mono">{row.instrument_id}</span> },
              { header: "Familie", cell: (row) => <small>{row.family}</small> },
              { header: "Kalender", cell: (row) => <small>{row.calendar}</small> },
              { header: "", align: "right", cell: (row) => <Button size="sm" variant="ghost" disabled={busy} onClick={() => void removeInstrument(row.instrument_id)}>Verwijder</Button> },
            ]}
          />
        </Panel>
      </div>

      <div className="lab-grid-3">
        <Panel title="CSV importeren">
          <div className="lab-form">
            <LabField label="Instrument">
              <select className="lab-select" value={importForm.instrument_id} onChange={(event) => setImportForm({ ...importForm, instrument_id: event.target.value })}>
                <option value="">— kies —</option>
                {instruments.map((row) => <option key={row.instrument_id} value={row.instrument_id}>{row.instrument_id}</option>)}
              </select>
            </LabField>
            <LabField label="Resolutie">
              <select className="lab-select" value={importForm.timeframe} onChange={(event) => setImportForm({ ...importForm, timeframe: event.target.value })}>
                {TIMEFRAMES.map((frame) => <option key={frame} value={frame}>{frame}</option>)}
              </select>
            </LabField>
            <LabField label="Vertraging beschikbaarheid (s)" hint="Tijd tussen event en moment waarop de simulatie de rij mag zien.">
              <Input value={importForm.availability_delay_seconds} onChange={(event) => setImportForm({ ...importForm, availability_delay_seconds: event.target.value })} />
            </LabField>
            <LabField label="OHLCV CSV">
              <Textarea rows={5} value={importForm.text} placeholder={"ts,open,high,low,close,volume\n2018-01-01T00:00:00+00:00,100,101,99,100.5,12"} onChange={(event) => setImportForm({ ...importForm, text: event.target.value })} />
            </LabField>
            <Button disabled={busy} onClick={() => void importCsv()}>Importeer en valideer</Button>
          </div>
        </Panel>

        <Panel title="Synthetische reeks">
          <div className="lab-form">
            <LabField label="Instrument">
              <select className="lab-select" value={syntheticForm.instrument_id} onChange={(event) => setSyntheticForm({ ...syntheticForm, instrument_id: event.target.value })}>
                <option value="">— kies —</option>
                {instruments.map((row) => <option key={row.instrument_id} value={row.instrument_id}>{row.instrument_id}</option>)}
              </select>
            </LabField>
            <div className="lab-form-row">
              <LabField label="Van"><Input value={syntheticForm.start} onChange={(event) => setSyntheticForm({ ...syntheticForm, start: event.target.value })} /></LabField>
              <LabField label="Tot"><Input value={syntheticForm.end} onChange={(event) => setSyntheticForm({ ...syntheticForm, end: event.target.value })} /></LabField>
            </div>
            <div className="lab-form-row">
              <LabField label="Seed"><Input value={syntheticForm.seed} onChange={(event) => setSyntheticForm({ ...syntheticForm, seed: event.target.value })} /></LabField>
              <LabField label="Regime">
                <select className="lab-select" value={syntheticForm.regime} onChange={(event) => setSyntheticForm({ ...syntheticForm, regime: event.target.value })}>
                  {["mixed", "trend", "range", "volatile", "crash"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
            </div>
            <LabNotice tone="warning">Synthetische data is geen markthistorie. Resultaten zeggen iets over de generator, niet over de wereld.</LabNotice>
            <Button variant="outline" disabled={busy} onClick={() => void generateSynthetic()}>Genereer reeks</Button>
          </div>
        </Panel>

        <Panel title="Publieke bron ophalen">
          <div className="lab-form">
            <LabField label="Bron">
              <select className="lab-select" value={downloadForm.provider_id} onChange={(event) => setDownloadForm({ ...downloadForm, provider_id: event.target.value })}>
                <option value="">— kies —</option>
                {providers.map((row, index) => (
                  <option key={String(row.provider_id ?? index)} value={String(row.provider_id ?? "")}>
                    {String(row.name ?? row.provider_id)}{row.usable ? "" : " (niet bruikbaar)"}
                  </option>
                ))}
              </select>
            </LabField>
            <LabField label="Instrument">
              <select className="lab-select" value={downloadForm.instrument_id} onChange={(event) => setDownloadForm({ ...downloadForm, instrument_id: event.target.value })}>
                <option value="">— kies —</option>
                {instruments.map((row) => <option key={row.instrument_id} value={row.instrument_id}>{row.instrument_id}</option>)}
              </select>
            </LabField>
            <div className="lab-form-row">
              <LabField label="Van (optioneel)"><Input value={downloadForm.start} onChange={(event) => setDownloadForm({ ...downloadForm, start: event.target.value })} /></LabField>
              <LabField label="Tot (optioneel)"><Input value={downloadForm.end} onChange={(event) => setDownloadForm({ ...downloadForm, end: event.target.value })} /></LabField>
            </div>
            <Button variant="outline" disabled={busy} onClick={() => void download()}>Haal op</Button>
            <LabTable
              rows={providers}
              keyOf={(row, index) => String(row.provider_id ?? index)}
              empty={<LabEmpty title="Geen bronnen" hint="De backend rapporteert beschikbare bronnen." />}
              columns={[
                { header: "Bron", cell: (row) => <small>{String(row.name ?? row.provider_id)}</small> },
                { header: "Status", cell: (row) => <LabStatus value={row.usable ? "completed" : "unavailable"} /> },
                { header: "Toelichting", cell: (row) => <small>{text(row.reason ?? row.licence)}</small> },
              ]}
            />
          </div>
        </Panel>
      </div>

      <Panel title={`Datasets (${datasets.length})`}>
        <LabTable
          rows={datasets}
          keyOf={(row) => row.dataset_id}
          empty={<LabEmpty title="Nog geen datasets" hint="Zonder dataset blijft elke simulatiefunctie inert." />}
          columns={[
            { header: "Dataset", cell: (row) => <button type="button" className="lab-link" onClick={() => void loadDetail(row.dataset_id)}>{row.name || row.dataset_id}</button> },
            { header: "Instrument", cell: (row) => <small>{row.instrument_id} · {row.timeframe}</small> },
            { header: "Herkomst", cell: (row) => <small>{row.provider}{row.is_synthetic ? " · SYNTHETIC" : ""}</small> },
            { header: "Periode", cell: (row) => <small>{shortTime(row.first_event_time)} → {shortTime(row.last_event_time)}</small> },
            { header: "Rijen", align: "right", cell: (row) => num(row.row_count, 0) },
            { header: "Rev", align: "right", cell: (row) => `v${row.revision}` },
            { header: "Bevroren", cell: (row) => <LabStatus value={row.frozen ? "completed" : "draft"} /> },
            { header: "", align: "right", cell: (row) => (row.frozen ? null : <Button size="sm" variant="outline" disabled={busy} onClick={() => void freeze(row.dataset_id)}>Bevries</Button>) },
          ]}
        />
      </Panel>

      {selected && detail ? (
        <div className="lab-grid-2">
          <Panel title="Datasetdetail" actions={<span className="lab-mono">{selected}</span>}>
            <LabKeyValues
              rows={[
                ["Provider", text(pick(detail, "dataset.provider"))],
                ["Licentie", text(pick(detail, "dataset.licence"))],
                ["Checksum", <span key="c" className="lab-mono">{text(pick(detail, "dataset.content_checksum"))}</span>],
                ["Laatste slotkoers", num(pick(detail, "latest_close.close"))],
                ["Rijen in / geaccepteerd", `${num(pick(detail, "dataset.quality.rows_in"), 0)} / ${num(pick(detail, "dataset.quality.rows_accepted"), 0)}`],
                ["Afgewezen rijen", num(pick(detail, "dataset.quality.rows_rejected"), 0)],
              ]}
            />
            <h3 className="lab-subhead">Chronologische splits</h3>
            <LabTable
              rows={Array.isArray(detail.splits) ? (detail.splits as Array<Record<string, unknown>>) : []}
              keyOf={(row, index) => String(row.name ?? index)}
              empty={<LabEmpty title="Geen splits" hint="Stel ontwikkeling/validatie/sealed test in." />}
              columns={[
                { header: "Split", cell: (row) => text(row.name) },
                { header: "Van", cell: (row) => <small>{shortTime(row.start)}</small> },
                { header: "Tot", cell: (row) => <small>{shortTime(row.end)}</small> },
              ]}
            />
            <div className="lab-form-row">
              <LabField label="Ontwikkeling"><Input value={splitForm.development} onChange={(event) => setSplitForm({ ...splitForm, development: event.target.value })} /></LabField>
              <LabField label="Validatie"><Input value={splitForm.validation} onChange={(event) => setSplitForm({ ...splitForm, validation: event.target.value })} /></LabField>
              <LabField label="Embargo (s)"><Input value={splitForm.embargo_seconds} onChange={(event) => setSplitForm({ ...splitForm, embargo_seconds: event.target.value })} /></LabField>
            </div>
            <Button size="sm" disabled={busy} onClick={() => void applySplits()}>Splits opslaan</Button>
            <small className="lab-hint">De rest van de reeks blijft sealed test en is precies één keer bruikbaar per strategieversie.</small>

            <h3 className="lab-subhead">Corporate actions</h3>
            <LabField
              label="Acties (JSON-lijst)"
              hint='Bijvoorbeeld [{"event_time":"2020-08-31T00:00:00+00:00","available_at":"2020-08-28T20:00:00+00:00","kind":"split","ratio":4}]. HADES levert geen gelicentieerde actiehistorie; zonder import zijn aandelenreeksen alleen ruw juist.'
            >
              <Textarea rows={4} value={actionsText} onChange={(event) => setActionsText(event.target.value)} />
            </LabField>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void importCorporateActions()}>
              Corporate actions importeren
            </Button>
          </Panel>

          <Panel title="Kwaliteit en gaten">
            <LabKeyValues
              rows={[
                ["Kalender", text(pick(gaps, "calendar"))],
                ["Waargenomen rijen", num(pick(gaps, "rows"), 0)],
                ["Ontbrekende perioden", num(pick(gaps, "missing_periods"), 0)],
                ["Gatenratio", pct(pick(gaps, "gap_ratio"))],
              ]}
            />
            <LabJson value={pick(gaps, "gaps")} label="Gatenlijst" />
            <h3 className="lab-subhead">Eerste rijen ({previewRows.length})</h3>
            <LabTable
              rows={previewRows.slice(0, 25)}
              keyOf={(row, index) => `${String(row.event_time ?? index)}`}
              empty={<LabEmpty title="Geen rijen" hint="De dataset bevat nog geen geaccepteerde observaties." />}
              columns={[
                { header: "Event", cell: (row) => <small>{shortTime(row.event_time)}</small> },
                { header: "Beschikbaar", cell: (row) => <small>{shortTime(row.available_at)}</small> },
                { header: "Open", align: "right", cell: (row) => num(row.open, 4) },
                { header: "Hoog", align: "right", cell: (row) => num(row.high, 4) },
                { header: "Laag", align: "right", cell: (row) => num(row.low, 4) },
                { header: "Slot", align: "right", cell: (row) => num(row.close, 4) },
              ]}
            />
          </Panel>
        </div>
      ) : null}
    </div>
  );
}
