"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, TerminalSquare, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/hades/ui";
import { hadesApi, PluginEvent } from "@/lib/hades-api";
import { PLUGIN_DEPENDENCY_POLL_MS } from "@/lib/ui-poll-intervals";
import { PluginsPage as PluginsPageCore } from "./plugins-page-core";

type RepairResult = Awaited<ReturnType<typeof hadesApi.repairPlugin>>;
type RepairMonitorState = {
  pluginId: string;
  running: boolean;
  startedAt: number;
  finishedAt: number | null;
  output: string;
  error: string | null;
};
type RepairMonitorBus = {
  installed: boolean;
  state: RepairMonitorState | null;
  listeners: Set<() => void>;
};
type InstrumentedApi = typeof hadesApi & { __pluginRepairMonitorBus?: RepairMonitorBus };

const instrumentedApi = hadesApi as InstrumentedApi;
const repairBus: RepairMonitorBus = instrumentedApi.__pluginRepairMonitorBus ?? {
  installed: false,
  state: null,
  listeners: new Set<() => void>(),
};
instrumentedApi.__pluginRepairMonitorBus = repairBus;

function notifyRepairMonitor() {
  for (const listener of repairBus.listeners) listener();
}

function dependencyResultOutput(result: RepairResult): string {
  const dependencies = result.dependencies as {
    logs?: Array<{ stdout?: unknown; stderr?: unknown; error?: unknown; command?: unknown }>;
    error?: unknown;
  };
  const chunks: string[] = [];
  for (const entry of dependencies.logs ?? []) {
    if (Array.isArray(entry.command)) chunks.push(`$ ${entry.command.map(String).join(" ")}`);
    if (typeof entry.stdout === "string" && entry.stdout.trim()) chunks.push(entry.stdout.trim());
    if (typeof entry.stderr === "string" && entry.stderr.trim()) chunks.push(entry.stderr.trim());
    if (typeof entry.error === "string" && entry.error.trim()) chunks.push(`ERROR: ${entry.error.trim()}`);
  }
  if (typeof dependencies.error === "string" && dependencies.error.trim()) chunks.push(`ERROR: ${dependencies.error.trim()}`);
  return chunks.join("\n").slice(-20_000);
}

if (!repairBus.installed) {
  const originalRepairPlugin = hadesApi.repairPlugin.bind(hadesApi);
  instrumentedApi.repairPlugin = async (pluginId: string) => {
    if (repairBus.state?.running) {
      throw new Error(`Dependency-repair draait al voor plugin '${repairBus.state.pluginId}'.`);
    }
    repairBus.state = {
      pluginId,
      running: true,
      startedAt: Date.now(),
      finishedAt: null,
      output: "",
      error: null,
    };
    notifyRepairMonitor();
    try {
      const result = await originalRepairPlugin(pluginId);
      const current = repairBus.state;
      if (current) {
        repairBus.state = {
          ...current,
          pluginId,
          running: false,
          finishedAt: Date.now(),
          output: dependencyResultOutput(result),
          error: typeof result.dependencies.error === "string" ? result.dependencies.error : null,
        };
      }
      notifyRepairMonitor();
      return result;
    } catch (reason) {
      const current = repairBus.state;
      if (current) {
        repairBus.state = {
          ...current,
          pluginId,
          running: false,
          finishedAt: Date.now(),
          error: reason instanceof Error ? reason.message : "Dependency-repair is mislukt.",
        };
      }
      notifyRepairMonitor();
      throw reason;
    }
  };
  repairBus.installed = true;
}

function DependencyRepairMonitor() {
  const [state, setState] = useState<RepairMonitorState | null>(repairBus.state);
  const [events, setEvents] = useState<PluginEvent[]>([]);
  const [pluginName, setPluginName] = useState("");
  const [now, setNow] = useState(Date.now());
  const [dismissedRun, setDismissedRun] = useState<number | null>(null);

  useEffect(() => {
    const listener = () => {
      setState(repairBus.state ? { ...repairBus.state } : null);
      setDismissedRun(null);
    };
    repairBus.listeners.add(listener);
    return () => { repairBus.listeners.delete(listener); };
  }, []);

  useEffect(() => {
    if (!state?.pluginId) {
      setEvents([]);
      setPluginName("");
      return;
    }
    let cancelled = false;
    const refresh = async () => {
      try {
        const [nextEvents, pluginResult] = await Promise.all([
          hadesApi.pluginEvents(state.pluginId),
          hadesApi.plugins(),
        ]);
        if (cancelled) return;
        setEvents(nextEvents);
        setPluginName(pluginResult.plugins.find((item) => item.id === state.pluginId)?.name ?? state.pluginId);
      } catch {
        // The repair request itself remains authoritative; monitoring must never abort it.
      }
    };
    void refresh();
    if (!state.running) return () => { cancelled = true; };
    const timer = window.setInterval(() => void refresh(), PLUGIN_DEPENDENCY_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [state?.pluginId, state?.running]);

  useEffect(() => {
    if (!state?.running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state?.running]);

  const dependencyEvents = useMemo(
    () => events.filter((event) => event.message.toLowerCase().includes("dependency")).slice(-18),
    [events],
  );

  if (!state || dismissedRun === state.startedAt) return null;
  const elapsedMs = (state.finishedAt ?? now) - state.startedAt;
  const elapsedSeconds = Math.max(0, Math.round(elapsedMs / 1000));
  const tone = state.running ? "info" : state.error ? "danger" : "success";

  return (
    <aside className="fixed bottom-4 right-4 z-[80] w-[min(760px,calc(100vw-2rem))] rounded-xl border bg-background/95 p-4 shadow-2xl backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 rounded-md border p-2">{state.running ? <Loader2 className="h-4 w-4 animate-spin" /> : state.error ? <TriangleAlert className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}</span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><strong>Dependency-installatie</strong><StatusBadge tone={tone}>{state.running ? "bezig" : state.error ? "mislukt" : "gereed"}</StatusBadge></div>
            <p className="mt-1 truncate text-sm text-muted-foreground">{pluginName || state.pluginId} · {elapsedSeconds}s · gevoelige sleutelpatronen worden geredigeerd</p>
          </div>
        </div>
        {!state.running ? <Button variant="ghost" size="icon" aria-label="Dependency-monitor sluiten" onClick={() => setDismissedRun(state.startedAt)}><X /></Button> : null}
      </div>

      <div className="mt-3 max-h-64 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
        {dependencyEvents.length ? dependencyEvents.map((event) => <div key={event.id} className="break-words"><span className="text-muted-foreground">[{new Date(event.created_at).toLocaleTimeString("nl-NL")}]</span> {event.message}</div>) : <div className="text-muted-foreground">Wachten op dependency-output…</div>}
        {!state.running && state.output ? <><div className="my-2 border-t" /><pre className="whitespace-pre-wrap break-words">{state.output}</pre></> : null}
        {state.error ? <div className="mt-2 break-words text-destructive">{state.error}</div> : null}
      </div>

      {state.running ? <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><TerminalSquare className="h-4 w-4" />Deze monitor ververst bounded terwijl de installatie loopt; de volledige uitvoer blijft in de persistente dependency-toolcall staan.</div> : null}
    </aside>
  );
}

export function PluginsPage() {
  return (
    <>
      <PluginsPageCore />
      <DependencyRepairMonitor />
    </>
  );
}
