import {
  dependencyStateLabel,
  dependencyStateTone,
  installPhaseSteps,
  type InstallOperationView,
  type InstallPlanView,
} from "../../pages/plugin-runtime/modules/viewModels";

type Props = {
  open: boolean;
  onClose: () => void;
  plan: InstallPlanView | null;
  operation: InstallOperationView | null;
  primaryCta: string;
  busy: boolean;
  onApproveAndInstall: () => void;
  onRetry: () => void;
};

export function ModulesInstallPanel({
  open,
  onClose,
  plan,
  operation,
  primaryCta,
  busy,
  onApproveAndInstall,
  onRetry,
}: Props) {
  if (!open) return null;
  const status = operation?.status || null;
  const phases = installPhaseSteps(operation?.phase ?? null);
  const failed = status === "FAILED" || operation?.phase === "FAILED";

  return (
    <div className="lv-v2-modules-drawer" role="dialog" aria-modal="true" aria-label="Install plan">
      <div className="lv-v2-modules-drawer__backdrop" onClick={onClose} />
      <aside className="lv-v2-modules-drawer__panel">
        <header className="lv-v2-modules-drawer__head">
          <h3>Install plan</h3>
          <button type="button" className="lv-v2-modules-icon-btn" onClick={onClose} aria-label="Sluiten">
            ×
          </button>
        </header>

        {!plan ? (
          <p className="lv-v2-modules-muted">Nog geen plan — kies Install om een plan te genereren.</p>
        ) : (
          <>
            <dl className="lv-v2-modules-dl">
              <div>
                <dt>Module</dt>
                <dd>{plan.moduleId}</dd>
              </div>
              <div>
                <dt>Requested ref</dt>
                <dd>{plan.requestedRef}</dd>
              </div>
              <div>
                <dt>Strategies</dt>
                <dd>{plan.strategies.join(", ") || "—"}</dd>
              </div>
              <div>
                <dt>Package manager</dt>
                <dd>{plan.packageManager || "—"}</dd>
              </div>
              <div>
                <dt>Privilege</dt>
                <dd>{plan.privilegeState || "—"}</dd>
              </div>
              <div>
                <dt>Plan hash</dt>
                <dd>
                  <code>{plan.planHash.slice(0, 16)}…</code>
                </dd>
              </div>
              <div>
                <dt>Approval</dt>
                <dd>{plan.requiresApproval ? "REQUIRED" : "not required"}</dd>
              </div>
            </dl>

            <h4>Dependencies</h4>
            <ul className="lv-v2-modules-deps-list">
              {plan.observations.map((o) => (
                <li key={o.dependencyId}>
                  <strong>{o.dependencyId}</strong>
                  <span className={`lv-v2-modules-badge is-${dependencyStateTone(o.state)}`}>
                    {dependencyStateLabel(o.state)}
                  </span>
                  {o.detail ? <span className="lv-v2-modules-muted">{o.detail}</span> : null}
                </li>
              ))}
              {plan.observations.length === 0 ? <li className="lv-v2-modules-muted">Geen dependency observations</li> : null}
            </ul>

            {plan.blockers.length > 0 ? (
              <>
                <h4>Blockers</h4>
                <pre className="lv-v2-modules-code">{JSON.stringify(plan.blockers, null, 2)}</pre>
              </>
            ) : null}

            <h4>Phases</h4>
            <ol className="lv-v2-modules-phases">
              {phases.map((p) => (
                <li key={p.id} className={`is-${p.state}`}>
                  {p.label}
                </li>
              ))}
            </ol>

            {operation?.errorDetail ? (
              <p className="lv-v2-modules-error" role="alert">
                {operation.errorCode ? `${operation.errorCode}: ` : ""}
                {operation.errorDetail}
              </p>
            ) : null}

            <div className="lv-v2-modules-drawer__actions">
              {failed ? (
                <button type="button" className="lv-v2-modules-btn is-primary" disabled={busy} onClick={onRetry}>
                  Retry install
                </button>
              ) : (
                <button
                  type="button"
                  className="lv-v2-modules-btn is-primary"
                  disabled={busy || !plan.installable || primaryCta.includes("PROGRESS") || primaryCta === "INSTALLED"}
                  onClick={onApproveAndInstall}
                >
                  {primaryCta}
                </button>
              )}
              <button type="button" className="lv-v2-modules-btn" onClick={onClose}>
                Sluiten
              </button>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
