import { Badge } from "../ui";
import type { DatasetServiceProjection } from "../../types/api";
import { serviceStateTone } from "../../pages/dataset-management/viewModels";

type Props = {
  services: DatasetServiceProjection[];
  loading: boolean;
};

const BADGE_TONE_MAP: Record<string, "success" | "warning" | "danger" | "muted" | "info"> = {
  green: "success",
  gold: "warning",
  red: "danger",
  muted: "muted",
  cyan: "info",
};

export function DatasetMgmtServices({ services, loading }: Props) {
  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-services" aria-label="Dataset Services">
      <h3 className="lv-v2-panel__title">Dataset Services</h3>
      {loading ? (
        <p className="lv-v2-dm-muted">Services laden…</p>
      ) : services.length === 0 ? (
        <p className="lv-v2-dm-muted">Geen serviceprojecties beschikbaar.</p>
      ) : (
        <ul className="lv-v2-dm-service-list">
          {services.map((svc) => (
            <li key={svc.id} className="lv-v2-dm-service-row">
              <span className={`lv-v2-dm-service-dot is-${serviceStateTone(svc.state)}`} aria-hidden="true" />
              <div className="lv-v2-dm-service-body">
                <div className="lv-v2-dm-service-name">{svc.name}</div>
                {svc.detail ? <div className="lv-v2-dm-service-detail">{svc.detail}</div> : null}
              </div>
              <Badge tone={BADGE_TONE_MAP[serviceStateTone(svc.state)] ?? "muted"}>{svc.label}</Badge>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
