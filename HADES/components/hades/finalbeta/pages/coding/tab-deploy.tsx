"use client";

import { useEffect } from "react";
import type { HadesCodingRuntime } from "@/components/hades/finalbeta/hooks/use-coding-live";
import { FbIcon } from "../../icons";

type Props = { coding: HadesCodingRuntime };

export function CodingTabDeploy({ coding }: Props) {
  useEffect(() => {
    void coding.loadReleaseConfidence();
  }, [coding.loadReleaseConfidence]);

  const gates = coding.releaseReport?.gates || [];
  const stages = coding.releaseReport?.verify_stages || [];

  return (
    <div className="coding-deploy-tab">
      <div className="coding-tab-b-layout">
        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Release confidence</strong>
              <button type="button" className="coding-tab-b-icon-btn" aria-label="Vernieuwen" onClick={() => void coding.loadReleaseConfidence()}>
                <FbIcon name="refresh" size={12} />
              </button>
            </div>
            <div className="coding-tab-b-card-body">
              {coding.releaseLoading ? (
                <div className="coding-empty">Laden…</div>
              ) : coding.releaseError ? (
                <div className="coding-banner danger">{coding.releaseError}</div>
              ) : coding.releaseReport ? (
                <>
                  <div className="coding-tab-b-kv">
                    <span>Overall</span>
                    <strong>{coding.releaseReport.overall}</strong>
                  </div>
                  <div className="coding-tab-b-kv">
                    <span>Platform</span>
                    <strong>{coding.releaseReport.platform || "—"}</strong>
                  </div>
                  {coding.releaseReport.note ? <p className="coding-hint">{coding.releaseReport.note}</p> : null}
                  <div className="coding-deploy-mini-cards">
                    {gates.map((gate) => (
                      <div key={gate.id} className="coding-deploy-mini">
                        <span>{gate.label}</span>
                        <strong>{gate.status}</strong>
                        {gate.detail ? <small>{gate.detail}</small> : null}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="coding-empty">Geen rapport.</div>
              )}
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Smoke test</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <p className="coding-hint">Optionele focused unittest smoke. Succes ≠ HTTP 200 alleen — inspecteer smoke.ok.</p>
              <button
                type="button"
                className="btn btn-gold"
                disabled={coding.releaseSmokeLoading}
                onClick={() => {
                  if (window.confirm("Smoke-test kan enkele minuten duren. Doorgaan?")) void coding.runReleaseSmoke();
                }}
              >
                {coding.releaseSmokeLoading ? "Smoke draait…" : "Run release smoke"}
              </button>
              {coding.releaseReport?.smoke ? (
                <pre className="coding-mini-pre">{JSON.stringify(coding.releaseReport.smoke, null, 2)}</pre>
              ) : null}
            </div>
          </article>
        </div>

        <div className="coding-tab-b-col">
          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Verify stages</strong>
            </div>
            <div className="coding-tab-b-card-body">
              {stages.length === 0 ? (
                <div className="coding-empty">Geen verify stages in rapport.</div>
              ) : (
                stages.map((stage) => (
                  <div key={String(stage.id || stage.label)} className="coding-tab-b-progress">
                    <div className="coding-tab-b-progress-top">
                      <span>{stage.label || stage.id}</span>
                      <span>{stage.status}</span>
                    </div>
                    {stage.detail ? <small>{stage.detail}</small> : null}
                  </div>
                ))
              )}
            </div>
          </article>

          <article className="coding-tab-b-card">
            <div className="coding-tab-b-card-head">
              <strong>Deploy targets</strong>
            </div>
            <div className="coding-tab-b-card-body">
              <div className="coding-unavailable">
                Remote deploy / promote / rollback / restart zijn niet beschikbaar in HADES Coding.
                Alleen lokale release confidence + smoke worden ondersteund.
              </div>
              <div className="coding-tab-b-actions">
                <button type="button" className="btn btn-outline" disabled title="Geen deploy backend">
                  Promote
                </button>
                <button type="button" className="btn btn-outline" disabled title="Geen deploy backend">
                  Rollback
                </button>
                <button type="button" className="btn btn-outline" disabled title="Geen deploy backend">
                  Restart
                </button>
              </div>
            </div>
          </article>
        </div>
      </div>
    </div>
  );
}
