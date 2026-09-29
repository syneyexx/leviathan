import { Link, useNavigate } from "react-router-dom";
import type { DashboardOverview } from "../../hooks/useDashboardOverview";
import { Badge, Button, EmptyState, ErrorState, LoadingState, Panel, ProgressBar, Sparkline } from "../ui";

type Props = {
  overview: DashboardOverview;
};

function formatActivityTime(raw: string): string {
  // Prefer HH:MM if ISO; otherwise show as-is (bounded).
  const d = new Date(raw);
  if (!Number.isNaN(d.getTime())) {
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  return raw.slice(0, 5);
}

export function DashboardActivityGrid({ overview }: Props) {
  const navigate = useNavigate();
  const { activities, research, trading, loading, errors } = overview;

  return (
    <section className="lv-v2-activity-grid" aria-label="Activiteit en domeinen">
      <Panel
        title="Recente Activiteiten"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <circle cx="12" cy="12" r="8" />
            <path d="M12 8v4l3 2" />
          </svg>
        }
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate("/tasks")}>
            Alles bekijken
          </Button>
        }
      >
        {errors.activity && activities.length === 0 ? (
          <ErrorState title="Activiteit unavailable" detail={errors.activity} />
        ) : loading && activities.length === 0 ? (
          <LoadingState />
        ) : activities.length === 0 ? (
          <EmptyState title="Geen recente activiteit" detail="Nog geen gemeten events." />
        ) : (
          <div className="lv-v2-list">
            {activities.map((a) => (
              <div key={a.id} className="lv-v2-list-row lv-v2-activity-row">
                <span className="lv-v2-activity-row__time">{formatActivityTime(a.time)}</span>
                <svg className="lv-v2-activity-row__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                  <circle cx="12" cy="12" r="3" />
                </svg>
                <span title={a.description}>{a.description}</span>
                <Badge tone={a.tone}>{a.domain}</Badge>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Onderzoek Overzicht"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <circle cx="11" cy="11" r="6.5" />
            <path d="M16 16l4 4" />
          </svg>
        }
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate("/research")}>
            Open Research
          </Button>
        }
      >
        {!research.available ? (
          errors.research ? (
            <ErrorState title="Research unavailable" detail={errors.research} />
          ) : loading ? (
            <LoadingState />
          ) : (
            <EmptyState title="Research unavailable" />
          )
        ) : research.projects.length === 0 ? (
          <EmptyState title="Geen projecten" detail="Nog geen research projecten." />
        ) : (
          <div className="lv-v2-list">
            {research.projects.map((p) => (
              <Link key={p.id} to="/research" className="lv-v2-research-row" style={{ textDecoration: "none", color: "inherit" }}>
                <div className="lv-v2-research-row__top">
                  <div>
                    <div className="lv-v2-research-row__title">{p.title}</div>
                    <div className="lv-v2-research-row__sub">{p.subtitle}</div>
                  </div>
                  <Badge tone={p.statusTone}>{p.status}</Badge>
                </div>
                <ProgressBar value={p.progress} tone="research" />
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Trading Overzicht"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M4 16l4.5-5 3.5 3 4-6 4 2" />
          </svg>
        }
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate("/trading/simulatie")}>
            Open Trading
          </Button>
        }
        meta={trading.paper ? "Paper / simulatie" : undefined}
      >
        {!trading.available ? (
          errors.trading ? (
            <ErrorState title="Trading unavailable" detail={errors.trading} />
          ) : loading ? (
            <LoadingState />
          ) : (
            <EmptyState title="Market data unavailable" />
          )
        ) : trading.instruments.length === 0 ? (
          <EmptyState title="Geen marktdata" detail="Geen READY market sources." />
        ) : (
          <div className="lv-v2-list">
            {trading.instruments.map((inst) => {
              const changeClass =
                inst.changePct == null
                  ? ""
                  : inst.changePct >= 0
                    ? "lv-v2-trading-row__change--up"
                    : "lv-v2-trading-row__change--down";
              return (
                <div key={inst.symbol} className="lv-v2-list-row lv-v2-trading-row">
                  <span className="lv-v2-trading-row__symbol">{inst.symbol}</span>
                  <span className="lv-v2-trading-row__side">
                    {inst.unavailable || inst.price == null ? "NO DATA" : inst.side ?? "Sim"}
                  </span>
                  <Sparkline
                    values={inst.spark}
                    width={56}
                    height={24}
                    stroke={inst.changePct != null && inst.changePct < 0 ? "#ef4444" : "#22c55e"}
                  />
                  <div className={`lv-v2-trading-row__price ${changeClass}`}>
                    {inst.unavailable || inst.price == null
                      ? "UNAVAILABLE"
                      : inst.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    {inst.changePct != null ? (
                      <div>
                        {inst.changePct >= 0 ? "+" : ""}
                        {inst.changePct.toFixed(2)}%
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </section>
  );
}
