import type { TrainingWorkspace } from "../../hooks/useTrainingWorkspace";
import { Badge, Button, Dialog } from "../ui";

type Props = {
  ws: TrainingWorkspace;
};

export function TrainingPreflightDrawer({ ws }: Props) {
  const pf = ws.preflight;
  const plan = ws.plan;
  const blocked = pf?.verdict === "BLOCKED";

  return (
    <Dialog
      open={ws.preflightOpen}
      title="Nieuwe training — preflight"
      onClose={() => ws.setPreflightOpen(false)}
      cancelLabel="Sluiten"
    >
      <div className="lv-v2-training-preflight">
        <p className="lv-v2-muted">
          Controleer config, hardware en dataset voordat de job wordt aangemaakt. Fixture-methode is
          niet beschikbaar in productie.
        </p>

        <dl className="lv-v2-training-preflight__summary">
          <div>
            <dt>Naam</dt>
            <dd>{ws.draft.name}</dd>
          </div>
          <div>
            <dt>Methode</dt>
            <dd>{ws.draft.method.toUpperCase()}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{ws.draft.baseModelRef || ws.selectedModelId || "—"}</dd>
          </div>
          <div>
            <dt>Dataset versie</dt>
            <dd>{ws.draft.datasetVersionId || ws.selectedVersionId || "—"}</dd>
          </div>
          <div>
            <dt>Device</dt>
            <dd>
              {ws.draft.deviceStrategy}
              {ws.draft.selectedStableDeviceId ? ` · ${ws.draft.selectedStableDeviceId}` : ""}
            </dd>
          </div>
        </dl>

        <div className="lv-v2-training-preflight__verdict">
          <span>Preflight</span>
          {pf ? (
            <Badge
              tone={
                pf.verdict === "PASS" ? "success" : pf.verdict === "WARNING" ? "warning" : "danger"
              }
            >
              {pf.verdict}
            </Badge>
          ) : (
            <span className="lv-v2-muted">Nog niet uitgevoerd</span>
          )}
        </div>

        {pf?.issues?.length ? (
          <ul className="lv-v2-training-preflight__issues">
            {pf.issues.map((issue, i) => (
              <li key={`${issue.code}-${i}`}>
                <Badge
                  tone={
                    issue.severity === "error" || issue.severity === "BLOCKED"
                      ? "danger"
                      : issue.severity === "warning"
                        ? "warning"
                        : "muted"
                  }
                >
                  {issue.severity}
                </Badge>
                <span>
                  {issue.code}: {issue.message}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        {plan ? (
          <div className="lv-v2-training-preflight__plan">
            <h4>Planner</h4>
            <p>
              {plan.strategy} — {plan.reason}
            </p>
            <ul>
              <li>
                Batch {plan.trainBatchSize} × accum {plan.gradientAccumulation} → effective{" "}
                {plan.effectiveBatchSize}
              </li>
              <li>
                Seq {plan.maxSeqLength} · {plan.precision}
                {plan.gradientCheckpointing ? " · grad ckpt" : ""}
                {plan.loadIn4bit ? " · 4-bit" : ""}
              </li>
            </ul>
            {plan.warnings?.length ? (
              <ul className="lv-v2-training-preflight__warnings">
                {plan.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        <div className="lv-v2-training-preflight__actions">
          <Button variant="secondary" size="sm" loading={ws.busy} onClick={() => void ws.runPreflight()}>
            Opnieuw preflight
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={ws.busy}
            disabled={blocked}
            onClick={() => void ws.createJob(false)}
          >
            Alleen aanmaken
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={ws.busy}
            disabled={blocked || Boolean(ws.methodDisabledReason(ws.draft.method))}
            onClick={() => void ws.createJob(true)}
          >
            Start training
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
