import { Link, useNavigate } from "react-router-dom";
import type { MediaOverview } from "../../hooks/useMediaOverview";
import type { TypesRange } from "../../lib/mediaClassify";
import { MEDIA_STATUS_LABEL } from "../../lib/mediaConnection";
import { Badge, Button, EmptyState, Panel, Sparkline } from "../ui";

type Props = {
  overview: MediaOverview;
};

const KIND_COLORS = {
  image: "#38bdf8",
  video: "#a855f7",
  audio: "#eab308",
  document: "#22d3ee",
} as const;

function PlatformGlyph({ id }: { id: string }) {
  const label =
    id === "youtube"
      ? "YT"
      : id === "tiktok"
        ? "TT"
        : id === "instagram"
          ? "IG"
          : id === "linkedin"
            ? "in"
            : "X";
  return <span className={`lv-v2-media-plat lv-v2-media-plat--${id}`}>{label}</span>;
}

function TypesChart({ overview }: { overview: MediaOverview }) {
  const days = overview.typesSeries;
  const max = Math.max(
    1,
    ...days.flatMap((d) => [d.counts.image, d.counts.video, d.counts.audio, d.counts.document]),
  );
  const hasData = days.some(
    (d) => d.counts.image + d.counts.video + d.counts.audio + d.counts.document > 0,
  );

  if (!hasData) {
    return (
      <EmptyState
        title="Geen analytics in periode"
        detail="Media jobs in het geselecteerde venster verschijnen hier."
      />
    );
  }

  return (
    <div className="lv-v2-media-types">
      <div className="lv-v2-media-types__chart" role="img" aria-label="Media types per dag">
        {days.map((day) => (
          <div key={day.key} className="lv-v2-media-types__day">
            <div className="lv-v2-media-types__bars">
              {(Object.keys(KIND_COLORS) as Array<keyof typeof KIND_COLORS>).map((kind) => (
                <span
                  key={kind}
                  className="lv-v2-media-types__bar"
                  style={{
                    height: `${Math.max(4, (day.counts[kind] / max) * 100)}%`,
                    background: KIND_COLORS[kind],
                    opacity: day.counts[kind] === 0 ? 0.25 : 1,
                  }}
                  title={`${kind}: ${day.counts[kind]}`}
                />
              ))}
            </div>
            <span className="lv-v2-media-types__label">{day.label}</span>
          </div>
        ))}
      </div>
      <ul className="lv-v2-media-types__legend">
        <li>
          <i style={{ background: KIND_COLORS.image }} /> Afbeeldingen
        </li>
        <li>
          <i style={{ background: KIND_COLORS.video }} /> Video&apos;s
        </li>
        <li>
          <i style={{ background: KIND_COLORS.audio }} /> Audio
        </li>
        <li>
          <i style={{ background: KIND_COLORS.document }} /> Documenten
        </li>
      </ul>
    </div>
  );
}

export function MediaMidGrid({ overview }: Props) {
  const navigate = useNavigate();
  const { typesRange, setTypesRange, tools, platforms } = overview;

  return (
    <section className="lv-v2-activity-grid lv-v2-media-mid" aria-label="Media types tools distributie">
      <Panel
        title="Media Types"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M4 19V5M8 19v-8M12 19v-5M16 19V8M20 19v-3" />
          </svg>
        }
        action={
          <select
            className="lv-v2-select"
            aria-label="Periode media types"
            value={typesRange}
            onChange={(e) => setTypesRange(e.target.value as TypesRange)}
          >
            <option value="24h">Afgelopen 24 uur</option>
            <option value="7d">Afgelopen 7 dagen</option>
            <option value="30d">Afgelopen 30 dagen</option>
            <option value="90d">Afgelopen 90 dagen</option>
          </select>
        }
      >
        <TypesChart overview={overview} />
      </Panel>

      <Panel
        title="AI Media Tools"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M12 3l2.2 4.5L19 8.2l-3.5 3.4.8 4.9L12 14.2 7.7 16.5l.8-4.9L5 8.2l4.8-.7L12 3z" />
          </svg>
        }
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate("/media/genereren")}>
            Open Studio
          </Button>
        }
      >
        <div className="lv-v2-media-tools">
          {tools.map((tool) => (
            <Link
              key={tool.id}
              to={tool.to}
              className={`lv-v2-media-tool${tool.available ? "" : " is-unavailable"}`}
              data-truth={tool.available ? "capability" : "unavailable"}
            >
              <strong>{tool.title}</strong>
              <span>{tool.subtitle}</span>
            </Link>
          ))}
        </div>
      </Panel>

      <Panel
        title="Distributie Status"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <circle cx="6" cy="12" r="2.2" />
            <circle cx="18" cy="7" r="2.2" />
            <circle cx="18" cy="17" r="2.2" />
            <path d="M8 12h3.5M14.2 8.2l-2.5 2.2M14.2 15.8l-2.5-2.2" />
          </svg>
        }
        action={
          <Link to="/media/planning" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm">
            Planning bekijken
          </Link>
        }
      >
        <div className="lv-v2-list lv-v2-media-dist">
          {platforms.map((p) => (
            <Link key={p.id} to={p.to} className="lv-v2-list-row lv-v2-media-dist-row" data-truth="not-connected">
              <PlatformGlyph id={p.id} />
              <span className="lv-v2-media-dist-row__name">{p.name}</span>
              <Badge tone={p.connected ? "success" : "muted"}>
                {p.connected ? "Actief" : MEDIA_STATUS_LABEL}
              </Badge>
              <span className="lv-v2-media-dist-row__count">{p.countLabel}</span>
              {p.spark.length >= 2 ? (
                <Sparkline values={p.spark} width={56} height={22} stroke="#22d3ee" />
              ) : (
                <span className="lv-v2-media-dist-row__spark-empty" aria-hidden="true" />
              )}
            </Link>
          ))}
        </div>
      </Panel>
    </section>
  );
}
