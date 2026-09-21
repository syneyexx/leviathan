import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabInstrument } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabNotice, LabStatus, LabTable, num, pick, refusalOf, runAction, shortTime, text } from "./shared";

export function KnowledgeTab() {
  const [models, setModels] = useState<Array<Record<string, unknown>>>([]);
  const [instruments, setInstruments] = useState<LabInstrument[]>([]);
  const [learnings, setLearnings] = useState<Array<Record<string, unknown>>>([]);
  const [gaps, setGaps] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "", instrument_id: "", timeframe: "1h", kind: "ridge", train_fraction: "0.7", embargo_rows: "5", alpha: "1.0", seed: "7" });

  const refresh = useCallback(async () => {
    try {
      const [modelPayload, instrumentPayload, gapPayload] = await Promise.all([
        hadesApi.labModels(),
        hadesApi.labInstruments(),
        hadesApi.labDataGaps(),
      ]);
      setModels(modelPayload.models || []);
      setInstruments(instrumentPayload.instruments || []);
      setGaps(gapPayload);
      setForm((current) => (current.instrument_id ? current : { ...current, instrument_id: instrumentPayload.instruments?.[0]?.instrument_id || "" }));
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Kennis laden mislukt.");
    }
    try {
      const dashboard = await hadesApi.tradingDashboard();
      setLearnings((dashboard.learnings || []) as unknown as Array<Record<string, unknown>>);
    } catch {
      setLearnings([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const train = async () => {
    if (!form.name.trim() || !form.instrument_id) {
      toast.error("Geef een modelnaam en kies een instrument.");
      return;
    }
    const result = await runAction(
      () => hadesApi.trainLabModel({
        name: form.name.trim(),
        instrument_id: form.instrument_id,
        timeframe: form.timeframe,
        kind: form.kind,
        train_fraction: Number(form.train_fraction) || 0.7,
        embargo_rows: Number(form.embargo_rows) || 0,
        alpha: Number(form.alpha) || 1,
        seed: Number(form.seed) || 7,
      }),
      { busy: setBusy, failure: "Training starten mislukt." },
    );
    if (!result) return;
    const refusal = refusalOf(result);
    if (refusal) toast.message(refusal);
    else toast.success("Training in de wachtrij gezet. De trainingsgrens wordt hard afgedwongen.");
    window.setTimeout(() => void refresh(), 2000);
  };

  return (
    <div className="lab-stack">
      <LabNotice tone="info">
        Leren gebeurt op de ontwikkelsplit. Voorbewerking, kenmerken en labels worden binnen het trainingsvenster gefit en
        met een expliciete trainingsgrens vastgelegd, zodat een model bij hergebruik geen toekomst kan zien.
      </LabNotice>

      <div className="lab-grid-2">
        <Panel title="Numeriek model trainen">
          <div className="lab-form">
            <LabField label="Naam"><Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></LabField>
            <LabField label="Instrument">
              <select className="lab-select" value={form.instrument_id} onChange={(event) => setForm({ ...form, instrument_id: event.target.value })}>
                <option value="">— kies —</option>
                {instruments.map((row) => <option key={row.instrument_id} value={row.instrument_id}>{row.instrument_id}</option>)}
              </select>
            </LabField>
            <div className="lab-form-row">
              <LabField label="Soort">
                <select className="lab-select" value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value })}>
                  {["ridge", "logistic"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </LabField>
              <LabField label="Resolutie"><Input value={form.timeframe} onChange={(event) => setForm({ ...form, timeframe: event.target.value })} /></LabField>
            </div>
            <div className="lab-form-row">
              <LabField label="Trainingsfractie"><Input value={form.train_fraction} onChange={(event) => setForm({ ...form, train_fraction: event.target.value })} /></LabField>
              <LabField label="Embargo (rijen)"><Input value={form.embargo_rows} onChange={(event) => setForm({ ...form, embargo_rows: event.target.value })} /></LabField>
              <LabField label="Alpha"><Input value={form.alpha} onChange={(event) => setForm({ ...form, alpha: event.target.value })} /></LabField>
            </div>
            <Button disabled={busy} onClick={() => void train()}>Train model</Button>
            <small className="lab-hint">
              Begin bij interpreteerbare basislijnen. Een model dat een eenvoudige regel niet verslaat, is geen vooruitgang.
            </small>
          </div>
        </Panel>

        <Panel title={`Getrainde modellen (${models.length})`} actions={<Button size="sm" variant="outline" onClick={() => void refresh()}>Ververs</Button>}>
          <LabTable
            rows={models}
            keyOf={(row, index) => String(row.model_id ?? index)}
            empty={<LabEmpty title="Nog geen modellen" hint="Train er één; strategieën van de familie model_signal gebruiken ze." />}
            columns={[
              { header: "Naam", cell: (row) => text(row.name) },
              { header: "Soort", cell: (row) => <small>{text(row.kind)} v{num(row.version, 0)}</small> },
              { header: "Split", cell: (row) => <small>{text(row.split)}</small> },
              { header: "Trainingsgrens", cell: (row) => <small>{shortTime(pick(row, "training_window.cutoff"))}</small> },
              { header: "Basislijn geslagen", cell: (row) => <LabStatus value={pick(row, "baseline_comparison.beats_baseline") ? "completed" : "draft"} /> },
              { header: "Hash", cell: (row) => <small className="lab-mono">{String(row.artefact_hash ?? "").slice(0, 10)}</small> },
            ]}
          />
        </Panel>
      </div>

      <div className="lab-grid-2">
        <Panel title="Marktkennis uit eerdere runs">
          <LabTable
            rows={learnings}
            keyOf={(row, index) => String(row.chunk_id ?? index)}
            empty={<LabEmpty title="Nog geen kennisfragmenten" hint="Discovery en evaluaties schrijven bevindingen naar Knowledge." />}
            columns={[
              { header: "Bron", cell: (row) => <small>{text(row.source_type)}</small> },
              { header: "Titel", cell: (row) => text(row.title) },
              { header: "Sectie", cell: (row) => <small>{text(row.heading, "")}</small> },
            ]}
          />
        </Panel>
        <Panel title="Wat dit lab niet weet">
          <LabTable
            rows={Array.isArray(gaps?.gaps) ? (gaps!.gaps as Array<Record<string, unknown>>) : []}
            keyOf={(row, index) => `${String(row.area ?? index)}`}
            empty={<LabEmpty title="Geen gaten geregistreerd" hint="De backend rapporteert hier ontbrekende externe data." />}
            columns={[
              { header: "Gebied", cell: (row) => text(row.area) },
              { header: "Ontbreekt", cell: (row) => <small>{text(row.missing)}</small> },
              { header: "Gevolg", cell: (row) => <small>{text(row.consequence)}</small> },
            ]}
          />
          <LabJson value={pick(gaps, "simulator_limitations")} label="Grenzen van de simulator" />
        </Panel>
      </div>
    </div>
  );
}
