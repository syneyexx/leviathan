import { DS_ACTIVITY_PERIODS } from "../../pages/datasets/constants";
import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";

type Props = {
  ws: DatasetsWorkspace;
};

export function DatasetsBottomWidgets({ ws }: Props) {
  const services = ws.overview?.services ?? [];
  const recentActivity = ws.filteredActivity.slice(0, 6);

  return (
    <div className="lv-v2-ds-bottom">
      <article className="lv-v2-panel lv-v2-ds-widget" aria-label="Dataset verwerking">
        <header className="lv-v2-ds-widget__head">
          <h3>Dataset Verwerking</h3>
          <span className="lv-v2-ds-widget__badge">Actieve taken ({ws.activeJobCount})</span>
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
                <span>{item.pct == null ? "UNMEASURED" : `${item.pct}%`}</span>
                <span>{item.eta}</span>
                {item.jobId ? (
                  <button
                    type="button"
                    className="lv-v2-ds-widget__link"
                    disabled={ws.busy}
                    onClick={() => void ws.onCancelDatasetJob(item.jobId!)}
                  >
                    Annuleer
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </article>

      <article className="lv-v2-panel lv-v2-ds-widget" aria-label="Bron integraties">
        <header className="lv-v2-ds-widget__head">
          <h3>Bron Integraties</h3>
          <button type="button" className="lv-v2-ds-widget__link" onClick={() => ws.setModal("hf")}>
            + Nieuwe bron
          </button>
        </header>
        {ws.overviewLoading && !ws.overview ? (
          <p className="lv-v2-muted">Services laden…</p>
        ) : services.length === 0 ? (
          <p className="lv-v2-muted">
            {ws.overviewError ? "Overview unavailable" : "Geen service projecties gerapporteerd"}
          </p>
        ) : (
          <ul className="lv-v2-ds-services">
            {services.slice(0, 6).map((svc) => {
              const active =
                svc.measured &&
                ["running", "ready", "busy", "active"].includes((svc.state || "").toLowerCase());
              return (
                <li key={svc.id}>
                  <span>{svc.name || svc.id}</span>
                  <span className={`lv-v2-ds-svc-pill is-${active ? "ok" : "unk"}`}>
                    {!svc.measured
                      ? "UNMEASURED"
                      : active
                        ? svc.label || "Actief"
                        : svc.label || svc.state || "UNKNOWN"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <button
          type="button"
          className="lv-v2-ds-widget__link"
          onClick={() => ws.openManageStorage()}
        >
          Bekijk alle →
        </button>
      </article>

      <article className="lv-v2-panel lv-v2-ds-widget" aria-label="Dataset opslag">
        <header className="lv-v2-ds-widget__head">
          <h3>Dataset Opslag</h3>
        </header>
        <p className="lv-v2-ds-storage-summary">
          {ws.storage.usedLabel}
          {ws.storage.capacityLabel ? ` / ${ws.storage.capacityLabel}` : " / UNMEASURED"}
          {ws.storage.estimated ? " (geschat)" : ""}
        </p>
        <div className={`lv-v2-ds-bar${ws.storage.pct == null ? " is-indeterminate" : ""}`}>
          <i style={ws.storage.pct != null ? { width: `${ws.storage.pct}%` } : undefined} />
        </div>
        <p className="lv-v2-muted">
          {ws.storage.pct != null
            ? `${ws.storage.pct}% gebruikt`
            : ws.storage.measurementNote || "Capaciteit UNMEASURED"}
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
      </article>

      <article className="lv-v2-panel lv-v2-ds-widget lv-v2-ds-widget--activity" aria-label="Dataset activiteit">
        <header className="lv-v2-ds-widget__head">
          <h3>Dataset Activiteit</h3>
          <select
            className="lv-v2-select lv-v2-select--xs"
            value={ws.activityPeriod}
            onChange={(e) => ws.setActivityPeriod(e.target.value)}
            aria-label="Activiteitsperiode"
          >
            {DS_ACTIVITY_PERIODS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </header>
        {ws.jobsError ? <p className="lv-v2-warn">{ws.jobsError}</p> : null}
        {recentActivity.length === 0 ? (
          <p className="lv-v2-muted">Geen activiteit in deze periode</p>
        ) : (
          <ul className="lv-v2-ds-activity-mini" aria-label="Recente activiteit">
            {recentActivity.map((e) => (
              <li key={e.id}>
                <time>{e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : "—"}</time>
                <span>{e.message}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="lv-v2-ds-widget__foot">
          <button
            type="button"
            className="lv-v2-ds-widget__link"
            onClick={() => ws.setModal("activity")}
          >
            Bekijk alle activiteiten →
          </button>
          <button type="button" className="lv-v2-ds-widget__link" onClick={() => ws.setModal("health")}>
            Health →
          </button>
        </div>
      </article>
    </div>
  );
}
