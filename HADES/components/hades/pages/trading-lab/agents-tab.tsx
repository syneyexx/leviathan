import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Panel } from "@/components/hades/ui";
import { hadesApi } from "@/lib/hades-api";
import { LabEmpty, LabField, LabJson, LabNotice, LabStatus, LabTable, num, pick, shortTime, text } from "./shared";

type Role = { role_id: string; name: string; mandate: string; reads: string[]; writes: string[]; forbidden: string[]; splits: string[]; output_schema: Record<string, string> };

export function AgentTeamTab({ strategyId }: { strategyId: string }) {
  const [manifest, setManifest] = useState<Record<string, unknown> | null>(null);
  const [sessions, setSessions] = useState<Array<Record<string, unknown>>>([]);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastRun, setLastRun] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [rolePayload, sessionPayload] = await Promise.all([hadesApi.labAgentRoles(), hadesApi.labAgentSessions(30)]);
      setManifest(rolePayload);
      setSessions(sessionPayload.sessions || []);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Agentrollen laden mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const roles = (Array.isArray(manifest?.roles) ? manifest!.roles : []) as Role[];
  const services = Object.entries((manifest?.deterministic_services || {}) as Record<string, string>);
  const chatAvailable = Boolean(manifest?.chat_available);
  const configuredModels = (manifest?.configured_models || {}) as Record<string, unknown>;

  const toggleRole = (roleId: string) => {
    setSelectedRoles((current) => (current.includes(roleId) ? current.filter((item) => item !== roleId) : [...current, roleId]));
  };

  const run = async () => {
    if (question.trim().length < 3) {
      toast.error("Formuleer een onderzoeksvraag.");
      return;
    }
    setBusy(true);
    try {
      const result = await hadesApi.runLabAgents({
        question: question.trim(),
        roles: selectedRoles.length ? selectedRoles : undefined,
        strategy_id: strategyId || undefined,
      });
      setLastRun(result);
      if (result.status === "unavailable") {
        toast.message(text(result.reason, "Agentteam niet beschikbaar."));
      } else {
        toast.success("Agentteam afgerond. De uitkomst is een voorstel, geen order.");
      }
      await refresh();
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Agentteam starten mislukt.");
    } finally {
      setBusy(false);
    }
  };

  const steps = Array.isArray(lastRun?.steps) ? (lastRun!.steps as Array<Record<string, unknown>>) : [];

  return (
    <div className="lab-stack">
      <LabNotice tone="info">
        Rollen zijn adviserend. Simulatie, boekhouding, risicotoets en orderuitvoering zijn deterministische services: die
        draaien zonder taalmodel en negeren elke poging van een rol om limieten op te rekken.
      </LabNotice>

      {!chatAvailable ? (
        <LabNotice tone="warning">Er is geen modelgateway gekoppeld aan het lab; rollen kunnen niet draaien.</LabNotice>
      ) : null}
      {Object.keys(configuredModels).length === 0 ? (
        <LabNotice tone="warning">
          Nog geen model gekozen in Instellingen. HADES kiest geen model voor je en hardcodeert er geen.
        </LabNotice>
      ) : null}

      <div className="lab-grid-2">
        <Panel title="Onderzoeksvraag">
          <div className="lab-form">
            <LabField label="Vraag aan het team" hint="Laat de rolselectie leeg om de standaardpijplijn te draaien.">
              <Textarea rows={4} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Welke trendstrategie is verdedigbaar op de bevroren BTC-dataset, en waarop zou hij falen?" />
            </LabField>
            <div className="lab-chip-row">
              {roles.map((role) => (
                <button key={role.role_id} type="button" className={`lab-chip${selectedRoles.includes(role.role_id) ? " is-active" : ""}`} onClick={() => toggleRole(role.role_id)}>
                  {role.name}
                </button>
              ))}
            </div>
            <Button disabled={busy || !chatAvailable} onClick={() => void run()}>Start rollenpijplijn</Button>
          </div>
        </Panel>

        <Panel title="Deterministische services (geen LLM)">
          <ul className="lab-bullets">
            {services.map(([service, reason]) => <li key={service}><strong>{service}</strong> — {reason}</li>)}
          </ul>
          <small className="lab-hint">{text(pick(manifest, "note"))}</small>
        </Panel>
      </div>

      <Panel title={`Rollen (${roles.length})`}>
        <LabTable
          rows={roles}
          keyOf={(row) => row.role_id}
          empty={<LabEmpty title="Geen rollen" hint="De backend levert het rollenmanifest." />}
          columns={[
            { header: "Rol", cell: (row) => <strong>{row.name}</strong> },
            { header: "Mandaat", cell: (row) => <small>{row.mandate}</small> },
            { header: "Leest", cell: (row) => <small>{(row.reads || []).join(", ")}</small> },
            { header: "Schrijft", cell: (row) => <small>{(row.writes || []).join(", ")}</small> },
            { header: "Verboden", cell: (row) => <small>{(row.forbidden || []).join(", ")}</small> },
            { header: "Splits", cell: (row) => <small>{(row.splits || []).join(", ")}</small> },
          ]}
        />
      </Panel>

      {steps.length > 0 ? (
        <Panel title="Laatste pijplijn">
          <LabTable
            rows={steps}
            keyOf={(row, index) => `${String(row.role_id ?? index)}`}
            empty={<LabEmpty title="Geen stappen" hint="De pijplijn leverde geen stappen op." />}
            columns={[
              { header: "Rol", cell: (row) => text(row.role_id) },
              { header: "Status", cell: (row) => <LabStatus value={String(row.status ?? "")} /> },
              { header: "Model", cell: (row) => <small>{text(row.model_id)}</small> },
              { header: "Ontbrekende velden", cell: (row) => <small>{(Array.isArray(row.missing_fields) ? row.missing_fields : []).join(", ") || "—"}</small> },
              { header: "Uitkomst", cell: (row) => <LabJson value={row.output} label="Gestructureerde output" /> },
            ]}
          />
          <small className="lab-hint">{text(pick(lastRun, "note"))}</small>
        </Panel>
      ) : null}

      <Panel title={`Sessies (${sessions.length})`} actions={<Button size="sm" variant="outline" onClick={() => void refresh()}>Ververs</Button>}>
        <LabTable
          rows={sessions}
          keyOf={(row, index) => String(row.session_id ?? index)}
          empty={<LabEmpty title="Nog geen sessies" hint="Elke pijplijn wordt met rol, model en prompt-hash vastgelegd." />}
          columns={[
            { header: "Titel", cell: (row) => text(row.title) },
            { header: "Status", cell: (row) => <LabStatus value={String(row.status ?? "")} /> },
            { header: "Stappen", align: "right", cell: (row) => num((pick(row, "result.steps") as unknown[] | undefined)?.length ?? 0, 0) },
            { header: "Gestart", cell: (row) => <small>{shortTime(row.created_at)}</small> },
          ]}
        />
      </Panel>
    </div>
  );
}
