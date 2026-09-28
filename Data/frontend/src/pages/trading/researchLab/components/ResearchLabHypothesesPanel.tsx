import { asRecord, familyLabelMap, type LabRunRecord } from "../viewModels";

function listField(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.map(String).filter(Boolean);
}

export function ResearchLabHypothesesPanel({
  hypotheses,
  loading,
  strategyFamilies,
}: {
  hypotheses: LabRunRecord[];
  loading?: boolean;
  strategyFamilies?: Record<string, unknown>[];
}) {
  const labels = familyLabelMap(strategyFamilies);
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }

  if (hypotheses.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>EMPTY / UNMEASURED</strong>
        No research hypotheses recorded for this lab yet. Autonomous discovery proposes hypotheses
        after the research cycle runs against READY market data.
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <article className="lv-rl-card">
        <h3>Research hypotheses ({hypotheses.length})</h3>
        <p className="lv-rl-card-hint" style={{ marginBottom: 10 }}>
          Status is lifecycle, not a measured edge. AGENT_PROPOSED ≠ proof.
        </p>
        <div className="lv-rl-hyp-list">
          {hypotheses.map((h) => {
            const id = String(h.hypothesis_id || "—");
            const status = String(h.status || "PROPOSED").toUpperCase();
            const trust = String(h.trust || "UNTRUSTED").toUpperCase();
            const statement = String(h.statement || h.observation || "");
            const mechanism = String(h.mechanism || "");
            const falsification = listField(h.falsification_criteria);
            const failureModes = listField(h.expected_failure_modes);
            const scope = asRecord(h.scope);
            const families = listField(h.strategy_family_preferences);
            return (
              <article key={id} className="lv-rl-hyp-card">
                <div className="lv-rl-hyp-top">
                  <span className="lv-rl-pill is-draft">{status}</span>
                  <span className="lv-rl-hyp-trust">{trust}</span>
                  <span className="lv-rl-hyp-id">{id.slice(0, 14)}</span>
                </div>
                <p className="lv-rl-hyp-statement">{statement || "No statement recorded"}</p>
                <dl className="lv-rl-dl">
                  <div>
                    <dt>Mechanism</dt>
                    <dd>{mechanism || "—"}</dd>
                  </div>
                  <div>
                    <dt>Falsification</dt>
                    <dd>
                      {falsification.length
                        ? falsification.join("; ")
                        : "UNMEASURED — no criteria recorded"}
                    </dd>
                  </div>
                  {failureModes.length ? (
                    <div>
                      <dt>Expected failure modes</dt>
                      <dd>{failureModes.join("; ")}</dd>
                    </div>
                  ) : null}
                  {families.length ? (
                    <div>
                      <dt>Family preferences</dt>
                      <dd>{families.map((f) => labels[f] || f).join(", ")}</dd>
                    </div>
                  ) : null}
                  {scope ? (
                    <div>
                      <dt>Scope</dt>
                      <dd>
                        {[
                          listField(scope.symbols).join(", "),
                          listField(scope.timeframes).join(", "),
                          listField(scope.regime_scope).join(", "),
                        ]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </article>
            );
          })}
        </div>
      </article>
    </div>
  );
}
