import { useCallback, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/hades/ui";
import { hadesApi } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabKeyValues, LabNotice, LabStats, LabStatus, LabTable, num, pct, pick, refusalOf, runAction, shortTime, text, useLabResource } from "./shared";

type LearningSection = "overview" | "beliefs" | "evolution" | "cycles" | "experiences";

export function LearningTab() {
  const [section, setSection] = useState<LearningSection>("overview");
  const [busy, setBusy] = useState(false);
  const [objective, setObjective] = useState("Leer van afgeronde development-experimenten");
  const [autonomy, setAutonomy] = useState("learn_only");
  const [parentIds, setParentIds] = useState("");
  const [experienceFilter, setExperienceFilter] = useState({ strategy_family: "", split: "development", regime_key: "" });
  const [selectedCycle, setSelectedCycle] = useState("");

  const overview = useLabResource(() => hadesApi.labLearningOverview());
  const beliefs = useLabResource(() => hadesApi.labBeliefs({ limit: 80 }));
  const lineage = useLabResource(() => hadesApi.labStrategyLineage());
  const candidates = useLabResource(() => hadesApi.labStrategyCandidates());
  const champions = useLabResource(() => hadesApi.labChampions());
  const cycles = useLabResource(() => hadesApi.labLearningCycles(40));
  const experiences = useLabResource(
    () =>
      hadesApi.labExperiences({
        strategy_family: experienceFilter.strategy_family || undefined,
        split: experienceFilter.split || undefined,
        regime_key: experienceFilter.regime_key || undefined,
        limit: 50,
      }),
    [experienceFilter.strategy_family, experienceFilter.split, experienceFilter.regime_key],
  );

  const reloadAll = useCallback(async () => {
    await Promise.all([overview.reload(), beliefs.reload(), lineage.reload(), candidates.reload(), champions.reload(), cycles.reload(), experiences.reload()]);
  }, [overview, beliefs, lineage, candidates, champions, cycles, experiences]);

  const startCycle = async () => {
    const result = await runAction(
      () =>
        hadesApi.startLabLearningCycle({
          objective: objective.trim(),
          autonomy_level: autonomy,
          parent_strategy_ids: parentIds.split(/[\s,]+/).filter(Boolean),
        }),
      { busy: setBusy, failure: "Leercyclus starten mislukt." },
    );
    const refused = refusalOf(result as Record<string, unknown> | null);
    if (refused) {
      toast.error(refused);
      return;
    }
    if (result) {
      toast.success("Leercyclus in de wachtrij. Dit blijft simulatie/paper.");
      await reloadAll();
    }
  };

  const ingest = async () => {
    const result = await runAction(() => hadesApi.ingestLabExperiences({}), { busy: setBusy, failure: "Experiences opbouwen mislukt." });
    if (result) {
      toast.success(`Experiences: ${text(pick(result, "created"), "0")} nieuw, ${text(pick(result, "skipped"), "0")} overgeslagen.`);
      await reloadAll();
    }
  };

  const counts = (overview.data || {}) as Record<string, unknown>;
  const countBag = (counts.counts || {}) as Record<string, unknown>;
  const cycleRows = ((cycles.data?.cycles || []) as Array<Record<string, unknown>>);
  const selected = cycleRows.find((row) => row.cycle_id === selectedCycle) || cycleRows[0];

  return (
    <div className="lab-stack">
      <LabNotice tone="warning">
        <strong>Leren is geen prompt en geen winstbot.</strong>
        <span>
          Een experience is bewijs. Aggregatie is statistiek. Een belief vereist evidence-referenties. Een kandidaat blijft een
          nieuwe strategieversie die opnieuw door development en onafhankelijke validatie moet. Geen sealed holdout, geen echt geld.
        </span>
      </LabNotice>

      <div className="lab-tabs" role="tablist" aria-label="Leren">
        {(
          [
            ["overview", "Overzicht"],
            ["beliefs", "Beliefs"],
            ["evolution", "Evolutie"],
            ["cycles", "Leercycli"],
            ["experiences", "Experiences"],
          ] as Array<[LearningSection, string]>
        ).map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={section === id} className={`lab-tab${section === id ? " is-active" : ""}`} onClick={() => setSection(id)}>
            {label}
          </button>
        ))}
      </div>

      {section === "overview" ? (
        <Panel title="Learning overview" actions={<Button size="sm" variant="outline" onClick={() => void reloadAll()}>Ververs</Button>}>
          {overview.error ? <LabNotice tone="danger">{overview.error}</LabNotice> : null}
          <LabStats
            items={[
              { label: "Experiences", value: num(countBag.experiences, 0) },
              { label: "Findings", value: num(countBag.findings, 0) },
              { label: "Ondersteunde beliefs", value: num(countBag.beliefs_supported, 0) },
              { label: "Verzwakt", value: num(countBag.beliefs_weakened, 0) },
              { label: "Retired", value: num(countBag.beliefs_retired, 0) },
              { label: "Actieve cycli", value: num(countBag.active_cycles, 0), note: `autonomie ${text(counts.autonomy_level, "off")}` },
            ]}
          />
          <p className="lab-hint">{text(counts.note)}</p>
          <div className="lab-button-row" style={{ marginTop: "0.75rem" }}>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void ingest()}>Experiences opbouwen</Button>
          </div>
        </Panel>
      ) : null}

      {section === "beliefs" ? (
        <Panel title="Trading beliefs">
          {beliefs.error ? <LabNotice tone="danger">{beliefs.error}</LabNotice> : null}
          <LabTable
            rows={(beliefs.data?.beliefs || []) as Array<Record<string, unknown>>}
            keyOf={(row, index) => String(row.belief_id ?? index)}
            empty={<LabEmpty title="Nog geen beliefs" hint="Rond een experiment af en start een leercyclus. Zonder evidence-referentie wordt niets opgeslagen." />}
            columns={[
              { header: "Claim", cell: (row) => <span>{text(row.claim)}<br /><small>{text(row.regime_key)} · {text(row.strategy_family)}</small></span> },
              { header: "Status", cell: (row) => <LabStatus value={String(row.status || "")} /> },
              { header: "Confidence", align: "right", cell: (row) => pct(row.confidence, 0) },
              { header: "Voor / tegen", align: "right", cell: (row) => `${num(row.supporting_count, 0)} / ${num(row.contradicting_count, 0)}` },
              { header: "Evidence", cell: (row) => <small>{Array.isArray(row.evidence_refs) ? String((row.evidence_refs as unknown[]).length) : "0"} refs</small> },
            ]}
          />
        </Panel>
      ) : null}

      {section === "evolution" ? (
        <div className="lab-grid-2">
          <Panel title="Champion / challenger">
            <LabTable
              rows={(champions.data?.champions || []) as Array<Record<string, unknown>>}
              keyOf={(row, index) => String(row.champion_id ?? index)}
              empty={<LabEmpty title="Nog geen champion" hint="Alleen een gevalideerde strategie kan champion worden. Development-winst is niet genoeg." />}
              columns={[
                { header: "Strategie", cell: (row) => `${text(row.strategy_id)} v${text(row.strategy_version)}` },
                { header: "Status", cell: (row) => <LabStatus value={String(row.status || "")} /> },
                { header: "Scope", cell: (row) => <small>{text(pick(row, "scope.instrument_id"))} {text(pick(row, "scope.timeframe"))}</small> },
              ]}
            />
          </Panel>
          <Panel title="Lineage">
            <LabTable
              rows={(lineage.data?.lineage || []) as Array<Record<string, unknown>>}
              keyOf={(row, index) => String(row.lineage_id ?? index)}
              empty={<LabEmpty title="Nog geen evolutie" hint="Mutaties maken een nieuwe versie; de ouder blijft onaangetast." />}
              columns={[
                { header: "Ouder → kind", cell: (row) => `v${text(row.parent_version)} → v${text(row.child_version)}` },
                { header: "Mutatie", cell: (row) => <span>{text(row.mutation_kind)}<br /><small>{text(row.mutation_reason)}</small></span> },
                { header: "Gen", align: "right", cell: (row) => num(row.generation, 0) },
              ]}
            />
            <h4 style={{ marginTop: "1rem" }}>Kandidaten</h4>
            <LabTable
              rows={(candidates.data?.candidates || []) as Array<Record<string, unknown>>}
              keyOf={(row, index) => String(row.candidate_id ?? index)}
              empty={<LabEmpty title="Geen kandidaten" hint="PROPOSE of hoger mag kandidaten genereren." />}
              columns={[
                { header: "Versie", cell: (row) => `v${text(row.strategy_version)}` },
                { header: "Waarom", cell: (row) => <small>{text(row.mutation_reason)}</small> },
                { header: "Status", cell: (row) => <LabStatus value={String(row.status || "")} /> },
                { header: "Afgewezen", cell: (row) => <small>{text(row.rejection_reason, "")}</small> },
              ]}
            />
          </Panel>
        </div>
      ) : null}

      {section === "cycles" ? (
        <div className="lab-stack">
          <Panel title="Nieuwe leercyclus">
            <div className="lab-form">
              <LabField label="Doel">
                <Input value={objective} onChange={(event) => setObjective(event.target.value)} />
              </LabField>
              <LabField label="Autonomie voor deze cyclus" hint="De globale default blijft staan; dit is alleen deze run.">
                <select className="lab-select" value={autonomy} onChange={(event) => setAutonomy(event.target.value)}>
                  <option value="learn_only">LEARN_ONLY — experiences en beliefs</option>
                  <option value="propose">PROPOSE — ook kandidaten, geen experimenten</option>
                  <option value="research">RESEARCH — development-experimenten</option>
                  <option value="auto_research">AUTO_RESEARCH — plus validatie, nooit sealed holdout</option>
                </select>
              </LabField>
              <LabField label="Parent strategy ids" hint="Optioneel, komma-gescheiden.">
                <Input value={parentIds} onChange={(event) => setParentIds(event.target.value)} placeholder="lstr_…" />
              </LabField>
            </div>
            <Button size="sm" disabled={busy} onClick={() => void startCycle()}>Start leercyclus</Button>
          </Panel>
          <Panel title="Cycli">
            <LabTable
              rows={cycleRows}
              keyOf={(row, index) => String(row.cycle_id ?? index)}
              empty={<LabEmpty title="Nog geen cycli" hint="Start er één. Een onderbroken cyclus hervat vanaf de laatste voltooide stap." />}
              columns={[
                { header: "Cyclus", cell: (row) => (
                  <button type="button" className="lab-link" onClick={() => setSelectedCycle(String(row.cycle_id || ""))}>
                    {text(row.cycle_id)}
                  </button>
                ) },
                { header: "Status", cell: (row) => <LabStatus value={String(row.status || "")} /> },
                { header: "Stap", cell: (row) => text(row.stage) },
                { header: "Autonomie", cell: (row) => text(row.autonomy_level) },
                { header: "Gestart", cell: (row) => shortTime(row.started_at || row.created_at) },
              ]}
            />
            {selected ? (
              <div style={{ marginTop: "1rem" }}>
                <LabKeyValues
                  rows={[
                    ["Doel", text(selected.objective)],
                    ["Fout", text(selected.failure_reason, "—")],
                    ["Kandidaten", String(((selected.generated_candidates as unknown[]) || []).length)],
                    ["Experimenten", String(((selected.experiment_ids as unknown[]) || []).length)],
                    ["Championwijzigingen", String(((selected.champion_changes as unknown[]) || []).length)],
                  ]}
                />
                <LabJson value={selected.report} label="Cyclusrapport" />
              </div>
            ) : null}
          </Panel>
        </div>
      ) : null}

      {section === "experiences" ? (
        <Panel title="Experiences" actions={<Button size="sm" variant="outline" onClick={() => void experiences.reload()}>Ververs</Button>}>
          <div className="lab-form">
            <LabField label="Familie">
              <Input value={experienceFilter.strategy_family} onChange={(event) => setExperienceFilter((current) => ({ ...current, strategy_family: event.target.value }))} />
            </LabField>
            <LabField label="Split">
              <Input value={experienceFilter.split} onChange={(event) => setExperienceFilter((current) => ({ ...current, split: event.target.value }))} />
            </LabField>
            <LabField label="Regime-sleutel">
              <Input value={experienceFilter.regime_key} onChange={(event) => setExperienceFilter((current) => ({ ...current, regime_key: event.target.value }))} />
            </LabField>
          </div>
          <p className="lab-hint">Getoond: {num(experiences.data?.experiences?.length, 0)} van {num(experiences.data?.count, 0)}. Rijen zijn gepagineerd; miljoenen experiences worden niet in één keer geladen.</p>
          <LabTable
            rows={(experiences.data?.experiences || []) as Array<Record<string, unknown>>}
            keyOf={(row, index) => String(row.experience_id ?? index)}
            empty={<LabEmpty title="Nog geen experiences" hint="Los later_outcome van beslissingen op en bouw experiences. Retries dupliceren niet." />}
            columns={[
              { header: "Tijd", cell: (row) => shortTime(row.event_time) },
              { header: "Regime", cell: (row) => text(row.regime_key) },
              { header: "Actie", cell: (row) => `${text(row.signal)}/${text(row.action)}` },
              { header: "Uitkomst", cell: (row) => <LabStatus value={String(row.outcome_class || "")} /> },
              { header: "Δ", align: "right", cell: (row) => pct(row.price_change, 2) },
              { header: "Split", cell: (row) => text(row.split) },
            ]}
          />
        </Panel>
      ) : null}
    </div>
  );
}
