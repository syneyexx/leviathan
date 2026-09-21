"use client";

import { useEffect } from "react";
import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";
import { FbIcon } from "../../icons";

type Props = { coding: HadesCodingRuntime };

export function CodingTabBranches({ coding }: Props) {
  useEffect(() => {
    if (coding.workspacePath) void coding.loadGitStatus();
  }, [coding.workspacePath, coding.loadGitStatus]);

  const dirty = Array.isArray(coding.gitStatus?.dirty)
    ? (coding.gitStatus.dirty as Array<{ path?: string; code?: string }>)
    : [];
  const branch = String(coding.gitStatus?.branch || "—");
  const isGit = Boolean(coding.gitStatus?.is_git);

  return (
    <div className="coding-branches-tab">
      <div className="coding-tab-grid">
        <article className="coding-panel">
          <div className="coding-panel-head">
            <strong>Branches</strong>
            <button type="button" className="coding-icon-btn" aria-label="Vernieuwen" onClick={() => void coding.loadGitStatus()}>
              <FbIcon name="refresh" size={12} />
            </button>
          </div>
          <div className="coding-unavailable">
            Branch create/switch/delete is niet beschikbaar in de HADES API. Alleen status + lokale commit.
          </div>
          <div className="coding-branch-row active">
            <span className="coding-agent-dot on" />
            <strong>{branch}</strong>
            <em>{isGit ? "local" : "geen git"}</em>
          </div>
          <button type="button" className="btn btn-outline btn-sm" disabled title="Niet ondersteund door backend">
            Nieuwe branch
          </button>
          <button type="button" className="btn btn-outline btn-sm" disabled title="Niet ondersteund door backend">
            Switch branch
          </button>
        </article>

        <article className="coding-panel">
          <div className="coding-panel-head">
            <strong>Git status</strong>
          </div>
          {coding.gitLoading ? (
            <div className="coding-empty">Laden…</div>
          ) : !coding.gitStatus ? (
            <div className="coding-empty">Laad git status voor de workspace.</div>
          ) : (
            <>
              <div className="coding-tab-b-kv">
                <span>Branch</span>
                <strong>{branch}</strong>
              </div>
              <div className="coding-tab-b-kv">
                <span>Dirty</span>
                <strong>{dirty.length || Number(coding.gitStatus.dirty_count || 0)}</strong>
              </div>
              <ul className="coding-dirty-list">
                {dirty.slice(0, 40).map((row) => (
                  <li key={`${row.code}-${row.path}`}>
                    <code>{row.code}</code> {row.path}
                  </li>
                ))}
              </ul>
              {typeof coding.gitStatus.diff === "string" && coding.gitStatus.diff ? (
                <pre className="coding-mini-pre">{String(coding.gitStatus.diff).slice(0, 4000)}</pre>
              ) : null}
            </>
          )}
        </article>

        <article className="coding-panel">
          <div className="coding-panel-head">
            <strong>Lokale commit</strong>
          </div>
          <p className="coding-hint">Geen push, merge of force. Alleen lokale commit met expliciete goedkeuring.</p>
          <label className="coding-field">
            <span>Message</span>
            <textarea value={coding.gitCommitMsg} onChange={(e) => coding.setGitCommitMsg(e.target.value)} rows={3} />
          </label>
          <label className="coding-check">
            <input
              type="checkbox"
              checked={coding.gitCommitApproved}
              onChange={(e) => coding.setGitCommitApproved(e.target.checked)}
            />
            Ik keur deze lokale commit goed
          </label>
          <button
            type="button"
            className="btn btn-gold btn-block"
            disabled={coding.gitCommitting || !coding.gitCommitApproved}
            onClick={() => {
              if (window.confirm("Lokale Git commit uitvoeren? (geen push)")) void coding.commitGit();
            }}
          >
            {coding.gitCommitting ? "Committen…" : "Commit"}
          </button>
        </article>
      </div>
    </div>
  );
}
