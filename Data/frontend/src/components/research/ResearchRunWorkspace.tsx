import { Link } from "react-router-dom";
import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import { confTone, statusBadgeTone, statusLabelNl } from "../../pages/research/researchHelpers";
import { Badge, Button, Panel, ProgressBar } from "../ui";

type Props = {
  ws: ResearchWorkspace;
};

export function ResearchRunWorkspace({ ws }: Props) {
  const { project } = ws;
  if (!project) return null;

  const progressLabel =
    ws.progress == null ? "UNMEASURED" : `${ws.progress}%`;

  return (
    <section className="lv-v2-research-run" aria-label="Actief onderzoek">
      <Panel
        title={project.title || project.topic}
        meta={<Badge tone={statusBadgeTone(project.status)}>{statusLabelNl(project.status)}</Badge>}
        action={
          <div className="lv-v2-research-run__actions">
            {ws.isLive ? (
              <Button
                variant="secondary"
                size="sm"
                loading={ws.busy}
                disabled={ws.busy || project.status === "cancelling"}
                onClick={() => void ws.onCancel()}
              >
                {project.status === "cancelling" ? "Annuleren…" : "Annuleer"}
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={ws.clearSelection}>
              Terug naar overzicht
            </Button>
          </div>
        }
      >
        <div className="lv-v2-research-run__progress">
          <div className="lv-v2-research-run__progress-meta">
            <span>Fase: {(project.phase || project.status).replace(/_/g, " ")}</span>
            <strong>{progressLabel}</strong>
          </div>
          {ws.progress != null ? <ProgressBar value={ws.progress} /> : null}
        </div>
      </Panel>

      <div className="lv-v2-research-run__grid">
        <Panel title="Timeline">
          <ol className="lv-v2-stepper">
            {ws.timeline.map((step) => (
              <li key={step.id} className={`lv-v2-stepper__item is-${step.status}`}>
                <span className="lv-v2-stepper__dot" aria-hidden="true" />
                <div>
                  <strong>{step.label}</strong>
                  {step.meta ? <em>{step.meta}</em> : null}
                </div>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel
          title="Bronnen"
          action={
            <Link className="lv-v2-brain-link" to="/knowledge">
              Knowledge Library
            </Link>
          }
        >
          {ws.sources.length === 0 ? (
            <p className="lv-v2-muted">
              {ws.diagnosis || "Bronnen verschijnen tijdens ingestion/retrieval."}
            </p>
          ) : (
            <ul className="lv-v2-research-source-list">
              {ws.evidenceRows.map((s) => (
                <li key={s.id}>
                  <strong>
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noopener noreferrer">
                        {s.title}
                      </a>
                    ) : (
                      s.title
                    )}
                  </strong>
                  <span>
                    {s.domain} · {s.supportLabel} · {s.ago}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {ws.ingestionProgress ? (
            <p className="lv-v2-muted" style={{ marginTop: 8 }}>
              Ingestie: {ws.ingestionProgress.phase || ws.ingestionProgress.status}
              {ws.ingestionProgress.progress_pct != null
                ? ` · ${Math.round(ws.ingestionProgress.progress_pct)}%`
                : " · UNMEASURED"}
              {` · brain synced ${ws.ingestionProgress.brain_synced} / failed ${ws.ingestionProgress.brain_failed}`}
              {ws.ingestionTotal > 0 ? ` · members ${ws.ingestionMembers.length}/${ws.ingestionTotal}` : ""}
            </p>
          ) : null}
        </Panel>

        <Panel
          title="Evidence & Claims"
          action={
            <Link className="lv-v2-brain-link" to="/evidence">
              Evidence Vault
            </Link>
          }
        >
          {ws.insightRows.length === 0 ? (
            <p className="lv-v2-muted">
              {ws.diagnosis ||
                (ws.isLive
                  ? "Claims verschijnen na claim analysis."
                  : "Nog geen claims voor dit project.")}
            </p>
          ) : (
            <ul className="lv-v2-research-insight-list">
              {ws.insightRows.map((item) => {
                const label = item.supportLabel ?? "Unmeasured";
                return (
                  <li key={item.id}>
                    <strong>{item.title}</strong>
                    <p>{item.body}</p>
                    <span className={`lv-v2-conf is-${confTone(label)}`}>{label}</span>
                  </li>
                );
              })}
            </ul>
          )}
          {ws.gaps.length > 0 ? (
            <div className="lv-v2-research-gaps">
              <h4>Open gaps</h4>
              <ul>
                {ws.gaps.slice(0, 6).map((g, i) => (
                  <li key={i}>{String((g as { question?: string; summary?: string }).question || (g as { summary?: string }).summary || JSON.stringify(g).slice(0, 120))}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {ws.conflicts.length > 0 ? (
            <div className="lv-v2-research-gaps">
              <h4>Conflicts</h4>
              <ul>
                {ws.conflicts.slice(0, 4).map((c) => (
                  <li key={c.conflict_id}>{c.summary}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </Panel>

        <Panel
          title="Web Results"
          action={
            <Link className="lv-v2-brain-link" to="/brain">
              Brain
            </Link>
          }
        >
          {ws.webRows.length === 0 ? (
            <p className="lv-v2-muted">
              {ws.diagnosis ||
                (project.allow_web
                  ? "Web results appear after retrieval."
                  : "Web is uitgeschakeld voor dit project.")}
            </p>
          ) : (
            <ul className="lv-v2-research-web-list">
              {ws.webRows.map((item) => (
                <li key={item.id}>
                  <span className="lv-v2-research-web-list__rank">{item.rank}</span>
                  <div>
                    <strong>
                      {item.url ? (
                        <a href={item.url} target="_blank" rel="noopener noreferrer">
                          {item.title}
                        </a>
                      ) : (
                        item.title
                      )}
                    </strong>
                    <em>{item.domain}</em>
                    <p>{item.snippet}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {ws.report ? (
          <Panel title="Report" className="lv-v2-research-run__report">
            <h4>{ws.report.title}</h4>
            <pre className="lv-v2-research-report">{ws.report.body_markdown.slice(0, 4000)}</pre>
          </Panel>
        ) : null}
      </div>
    </section>
  );
}
