"use client";

import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";
import { buildStatusLabel, loopPhaseLabel } from "@/components/hades/features/coding/coding-runtime-core";
import { FbIcon } from "../../icons";

type Props = { coding: HadesCodingRuntime };

const ROLES = [
  { id: "investigator", label: "Investigator", match: /investigat|explore|index/i },
  { id: "planner", label: "Planner", match: /plan|dag/i },
  { id: "editor", label: "Editor", match: /edit|apply_edits|propos/i },
  { id: "reviewer", label: "Reviewer", match: /review/i },
  { id: "verifier", label: "Verifier", match: /test|verif|repair/i },
  { id: "debugger", label: "Debugger", match: /diagnos|debug|fail/i },
];

export function CodingTabAgents({ coding }: Props) {
  const phase = String(coding.jobPhase || "");
  const status = String(coding.jobSnapshot?.status || coding.selectedRun?.status || "idle");

  return (
    <div className="coding-agents-tab">
      <div className="coding-tab-b-layout">
        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Coding roles</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <p className="coding-hint">
                Dit zijn logische specialist-rollen in één Coding-job — geen aparte permanente agentprocessen.
              </p>
              <div className="coding-agents-flow">
                {ROLES.map((role, index) => {
                  const active = role.match.test(phase) || (status === "running" && index === 0 && !phase);
                  return (
                    <div key={role.id} className={`coding-agents-node${active ? " active" : ""}`}>
                      {role.label}
                      {index < ROLES.length - 1 ? <span className="coding-agents-arrow">&rarr;</span> : null}
                    </div>
                  );
                })}
              </div>
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Routing & autonomy</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <label className="coding-field">
                <span>Strategy</span>
                <select
                  value={coding.codingStrategy}
                  onChange={(e) => coding.setCodingStrategy(e.target.value as typeof coding.codingStrategy)}
                >
                  <option value="fast">fast</option>
                  <option value="investigate">investigate</option>
                  <option value="auto">auto</option>
                </select>
              </label>
              <label className="coding-field">
                <span>Autonomy</span>
                <select
                  value={coding.autonomyProfile}
                  onChange={(e) => coding.setAutonomyProfile(e.target.value as typeof coding.autonomyProfile)}
                >
                  <option value="analyze_only">analyze_only — geen worktree edits</option>
                  <option value="managed_workspace_modify">managed_workspace_modify</option>
                  <option value="reviewable_result">reviewable_result (default)</option>
                </select>
              </label>
              <label className="coding-check" title={coding.omnirouteStatus?.explanation || coding.omnirouteStatus?.reason || ""}>
                <input
                  type="checkbox"
                  checked={coding.useOmniroute}
                  disabled={!coding.omnirouteStatus?.usable}
                  onChange={(e) => coding.setUseOmniroute(e.target.checked)}
                />
                OmniRoute {coding.omnirouteStatus?.usable ? `(${coding.omnirouteStatus.status_label})` : "(unavailable)"}
              </label>
              <div className="coding-tab-b-kv">
                <span>Route</span>
                <strong>{coding.omnirouteLabel}</strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>Model</span>
                <strong>{coding.activeModel || "—"}</strong>
              </div>
            </div>
          </article>
        </div>

        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Actieve job</strong>
              <span className="coding-tab-b-pill">{buildStatusLabel(status)}</span>
            </div>
            <div className="coding-tab-b-card-body">
              <div className="coding-tab-b-kv">
                <span>Job ID</span>
                <strong>{coding.activeJobId || "—"}</strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>Fase</span>
                <strong>{loopPhaseLabel(phase)}</strong>
              </div>
              <div className="coding-tab-b-actions">
                <button type="button" className="btn btn-outline" disabled={!coding.activeJobId} onClick={() => void coding.pauseJob()}>
                  Pause
                </button>
                <button type="button" className="btn btn-outline" disabled={!coding.activeJobId} onClick={() => void coding.resumeJob()}>
                  Resume
                </button>
                <button type="button" className="btn btn-outline" disabled={!coding.activeJobId} onClick={() => void coding.cancelJob()}>
                  Cancel
                </button>
                <button type="button" className="btn btn-outline" onClick={() => void coding.recoverJobs()}>
                  Recover
                </button>
              </div>
              <label className="coding-field">
                <span>Redirect note</span>
                <input value={coding.jobRedirectNote} onChange={(e) => coding.setJobRedirectNote(e.target.value)} />
              </label>
              <button type="button" className="btn btn-outline btn-sm" disabled={!coding.activeJobId} onClick={() => void coding.redirectJob()}>
                Redirect
              </button>
              <label className="coding-field">
                <span>Human rating</span>
                <select
                  value={coding.humanJobRating}
                  onChange={(e) => coding.setHumanJobRating(e.target.value as typeof coding.humanJobRating)}
                >
                  <option value="directly_usable">directly_usable</option>
                  <option value="usable_after_small_correction">usable_after_small_correction</option>
                  <option value="needs_major_correction">needs_major_correction</option>
                  <option value="unusable">unusable</option>
                </select>
              </label>
              <button type="button" className="btn btn-outline btn-sm" disabled={!coding.activeJobId} onClick={() => void coding.rateActiveJob()}>
                Rating opslaan
              </button>
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Event timeline</strong>
            </div>
            <div className="coding-tab-b-card-body flush">
              <ul className="coding-event-list">
                {coding.jobEvents.length === 0 ? (
                  <li>Geen events</li>
                ) : (
                  coding.jobEvents
                    .slice()
                    .reverse()
                    .slice(0, 40)
                    .map((ev, index) => (
                      <li key={String(ev.id || ev.seq || index)}>
                        <FbIcon name="bolt" size={11} />
                        <div>
                          <strong>{String(ev.event || ev.type || ev.phase || "event")}</strong>
                          <small>{String(ev.message || ev.detail || "").slice(0, 120)}</small>
                        </div>
                      </li>
                    ))
                )}
              </ul>
            </div>
          </article>
        </div>
      </div>
    </div>
  );
}
