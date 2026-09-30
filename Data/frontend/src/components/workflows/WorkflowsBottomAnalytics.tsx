import { Gauge, Panel } from "../ui";
import type { WorkflowOverview } from "../../types/api";

type Props = {
  overview: WorkflowOverview | null;
};

export function WorkflowsBottomAnalytics({ overview }: Props) {
  const chart = overview?.chart;
  const resources = overview?.resources;
  const top = overview?.top_workflows?.items ?? [];
  const buckets = chart?.buckets ?? [];
  const maxBucket = Math.max(
    1,
    ...buckets.map((b) => (b.succeeded || 0) + (b.failed || 0) + (b.cancelled || 0)),
  );

  const cpu =
    resources?.cpu?.available && resources.cpu.utilization_pct != null
      ? resources.cpu.utilization_pct
      : null;
  const memUsed = resources?.memory?.used_bytes;
  const memTotal = resources?.memory?.total_bytes;
  const memPct =
    resources?.memory?.available && memUsed != null && memTotal
      ? (memUsed / memTotal) * 100
      : null;
  const workersBusy = resources?.workers?.busy;
  const workersCap = resources?.workers?.capacity;
  const workersPct =
    resources?.workers?.available && workersBusy != null && workersCap
      ? (workersBusy / workersCap) * 100
      : null;

  return (
    <section className="lv-v2-wf-analytics" aria-label="Workflow analytics">
      <Panel title="Workflow Executies (24u)" className="lv-v2-wf-analytics__chart">
        <div className="lv-v2-wf-bars" role="img" aria-label="Executie volume">
          {buckets.length === 0 ? (
            <p className="lv-v2-muted">Geen chart data — UNMEASURED</p>
          ) : (
            buckets.map((b, i) => {
              const total = (b.succeeded || 0) + (b.failed || 0) + (b.cancelled || 0);
              const h = Math.max(4, Math.round((total / maxBucket) * 100));
              return (
                <div key={b.bucket_start || i} className="lv-v2-wf-bars__col" title={`${total}`}>
                  <div className="lv-v2-wf-bars__stack" style={{ height: `${h}%` }}>
                    <i className="is-ok" style={{ flex: b.succeeded || 0.01 }} />
                    <i className="is-bad" style={{ flex: b.failed || 0 }} />
                    <i className="is-cancel" style={{ flex: b.cancelled || 0 }} />
                  </div>
                </div>
              );
            })
          )}
        </div>
        <div className="lv-v2-wf-bars__legend">
          <span>
            <i className="is-ok" /> Succesvol ({chart?.series.succeeded ?? "—"})
          </span>
          <span>
            <i className="is-bad" /> Gefaald ({chart?.series.failed ?? "—"})
          </span>
          <span>
            <i className="is-cancel" /> Geannuleerd ({chart?.series.cancelled ?? "—"})
          </span>
        </div>
      </Panel>

      <Panel title="Resource Gebruik" className="lv-v2-wf-analytics__resources">
        <div className="lv-v2-wf-gauges">
          <Gauge
            label="CPU"
            value={cpu}
            sublabel={resources?.cpu?.display ?? "UNMEASURED"}
            color="#38bdf8"
          />
          <Gauge
            label="Geheugen"
            value={memPct}
            sublabel={resources?.memory?.display ?? "UNMEASURED"}
            color="#a78bfa"
          />
          <Gauge
            label="Actieve Workers"
            value={workersPct}
            sublabel={resources?.workers?.display ?? "UNMEASURED"}
            color="#34d399"
          />
        </div>
      </Panel>

      <Panel title="Top Workflows" className="lv-v2-wf-analytics__top" meta="Laatste 7 dagen">
        <ol className="lv-v2-wf-top-list">
          {top.length === 0 ? (
            <li className="lv-v2-muted">Geen data — UNMEASURED</li>
          ) : (
            top.map((item) => (
              <li key={item.workflow_id}>
                <span className="lv-v2-wf-top-list__rank">{item.rank ?? ""}</span>
                <span className="lv-v2-wf-top-list__name">{item.name}</span>
                <span className="lv-v2-wf-top-list__count">{item.execution_count}</span>
                <span className="lv-v2-wf-top-list__bar">
                  <i style={{ width: `${Math.round((item.relative ?? 0) * 100)}%` }} />
                </span>
              </li>
            ))
          )}
        </ol>
      </Panel>
    </section>
  );
}
