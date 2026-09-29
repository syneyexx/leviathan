import { Link } from "react-router-dom";
import type { DashboardOverview } from "../../hooks/useDashboardOverview";
import { Badge, EmptyState, ErrorState, Gauge, LoadingState, Panel, ProgressBar } from "../ui";

type Props = {
  overview: DashboardOverview;
};

export function DashboardOperationsGrid({ overview }: Props) {
  const { healthGauges, workers, workersAvailable, queue, loading, errors } = overview;
  const g = healthGauges;

  return (
    <section className="lv-v2-ops-grid" aria-label="Operaties">
      <Panel
        title="Systeem Gezondheid"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M4 14h3l2-5 3 10 2-6h4" />
          </svg>
        }
        action={
          g.cpu.available || g.ram.available || g.gpu.available || g.disk.available ? (
            <Badge tone="success">Gezond</Badge>
          ) : (
            <Badge tone="muted">UNMEASURED</Badge>
          )
        }
      >
        {loading && !g.cpu.available && !g.ram.available ? (
          <LoadingState label="Telemetry laden…" />
        ) : errors.telemetry && !g.cpu.available ? (
          <ErrorState title="Telemetry unavailable" detail={errors.telemetry} />
        ) : (
          <div className="lv-v2-gauges">
            <Gauge label="CPU" value={g.cpu.available ? g.cpu.pct : null} sublabel={g.cpu.sublabel} color="#22d3ee" />
            <Gauge label="RAM" value={g.ram.available ? g.ram.pct : null} sublabel={g.ram.sublabel} color="#3b82f6" />
            <Gauge label="GPU" value={g.gpu.available ? g.gpu.pct : null} sublabel={g.gpu.sublabel} color="#84cc16" />
            <Gauge label="Schijf" value={g.disk.available ? g.disk.pct : null} sublabel={g.disk.sublabel} color="#64748b" />
          </div>
        )}
      </Panel>

      <Panel
        title="Actieve Workers"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <circle cx="12" cy="8" r="3" />
            <path d="M5 19c1.8-3 4.2-4.5 7-4.5S17.2 16 19 19" />
          </svg>
        }
        meta={workersAvailable ? `${workers.length} getoond` : undefined}
      >
        {!workersAvailable ? (
          errors.workers ? (
            <ErrorState title="Workers unavailable" detail={errors.workers} />
          ) : loading ? (
            <LoadingState />
          ) : (
            <EmptyState title="Geen worker data" detail="Worker Fabric status is unavailable." />
          )
        ) : workers.length === 0 ? (
          <EmptyState title="Geen actieve workers" detail="Er draaien momenteel geen busy workers." />
        ) : (
          <div className="lv-v2-list">
            {workers.map((w) => (
              <div key={w.id} className="lv-v2-list-row lv-v2-worker-row">
                <span className={`lv-v2-status-dot lv-v2-status-dot--info`} />
                <span className="lv-v2-worker-row__name" title={w.name}>
                  {w.name}
                </span>
                <span className="lv-v2-worker-row__meta">{w.domain}</span>
                <span className="lv-v2-worker-row__meta">{w.target}</span>
                <div>
                  <ProgressBar value={w.progress} tone="default" label={w.progressLabel} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Taak Queue"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M8 7h11M8 12h11M8 17h11M5 7h.01M5 12h.01M5 17h.01" />
          </svg>
        }
        meta={
          overview.jobs.available
            ? `${overview.jobs.active ?? 0} actief / ${overview.jobs.queued ?? 0} totaal`
            : undefined
        }
        action={
          <Link to="/tasks" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm">
            Open
          </Link>
        }
      >
        {queue.length === 0 ? (
          loading ? (
            <LoadingState />
          ) : (
            <EmptyState title="Geen actieve jobs" detail="De queue is leeg." />
          )
        ) : (
          <div className="lv-v2-list">
            {queue.map((item, index) => (
              <Link
                key={item.id}
                to={item.to ?? "/tasks"}
                className="lv-v2-list-row lv-v2-queue-row"
              >
                <span className="lv-v2-queue-row__index">{index + 1}</span>
                <span className="lv-v2-queue-row__title" title={item.title}>
                  {item.title}
                </span>
                <Badge tone={item.tone}>{item.domain}</Badge>
                <ProgressBar value={item.progress} />
                <span className="lv-v2-queue-row__time">{item.duration}</span>
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </section>
  );
}
