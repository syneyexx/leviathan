"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Clock3, GitBranch, Loader2, Mic, PlayCircle, Plus, RefreshCcw, RotateCcw, Search, ShieldCheck, StopCircle, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { PageHeader, Panel, StatCard, StatusBadge } from "@/components/hades/ui";
import { ExecutionCompletionBanner } from "@/components/hades/execution-completion-banner";
import { assessTaskCompletion, mentionsSelfCorrection } from "@/lib/execution-completion";
import { formatDate, hadesApi, HadesAgent, HadesTask, LmModel, TaskEvent, WorkStep, WorkSummary } from "@/lib/hades-api";
import { readHashQuery, readHashSelection } from "@/lib/hash-query";
import { TASKS_ACTIVE_POLL_MS } from "@/lib/ui-poll-intervals";

function readVoiceQueryFlag(): boolean {
  if (typeof window === "undefined") return false;
  const params = readHashQuery();
  const raw = (params.get("voice") || "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes";
}

const statusCopy: Record<HadesTask["status"], string> = {
  queued: "In wachtrij",
  running: "Actief",
  completed: "Voltooid",
  failed: "Mislukt",
  cancelled: "Geannuleerd",
  blocked: "Geblokkeerd",
};
const priorityCopy = { low: "Laag", normal: "Normaal", high: "Hoog" } as const;

const workStatusCopy: Record<string, string> = {
  queued: "In wachtrij",
  running: "Actief",
  completed: "Voltooid",
  failed: "Mislukt",
  cancelled: "Geannuleerd",
};

function taskControlState(task: HadesTask | null | undefined): string {
  const raw = (task as { control_state?: string } | null | undefined)?.control_state;
  return String(raw || "active").toLowerCase();
}

function taskIsPaused(task: HadesTask | null | undefined): boolean {
  const cs = taskControlState(task);
  return cs === "paused" || cs === "pause_requested";
}

function taskStatusLabel(task: HadesTask): string {
  if (task.status === "running" && taskIsPaused(task)) {
    return taskControlState(task) === "pause_requested" ? "Pauze aangevraagd" : "Gepauzeerd";
  }
  return statusCopy[task.status] || task.status;
}

function resolveWorkStep(stepId: string, steps: WorkStep[]): WorkStep | undefined {
  return steps.find((step) => step.step_key === stepId || step.id === stepId);
}

export function TasksPage() {
  const [tasks, setTasks] = useState<HadesTask[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [work, setWork] = useState<WorkSummary | null>(null);
  const [models, setModels] = useState<LmModel[]>([]);
  const [agents, setAgents] = useState<HadesAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ title: "", prompt: "", agent: "auto", priority: "normal" as HadesTask["priority"], model_id: "", auto_start: true, schedule_enabled: false, frequency: "once", run_at: "", timezone: "UTC" });
  const [inbox, setInbox] = useState<Array<Record<string, unknown>>>([]);
  const [approvals, setApprovals] = useState<Array<Record<string, unknown>>>([]);
  const [approvalsError, setApprovalsError] = useState<string | null>(null);
  const [detailLoadError, setDetailLoadError] = useState<string | null>(null);
  const [voiceTranscript, setVoiceTranscript] = useState("");
  const [voiceProposal, setVoiceProposal] = useState<Record<string, unknown> | null>(null);
  const [voicePreviewing, setVoicePreviewing] = useState(false);
  const [voiceCreating, setVoiceCreating] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [voiceAutoStart, setVoiceAutoStart] = useState(false);
  const [voiceFocus, setVoiceFocus] = useState(false);
  const voicePanelRef = useRef<HTMLDivElement | null>(null);

  const selected = useMemo(() => tasks.find((item) => item.id === selectedId) ?? tasks[0], [tasks, selectedId]);
  const checkpointState = (work?.checkpoint as { state?: Record<string, unknown> } | null)?.state;
  const taskCompletion = useMemo(
    () => (selected
      ? assessTaskCompletion({
        status: selected.status,
        error: selected.error,
        checkpointPhase: String(checkpointState?.phase || ""),
        acceptance_checklist: Array.isArray(checkpointState?.acceptance_checklist)
          ? (checkpointState?.acceptance_checklist as Array<Record<string, unknown>>)
          : undefined,
      })
      : null),
    [selected, checkpointState],
  );
  const confirmedOutcome = useMemo(() => {
    const raw = (work as { confirmed_outcome?: Record<string, unknown> } | null)?.confirmed_outcome
      || (selected as { confirmed_outcome?: Record<string, unknown> } | undefined)?.confirmed_outcome;
    return raw && typeof raw === "object" ? raw : null;
  }, [work, selected]);
  const checkpointResumeAvailable = Boolean(
    (work?.checkpoint || (work?.steps?.length ?? 0) > 0)
    && selected
    && ["queued", "failed", "cancelled", "completed"].includes(selected.status),
  );
  const stepById = useMemo(() => {
    const map = new Map<string, WorkStep>();
    for (const step of work?.steps ?? []) {
      map.set(step.id, step);
      if (step.step_key) map.set(step.step_key, step);
    }
    return map;
  }, [work?.steps]);
  const counts = useMemo(() => ({
    queued: tasks.filter((item) => item.status === "queued").length,
    running: tasks.filter((item) => item.status === "running").length,
    completed: tasks.filter((item) => item.status === "completed").length,
    failed: tasks.filter((item) => item.status === "failed").length,
  }), [tasks]);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const items = await hadesApi.tasks();
      setTasks(items);
      const deeplinkId = readHashSelection(["t", "id"]);
      setSelectedId((current) => {
        const preferred = deeplinkId && items.some((item) => item.id === deeplinkId) ? deeplinkId : current;
        return items.some((item) => item.id === preferred) ? preferred : items[0]?.id ?? "";
      });
    } catch (reason) {
      if (!quiet) toast.error(reason instanceof Error ? reason.message : "Taken laden is mislukt.");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const applyDeeplink = () => {
      const deeplinkId = readHashSelection(["t", "id"]);
      if (!deeplinkId) return;
      setSelectedId((current) => (tasks.some((item) => item.id === deeplinkId) ? deeplinkId : current));
    };
    applyDeeplink();
    window.addEventListener("hashchange", applyDeeplink);
    window.addEventListener("popstate", applyDeeplink);
    return () => {
      window.removeEventListener("hashchange", applyDeeplink);
      window.removeEventListener("popstate", applyDeeplink);
    };
  }, [tasks]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void Promise.all([
        refresh(),
        hadesApi.models().then((data) => setModels(data.models)).catch(() => undefined),
        hadesApi.agents().then((data) => setAgents(data.items)).catch(() => undefined),
        hadesApi.inbox().then((items) => {
          setInbox(items as Array<Record<string, unknown>>);
          setApprovalsError(null);
        }).catch((reason: Error) => {
          setApprovalsError(reason.message || "Inbox laden mislukt.");
        }),
        hadesApi.approvals().then((items) => {
          setApprovals(items as Array<Record<string, unknown>>);
          setApprovalsError(null);
        }).catch((reason: Error) => {
          setApprovalsError(reason.message || "Goedkeuringen laden mislukt.");
        }),
      ]);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    const syncVoiceFocus = () => {
      const active = readVoiceQueryFlag();
      setVoiceFocus(active);
      if (!active) return;
      window.setTimeout(() => {
        voicePanelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        voicePanelRef.current?.querySelector("textarea")?.focus();
      }, 80);
    };
    syncVoiceFocus();
    window.addEventListener("hashchange", syncVoiceFocus);
    return () => window.removeEventListener("hashchange", syncVoiceFocus);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!selected?.id) { setEvents([]); setWork(null); setDetailLoadError(null); return; }
      void Promise.all([
        hadesApi.taskEvents(selected.id).then((items) => {
          setEvents(items);
          setDetailLoadError(null);
        }).catch((reason: Error) => {
          setDetailLoadError(reason.message || "Uitvoeringslog laden mislukt.");
        }),
        hadesApi.taskWork(selected.id).then((summary) => {
          setWork(summary);
          setDetailLoadError(null);
        }).catch((reason: Error) => {
          setDetailLoadError(reason.message || "Work-runtime laden mislukt.");
        }),
      ]);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selected?.id, selected?.status]);

  useEffect(() => {
    if (!tasks.some((item) => item.status === "running" || item.status === "queued")) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void refresh(true);
    }, TASKS_ACTIVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, tasks]);

  // Browser refresh / tab focus: reconnect to live Work Runtime state (no stale "bezig").
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      void refresh(true);
    };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  const createTask = async () => {
    if (!form.title.trim() || !form.prompt.trim()) return;
    setSaving(true);
    try {
      const schedule = form.schedule_enabled ? {
        frequency: form.frequency,
        timezone: form.timezone,
        run_at: form.run_at || undefined,
        enabled: true,
      } : undefined;
      const item = await hadesApi.createTask({
        title: form.title,
        prompt: form.prompt,
        agent: form.agent,
        priority: form.priority,
        model_id: form.model_id || undefined,
        auto_start: form.schedule_enabled ? false : form.auto_start,
        schedule,
      } as Parameters<typeof hadesApi.createTask>[0] & { schedule?: Record<string, unknown> });
      if (form.schedule_enabled && form.run_at) {
        await hadesApi.scheduleTask(item.id, {
          frequency: form.frequency,
          timezone: form.timezone,
          run_at: form.run_at,
          enabled: true,
        });
      }
      setDialogOpen(false);
      setForm({ title: "", prompt: "", agent: "auto", priority: "normal", model_id: "", auto_start: true, schedule_enabled: false, frequency: "once", run_at: "", timezone: "UTC" });
      setSelectedId(item.id);
      await refresh(true);
      const status = String(item.status || "");
      if (form.schedule_enabled) {
        toast.success("Geplande taak opgeslagen (draait alleen terwijl HADES actief is).");
      } else if (["failed", "cancelled", "error", "blocked"].includes(status)) {
        toast.error(`Taak eindigde in status: ${status}.`);
      } else if (form.auto_start && ["running", "queued", "pending"].includes(status)) {
        toast.success(status === "running" ? "Taak gestart." : "Taak toegevoegd aan de wachtrij.");
      } else if (form.auto_start) {
        toast.message(`Taak aangemaakt (status: ${status || "onbekend"}).`);
      } else {
        toast.success("Taak toegevoegd aan de wachtrij.");
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Taak maken is mislukt.");
    } finally {
      setSaving(false);
    }
  };

  const act = async (action: "run" | "cancel" | "retry" | "pause" | "resume" | "resume-checkpoint") => {
    if (!selected) return;
    try {
      if (action === "run") await hadesApi.runTask(selected.id);
      if (action === "cancel") await hadesApi.cancelTask(selected.id);
      if (action === "retry") await hadesApi.retryTask(selected.id);
      if (action === "resume-checkpoint") {
        await hadesApi.resumeTaskCheckpoint(selected.id);
        toast.success("Hervatten vanaf checkpoint — voltooide stappen behouden.");
      }
      if (action === "pause") await hadesApi.controlTask(selected.id, { action: "pause" });
      if (action === "resume") await hadesApi.controlTask(selected.id, { action: "resume" });
      await refresh(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Actie is mislukt.");
    }
  };

  const redirectTask = async () => {
    if (!selected) return;
    const instruction = window.prompt("Vervolginstructie voor deze taak:");
    if (!instruction?.trim()) return;
    try {
      await hadesApi.controlTask(selected.id, { action: "redirect", instruction: instruction.trim() });
      toast.success("Bijsturing opgeslagen.");
      await refresh(true);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Bijsturen mislukt.");
    }
  };

  const previewVoiceTask = async () => {
    const transcript = voiceTranscript.trim();
    if (!transcript) {
      setVoiceError("Plak een transcript of STT-uitvoer.");
      return;
    }
    setVoicePreviewing(true);
    setVoiceError(null);
    try {
      const result = await hadesApi.voiceToTask({ transcript, create: false });
      setVoiceProposal(result.proposal ?? null);
    } catch (reason) {
      setVoiceProposal(null);
      setVoiceError(reason instanceof Error ? reason.message : "Voorvertoning mislukt.");
    } finally {
      setVoicePreviewing(false);
    }
  };

  const createVoiceTask = async () => {
    const transcript = voiceTranscript.trim();
    if (!transcript) {
      setVoiceError("Plak een transcript of STT-uitvoer.");
      return;
    }
    setVoiceCreating(true);
    setVoiceError(null);
    try {
      const result = await hadesApi.voiceToTask({ transcript, create: true, auto_start: voiceAutoStart });
      setVoiceProposal(result.proposal ?? null);
      if (result.task?.id) {
        setSelectedId(result.task.id);
        await refresh(true);
        const started = Boolean(result.started);
        toast.success(
          started
            ? "Taak aangemaakt en gestart uit transcript."
            : voiceAutoStart
              ? "Taak aangemaakt; start stond aan maar planner was niet beschikbaar — staat in wachtrij."
              : "Taak aangemaakt uit transcript.",
        );
      } else {
        toast.message("Geen taak aangemaakt — controleer het voorstel.");
      }
    } catch (reason) {
      setVoiceError(reason instanceof Error ? reason.message : "Taak aanmaken mislukt.");
    } finally {
      setVoiceCreating(false);
    }
  };

  return (
    <div className="page page-tasks">
      <PageHeader title="Taken" description="Maak lokale LLM-taken, volg de wachtrij en bewaar ieder resultaat." actions={
        <><Button variant="outline" onClick={() => refresh()}><RefreshCcw />Vernieuwen</Button><Dialog open={dialogOpen} onOpenChange={setDialogOpen}><DialogTrigger asChild><Button><Plus />Nieuwe taak</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Nieuwe lokale taak</DialogTitle><DialogDescription>De taak wordt persistent opgeslagen, op prioriteit ingepland en naar een passende specialist gerouteerd.</DialogDescription></DialogHeader><div className="dialog-form"><label><span>Naam</span><Input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="Bijvoorbeeld: Vat projectnotities samen" /></label><label><span>Instructie</span><Textarea value={form.prompt} onChange={(event) => setForm({ ...form, prompt: event.target.value })} placeholder="Beschrijf precies wat het model moet opleveren…" /></label><div className="form-grid two"><label><span>Specialist</span><Select value={form.agent} onValueChange={(value) => setForm({ ...form, agent: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="auto">Automatisch routeren</SelectItem>{agents.filter((agent) => agent.enabled).map((agent) => <SelectItem key={agent.id} value={agent.id}>{agent.name}</SelectItem>)}</SelectContent></Select></label><label><span>Prioriteit</span><Select value={form.priority} onValueChange={(value: HadesTask["priority"]) => setForm({ ...form, priority: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="low">Laag</SelectItem><SelectItem value="normal">Normaal</SelectItem><SelectItem value="high">Hoog</SelectItem></SelectContent></Select></label></div><label><span>Model</span><Select value={form.model_id || "active"} onValueChange={(value) => setForm({ ...form, model_id: value === "active" ? "" : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">Actief model</SelectItem>{models.map((model) => <SelectItem key={model.id} value={model.id}>{model.id}</SelectItem>)}</SelectContent></Select></label><label className="inline-toggle"><span><strong>Direct starten</strong><small>Anders blijft de taak in de wachtrij.</small></span><Switch checked={form.auto_start} onCheckedChange={(checked) => setForm({ ...form, auto_start: checked })} /></label>
<label className="inline-toggle"><span><strong>Plan lokale uitvoering</strong><small>Alleen terwijl de HADES-backend draait. Geen cloudplanning.</small></span><Switch checked={form.schedule_enabled} onCheckedChange={(checked) => setForm({ ...form, schedule_enabled: checked, auto_start: checked ? false : form.auto_start })} /></label>
{form.schedule_enabled ? <div className="form-grid two"><label><span>Frequentie</span><Select value={form.frequency} onValueChange={(value) => setForm({ ...form, frequency: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="once">Eenmalig</SelectItem><SelectItem value="daily">Dagelijks</SelectItem><SelectItem value="weekly">Wekelijks</SelectItem></SelectContent></Select></label><label><span>Tijdzone</span><Input value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })} /></label><label><span>Eerste uitvoering (ISO)</span><Input value={form.run_at} onChange={(event) => setForm({ ...form, run_at: event.target.value })} placeholder="2026-09-08T09:00:00+00:00" /></label></div> : null}
</div><DialogFooter><Button variant="outline" onClick={() => setDialogOpen(false)}>Annuleren</Button><Button onClick={createTask} disabled={saving || !form.title.trim() || !form.prompt.trim()}>{saving ? <Loader2 className="spin" /> : <PlayCircle />}Taak maken</Button></DialogFooter></DialogContent></Dialog></>
      } />

      <section className="stat-grid four"><StatCard label="In wachtrij" value={String(counts.queued)} note="Wacht op capaciteit" icon={<Clock3 />} /><StatCard label="Actief" value={String(counts.running)} note="Lokale uitvoering" icon={<Activity />} /><StatCard label="Voltooid" value={String(counts.completed)} note="Persistent bewaard" icon={<CheckCircle2 />} /><StatCard label="Mislukt" value={String(counts.failed)} note="Opnieuw uitvoerbaar" icon={<XCircle />} /></section>

      <div className="split-layout task-split">
        <Panel title="Taakwachtrij" actions={loading ? <Loader2 className="spin muted-icon" /> : <StatusBadge>{tasks.length} taken</StatusBadge>}>
          <div className="table-scroll"><table className="data-table"><thead><tr><th>Naam</th><th>Agent</th><th>Prioriteit</th><th>Status</th><th>Aangemaakt</th><th>Voortgang</th></tr></thead><tbody>{tasks.map((task) => <tr key={task.id} className={task.id === selected?.id ? "selected-row clickable-row" : "clickable-row"} onClick={() => setSelectedId(task.id)}><td><strong>{task.title}</strong><small>{task.model_id || "Actief model"}</small></td><td>{task.agent}</td><td><StatusBadge tone={task.priority === "high" ? "danger" : task.priority === "low" ? "success" : "warning"}>{priorityCopy[task.priority]}</StatusBadge></td><td><StatusBadge tone={task.status === "completed" ? "success" : task.status === "failed" || task.status === "blocked" ? "danger" : task.status === "running" && taskIsPaused(task) ? "warning" : task.status === "running" ? "info" : "warning"}>{taskStatusLabel(task)}</StatusBadge></td><td>{formatDate(task.created_at)}</td><td><Progress value={task.progress} /><small>{task.progress}%</small></td></tr>)}</tbody></table>{!tasks.length && !loading ? <div className="table-empty">Nog geen taken. Maak je eerste lokale taak aan.</div> : null}</div>
          <div className="table-footer"><span>{tasks.length} lokale taken</span><span>Resultaten blijven na een herstart beschikbaar</span></div>
        </Panel>

        <div className="details-stack">
          <Panel title={selected?.title ?? "Geen taak geselecteerd"} actions={selected ? <StatusBadge tone={selected.status === "completed" ? "success" : selected.status === "failed" || selected.status === "blocked" ? "danger" : selected.status === "running" && taskIsPaused(selected) ? "warning" : "info"}>{taskStatusLabel(selected)}</StatusBadge> : null}>
            {selected ? <><ExecutionCompletionBanner assessment={taskCompletion} />{confirmedOutcome ? <p className="muted">Bevestigde uitkomst (Mission Control/Tasks): {String(confirmedOutcome.status || "")}{confirmedOutcome.confirmed ? " · confirmed" : " · unconfirmed"}{confirmedOutcome.source ? ` · ${String(confirmedOutcome.source)}` : ""}</p> : null}<div className="detail-section"><span className="eyebrow">Instructie</span><p>{selected.prompt}</p></div><div className="mini-grid"><div><span>Agent</span><strong>{selected.agent}</strong><small>Lokale runtime</small></div><div><span>Model</span><strong>{selected.model_id || "Actief model"}</strong><small>{priorityCopy[selected.priority]} prioriteit</small></div></div>
            <div className="detail-section flight-timeline-hook">
              <span className="eyebrow">Flight / timeline</span>
              <p className="muted">
                Run-id: <code>{selected.id}</code>
                {" · "}
                <a href={`#/mission-control?flight=${encodeURIComponent(selected.id)}`}>Open timeline in Mission Control</a>
                {" · "}
                <button
                  type="button"
                  className="linkish"
                  onClick={() => {
                    void hadesApi.runEvents(selected.id).then((payload) => {
                      const lines = (payload.events || []).slice(-12).map((ev) => {
                        const t = String(ev.type || ev.event_type || "event");
                        const seq = ev.sequence != null ? `#${String(ev.sequence)}` : "";
                        return `[${t}${seq}]`;
                      });
                      toast.message(lines.length ? `Run-events: ${lines.join(" ")}` : "Geen run-events voor deze taak.");
                    }).catch(() => toast.error("Run-events niet beschikbaar."));
                  }}
                >
                  Toon recente run-events
                </button>
              </p>
            </div>
            <div className="detail-section"><div className="progress-copy"><span>Voortgang</span><strong>{selected.progress}%</strong></div><Progress value={selected.progress} /></div>{selected.result ? <div className="task-result"><span className="eyebrow">Resultaat</span><p>{selected.result}</p></div> : null}{selected.error ? <div className="inline-error"><XCircle />{selected.error}</div> : null}<div className="button-row">{selected.status === "queued" ? <Button onClick={() => act("run")}><PlayCircle />Starten</Button> : null}{selected.status === "running" && !taskIsPaused(selected) ? <Button variant="outline" onClick={() => act("pause")}>Pauzeren</Button> : null}{selected.status === "running" && taskIsPaused(selected) ? <Button variant="outline" onClick={() => act("resume")}>Hervatten</Button> : null}{checkpointResumeAvailable ? <Button variant="outline" onClick={() => act("resume-checkpoint")}><Clock3 />Hervat checkpoint</Button> : null}{selected.status === "running" || selected.status === "queued" ? <Button variant="outline" onClick={() => redirectTask()}>Bijsturen</Button> : null}{selected.status === "queued" || selected.status === "running" ? <Button variant="destructive" onClick={() => act("cancel")}><StopCircle />Annuleren</Button> : null}{["failed", "cancelled", "completed"].includes(selected.status) ? <Button variant="outline" onClick={() => act("retry")}><RotateCcw />Opnieuw uitvoeren</Button> : null}</div></> : <p className="empty-copy">Selecteer of maak een taak.</p>}
          </Panel>
          <Panel title="Work Runtime" actions={<StatusBadge tone={work?.steps.some((step) => step.status === "failed") ? "danger" : work?.steps.length ? "info" : "neutral"}><GitBranch />{work?.steps.length ?? 0} stappen</StatusBadge>}>
            {work?.steps.length ? <div className="work-step-list">{work.steps.map((step) => {
              const selfCorrection = mentionsSelfCorrection(`${step.title} ${step.instruction} ${step.output || ""} ${step.error || ""}`);
              return <div className={selfCorrection ? "work-step self-correction-highlight" : "work-step"} key={step.id}>
              <div className="work-step-head"><span className={`work-step-index status-${step.status === "completed" ? "success" : step.status === "failed" ? "danger" : step.status === "running" ? "info" : "neutral"}`}>{step.step_index + 1}</span><div><strong>{step.title}</strong><small>{step.agent_id} · {step.kind}</small></div><StatusBadge tone={step.status === "completed" ? "success" : step.status === "failed" ? "danger" : step.status === "running" ? "info" : "neutral"}>{step.status}</StatusBadge></div>
              {selfCorrection ? <div className="self-correction-tag"><RotateCcw />Herplanning / retry gedetecteerd</div> : null}
              <p>{step.instruction}</p>
              {step.output ? <details><summary>Stapresultaat</summary><pre>{step.output}</pre></details> : null}
              {step.error ? <div className="inline-error"><XCircle />{step.error}</div> : null}
            </div>;
            })}</div> : <p className="empty-copy">Het plan verschijnt zodra de Work Planner de taak heeft ontleed.</p>}
            {work?.checkpoint ? (
              <div className="checkpoint-panel">
                <div className="checkpoint-panel-head">
                  <strong>Checkpoint</strong>
                  <StatusBadge tone="info"><Clock3 />{formatDate(work.checkpoint.created_at)}</StatusBadge>
                </div>
                <dl className="detail-list spaced">
                  <div><dt>ID</dt><dd><code>{work.checkpoint.id}</code></dd></div>
                  <div><dt>Aangemaakt</dt><dd>{formatDate(work.checkpoint.created_at)}</dd></div>
                  {Object.entries(work.checkpoint.state || {}).filter(([key]) => key !== "acceptance_checklist").map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
                    </div>
                  ))}
                </dl>
                {Array.isArray((work.checkpoint.state as Record<string, unknown> | undefined)?.acceptance_checklist) ? (
                  <div className="acceptance-checklist-panel">
                    <strong>Acceptatiechecklist</strong>
                    <ul className="acceptance-checklist">
                      {((work.checkpoint.state as Record<string, unknown>).acceptance_checklist as Array<Record<string, unknown>>).map((row) => (
                        <li key={String(row.criterion)} className={row.met ? "criterion-met" : "criterion-unmet"}>
                          <span aria-hidden>{row.met ? "✓" : "✗"}</span>
                          <span>
                            {String(row.criterion || "")}
                            {row.note ? <small> — {String(row.note)}</small> : null}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {checkpointResumeAvailable ? (
                  <p className="checkpoint-resume-hint">
                    <AlertTriangle />
                    Checkpoint/stappen aanwezig — gebruik <strong>Hervat checkpoint</strong> (voltooide stappen blijven behouden; Opnieuw wist het plan).
                  </p>
                ) : null}
              </div>
            ) : null}
          </Panel>
          {work?.waves?.length ? (
            <Panel
              title="Orchestratiebord"
              eyebrow="Parallelle uitvoeringsgolven"
              actions={
                <StatusBadge tone="info">
                  <GitBranch />
                  {work.waves.length} golf{work.waves.length === 1 ? "" : "en"}
                </StatusBadge>
              }
            >
              {Object.keys(work.counts).length ? (
                <div className="wave-budget-row">
                  {Object.entries(work.counts).map(([status, count]) => (
                    <div className="wave-budget-chip" key={status}>
                      <span>{workStatusCopy[status] ?? status}</span>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="wave-board">
                {work.waves.map((wave, waveIndex) => (
                  <div className="wave-column" key={`wave-${waveIndex}`}>
                    <div className="wave-column-head">
                      <strong>Golf {waveIndex + 1}</strong>
                      <small>{wave.length} stap{wave.length === 1 ? "" : "pen"}</small>
                    </div>
                    <div className="wave-step-list">
                      {wave.map((stepId) => {
                        const step = stepById.get(stepId) ?? resolveWorkStep(stepId, work.steps);
                        const tone = step?.status === "completed"
                          ? "success"
                          : step?.status === "failed"
                            ? "danger"
                            : step?.status === "running"
                              ? "info"
                              : "neutral";
                        return (
                          <div className="wave-step-card" key={`${waveIndex}-${stepId}`}>
                            <span className="wave-step-id">{stepId}</span>
                            <strong>{step?.title ?? stepId}</strong>
                            {step ? (
                              <StatusBadge tone={tone}>{step.status}</StatusBadge>
                            ) : (
                              <small className="text-muted-foreground">Nog niet in work-stappen</small>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
          <div ref={voicePanelRef} className={voiceFocus ? "voice-panel-focus" : undefined}>
          <Panel title="Spraak → taak" actions={<StatusBadge tone="info"><Mic />Plak / lokale STT</StatusBadge>}>
            <div className="form-stack compact-panel">
              <div className="security-note compact">
                <Mic />
                <span>
                  <strong>Ondersteund pad: plak / lokale STT</strong>
                  <small>
                    Dit Spraak→taak-pad doet zelf geen ASR en gebruikt geen cloud-STT. Plak transcript hier, via chat <code>/voice …</code>,
                    of plugin <code>local-stt-paste</code> (<code>transcribe_paste</code>) → <code>POST /api/voice/to-task</code>.
                    Ingebouwde microfoon-ASR zit in Chat → Spraak (`backend/voice`). Optioneel: VoiceStudio (Plugins) kan lokaal ASR/TTS draaien — plak die tekst hier.
                    Spraakherkenning is ook configureerbaar onder Instellingen → Spraak (paste / VoiceStudio STT); echo-guard blokkeert mic tijdens VoiceStudio-TTS.

                  </small>
                </span>
              </div>
              <label>
                <span>Transcript (lokale STT of handmatig — geen microfoon in HADES)</span>
                <Textarea
                  value={voiceTranscript}
                  onChange={(event) => {
                    setVoiceTranscript(event.target.value);
                    setVoiceError(null);
                  }}
                  rows={4}
                  placeholder="Plak hier output van lokale STT (OS-dictatie, Whisper, VoiceStudio, …)"
                />
              </label>
              <label className="inline-toggle">
                <span>
                  <strong>Direct starten</strong>
                  <small>Na aanmaken ook inplannen/starten (anders alleen wachtrij).</small>
                </span>
                <Switch checked={voiceAutoStart} onCheckedChange={setVoiceAutoStart} />
              </label>
              {voiceError ? <div className="inline-error"><XCircle />{voiceError}</div> : null}
              <div className="button-row">
                <Button size="sm" variant="outline" onClick={() => void previewVoiceTask()} disabled={voicePreviewing || !voiceTranscript.trim()}>
                  {voicePreviewing ? <Loader2 className="spin" /> : <Search />}
                  Voorvertoning
                </Button>
                <Button size="sm" onClick={() => void createVoiceTask()} disabled={voiceCreating || !voiceTranscript.trim()}>
                  {voiceCreating ? <Loader2 className="spin" /> : voiceAutoStart ? <PlayCircle /> : <Plus />}
                  {voiceAutoStart ? "Aanmaken & starten" : "Taak aanmaken"}
                </Button>
              </div>
              {voiceProposal ? (
                <dl className="detail-list spaced voice-proposal">
                  <div><dt>Titel</dt><dd>{String(voiceProposal.title ?? "—")}</dd></div>
                  <div><dt>Agent</dt><dd>{String(voiceProposal.agent ?? "auto")}</dd></div>
                  <div><dt>Prioriteit</dt><dd>{String(voiceProposal.priority ?? "normal")}</dd></div>
                  <div><dt>Bron</dt><dd>{String(voiceProposal.source ?? "voice_transcript")}</dd></div>
                  {Array.isArray(voiceProposal.acceptance_criteria) && voiceProposal.acceptance_criteria.length ? (
                    <div><dt>Acceptatie</dt><dd>{voiceProposal.acceptance_criteria.map(String).join(" · ")}</dd></div>
                  ) : null}
                  {voiceProposal.note ? <div><dt>Notitie</dt><dd>{String(voiceProposal.note)}</dd></div> : null}
                </dl>
              ) : (
                <p className="empty-copy">Geen voorstel — plak transcript en kies Voorvertoning.</p>
              )}
            </div>
          </Panel>
          </div>
          <Panel title="Uitvoeringslog" actions={<StatusBadge tone="success">Persistent</StatusBadge>}><div className="log-view">{detailLoadError ? <code className="inline-error">{detailLoadError}</code> : null}{events.length ? events.map((event) => {
            const highlight = mentionsSelfCorrection(event.message);
            return <code className={highlight ? "self-correction-log" : undefined} key={event.id}>[{formatDate(event.created_at)}] {event.message}</code>;
          }) : !detailLoadError ? <code>Nog geen logregels.</code> : null}</div></Panel>
          <Panel title="Inbox & aanvragen" actions={<StatusBadge>{inbox.filter((item) => item.status === "unread").length + approvals.length} open</StatusBadge>}>
            <div className="inbox-list">
              {approvalsError ? <p className="empty-copy inline-error">{approvalsError}</p> : null}
              {approvals.map((item) => (
                <div className="inbox-item" key={String(item.id)}>
                  <strong>{String(item.tool_name || item.kind)}</strong>
                  <small>{String(item.expected_effect || "")}</small>
                  <div className="button-row">
                    <Button size="sm" onClick={async () => {
                      try {
                        const decided = await hadesApi.decideApproval(String(item.id), true);
                        setApprovals(await hadesApi.approvals() as Array<Record<string, unknown>>);
                        if (decided.resume_ok === false) {
                          toast.error(decided.resume_error ? `Goedgekeurd, hervatten mislukt: ${decided.resume_error}` : "Goedgekeurd, maar hervatten is mislukt.");
                        } else {
                          toast.success(decided.resume_ok === true ? "Goedgekeurd en hervat." : "Goedgekeurd.");
                        }
                      } catch (reason) {
                        toast.error(reason instanceof Error ? reason.message : "Goedkeuren is mislukt.");
                      }
                    }}>Goedkeuren</Button>
                    <Button size="sm" variant="outline" onClick={async () => {
                      try {
                        await hadesApi.decideApproval(String(item.id), false);
                        setApprovals(await hadesApi.approvals() as Array<Record<string, unknown>>);
                        toast.success("Afgewezen.");
                      } catch (reason) {
                        toast.error(reason instanceof Error ? reason.message : "Afwijzen is mislukt.");
                      }
                    }}>Afwijzen</Button>
                  </div>
                </div>
              ))}
              {inbox.slice(0, 8).map((item) => (
                <button type="button" className="inbox-item" key={String(item.id)} onClick={async () => { await hadesApi.readInbox(String(item.id)); setInbox(await hadesApi.inbox() as Array<Record<string, unknown>>); }}>
                  <strong>{String(item.title)}</strong>
                  <small>{String(item.kind)} · {String(item.status)}</small>
                </button>
              ))}
              {!approvalsError && !approvals.length && !inbox.length ? <p className="empty-copy">Geen openstaande inbox-items.</p> : null}
            </div>
          </Panel>
          <Panel title="Uitvoeringsbeleid"><div className="policy-row"><ShieldCheck /><span><strong>Local-only taakrunner</strong><small>Deterministische services doen scans/indexing; LLM-agents doen planning en synthese. Tools blijven achter de Permission Engine en Ready-pluginstatus. Schema-toestemming is geen algemene goedkeuring voor side effects.</small></span></div></Panel>
        </div>
      </div>
    </div>
  );
}
