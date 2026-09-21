"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCcw,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { AgentDetailPanel } from "@/components/hades/features/agents/AgentDetailPanel";
import { AgentPracticePanel } from "@/components/hades/features/agents/AgentPracticePanel";
import { AgentUsagePanel } from "@/components/hades/features/agents/AgentUsagePanel";
import { AgentsActivityPanel } from "@/components/hades/features/agents/AgentsActivityPanel";
import { AgentsList } from "@/components/hades/features/agents/AgentsList";
import { AgentsSummary } from "@/components/hades/features/agents/AgentsSummary";
import { AgentsToolbar } from "@/components/hades/features/agents/AgentsToolbar";
import { SpecialistContractsPanel } from "@/components/hades/features/agents/SpecialistContractsPanel";
import type {
  AgentMutationAction,
  PracticeResult,
  PracticeScenario,
} from "@/components/hades/features/agents/types";
import { PageHeader } from "@/components/hades/ui";
import {
  filterAgents,
  sortAgents,
  type AgentSortKey,
} from "@/lib/agents-console";
import {
  hadesApi,
  type AgentsConsoleResponse,
  type HadesAgent,
  type SpecialistContract,
} from "@/lib/hades-api";

export function AgentsPage() {
  const [data, setData] = useState<AgentsConsoleResponse | null>(null);
  const [detail, setDetail] = useState<HadesAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [role, setRole] = useState("all");
  const [provider, setProvider] = useState("all");
  const [model, setModel] = useState("all");
  const [activeOnly, setActiveOnly] = useState(false);
  const [errorOnly, setErrorOnly] = useState(false);
  const [sortKey, setSortKey] = useState<AgentSortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [mutating, setMutating] = useState<AgentMutationAction | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [practiceScenarios, setPracticeScenarios] = useState<PracticeScenario[]>([]);
  const [practiceResults, setPracticeResults] = useState<Record<string, PracticeResult>>({});
  const [practiceLoading, setPracticeLoading] = useState(true);
  const [practiceRunning, setPracticeRunning] = useState<string | null>(null);
  const [specialists, setSpecialists] = useState<SpecialistContract[]>([]);
  const [specialistsLoading, setSpecialistsLoading] = useState(true);
  const [specialistsError, setSpecialistsError] = useState<string | null>(null);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const payload = await hadesApi.agents();
      setData(payload);
      setError(null);
      setSelectedId((current) => (payload.items.some((item) => item.id === current) ? current : payload.items[0]?.id ?? ""));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Agents laden is mislukt.";
      setError(message);
      if (!quiet) toast.error(message);
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    setSpecialistsLoading(true);
    void hadesApi.specialists()
      .then((payload) => {
        if (!cancelled) {
          setSpecialists(payload.items);
          setSpecialistsError(null);
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setSpecialists([]);
          setSpecialistsError(reason instanceof Error ? reason.message : "Specialist-contracten laden is mislukt.");
        }
      })
      .finally(() => {
        if (!cancelled) setSpecialistsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setPracticeLoading(true);
    void hadesApi.practiceScenarios()
      .then((payload) => {
        if (!cancelled) setPracticeScenarios(payload.scenarios);
      })
      .catch((reason) => {
        if (!cancelled) toast.error(reason instanceof Error ? reason.message : "Practice-scenario's laden is mislukt.");
      })
      .finally(() => {
        if (!cancelled) setPracticeLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const busy = data?.items.some((item) => item.status === "running" || item.status === "busy") ?? false;
    const intervalMs = busy ? 1_500 : 4_000;
    const timer = window.setInterval(() => void refresh(true), intervalMs);
    return () => window.clearInterval(timer);
  }, [data?.summary.running, data?.items, refresh]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setDetailLoading(true);
      void hadesApi.agent(selectedId)
        .then((item) => {
          if (!cancelled) setDetail(item);
        })
        .catch(() => {
          if (!cancelled) setDetail(data?.items.find((item) => item.id === selectedId) ?? null);
        })
        .finally(() => {
          if (!cancelled) setDetailLoading(false);
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [selectedId, data?.summary.running, data?.items]);

  const agents = data?.items ?? [];
  const roles = useMemo(() => [...new Set(agents.map((item) => item.role).filter(Boolean))].sort(), [agents]);
  const providers = useMemo(() => [...new Set(agents.map((item) => item.provider || "").filter(Boolean))].sort(), [agents]);
  const models = useMemo(() => [...new Set(agents.map((item) => item.model || "").filter(Boolean))].sort(), [agents]);

  const visible = useMemo(
    () => sortAgents(
      filterAgents(agents, { query, status, role, provider, model, activeOnly, errorOnly }),
      sortKey,
      sortDir,
    ),
    [activeOnly, agents, errorOnly, model, provider, query, role, sortDir, sortKey, status],
  );

  const selected = detail ?? agents.find((item) => item.id === selectedId) ?? null;
  const summary = data?.summary;

  const toggleSort = (key: AgentSortKey) => {
    if (sortKey === key) setSortDir((current) => (current === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "name" || key === "status" ? "asc" : "desc");
    }
  };

  const runPractice = async (scenarioId: string) => {
    if (practiceRunning) return;
    setPracticeRunning(scenarioId);
    try {
      const result = await hadesApi.practiceRun(scenarioId);
      setPracticeResults((current) => ({ ...current, [result.scenario_id]: result }));
      if (result.passed) toast.success(`Scenario ${result.scenario_id} geslaagd.`);
      else toast.error(`Scenario ${result.scenario_id} mislukt.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : `Scenario ${scenarioId} uitvoeren is mislukt.`);
    } finally {
      setPracticeRunning(null);
    }
  };

  const runAllPractice = async () => {
    if (practiceRunning) return;
    setPracticeRunning("all");
    try {
      const payload = await hadesApi.practiceRunAll();
      const next: Record<string, PracticeResult> = {};
      for (const item of payload.results) {
        const scenarioId = String(item.scenario_id ?? "");
        if (!scenarioId) continue;
        next[scenarioId] = {
          scenario_id: scenarioId,
          passed: Boolean(item.passed),
          trace: (item.trace as Record<string, unknown>) ?? {},
          notes: Array.isArray(item.notes) ? item.notes.map(String) : [],
        };
      }
      setPracticeResults((current) => ({ ...current, ...next }));
      if (payload.passed) toast.success(`Alle ${payload.summary.total ?? payload.results.length} scenario's geslaagd.`);
      else toast.error(`${payload.summary.failed ?? 0} scenario('s) mislukt.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Alle scenario's uitvoeren is mislukt.");
    } finally {
      setPracticeRunning(null);
    }
  };

  const mutate = async (action: AgentMutationAction) => {
    if (!selected) return;
    if (action === "refresh") {
      await refresh();
      return;
    }
    if (mutating) return;
    if (action === "cancel" && !window.confirm(`Huidige run(s) voor ${selected.name} annuleren?`)) return;
    if (action === "disable" && !window.confirm(`${selected.name} uitschakelen?`)) return;
    setMutating(action);
    try {
      if (action === "enable") await hadesApi.setAgentState(selected.id, true);
      if (action === "disable") await hadesApi.setAgentState(selected.id, false);
      if (action === "cancel") {
        const result = await hadesApi.cancelAgentCurrent(selected.id);
        if (result.cancelled_task_ids.length) {
          toast.success(`${result.cancelled_task_ids.length} taak(en) geannuleerd.`);
        } else {
          toast.message("Geen actieve run om te annuleren.");
        }
      }
      await refresh(true);
      const fresh = await hadesApi.agent(selected.id).catch(() => null);
      if (fresh) setDetail(fresh);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Actie mislukt.");
    } finally {
      setMutating(null);
    }
  };

  return (
    <div className="page page-agents">
      <PageHeader
        title="Agents"
        description="Operationeel overzicht van alle HADES-specialisten: status, runs, usage en hiërarchie. (*) = nog niet geïmplementeerd."
        actions={
          <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
            {loading ? <Loader2 className="spin" /> : <RefreshCcw />}
            Vernieuwen
          </Button>
        }
      />

      {error ? (
        <div className="inline-error" role="alert">
          <AlertTriangle />
          <span>
            <strong>Agents-console niet beschikbaar.</strong> {error}
            <Button size="sm" variant="outline" className="ml-2" onClick={() => void refresh()}>Opnieuw proberen</Button>
          </span>
        </div>
      ) : null}

      <AgentsSummary summary={summary} />

      <AgentsList
        agents={agents}
        visibleAgents={visible}
        selectedId={selected?.id}
        loading={loading}
        hasError={Boolean(error)}
        onSelect={setSelectedId}
        onSort={toggleSort}
        toolbar={
          <AgentsToolbar
            query={query}
            status={status}
            role={role}
            provider={provider}
            model={model}
            activeOnly={activeOnly}
            errorOnly={errorOnly}
            roles={roles}
            providers={providers}
            models={models}
            onQueryChange={setQuery}
            onStatusChange={setStatus}
            onRoleChange={setRole}
            onProviderChange={setProvider}
            onModelChange={setModel}
            onActiveOnlyChange={setActiveOnly}
            onErrorOnlyChange={setErrorOnly}
          />
        }
      />

      <section className="mt-3 grid gap-3 xl:grid-cols-[1.55fr_1fr_1.1fr]">
        <AgentDetailPanel
          selected={selected}
          detailLoading={detailLoading}
          mutating={mutating}
          onMutate={(action) => void mutate(action)}
          onSelect={setSelectedId}
        />
        <AgentUsagePanel selected={selected} />
        <AgentsActivityPanel
          activity={data?.activity || []}
          selected={selected}
          onSelect={setSelectedId}
        />
      </section>

      <SpecialistContractsPanel
        specialists={specialists}
        loading={specialistsLoading}
        error={specialistsError}
      />

      <AgentPracticePanel
        scenarios={practiceScenarios}
        results={practiceResults}
        loading={practiceLoading}
        running={practiceRunning}
        onRun={(scenarioId) => void runPractice(scenarioId)}
        onRunAll={() => void runAllPractice()}
      />
    </div>
  );
}
