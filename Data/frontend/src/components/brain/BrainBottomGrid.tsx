import { Link } from "react-router-dom";
import type { BrainOverview } from "../../hooks/useBrainOverview";
import { categoryColor } from "../../pages/brain/brain-categories";
import { Badge, Panel, ProgressBar } from "../ui";

type Props = {
  overview: BrainOverview;
};

function prettyClusterLabel(label: string): string {
  return label
    .split(/[._-]+/g)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function BrainBottomGrid({ overview }: Props) {
  const {
    clusters,
    clustersAvailable,
    activity,
    activityAvailable,
    entityTypes,
    reasoningQueue,
    reasoningAvailable,
    healthGauges,
    evidenceSources,
    evidenceSourcesAvailable,
    loading,
  } = overview;

  const maxCluster = Math.max(1, ...clusters.map((c) => c.nodes));

  return (
    <section className="lv-v2-brain-bottom" aria-label="Brain operationeel overzicht">
      <Panel
        title="Geheugen Clusters"
        action={
          <Link className="lv-v2-brain-link" to="/memory">
            Alles bekijken
          </Link>
        }
      >
        {!clustersAvailable && loading ? (
          <p className="lv-v2-muted">Laden…</p>
        ) : !clustersAvailable ? (
          <p className="lv-v2-muted">UNAVAILABLE</p>
        ) : clusters.length === 0 ? (
          <p className="lv-v2-muted">Geen clusters in deze projectie</p>
        ) : (
          <ul className="lv-v2-stat-list">
            {clusters.slice(0, 6).map((cluster) => (
              <li key={cluster.id} className="lv-v2-stat-list__row">
                <i className="lv-v2-stat-list__dot" style={{ background: cluster.color }} />
                <span className="lv-v2-stat-list__label">{prettyClusterLabel(cluster.label)}</span>
                <strong className="lv-v2-stat-list__value">{cluster.nodes}</strong>
                <ProgressBar value={Math.round((cluster.nodes / maxCluster) * 100)} />
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Recente Kennis Activiteit">
        {!activityAvailable && loading ? (
          <p className="lv-v2-muted">Laden…</p>
        ) : !activityAvailable ? (
          <p className="lv-v2-muted">Geen data</p>
        ) : activity.length === 0 ? (
          <p className="lv-v2-muted">Geen recente activiteit</p>
        ) : (
          <ul className="lv-v2-activity-list">
            {activity.map((row) => (
              <li key={row.id} className="lv-v2-activity-list__row">
                <time>{row.time}</time>
                <span className="lv-v2-activity-list__desc">{row.description}</span>
                <Badge tone={row.tone}>{row.badge}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <div className="lv-v2-brain-bottom__stack">
        <Panel title="Entity Types">
          {entityTypes.length === 0 ? (
            <p className="lv-v2-muted">{loading ? "Laden…" : "Geen data"}</p>
          ) : (
            <ul className="lv-v2-stat-list">
              {entityTypes.map((row) => (
                <li key={row.id} className="lv-v2-stat-list__row">
                  <i
                    className="lv-v2-stat-list__dot"
                    style={{ background: categoryColor(row.category) }}
                  />
                  <span className="lv-v2-stat-list__label">{row.label}</span>
                  <strong className="lv-v2-stat-list__value">
                    {row.count.toLocaleString("nl-NL")}
                  </strong>
                  <span className="lv-v2-stat-list__pct">{row.pct}%</span>
                  <ProgressBar value={row.pct} />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Bewijs Bronnen">
          {!evidenceSourcesAvailable ? (
            <p className="lv-v2-muted">{overview.errors.evidence ? "UNAVAILABLE" : loading ? "Laden…" : "Geen data"}</p>
          ) : evidenceSources.length === 0 ? (
            <p className="lv-v2-muted">Geen bronnen</p>
          ) : (
            <ul className="lv-v2-compact-chips">
              {evidenceSources.map((src) => (
                <li key={src.id}>
                  <span>{src.label}</span>
                  <strong>{src.count}</strong>
                </li>
              ))}
              <li>
                <Link className="lv-v2-brain-link" to="/evidence">
                  Evidence Vault →
                </Link>
              </li>
            </ul>
          )}
        </Panel>
      </div>

      <div className="lv-v2-brain-bottom__stack">
        <Panel title="Redenering Queue">
          {!reasoningAvailable ? (
            <p className="lv-v2-muted">UNAVAILABLE</p>
          ) : reasoningQueue.length === 0 ? (
            <p className="lv-v2-muted">Geen actieve redeneertaken</p>
          ) : (
            <ul className="lv-v2-queue-list">
              {reasoningQueue.map((job, index) => (
                <li key={job.id} className="lv-v2-queue-list__row">
                  <span className="lv-v2-queue-list__idx">{index + 1}</span>
                  <div className="lv-v2-queue-list__main">
                    <div className="lv-v2-queue-list__title-row">
                      <strong>{job.title}</strong>
                      <Badge tone={job.stateTone === "info" ? "info" : job.stateTone === "warning" ? "warning" : "muted"}>
                        {job.state}
                      </Badge>
                    </div>
                    <ProgressBar value={job.progress} />
                    <span className="lv-v2-queue-list__elapsed">{job.elapsed}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Systeem Gezondheid">
          <div className="lv-v2-brain-health">
            {healthGauges.map((g) => (
              <div key={g.id} className="lv-v2-brain-health__item">
                <div
                  className={`lv-v2-brain-health__ring${g.statusLabel === "Goed" ? " is-good" : g.statusLabel === "Fout" || g.statusLabel === "Offline" ? " is-bad" : ""}`}
                  role="img"
                  aria-label={`${g.label}: ${g.statusLabel}`}
                >
                  <span>{g.statusLabel === "Goed" ? "OK" : g.statusLabel.slice(0, 3)}</span>
                </div>
                <span className="lv-v2-brain-health__label">{g.label}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </section>
  );
}
