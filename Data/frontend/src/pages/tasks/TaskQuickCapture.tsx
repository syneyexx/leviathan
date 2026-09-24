import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AgentDefinition } from "../../types/api";
import { IconClose } from "./TaskIcons";
import { errMsg } from "./taskUtils";

type Props = {
  open: boolean;
  agents: AgentDefinition[];
  onClose: () => void;
  onCreated: () => void;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
};

export function TaskQuickCapture({ open, agents, onClose, onCreated, onError, onSuccess }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("medium");
  const [dueAt, setDueAt] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  async function submit() {
    const t = title.trim();
    if (!t) {
      onError("Title is required");
      return;
    }
    const agent = agents.find((a) => a.agentId === assigneeId);
    setBusy(true);
    try {
      await api.quickCaptureTask({
        title: t,
        description: description.trim(),
        priority,
        dueAt: dueAt ? new Date(dueAt).toISOString() : null,
        assigneeType: agent ? "agent" : "none",
        assigneeId: agent?.agentId ?? null,
        assigneeName: agent?.name ?? null,
      });
      onSuccess("Task captured");
      onCreated();
      onClose();
    } catch (err) {
      onError(errMsg(err, "Quick capture failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lv-tasks-modal-backdrop" role="presentation" onClick={() => !busy && onClose()}>
      <div
        className="lv-tasks-modal lv-tasks-modal--sm"
        role="dialog"
        aria-modal="true"
        aria-label="Quick Capture"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="lv-tasks-modal-head">
          <h2>Quick Capture</h2>
          <button type="button" className="lv-tasks-icon-btn" aria-label="Close" disabled={busy} onClick={onClose}>
            <IconClose />
          </button>
        </header>
        <div className="lv-tasks-modal-body">
          <label className="lv-tasks-form-field">
            <span>Title</span>
            <input
              value={title}
              disabled={busy}
              autoFocus
              placeholder="What's the task?"
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submit();
                }
              }}
            />
          </label>
          <label className="lv-tasks-form-field">
            <span>Description (optional)</span>
            <textarea
              value={description}
              disabled={busy}
              rows={2}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <div className="lv-tasks-form-row">
            <label className="lv-tasks-form-field">
              <span>Priority</span>
              <select value={priority} disabled={busy} onChange={(e) => setPriority(e.target.value)}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label className="lv-tasks-form-field">
              <span>Due</span>
              <input
                type="datetime-local"
                value={dueAt}
                disabled={busy}
                onChange={(e) => setDueAt(e.target.value)}
              />
            </label>
          </div>
          <label className="lv-tasks-form-field">
            <span>Assignee</span>
            <select value={assigneeId} disabled={busy} onChange={(e) => setAssigneeId(e.target.value)}>
              <option value="">Unassigned</option>
              {agents.map((a) => (
                <option key={a.agentId} value={a.agentId}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <footer className="lv-tasks-modal-foot">
          <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="lv-tasks-btn lv-tasks-btn--gold" disabled={busy} onClick={() => void submit()}>
            {busy ? "Saving…" : "Capture"}
          </button>
        </footer>
      </div>
    </div>
  );
}
