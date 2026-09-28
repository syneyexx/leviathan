import { asRecord, type LabRunRecord } from "../viewModels";

export function ResearchLabPaperPanel({
  lab,
  learning,
}: {
  lab: LabRunRecord | null;
  learning: LabRunRecord | null;
}) {
  const meta = asRecord(lab?.metadata) || {};
  const learningMeta = asRecord(learning?.metadata) || {};
  const paperId =
    meta.paper_deployment_id != null
      ? String(meta.paper_deployment_id)
      : learningMeta.paper_deployment_id != null
        ? String(learningMeta.paper_deployment_id)
        : null;
  const paperStatus =
    meta.paper_status != null
      ? String(meta.paper_status)
      : learningMeta.paper_status != null
        ? String(learningMeta.paper_status)
        : null;

  if (!paperId && !paperStatus) {
    return (
      <div className="lv-rl-empty">
        <strong>EMPTY / UNMEASURED</strong>
        No paper deployment is linked to this research lab. Qualification / paper promotion is a separate
        operator path — this panel does not invent session PnL or live fills.
      </div>
    );
  }

  return (
    <article className="lv-rl-card">
      <h3>Paper linkage</h3>
      <dl className="lv-rl-dl">
        <div>
          <dt>Paper deployment</dt>
          <dd>{paperId || "—"}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{paperStatus || "UNMEASURED"}</dd>
        </div>
      </dl>
      <p className="lv-rl-card-hint">
        Values shown only when present on lab / learning metadata. Live trading is not controlled here.
      </p>
    </article>
  );
}
