import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";

type Props = {
  ws: DatasetsWorkspace;
};

export function DatasetsBottomWidgets({ ws }: Props) {
  const services = ws.overview?.services ?? [];
  const recentActivity = ws.activityEntries.slice(0, 8);

  return (
    <div className="lv-v2-ds-bottom">
      <article className="lv-v2-panel lv-v2-ds-widget" aria-label="Dataset pipeline">
        <header className="lv-v2-ds-widget__head">
          <h3>Dataset Pipeline</h3>
          <button type="button" className="lv-v2-ds-widget__link" onClick={() => void ws.onProcessQueue()}>
            Process queue →
          </button>
        </header>
        <ul className="lv-v2-ds-pipeline">
          {ws.pipelineItems.map((item) => (
            <li key={item.id}>
              <div className="lv-v2-ds-pipeline__title">{item.title}</div>
              <div className="lv-v2-ds-pipeline__detail">{item.detail}</div>
              <div className={`lv-v2-ds-bar${item.pct == null ? " is-indeterminate" : ""}`}>
                <i style={item.pct != null ? { width: `${item.pct}%` } : undefined} />
              </div>
              <div className="lv-v2-ds-pipeline__meta">
                <span>{item.pct == null ? "progress unmeasured" : `${item.pct}%`}</span>
                <span>{item.eta}</span>
              </div>
            </li>
          ))}
        </ul>
      </article>

      <article className="lv-v2-panel lv-v2-ds-widget" aria-label="Source integrations">
        <header className="lv-v2-ds-widget__head">
          <h3>Source Integrations</h3>
        </header>
        {ws.overviewLoading && !ws.overview ? (
          <p className="lv-v2-muted">Loading services…</p>
        ) : services.length === 0 ? (
          <p className="lv-v2-muted">
            {ws.overviewError ? "Overview unavailable" : "No service projections reported"}
          </p>
        ) : (
          <ul className="lv-v2-ds-services">
            {services.slice(0, 8).map((svc) => (
              <li key={svc.id}>
                <span>{svc.name || svc.id}</span>
                <span className={`lv-v2-ds-svc-pill is-${svc.measured ? "ok" : "unk"}`}>
                  {svc.measured ? svc.label || svc.state : "UNMEASURED"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </article>

      <article className="lv-v2-panel lv-v2-ds-widget" aria-label="Dataset storage">
        <header className="lv-v2-ds-widget__head">
          <h3>Dataset Storage</h3>
        </header>
        <p className="lv-v2-ds-storage-summary">
          {ws.storage.usedLabel}
          {ws.storage.capacityLabel ? ` of ${ws.storage.capacityLabel}` : ""}
          {ws.storage.estimated ? " (estimated)" : ""}
        </p>
        <div className={`lv-v2-ds-bar${ws.storage.pct == null ? " is-indeterminate" : ""}`}>
          <i style={ws.storage.pct != null ? { width: `${ws.storage.pct}%` } : undefined} />
        </div>
        <p className="lv-v2-muted">
          {ws.storage.pct != null
            ? `${ws.storage.pct}% used`
            : ws.storage.measurementNote || "Capacity unmeasured"}
        </p>
        <ul className="lv-v2-ds-legend">
          {ws.storage.segments.map((seg) => (
            <li key={seg.id}>
              <i style={{ background: seg.color }} />
              <span>{seg.label}</span>
              <b>{seg.bytesLabel}</b>
            </li>
          ))}
        </ul>
        <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" onClick={ws.openManageStorage}>
          Manage Storage
        </button>
      </article>

      <article className="lv-v2-panel lv-v2-ds-widget" aria-label="Dataset health">
        <header className="lv-v2-ds-widget__head">
          <h3>Dataset Health</h3>
        </header>
        <ul className="lv-v2-ds-health">
          {ws.healthItems.map((item) => (
            <li key={item.id}>
              <span className="lv-v2-ds-health__label">{item.label}</span>
              <span className={`lv-v2-ds-health__pct is-${item.tone}`}>
                {item.pct == null ? "UNMEASURED" : `${item.pct}%`}
              </span>
              {item.hint ? <span className="lv-v2-ds-health__hint">{item.hint}</span> : null}
              <div className={`lv-v2-ds-health__bar is-${item.tone}`}>
                <i style={{ width: `${item.pct ?? 0}%` }} />
              </div>
            </li>
          ))}
        </ul>
        {recentActivity.length > 0 ? (
          <ul className="lv-v2-ds-activity-mini" aria-label="Recent activity">
            {recentActivity.slice(0, 4).map((e) => (
              <li key={e.id}>
                <time>{e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : "—"}</time>
                <span>{e.message}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </article>
    </div>
  );
}
