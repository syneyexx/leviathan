"use client";

import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";
import { buildStatusLabel } from "@/components/hades/features/coding/coding-runtime-core";
import { FbIcon } from "../../icons";

type Props = { coding: HadesCodingRuntime };

export function CodingTabBuild({ coding }: Props) {
  const tests = Array.isArray(coding.selectedRun?.result?.test_results)
    ? (coding.selectedRun?.result?.test_results as Array<Record<string, unknown>>)
    : [];
  const review = (coding.selectedRun?.result?.review ||
    (coding.selectedRun?.result?.coding as Record<string, unknown> | undefined)?.review ||
    {}) as Record<string, unknown>;

  return (
    <div className="coding-build-tab">
      <div className="coding-tab-b-layout">
        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Test suites</strong>
            </div>
            <div className="coding-tab-b-card-body flush">
              {coding.TEST_SUITES.map((suite) => (
                <button
                  key={suite.id}
                  type="button"
                  className={`coding-build-suite${coding.testSuite === suite.id ? " active" : ""}`}
                  onClick={() => coding.setTestSuite(suite.id)}
                >
                  {suite.label}
                </button>
              ))}
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Run</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <p className="coding-hint">Tests draaien via de canonieke Coding/build executor (allowlist), niet via willekeurige shell.</p>
              <button type="button" className="btn btn-gold btn-block" onClick={() => coding.setNewTaskOpen(true)}>
                Start Coding-run met suite
              </button>
              {coding.activeJobId ? (
                <div className="coding-tab-b-actions" style={{ marginTop: 10 }}>
                  <button type="button" className="btn btn-outline" onClick={() => void coding.cancelJob()}>
                    Annuleren
                  </button>
                  <button type="button" className="btn btn-outline" onClick={() => coding.activeJobId && void coding.attachJob(coding.activeJobId)}>
                    Refresh job
                  </button>
                </div>
              ) : null}
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Terminal</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <label className="coding-field">
                <span>Argv</span>
                <input value={coding.terminalArgv} onChange={(e) => coding.setTerminalArgv(e.target.value)} />
              </label>
              <label className="coding-field">
                <span>Cwd</span>
                <input value={coding.terminalCwd} onChange={(e) => coding.setTerminalCwd(e.target.value)} placeholder={coding.workspacePath || ""} />
              </label>
              <button type="button" className="btn btn-outline btn-block" disabled={coding.terminalRunning} onClick={() => void coding.runTerminal()}>
                {coding.terminalRunning ? "Bezig…" : "Run terminal"}
              </button>
              {coding.terminalError ? <div className="coding-banner danger">{coding.terminalError}</div> : null}
              {coding.terminalResult ? (
                <pre className="coding-tab-b-log">
                  {`$ ${coding.terminalResult.argv.join(" ")}\nexit ${coding.terminalResult.exit_code} · ${coding.terminalResult.duration_ms}ms\n`}
                  {coding.terminalResult.stdout}
                  {coding.terminalResult.stderr}
                </pre>
              ) : null}
            </div>
          </article>
        </div>

        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-build-header">
              <div>
                <strong>Resultaat</strong>
                <div className="coding-hint">
                  {coding.selectedRun
                    ? `${coding.selectedRun.id} · ${buildStatusLabel(coding.selectedRun.status)}`
                    : coding.activeJobId
                      ? `Job ${coding.activeJobId}`
                      : "Geen geselecteerde run"}
                </div>
              </div>
              <span className="coding-tab-b-pill">
                {buildStatusLabel(String(coding.selectedRun?.status || coding.jobSnapshot?.status || "idle"))}
              </span>
            </div>
            <div className="coding-build-results">
              <div className="coding-build-result-box">
                <span>Tests</span>
                <strong>{tests.length}</strong>
              </div>
              <div className="coding-build-result-box">
                <span>Frontier</span>
                <strong>{coding.frontierStatus || "—"}</strong>
              </div>
              <div className="coding-build-result-box">
                <span>Review</span>
                <strong>{String(review.overall || review.status || "—")}</strong>
              </div>
            </div>
            {String(review.overall || review.status || "").includes("weaken") ||
            Array.isArray(review.test_weakening) ||
            review.weakening ? (
              <div className="coding-settings-warn-box">Test weakening gedetecteerd — zie review-details.</div>
            ) : null}
            {coding.codingFailureReason ? (
              <div className="coding-banner danger" role="alert">
                {coding.codingFailureReason}
              </div>
            ) : null}
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Test output</strong>
              <span className="coding-live compact">
                <FbIcon name="bolt" size={11} />
                live
              </span>
            </div>
            <pre className="coding-build-log">{coding.buildLogs || "Geen testlogs."}</pre>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Debug diagnose</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <button type="button" className="btn btn-outline btn-sm" onClick={() => coding.loadDebugFromSelectedRun()}>
                Laad logs van run
              </button>
              <label className="coding-field">
                <span>Logs</span>
                <textarea value={coding.debugLogs} onChange={(e) => coding.setDebugLogs(e.target.value)} rows={5} />
              </label>
              <label className="coding-field">
                <span>Failing test</span>
                <input value={coding.debugFailingTest} onChange={(e) => coding.setDebugFailingTest(e.target.value)} />
              </label>
              <label className="coding-field">
                <span>Context files JSON</span>
                <textarea value={coding.debugContextJson} onChange={(e) => coding.setDebugContextJson(e.target.value)} rows={3} />
              </label>
              <button type="button" className="btn btn-outline" disabled={coding.debugLoading} onClick={() => void coding.runDebugDiagnose()}>
                {coding.debugLoading ? "Diagnose…" : "Run diagnose"}
              </button>
              {coding.debugError ? <div className="coding-banner danger">{coding.debugError}</div> : null}
              {coding.debugResult ? (
                <>
                  <pre className="coding-mini-pre">{JSON.stringify(coding.debugResult, null, 2).slice(0, 4000)}</pre>
                  <button type="button" className="btn btn-outline btn-sm" onClick={() => coding.loadProposedEditsIntoComposer()}>
                    Proposed edits → composer (geen auto-apply)
                  </button>
                </>
              ) : null}
            </div>
          </article>
        </div>
      </div>
    </div>
  );
}
