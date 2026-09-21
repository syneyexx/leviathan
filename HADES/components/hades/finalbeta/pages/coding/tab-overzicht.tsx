"use client";

import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";
import { buildStatusLabel, collectReviewDiffText, loopPhaseLabel } from "@/components/hades/features/coding/coding-runtime-core";
import { FbIcon } from "../../icons";

type DiffTab = "Diff" | "Code" | "Voorstel" | "AI Uitleg";

type SharedProps = {
  coding: HadesCodingRuntime;
  selectedFile: number;
  setSelectedFile: (n: number) => void;
  diffTab: DiffTab;
  setDiffTab: (t: DiffTab) => void;
};

type OverzichtProps = SharedProps & {
  onOpenTab: (tab: "Bestanden" | "Wijzigingen" | "Branches" | "Build & testen" | "Agents") => void;
};

function DiffPane({ coding, selectedFile, setSelectedFile, diffTab, setDiffTab }: SharedProps) {
  const files = coding.changedFiles;
  const file = files[selectedFile] || files[0];
  const diffText = file?.diff || coding.reviewDiffText || collectReviewDiffText(coding.selectedRun?.result ?? null);
  const lines = (diffText || "").split("\n").slice(0, 400);
  const codingResult = (coding.selectedRun?.result?.coding || coding.jobSnapshot?.result || {}) as Record<string, unknown>;
  const review = (codingResult.review || coding.selectedRun?.result?.review || {}) as Record<string, unknown>;
  const explanation =
    typeof review.summary === "string"
      ? review.summary
      : typeof codingResult.explanation === "string"
        ? codingResult.explanation
        : typeof coding.selectedRun?.result?.message === "string"
          ? String(coding.selectedRun.result.message)
          : "Geen AI-uitleg beschikbaar voor deze run.";

  return (
    <>
      <div className="coding-files">
        <div className="coding-panel-head">
          <strong>Wijzigingen ({files.length})</strong>
          <div className="coding-panel-actions">
            <button type="button" className="coding-mini" onClick={() => void coding.loadConflicts()} disabled={coding.conflictsLoading || !coding.selectedRun}>
              Conflicts
            </button>
            <button type="button" className="coding-icon-btn" aria-label="Vernieuwen" onClick={() => void coding.loadConflicts()}>
              <FbIcon name="refresh" size={12} />
            </button>
          </div>
        </div>
        <div className="coding-file-list">
          {files.length === 0 ? (
            <div className="coding-empty">Geen gewijzigde bestanden. Start een Coding-taak of selecteer een voltooide run.</div>
          ) : (
            files.map((item, index) => (
              <button
                key={item.path}
                type="button"
                className={`coding-file${index === selectedFile ? " active" : ""}`}
                onClick={() => setSelectedFile(index)}
              >
                <span className="coding-file-action">{item.action}</span>
                <span className="coding-file-path">{item.path}</span>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="coding-diff">
        <div className="coding-panel-head">
          <div className="coding-diff-tabs">
            {(["Diff", "Code", "Voorstel", "AI Uitleg"] as DiffTab[]).map((label) => (
              <button
                key={label}
                type="button"
                className={diffTab === label ? "active" : undefined}
                onClick={() => setDiffTab(label)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="coding-panel-actions">
            <button
              type="button"
              className="coding-mini"
              disabled={!coding.selectedRun || coding.mutatingRun === "apply"}
              onClick={() => {
                if (!coding.applyApproved) {
                  coding.setApplyApproved(true);
                  return;
                }
                if (window.confirm(`Wijzigingen toepassen op ${coding.selectedRun?.sourceRepo || coding.sourceRepo}?`)) {
                  void coding.applyRun();
                }
              }}
            >
              {coding.applyApproved ? "Apply" : "Approve apply"}
            </button>
            <button
              type="button"
              className="coding-icon-btn"
              aria-label="Kopiëren"
              onClick={() => void navigator.clipboard?.writeText(diffText || "")}
            >
              <FbIcon name="copy" size={12} />
            </button>
          </div>
        </div>
        <div className="coding-diff-body">
          {diffTab === "AI Uitleg" ? (
            <pre className="coding-plain">{explanation}</pre>
          ) : diffTab === "Voorstel" ? (
            <pre className="coding-plain">{JSON.stringify(review || coding.composerPlan || { note: "Geen voorstel" }, null, 2)}</pre>
          ) : lines.length === 0 ? (
            <div className="coding-empty">Geen unified diff beschikbaar.</div>
          ) : (
            lines.map((line, index) => {
              const kind = line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "ctx";
              return (
                <div key={`${index}-${line.slice(0, 24)}`} className={`coding-line ${kind}`}>
                  <span className="coding-ln">{index + 1}</span>
                  <code>{line || " "}</code>
                </div>
              );
            })
          )}
        </div>
        {coding.conflicts && coding.conflicts.length > 0 ? (
          <div className="coding-conflict-banner">
            Apply geblokkeerd: {coding.conflicts.length} conflict(en).{" "}
            {coding.conflicts
              .slice(0, 3)
              .map((c) => String(c.path || c.file || ""))
              .filter(Boolean)
              .join(", ")}
          </div>
        ) : null}
        <div className="coding-diff-actions">
          <label className="coding-check">
            <input
              type="checkbox"
              checked={coding.applyApproved}
              onChange={(e) => coding.setApplyApproved(e.target.checked)}
            />
            Expliciete apply-goedkeuring
          </label>
          <button
            type="button"
            className="btn btn-gold"
            disabled={!coding.selectedRun || !coding.applyApproved || coding.mutatingRun === "apply" || (coding.applyPreview?.can_apply === false)}
            onClick={() => {
              if (window.confirm(`Wijzigingen toepassen op ${coding.selectedRun?.sourceRepo || coding.sourceRepo}?`)) {
                void coding.applyRun();
              }
            }}
          >
            Apply to source
          </button>
          <button
            type="button"
            className="btn btn-outline"
            disabled={!coding.selectedRun || coding.mutatingRun === "restore"}
            onClick={() => {
              if (window.confirm("Backup herstellen voor deze build-run?")) void coding.restoreRun();
            }}
          >
            Restore backup
          </button>
        </div>
      </div>
    </>
  );
}

export function CodingTabOverzicht({
  coding,
  selectedFile,
  setSelectedFile,
  diffTab,
  setDiffTab,
  onOpenTab,
}: OverzichtProps) {
  const dirty = Array.isArray(coding.gitStatus?.dirty) ? (coding.gitStatus.dirty as Array<{ path?: string; code?: string }>) : [];
  const events = coding.jobEvents.slice(-8).reverse();

  return (
    <div className="coding-overzicht">
      <div className="coding-repo">
        <div className="coding-repo-main">
          <FbIcon name="folder" size={16} />
          <div>
            <strong>{coding.workspacePath || "Geen workspace geselecteerd"}</strong>
            <span>{coding.fsMeta?.root || coding.sourceRepo || "Stel source_repo in via Nieuwe taak"}</span>
          </div>
        </div>
        <button type="button" className="coding-branch" onClick={() => void coding.loadGitStatus()}>
          <FbIcon name="line" size={12} />
          {String(coding.gitStatus?.branch || "git status")}
        </button>
        <div className="coding-repo-actions">
          <button type="button" className="btn btn-outline" onClick={() => void coding.openInEditor()}>
            <FbIcon name="external" size={13} />
            Editor
          </button>
          <button type="button" className="btn btn-gold" onClick={() => coding.startNewRun()}>
            Nieuwe taak
          </button>
        </div>
      </div>

      <div className="coding-status">
        <div className="coding-stat">
          <div className="coding-stat-label">Job</div>
          <div className="coding-stat-value">{buildStatusLabel(String(coding.jobSnapshot?.status || coding.selectedRun?.status || "idle"))}</div>
        </div>
        <div className="coding-stat">
          <div className="coding-stat-label">Fase</div>
          <div className="coding-stat-value">{loopPhaseLabel(coding.jobPhase)}</div>
        </div>
        <div className="coding-stat">
          <div className="coding-stat-label">Wijzigingen</div>
          <div className="coding-stat-value">{coding.changedFiles.length}</div>
        </div>
        <div className="coding-stat">
          <div className="coding-stat-label">Dirty files</div>
          <div className="coding-stat-value">{dirty.length || Number(coding.gitStatus?.dirty_count || 0)}</div>
        </div>
        <div className="coding-stat">
          <div className="coding-stat-label">OmniRoute</div>
          <div className="coding-stat-value">{coding.omnirouteStatus?.usable ? (coding.useOmniroute ? "on" : "off") : "n/a"}</div>
        </div>
        <div className="coding-stat">
          <div className="coding-stat-label">Frontier</div>
          <div className="coding-stat-value">{coding.frontierStatus ? buildStatusLabel(coding.frontierStatus) : "—"}</div>
        </div>
      </div>

      {coding.codingFailureReason ? (
        <div className="coding-banner danger" role="alert">
          {coding.codingFailureReason}
        </div>
      ) : null}

      <div className="coding-work">
        <DiffPane
          coding={coding}
          selectedFile={selectedFile}
          setSelectedFile={setSelectedFile}
          diffTab={diffTab}
          setDiffTab={setDiffTab}
        />

        <aside className="coding-side">
          <div className="coding-plan">
            <div className="coding-panel-head">
              <strong>Recente jobs</strong>
              <button type="button" className="coding-icon-btn" aria-label="Vernieuwen" onClick={() => void coding.refreshRecentJobs()}>
                <FbIcon name="refresh" size={12} />
              </button>
            </div>
            <ul className="coding-plan-list">
              {coding.recentJobs.length === 0 ? (
                <li className="todo">Nog geen jobs</li>
              ) : (
                coding.recentJobs.slice(0, 8).map((job) => {
                  const id = String(job.id || "");
                  return (
                    <li key={id}>
                      <button type="button" className="coding-job-link" onClick={() => void coding.attachJob(id)}>
                        <span>{buildStatusLabel(String(job.status || ""))}</span>
                        <small>{String(job.goal || id).slice(0, 48)}</small>
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          </div>

          <div className="coding-terminal">
            <div className="coding-panel-head">
              <strong>Activity</strong>
            </div>
            <pre>
              {events.length === 0
                ? "Geen job-events."
                : events
                    .map((ev) => `${String(ev.seq || "")} ${String(ev.event || ev.type || ev.phase || "event")} ${String(ev.message || "").slice(0, 80)}`)
                    .join("\n")}
            </pre>
          </div>

          <div className="coding-actions">
            <button type="button" className="btn btn-outline" onClick={() => onOpenTab("Branches")}>
              Git
            </button>
            <button type="button" className="btn btn-outline" onClick={() => onOpenTab("Wijzigingen")}>
              Review
            </button>
            <button type="button" className="btn btn-outline" onClick={() => onOpenTab("Build & testen")}>
              Terminal
            </button>
            <button type="button" className="btn btn-outline" onClick={() => onOpenTab("Agents")}>
              Agents
            </button>
            <button type="button" className="btn btn-outline coding-more" onClick={() => onOpenTab("Bestanden")}>
              Bestanden
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

export function CodingTabWijzigingen(props: SharedProps) {
  return (
    <div className="coding-wijzigingen">
      <div className="coding-work coding-work-solo">
        <DiffPane {...props} />
      </div>
    </div>
  );
}
