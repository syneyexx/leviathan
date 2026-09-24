import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { TaskAutoPlanProposal } from "../../types/api";
import { IconClose } from "./TaskIcons";
import { errMsg } from "./taskUtils";

type Props = {
  open: boolean;
  onClose: () => void;
  onCommitted: () => void;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
};

export function TaskAutoPlanDialog({ open, onClose, onCommitted, onError, onSuccess }: Props) {
  const [brief, setBrief] = useState("");
  const [project, setProject] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [priority, setPriority] = useState("");
  const [proposals, setProposals] = useState<TaskAutoPlanProposal[]>([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"edit" | "preview">("edit");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  async function preview() {
    const b = brief.trim();
    if (!b) {
      onError("Brief is required");
      return;
    }
    setBusy(true);
    try {
      const res = await api.previewTaskAutoPlan({
        brief: b,
        project: project.trim() || null,
        targetDate: targetDate ? new Date(targetDate).toISOString() : null,
        priority: priority || null,
      });
      setProposals(res.proposals ?? []);
      setPhase("preview");
      if (!(res.proposals ?? []).length) onError("No proposals returned");
    } catch (err) {
      onError(errMsg(err, "Auto-plan preview failed"));
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!proposals.length) {
      onError("Nothing to commit");
      return;
    }
    for (const p of proposals) {
      if (!(p.title || "").trim()) {
        onError("Every proposal needs a title");
        return;
      }
    }
    setBusy(true);
    try {
      const res = await api.commitTaskAutoPlan({
        proposals,
        project: project.trim() || null,
      });
      onSuccess(`Created ${res.tasks.length} task(s)`);
      onCommitted();
      onClose();
    } catch (err) {
      onError(errMsg(err, "Auto-plan commit failed"));
    } finally {
      setBusy(false);
    }
  }

  function updateProposal(index: number, patch: Partial<TaskAutoPlanProposal>) {
    setProposals((prev) => prev.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  }

  function removeProposal(index: number) {
    setProposals((prev) => prev.filter((_, i) => i !== index));
  }

  return (
    <div className="lv-tasks-modal-backdrop" role="presentation" onClick={() => !busy && onClose()}>
      <div
        className="lv-tasks-modal lv-tasks-modal--lg"
        role="dialog"
        aria-modal="true"
        aria-label="Auto-Plan"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="lv-tasks-modal-head">
          <h2>Auto-Plan</h2>
          <button type="button" className="lv-tasks-icon-btn" aria-label="Close" disabled={busy} onClick={onClose}>
            <IconClose />
          </button>
        </header>
        <div className="lv-tasks-modal-body">
          {phase === "edit" ? (
            <>
              <label className="lv-tasks-form-field">
                <span>Brief</span>
                <textarea
                  value={brief}
                  disabled={busy}
                  rows={5}
                  autoFocus
                  placeholder="Describe the outcome you want planned into tasks…"
                  onChange={(e) => setBrief(e.target.value)}
                />
              </label>
              <div className="lv-tasks-form-row">
                <label className="lv-tasks-form-field">
                  <span>Project (optional)</span>
                  <input value={project} disabled={busy} onChange={(e) => setProject(e.target.value)} />
                </label>
                <label className="lv-tasks-form-field">
                  <span>Target date</span>
                  <input
                    type="date"
                    value={targetDate}
                    disabled={busy}
                    onChange={(e) => setTargetDate(e.target.value)}
                  />
                </label>
                <label className="lv-tasks-form-field">
                  <span>Priority bias</span>
                  <select value={priority} disabled={busy} onChange={(e) => setPriority(e.target.value)}>
                    <option value="">Default</option>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
              </div>
            </>
          ) : (
            <div className="lv-tasks-proposal-list">
              {proposals.length === 0 ? (
                <p className="lv-tasks-empty">No proposals</p>
              ) : (
                proposals.map((p, index) => (
                  <div key={index} className="lv-tasks-proposal">
                    <div className="lv-tasks-form-row">
                      <label className="lv-tasks-form-field" style={{ flex: 2 }}>
                        <span>Title</span>
                        <input
                          value={p.title}
                          disabled={busy}
                          onChange={(e) => updateProposal(index, { title: e.target.value })}
                        />
                      </label>
                      <label className="lv-tasks-form-field">
                        <span>Priority</span>
                        <select
                          value={p.priority || "medium"}
                          disabled={busy}
                          onChange={(e) => updateProposal(index, { priority: e.target.value })}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </label>
                      <button
                        type="button"
                        className="lv-tasks-btn lv-tasks-btn--ghost"
                        disabled={busy}
                        onClick={() => removeProposal(index)}
                      >
                        Remove
                      </button>
                    </div>
                    <label className="lv-tasks-form-field">
                      <span>Description</span>
                      <textarea
                        value={p.description || ""}
                        disabled={busy}
                        rows={2}
                        onChange={(e) => updateProposal(index, { description: e.target.value })}
                      />
                    </label>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        <footer className="lv-tasks-modal-foot">
          {phase === "preview" ? (
            <button
              type="button"
              className="lv-tasks-btn lv-tasks-btn--outline"
              disabled={busy}
              onClick={() => setPhase("edit")}
            >
              Back
            </button>
          ) : (
            <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" disabled={busy} onClick={onClose}>
              Cancel
            </button>
          )}
          {phase === "edit" ? (
            <button type="button" className="lv-tasks-btn lv-tasks-btn--gold" disabled={busy} onClick={() => void preview()}>
              {busy ? "Previewing…" : "Preview"}
            </button>
          ) : (
            <button type="button" className="lv-tasks-btn lv-tasks-btn--gold" disabled={busy} onClick={() => void commit()}>
              {busy ? "Committing…" : "Commit Plan"}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
