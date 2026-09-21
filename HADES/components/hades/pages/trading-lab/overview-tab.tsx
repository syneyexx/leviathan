import { Button } from "@/components/ui/button";
import { Panel } from "@/components/hades/ui";
import { hadesApi, type LabOverview } from "@/lib/hades-api";
import { LabEmpty, LabNotice, LabStats, LabStatus, LabTable, num, pct, pick, shortTime, text, useLabResource } from "./shared";

export function OverviewTab({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const { data, error, loading, reload } = useLabResource<LabOverview>(() => hadesApi.labOverview());
  const {
    data: capabilities,
    error: capabilitiesError,
    loading: capabilitiesLoading,
    reload: reloadCapabilities,
  } = useLabResource<Record<string, unknown>>(() => hadesApi.labCapabilities());

  if (error) {
    return (
      <Panel title="Overzicht">
        <LabNotice tone="danger">Overzicht laden mislukt: {error}</LabNotice>
        <Button size="sm" variant="outline" onClick={() => void reload()}>Opnieuw proberen</Button>
      </Panel>
    );
  }
  if (!data) {
    return <Panel title="Overzicht"><LabEmpty title={loading ? "Laden…" : "Geen data"} hint="Het lab antwoordt zodra de backend beschikbaar is." /></Panel>;
  }

  const counts = data.counts || {};
  const queue = data.queue || {};
  const strategyCaps = Array.isArray(capabilities?.strategies) ? (capabilities?.strategies as Array<Record<string, unknown>>) : [];
  const instrumentCaps = Array.isArray(capabilities?.instruments) ? (capabilities?.instruments as Array<Record<string, unknown>>) : [];

  return (
    <div className="lab-stack">
      <LabNotice tone="warning">
        <strong>{data.mode}</strong>
        <span>
          Alles op deze pagina is simulatie of papieren administratie. Er is geen brokerkoppeling, geen orderroute naar een
          beurs en geen betaalde datafeed in HADES.
        </span>
      </LabNotice>

      <Panel title="Labstatus" actions={<Button size="sm" variant="outline" onClick={() => void reload()}>Ververs</Button>}>
        <LabStats
          items={[
            { label: "Instrumenten", value: num(counts.instruments, 0) },
            { label: "Datasets", value: num(counts.datasets, 0), note: `${num(counts.frozen_datasets, 0)} bevroren · ${num(counts.synthetic_datasets, 0)} synthetisch` },
            { label: "Strategieën", value: num(counts.strategies, 0), note: `${num(data.lifecycle?.total, 0)} in levenscyclus` },
            { label: "Experimenten", value: num(counts.experiments, 0) },
            { label: "Runs", value: num(counts.runs, 0) },
            { label: "Evaluaties", value: num(counts.evaluations, 0) },
            { label: "Experiences", value: num(counts.experiences, 0) },
            { label: "Beliefs", value: num(counts.beliefs, 0), note: `autonomie ${text(pick(data, "learning.autonomy_level"), "off")}` },
          ]}
        />
        <div className="lab-inline-facts">
          <span>Datadekking: {shortTime(data.coverage?.first_event_time)} → {shortTime(data.coverage?.last_event_time)}</span>
          <span>{num(data.coverage?.rows, 0)} rijen over {num(data.coverage?.instruments, 0)} instrument(en)</span>
          <span>Wachtrij: {num(pick(queue, "running"), 0)} actief · {num(pick(queue, "queued"), 0)} wachtend · {num(pick(queue, "max_workers"), 0)} workers</span>
        </div>
      </Panel>

      <Panel
        title="Capability matrix"
        actions={<Button size="sm" variant="outline" onClick={() => void reloadCapabilities()}>Ververs matrix</Button>}
      >
        {capabilitiesError ? (
          <LabNotice tone="danger">Capability matrix laden mislukt: {capabilitiesError}</LabNotice>
        ) : capabilitiesLoading && !capabilities ? (
          <LabEmpty title="Laden…" hint="Instrument- en strategiefamilies worden opgehaald." />
        ) : (
          <div className="lab-grid-2">
            <LabTable
              rows={instrumentCaps}
              keyOf={(row, index) => String(row.family ?? index)}
              empty={<LabEmpty title="Geen instrumentcaps" hint="De backend matrix is leeg." />}
              columns={[
                { header: "Familie", cell: (row) => text(row.family) },
                { header: "Status", cell: (row) => <LabStatus value={String(row.implementation ?? "")} /> },
                {
                  header: "Ontbrekende data",
                  cell: (row) => {
                    const missing = Array.isArray(row.missing_external_data) ? row.missing_external_data : [];
                    return <small>{missing.length ? missing.map(String).join("; ") : "—"}</small>;
                  },
                },
              ]}
            />
            <LabTable
              rows={strategyCaps}
              keyOf={(row, index) => String(row.family ?? index)}
              empty={<LabEmpty title="Geen strategiecaps" hint="De backend matrix is leeg." />}
              columns={[
                { header: "Familie", cell: (row) => text(row.label ?? row.family) },
                { header: "Status", cell: (row) => <LabStatus value={String(row.implementation ?? "")} /> },
                {
                  header: "Blocked / missing",
                  cell: (row) => {
                    const missing = Array.isArray(row.missing_external_data) ? row.missing_external_data : [];
                    return <small>{missing.length ? missing.map(String).join("; ") : text(row.notes, "—")}</small>;
                  },
                },
              ]}
            />
          </div>
        )}
        <div className="lab-inline-facts">
          <span>
            <code>blocked_missing_data</code> blijft geweigerd aan de API-grens — geen lookalike fills.
          </span>
        </div>
      </Panel>

      {(data.warnings || []).length > 0 ? (
        <Panel title="Waarschuwingen over de huidige staat">
          <ul className="lab-bullets">
            {data.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </Panel>
      ) : null}

      <div className="lab-grid-2">
        <Panel title="Strategielevenscyclus">
          <LabTable
            rows={Object.entries(data.lifecycle?.counts || {})}
            keyOf={([state]) => state}
            empty={<LabEmpty title="Nog geen strategieën" hint="Registreer een strategie in Strategy Lab." />}
            columns={[
              { header: "Status", cell: ([state]) => <LabStatus value={state} /> },
              { header: "Aantal", align: "right", cell: ([, count]) => num(count, 0) },
            ]}
          />
        </Panel>
        <Panel title="Databronnen">
          <LabTable
            rows={data.providers || []}
            keyOf={(row, index) => String(row.provider_id ?? index)}
            empty={<LabEmpty title="Geen providers" hint="Providers worden door de backend aangeleverd." />}
            columns={[
              { header: "Bron", cell: (row) => text(row.name ?? row.provider_id) },
              { header: "Bruikbaar", cell: (row) => <LabStatus value={row.usable ? "completed" : "unavailable"} /> },
              { header: "Reden / licentie", cell: (row) => <small>{text(row.reason ?? row.licence)}</small> },
            ]}
          />
        </Panel>
      </div>

      <div className="lab-grid-2">
        <Panel title="Bekende datagaten">
          <LabTable
            rows={data.known_data_gaps || []}
            keyOf={(row, index) => `${row.area}-${index}`}
            empty={<LabEmpty title="Geen gaten geregistreerd" hint="De backend rapporteert hier wat ontbreekt." />}
            columns={[
              { header: "Gebied", cell: (row) => row.area },
              { header: "Ontbreekt", cell: (row) => <small>{row.missing}</small> },
              { header: "Gevolg", cell: (row) => <small>{row.consequence}</small> },
            ]}
          />
        </Panel>
        <Panel title="Grenzen van de simulator">
          <ul className="lab-bullets">
            {(data.simulator_limitations || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </Panel>
      </div>

      <Panel title="Recente runs">
        <LabTable
          rows={data.recent_runs || []}
          keyOf={(row) => row.run_id}
          empty={<LabEmpty title="Nog geen runs" hint="Start een simulatie in de Simulator-tab." />}
          columns={[
            { header: "Run", cell: (row) => <button type="button" className="lab-link" onClick={() => onOpenRun(row.run_id)}>{text(row.label, row.run_id)}</button> },
            { header: "Modus", cell: (row) => <small>{text(row.mode)} · {text(row.split)}</small> },
            { header: "Status", cell: (row) => <LabStatus value={row.status} /> },
            { header: "Voortgang", align: "right", cell: (row) => `${num(row.progress, 0)}%` },
            { header: "Rendement", align: "right", cell: (row) => pct(pick(row.result, "metrics.total_return")) },
          ]}
        />
      </Panel>

      <div className="lab-grid-2">
        <Panel title="Recente experimenten">
          <LabTable
            rows={data.recent_experiments || []}
            keyOf={(row) => row.experiment_id}
            empty={<LabEmpty title="Nog geen experimenten" hint="Preregistreer een zoektocht in Experiments." />}
            columns={[
              { header: "Titel", cell: (row) => text(row.title) },
              { header: "Familie", cell: (row) => <small>{text(row.strategy_family)}</small> },
              { header: "Status", cell: (row) => <LabStatus value={row.status} /> },
              { header: "Trials", align: "right", cell: (row) => `${num(row.trials_completed, 0)}/${num(row.search_budget, 0)}` },
            ]}
          />
        </Panel>
        <Panel title="Recente evaluaties">
          <LabTable
            rows={data.recent_evaluations || []}
            keyOf={(row) => row.report_id}
            empty={<LabEmpty title="Nog geen evaluaties" hint="Een onafhankelijke evaluatie is vereist voor promotie." />}
            columns={[
              { header: "Strategie", cell: (row) => <small>{text(row.strategy_id)} v{num(row.strategy_version, 0)}</small> },
              { header: "Oordeel", cell: (row) => <LabStatus value={row.verdict} /> },
              { header: "Bewijsklasse", cell: (row) => <small>{text(row.evidence_class)}</small> },
              { header: "Deflated Sharpe", align: "right", cell: (row) => num(row.deflated_sharpe) },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
