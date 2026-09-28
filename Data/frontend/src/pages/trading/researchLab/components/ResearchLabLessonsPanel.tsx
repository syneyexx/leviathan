import { fmtMetric, type LabRunRecord } from "../viewModels";

export function ResearchLabLessonsPanel({
  lessons,
  loading,
}: {
  lessons: LabRunRecord[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="lv-rl-skel">
        <div className="lv-rl-skel-bar" style={{ height: 160 }} />
      </div>
    );
  }

  if (lessons.length === 0) {
    return (
      <div className="lv-rl-empty">
        <strong>EMPTY / UNMEASURED</strong>
        No lessons recorded for this lab. Lessons appear after learning cycles emit claims; AGENT_PROPOSED
        claims are not proof.
      </div>
    );
  }

  return (
    <article className="lv-rl-card">
      <h3>Lessons ({lessons.length})</h3>
      <p className="lv-rl-card-hint" style={{ marginBottom: 10 }}>
        Trust labels are epistemic — not measured alpha.
      </p>
      <div className="lv-rl-table-wrap" style={{ maxHeight: 520 }}>
        <table className="lv-rl-table">
          <thead>
            <tr>
              <th>Trust</th>
              <th>Claim</th>
              <th>Confidence</th>
              <th>Id</th>
            </tr>
          </thead>
          <tbody>
            {lessons.map((l) => (
              <tr key={String(l.lesson_id)}>
                <td>{String(l.trust || "—")}</td>
                <td>{String(l.claim || "—")}</td>
                <td>{fmtMetric(l.confidence)}</td>
                <td>{String(l.lesson_id || "—").slice(0, 12)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
