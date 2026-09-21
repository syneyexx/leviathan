"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCcw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { hadesApi } from "@/lib/hades-api";

type ProjectRow = Record<string, unknown>;
type ContextPackage = Record<string, unknown>;

/**
 * Compact project continuity surface — goals/constraints/decisions with provenance.
 * Uses existing Classic panel styling; not a new dashboard page.
 */
export function ProjectContinuityPanel() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [context, setContext] = useState<ContextPackage | null>(null);
  const [name, setName] = useState("");
  const [constraint, setConstraint] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<ProjectRow[]>([]);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const list = await hadesApi.projects("active");
      setProjects(list.projects || []);
      const sug = await hadesApi.proactiveSuggestions("open");
      setSuggestions(sug.suggestions || []);
      const id = selectedId || String(list.projects?.[0]?.id || "");
      if (id) {
        setSelectedId(id);
        setContext(await hadesApi.projectContext(id));
      } else {
        setContext(null);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Projecten laden mislukt");
    } finally {
      setBusy(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createProject() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const created = await hadesApi.createProject({ name: name.trim() });
      const id = String(created.project?.id || "");
      if (!id) {
        toast.error("Project aanmaken mislukt (geen project-id).");
        setBusy(false);
        return;
      }
      setName("");
      setSelectedId(id);
      await refresh();
      toast.success("Project aangemaakt");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Aanmaken mislukt");
      setBusy(false);
    }
  }

  async function addConstraint() {
    if (!selectedId || !constraint.trim()) return;
    setBusy(true);
    try {
      await hadesApi.addProjectItem(selectedId, {
        kind: "constraint",
        title: constraint.trim().slice(0, 200),
        body: constraint.trim(),
        provenance: "user_explicit",
        replace_overlapping: true,
      });
      setConstraint("");
      setContext(await hadesApi.projectContext(selectedId));
      toast.success("Constraint bijgewerkt");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Constraint opslaan mislukt");
    } finally {
      setBusy(false);
    }
  }

  const goals = (context?.goals as ProjectRow[] | undefined) || [];
  const constraints = (context?.constraints as ProjectRow[] | undefined) || [];
  const decisions = (context?.decisions as ProjectRow[] | undefined) || [];
  const stale = (context?.stale_assumptions as ProjectRow[] | undefined) || [];

  return (
    <Panel
      title="Projectcontinuïteit"
      eyebrow="Duurzaam · herstartbaar"
      actions={
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={busy}>
          <RefreshCcw /> Vernieuwen
        </Button>
      }
    >
      <p className="panel-copy">
        Doelen, besluiten en constraints over herstarts heen — met herkomstlabel, zonder verborgen redenering.
      </p>
      <div className="form-grid two" style={{ marginBottom: "1rem" }}>
        <label>
          <span>Nieuw project</span>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Projectnaam" />
            <Button onClick={() => void createProject()} disabled={busy || !name.trim()}>
              <Plus /> Aanmaken
            </Button>
          </div>
        </label>
        <label>
          <span>Actief project</span>
          <select
            value={selectedId}
            onChange={(e) => {
              const id = e.target.value;
              setSelectedId(id);
              if (id) void hadesApi.projectContext(id).then(setContext).catch(() => setContext(null));
            }}
          >
            <option value="">—</option>
            {projects.map((p) => (
              <option key={String(p.id)} value={String(p.id)}>
                {String(p.name || p.id)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {context ? (
        <div className="mini-grid" style={{ marginBottom: "1rem" }}>
          <div>
            <span>Doelen</span>
            <strong>{goals.length}</strong>
            <ul className="muted">
              {goals.slice(0, 4).map((g) => (
                <li key={String(g.id)}>
                  [{String(g.provenance)}] {String(g.title)}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>Besluiten</span>
            <strong>{decisions.length}</strong>
            <ul className="muted">
              {decisions.slice(0, 4).map((d) => (
                <li key={String(d.id)}>
                  [{String(d.provenance)}] {String(d.title)}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>Constraints</span>
            <strong>{constraints.length}</strong>
            <ul className="muted">
              {constraints.slice(0, 4).map((c) => (
                <li key={String(c.id)}>
                  [{String(c.provenance)}] {String(c.title)}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>Verouderde aannames</span>
            <strong>{stale.length}</strong>
            <small>Blijven zichtbaar, niet stilzwijgend actief</small>
          </div>
        </div>
      ) : (
        <p className="muted">Selecteer of maak een project om het contextpakket te zien.</p>
      )}

      {selectedId ? (
        <label>
          <span>Constraint wijzigen (vervangt overlappende actieve constraint)</span>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Input
              value={constraint}
              onChange={(e) => setConstraint(e.target.value)}
              placeholder="Bijv. Correctie: latency mag onder 5s in plaats van 2s"
            />
            <Button variant="outline" onClick={() => void addConstraint()} disabled={busy || !constraint.trim()}>
              Bijwerken
            </Button>
          </div>
        </label>
      ) : null}

      {suggestions.length > 0 ? (
        <div style={{ marginTop: "1rem" }}>
          <span className="eyebrow">Proactieve suggesties</span>
          <ul>
            {suggestions.slice(0, 5).map((s) => (
              <li key={String(s.id)}>
                <StatusBadge tone="warning">{String(s.action_kind || "suggest")}</StatusBadge>{" "}
                {String(s.reason || "")}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}
