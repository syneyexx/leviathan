import { Link, useNavigate } from "react-router-dom";
import type { MediaOverview } from "../../hooks/useMediaOverview";
import { MEDIA_KIND_LABEL } from "../../lib/mediaClassify";
import { Badge, Button, EmptyState, LoadingState, Panel, ProgressBar } from "../ui";

type Props = {
  overview: MediaOverview;
};

const KIND_TONE: Record<string, "info" | "research" | "warning" | "data"> = {
  image: "info",
  video: "research",
  audio: "warning",
  document: "data",
};

const KIND_COLOR: Record<string, string> = {
  image: "#38bdf8",
  video: "#a855f7",
  audio: "#eab308",
  document: "#22d3ee",
};

function StorageDonut({
  pct,
  usedLabel,
  totalLabel,
}: {
  pct: number | null;
  usedLabel: string;
  totalLabel: string;
}) {
  const value = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  const r = 42;
  const c = 2 * Math.PI * r;
  const filled = (value / 100) * c;
  return (
    <div className="lv-v2-media-donut" aria-hidden={pct == null}>
      <svg viewBox="0 0 120 120" width="132" height="132">
        <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(148,163,184,0.12)" strokeWidth="14" />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          stroke="#22d3ee"
          strokeWidth="14"
          strokeDasharray={`${filled} ${c - filled}`}
          strokeLinecap="round"
          transform="rotate(-90 60 60)"
        />
      </svg>
      <div className="lv-v2-media-donut__center">
        <strong>{usedLabel}</strong>
        <span>van {totalLabel}</span>
      </div>
    </div>
  );
}

function RecentThumb({ kind }: { kind: string }) {
  if (kind === "video") {
    return (
      <div className="lv-v2-media-thumb lv-v2-media-thumb--video" aria-hidden="true">
        <span className="lv-v2-media-thumb__play" />
      </div>
    );
  }
  if (kind === "audio") {
    return (
      <div className="lv-v2-media-thumb lv-v2-media-thumb--audio" aria-hidden="true">
        <span className="lv-v2-media-thumb__wave" />
      </div>
    );
  }
  if (kind === "document") {
    return (
      <div className="lv-v2-media-thumb lv-v2-media-thumb--doc" aria-hidden="true">
        PDF
      </div>
    );
  }
  return <div className="lv-v2-media-thumb lv-v2-media-thumb--image" aria-hidden="true" />;
}

export function MediaOpsGrid({ overview }: Props) {
  const navigate = useNavigate();
  const { storage, recentMedia, generationJobs, loading } = overview;

  return (
    <section className="lv-v2-ops-grid lv-v2-media-ops" aria-label="Media opslag en generatie">
      <Panel
        title="Media Opslag"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <ellipse cx="12" cy="6" rx="7" ry="3" />
            <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
          </svg>
        }
        action={
          <Badge tone={storage.available ? "success" : "muted"}>
            {storage.available ? `${storage.pctLabel} gebruikt` : "N/A"}
          </Badge>
        }
      >
        {loading && !storage.available ? (
          <LoadingState label="Opslag laden…" />
        ) : !storage.available ? (
          <EmptyState title="Opslag unavailable" detail={storage.note} />
        ) : (
          <div className="lv-v2-media-storage">
            <StorageDonut
              pct={storage.usedPct}
              usedLabel={storage.usedLabel}
              totalLabel={storage.totalLabel}
            />
            <ul className="lv-v2-media-storage__legend">
              {storage.slices.map((slice) => (
                <li key={slice.kind}>
                  <span
                    className="lv-v2-media-storage__dot"
                    style={{ background: KIND_COLOR[slice.kind] }}
                  />
                  <span>{slice.label}</span>
                  <em data-truth="unavailable">UNAVAILABLE</em>
                </li>
              ))}
            </ul>
            <p className="lv-v2-panel__meta">{storage.note}</p>
          </div>
        )}
      </Panel>

      <Panel
        title="Recente Media"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <rect x="4" y="5" width="16" height="14" rx="2" />
            <path d="M4 15l4-3 3 2 4-4 5 5" />
          </svg>
        }
        action={
          <Link to="/media/library" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm">
            Alles bekijken
          </Link>
        }
      >
        {loading && recentMedia.length === 0 ? (
          <LoadingState />
        ) : recentMedia.length === 0 ? (
          <EmptyState
            title="Geen recente media"
            detail="Voltooide media jobs verschijnen hier."
          />
        ) : (
          <div className="lv-v2-media-recent">
            {recentMedia.map((item) => (
              <Link key={item.id} to={item.to} className="lv-v2-media-recent__item">
                <RecentThumb kind={item.kind} />
                {item.durationLabel ? (
                  <span className="lv-v2-media-recent__dur">{item.durationLabel}</span>
                ) : null}
                <div className="lv-v2-media-recent__meta">
                  <strong title={item.name}>{item.name}</strong>
                  <span>{item.relative}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Media Generatie"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M12 4v16M4 12h16" />
          </svg>
        }
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate("/media/genereren")}>
            + Nieuwe generatie
          </Button>
        }
      >
        {loading && generationJobs.length === 0 ? (
          <LoadingState />
        ) : generationJobs.length === 0 ? (
          <EmptyState
            title="Geen generatiejobs"
            detail="Start een nieuwe generatie om voortgang te zien."
          />
        ) : (
          <div className="lv-v2-list lv-v2-media-gen-list">
            {generationJobs.map((job) => (
              <div key={job.id} className="lv-v2-list-row lv-v2-media-gen-row">
                <span
                  className={`lv-v2-status-dot ${
                    job.tone === "done"
                      ? "lv-v2-status-dot--success"
                      : job.tone === "failed"
                        ? "lv-v2-status-dot--danger"
                        : job.tone === "running"
                          ? "lv-v2-status-dot--success"
                          : "lv-v2-status-dot--warning"
                  }`}
                />
                <span className="lv-v2-media-gen-row__title" title={job.title}>
                  {job.title}
                </span>
                <Badge tone={KIND_TONE[job.kind] ?? "muted"}>{MEDIA_KIND_LABEL[job.kind]}</Badge>
                <ProgressBar value={job.progress} label={job.progressLabel} />
                <span className="lv-v2-media-gen-row__time">{job.timeLabel}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </section>
  );
}
