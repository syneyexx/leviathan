import { Link } from "react-router-dom";
import { Panel, StatusDot } from "../ui";
import type { ConsoleOverviewService } from "../../types/api";
import { formatRate, serviceStatusTone } from "../../pages/console/consoleFormat";

type Props = {
  services: ConsoleOverviewService[];
};

export function ConsoleServicesPanel({ services }: Props) {
  const maxRate = Math.max(
    0,
    ...services.map((s) => (s.events_per_min != null && Number.isFinite(s.events_per_min) ? s.events_per_min : 0)),
  );

  return (
    <Panel
      className="lv-v2-console-services"
      title="Actieve Services"
      action={
        <Link className="lv-v2-console-link" to="/performance">
          Alles bekijken
        </Link>
      }
    >
      <ul className="lv-v2-console-services__list">
        {services.length === 0 ? (
          <li className="lv-v2-muted">Geen services — UNMEASURED</li>
        ) : (
          services.map((s) => {
            const tone = serviceStatusTone(s.status, s.measured);
            const rate = s.events_per_min;
            const pct =
              rate != null && Number.isFinite(rate) && maxRate > 0
                ? Math.max(4, Math.round((rate / maxRate) * 100))
                : null;
            return (
              <li key={s.id} className="lv-v2-console-services__row">
                <StatusDot
                  tone={tone}
                  title={
                    s.measured
                      ? `${s.status}${s.detail ? ` — ${s.detail}` : ""}`
                      : `unmeasured — ${s.status}`
                  }
                />
                <div className="lv-v2-console-services__copy">
                  <div className="name">{s.name}</div>
                  <div className="meta">
                    {s.measured ? s.status : "unmeasured"}
                    {rate != null ? ` · ${formatRate(rate)}/min` : " · —/min"}
                  </div>
                </div>
                <div className="lv-v2-console-services__bar" aria-hidden="true">
                  {pct != null ? <i style={{ width: `${pct}%` }} /> : <i className="is-empty" />}
                </div>
              </li>
            );
          })
        )}
      </ul>
    </Panel>
  );
}
