import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AgentDefinition, CapabilityListItem, TaskCreatePayload, WorkflowRecord } from "../../types/api";
import { IconClose } from "./TaskIcons";
import { errMsg } from "./taskUtils";

type Props = {
  open: boolean;
  busy?: boolean;
  agents: AgentDefinition[];
  onClose: () => void;
  onCreated: () => void;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
  defaultBoardColumn?: string;
};

const EMPTY: TaskCreatePayload = {
  title: "",
  description: "",
  priority: "medium",
  boardColumn: "backlog",
  tags: [],
  project: "",
  assigneeType: "none",
  executionBinding: "manual",
};

export function TaskCreateDialog({
  open,
  busy: parentBusy,
  agents,
  onClose,
  onCreated,
  onError,
  onSuccess,
  defaultBoardColumn = "backlog",
}: Props) {
  const [form, setForm] = useState<TaskCreatePayload>({ ...EMPTY, boardColumn: defaultBoardColumn });
  const [tagsText, setTagsText] = useState("");
  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadingOpts, setLoadingOpts] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingOpts(true);
    void (async () => {
      try {
        const [caps, wfs] = await Promise.all([
          api.listCapabilities({ limit: 200 }),
          api.listWorkflows(100),
        ]);
        if (cancelled) return;
        setCapabilities(caps.capabilities ?? []);
        setWorkflows(wfs.workflows ?? []);
      } catch (err) {
        if (!cancelled) onError(errMsg(err, "Failed to load create options"));
      } finally {
        if (!cancelled) setLoadingOpts(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, onError]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy && !parentBusy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, parentBusy, onClose]);

  if (!open) return null;

  const disabled = busy || parentBusy || loadingOpts;

  async function submit() {
    const title = (form.title || "").trim();
    if (!title) {
      onError("Title is required");
      return;
    }
    const binding = form.executionBinding || "manual";
    if (binding === "capability_job" && !form.capabilityId) {
      onError("Select a capability for capability job binding");
      return;
    }
    if (binding === "agent_mission" && !(form.missionRequest || "").trim()) {
      onError("Mission request is required for agent mission binding");
      return;
    }
    if (binding === "workflow" && !form.workflowId) {
      onError("Select a workflow for workflow binding");
      return;
    }

    const tags = tagsText
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    let assigneeType = form.assigneeType || "none";
    let assigneeId = form.assigneeId || null;
    let assigneeName = form.assigneeName || null;
    if (assigneeId) {
      const agent = agents.find((a) => a.agentId === assigneeId);
      assigneeType = "agent";
      assigneeName = agent?.name ?? assigneeName;
    } else {
      assigneeType = "none";
      assigneeId = null;
      assigneeName = null;
    }

    const payload: TaskCreatePayload = {
      title,
      description: (form.description || "").trim(),
      priority: form.priority || "medium",
      boardColumn: form.boardColumn || "backlog",
      tags,
      project: (form.project || "").trim() || null,
      assigneeType,
      assigneeId,
      assigneeName,
      dueAt: form.dueAt || null,
      plannedStartAt: form.plannedStartAt || null,
      executionBinding: binding,
      capabilityId: binding === "capability_job" ? form.capabilityId || null : null,
      missionRequest: binding === "agent_mission" ? (form.missionRequest || "").trim() : null,
      workflowId: binding === "workflow" ? form.workflowId || null : null,
    };

    setBusy(true);
    try {
      await api.createTask(payload);
      onSuccess("Task created");
      onCreated();
      onClose();
    } catch (err) {
      onError(errMsg(err, "Failed to create task"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lv-tasks-modal-backdrop" role="presentation" onClick={() => !disabled && onClose()}>
      <div
        className="lv-tasks-modal"
        role="dialog"
        aria-modal="true"
        aria-label="New Task"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="lv-tasks-modal-head">
          <h2>New Task</h2>
          <button type="button" className="lv-tasks-icon-btn" aria-label="Close" disabled={disabled} onClick={onClose}>
            <IconClose />
          </button>
        </header>
        <div className="lv-tasks-modal-body">
          <label className="lv-tasks-form-field">
            <span>Title</span>
            <input
              value={form.title || ""}
              disabled={disabled}
              onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              placeholder="Task title"
              autoFocus
            />
          </label>
          <label className="lv-tasks-form-field">
            <span>Description</span>
            <textarea
              value={form.description || ""}
              disabled={disabled}
              rows={3}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="Optional description"
            />
          </label>
          <div className="lv-tasks-form-row">
            <label className="lv-tasks-form-field">
              <span>Priority</span>
              <select
                value={form.priority || "medium"}
                disabled={disabled}
                onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label className="lv-tasks-form-field">
              <span>Board column</span>
              <select
                value={form.boardColumn || "backlog"}
                disabled={disabled}
                onChange={(e) => setForm((f) => ({ ...f, boardColumn: e.target.value }))}
              >
                <option value="backlog">Backlog</option>
                <option value="in_progress">In Progress</option>
                <option value="review">Review</option>
                <option value="done">Done</option>
              </select>
            </label>
          </div>
          <div className="lv-tasks-form-row">
            <label className="lv-tasks-form-field">
              <span>Due</span>
              <input
                type="datetime-local"
                disabled={disabled}
                value={toLocalInput(form.dueAt)}
                onChange={(e) => setForm((f) => ({ ...f, dueAt: fromLocalInput(e.target.value) }))}
              />
            </label>
            <label className="lv-tasks-form-field">
              <span>Planned start</span>
              <input
                type="datetime-local"
                disabled={disabled}
                value={toLocalInput(form.plannedStartAt)}
                onChange={(e) => setForm((f) => ({ ...f, plannedStartAt: fromLocalInput(e.target.value) }))}
              />
            </label>
          </div>
          <label className="lv-tasks-form-field">
            <span>Tags (comma-separated)</span>
            <input
              value={tagsText}
              disabled={disabled}
              onChange={(e) => setTagsText(e.target.value)}
              placeholder="Finance, Planning"
            />
          </label>
          <label className="lv-tasks-form-field">
            <span>Project</span>
            <input
              value={form.project || ""}
              disabled={disabled}
              onChange={(e) => setForm((f) => ({ ...f, project: e.target.value }))}
              placeholder="Optional project"
            />
          </label>
          <label className="lv-tasks-form-field">
            <span>Assignee</span>
            <select
              value={form.assigneeId || ""}
              disabled={disabled}
              onChange={(e) => {
                const id = e.target.value;
                const agent = agents.find((a) => a.agentId === id);
                setForm((f) => ({
                  ...f,
                  assigneeId: id || null,
                  assigneeName: agent?.name ?? null,
                  assigneeType: id ? "agent" : "none",
                }));
              }}
            >
              <option value="">Unassigned</option>
              {agents.map((a) => (
                <option key={a.agentId} value={a.agentId}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="lv-tasks-form-field">
            <span>Execution binding</span>
            <select
              value={form.executionBinding || "manual"}
              disabled={disabled}
              onChange={(e) => setForm((f) => ({ ...f, executionBinding: e.target.value }))}
            >
              <option value="manual">Manual</option>
              <option value="agent_mission">Agent mission</option>
              <option value="capability_job">Capability job</option>
              <option value="workflow">Workflow</option>
            </select>
          </label>
          {form.executionBinding === "capability_job" ? (
            <label className="lv-tasks-form-field">
              <span>Capability</span>
              <select
                value={form.capabilityId || ""}
                disabled={disabled}
                onChange={(e) => setForm((f) => ({ ...f, capabilityId: e.target.value || null }))}
              >
                <option value="">Select capability…</option>
                {capabilities.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name || c.id}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {form.executionBinding === "agent_mission" ? (
            <label className="lv-tasks-form-field">
              <span>Mission request</span>
              <textarea
                value={form.missionRequest || ""}
                disabled={disabled}
                rows={3}
                onChange={(e) => setForm((f) => ({ ...f, missionRequest: e.target.value }))}
                placeholder="What should the agent do?"
              />
            </label>
          ) : null}
          {form.executionBinding === "workflow" ? (
            <label className="lv-tasks-form-field">
              <span>Workflow</span>
              <select
                value={form.workflowId || ""}
                disabled={disabled}
                onChange={(e) => setForm((f) => ({ ...f, workflowId: e.target.value || null }))}
              >
                <option value="">Select workflow…</option>
                {workflows.map((w) => (
                  <option key={w.workflow_id} value={w.workflow_id}>
                    {w.name || w.workflow_id}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <footer className="lv-tasks-modal-foot">
          <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" disabled={disabled} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="lv-tasks-btn lv-tasks-btn--gold" disabled={disabled} onClick={() => void submit()}>
            {busy ? "Creating…" : "Create Task"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}
