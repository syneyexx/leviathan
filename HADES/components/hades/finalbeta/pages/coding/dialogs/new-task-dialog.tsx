"use client";

import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";
import { FbIcon } from "../../../icons";

type Props = {
  coding: HadesCodingRuntime;
  open: boolean;
  onClose: () => void;
};

export function CodingNewTaskDialog({ coding, open, onClose }: Props) {
  if (!open) return null;
  return (
    <div className="coding-dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="coding-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Nieuwe Coding-taak"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="coding-dialog-head">
          <strong>Nieuwe Coding-taak</strong>
          <button type="button" className="coding-icon-btn" aria-label="Sluiten" onClick={onClose}>
            <FbIcon name="stop" size={14} />
          </button>
        </div>
        <div className="coding-dialog-body">
          <label className="coding-field">
            <span>Source repository</span>
            <input
              value={coding.sourceRepo}
              onChange={(e) => {
                coding.setSourceRepo(e.target.value);
                if (!coding.symbolsPath) coding.setSymbolsPath(e.target.value);
              }}
              placeholder="C:\Projects\mijn-repo"
            />
          </label>
          <label className="coding-field">
            <span>Doel (natuurlijke taal)</span>
            <textarea
              value={coding.composerGoal}
              onChange={(e) => coding.setComposerGoal(e.target.value)}
              rows={4}
              placeholder="Fix the authentication race condition without changing the public API."
            />
          </label>
          <div className="coding-field-row">
            <label className="coding-field">
              <span>Test suite</span>
              <select value={coding.testSuite} onChange={(e) => coding.setTestSuite(e.target.value as typeof coding.testSuite)}>
                {coding.TEST_SUITES.map((suite) => (
                  <option key={suite.id} value={suite.id}>
                    {suite.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="coding-field">
              <span>Max attempts</span>
              <input value={coding.maxAttempts} onChange={(e) => coding.setMaxAttempts(e.target.value)} />
            </label>
          </div>
          <div className="coding-field-row">
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
                <option value="analyze_only">analyze_only</option>
                <option value="managed_workspace_modify">managed_workspace_modify</option>
                <option value="reviewable_result">reviewable_result</option>
              </select>
            </label>
          </div>
          <div className="coding-field-row">
            <label className="coding-check">
              <input
                type="checkbox"
                checked={coding.backgroundRun}
                onChange={(e) => coding.setBackgroundRun(e.target.checked)}
              />
              Achtergrondjob
            </label>
            <label className="coding-check" title={coding.omnirouteStatus?.reason || ""}>
              <input
                type="checkbox"
                checked={coding.useOmniroute}
                disabled={!coding.omnirouteStatus?.usable}
                onChange={(e) => coding.setUseOmniroute(e.target.checked)}
              />
              OmniRoute
              {!coding.omnirouteStatus?.usable ? " (niet beschikbaar)" : ""}
            </label>
          </div>
          <div className="coding-preflight" role="status" aria-live="polite">
            <strong>Preflight</strong>
            <div className="coding-preflight-row">
              Model: {coding.activeModel || "—"} · LM: {coding.lmConnected ? "connected" : "offline"}
            </div>
            {coding.preflight?.analyzeOnlyBlocksMutation ? (
              <p className="coding-preflight-block">Analyze-only: deze taak mag geen bestanden wijzigen.</p>
            ) : null}
            {coding.preflight && !coding.preflight.ready ? (
              <ul className="coding-preflight-list">
                {coding.preflight.blockers.map((b) => (
                  <li key={b.code}>{b.message}</li>
                ))}
              </ul>
            ) : (
              <p className="coding-preflight-ok">{coding.preflight?.humanSummaryNl || "Klaar om te starten."}</p>
            )}
          </div>
          <details className="coding-advanced">
            <summary>Advanced</summary>
            <label className="coding-field">
              <span>Selector mode</span>
              <select
                value={coding.selectorMode}
                onChange={(e) => coding.setSelectorMode(e.target.value as typeof coding.selectorMode)}
              >
                <option value="deterministic">deterministic</option>
                <option value="model">model</option>
              </select>
            </label>
            <label className="coding-field">
              <span>Structured edits JSON</span>
              <textarea value={coding.editsJson} onChange={(e) => coding.setEditsJson(e.target.value)} rows={5} />
            </label>
            <label className="coding-field">
              <span>Repair waves JSON</span>
              <textarea value={coding.repairWavesJson} onChange={(e) => coding.setRepairWavesJson(e.target.value)} rows={3} />
            </label>
            <div className="coding-dialog-actions">
              <button type="button" className="btn btn-outline" disabled={coding.planLoading} onClick={() => void coding.previewComposerPlan()}>
                Plan preview
              </button>
              <label className="coding-check">
                <input
                  type="checkbox"
                  checked={coding.planApproved}
                  onChange={(e) => coding.setPlanApproved(e.target.checked)}
                  disabled={!coding.composerPlan}
                />
                Plan goedgekeurd
              </label>
            </div>
            {coding.composerPlan ? (
              <pre className="coding-mini-pre">{JSON.stringify(coding.composerPlan, null, 2)}</pre>
            ) : null}
          </details>
        </div>
        <div className="coding-dialog-foot">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            Annuleren
          </button>
          <button
            type="button"
            className="btn btn-gold"
            disabled={coding.building || (Boolean(coding.preflight) && !coding.preflight.ready && !coding.editsJson.trim())}
            onClick={() => void coding.submitBuild()}
          >
            {coding.building ? "Bezig…" : "Start Coding-taak"}
          </button>
        </div>
      </div>
    </div>
  );
}
