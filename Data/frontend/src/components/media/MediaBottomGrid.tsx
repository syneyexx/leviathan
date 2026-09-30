import { Link } from "react-router-dom";
import type { MediaOverview } from "../../hooks/useMediaOverview";
import { formatBytes, formatPct } from "../../lib/dashboardNormalize";
import { MEDIA_KIND_LABEL } from "../../lib/mediaClassify";
import { Badge, EmptyState, Panel, ProgressBar } from "../ui";

type Props = {
  overview: MediaOverview;
};

export function MediaBottomGrid({ overview }: Props) {
  const { activities, gpuPanel, performance, perfRange, setPerfRange } = overview;
  const selected = gpuPanel.devices[gpuPanel.selectedIndex] ?? gpuPanel.devices[0] ?? null;

  return (
    <section className="lv-v2-bottom-grid lv-v2-media-bottom" aria-label="Taken GPU prestaties">
      <Panel
        title="Actieve Taken"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M8 7h11M8 12h11M8 17h11M5 7h.01M5 12h.01M5 17h.01" />
          </svg>
        }
        action={
          <Link to="/tasks" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm">
            Alles bekijken
          </Link>
        }
      >
        {activities.length === 0 ? (
          <EmptyState title="Geen recente media-activiteit" detail="Jobs en events verschijnen hier." />
        ) : (
          <div className="lv-v2-list">
            {activities.map((a) => (
              <div key={a.id} className="lv-v2-list-row lv-v2-activity-row lv-v2-media-activity-row">
                <span className="lv-v2-activity-row__time">{a.time}</span>
                <svg
                  className="lv-v2-activity-row__icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="12" r="8" />
                  <path d="M12 8v4l2.5 2.5" />
                </svg>
                <span className="lv-v2-media-activity-row__text" title={a.description}>
                  {a.description}
                </span>
                <Badge tone={a.tone}>
                  {a.kind === "system" ? "Systeem" : MEDIA_KIND_LABEL[a.kind]}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="GPU & Rendering"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <rect x="4" y="6" width="16" height="12" rx="2" />
            <path d="M8 20h8" />
          </svg>
        }
        action={
          gpuPanel.devices.length > 0 ? (
            <select
              className="lv-v2-select"
              aria-label="Selecteer GPU"
              value={gpuPanel.selectedIndex}
              onChange={(e) => gpuPanel.setSelectedIndex(Number(e.target.value))}
            >
              {gpuPanel.devices.map((d, index) => (
                <option key={d.index} value={index}>
                  {d.name}
                  {d.vramTotalBytes != null ? ` (${formatBytes(d.vramTotalBytes)})` : ""}
                </option>
              ))}
            </select>
          ) : undefined
        }
      >
        {!selected ? (
          <EmptyState title="Geen GPU gedetecteerd" detail="Hardware telemetry unavailable." />
        ) : (
          <div className="lv-v2-meter-block">
            <div className="lv-v2-meter-row">
              <div className="lv-v2-meter-row__head">
                <span>GPU Gebruik</span>
                <span className="lv-v2-meter-row__value">
                  {selected.util != null ? formatPct(selected.util, true) : "N/A"}
                </span>
              </div>
              <ProgressBar value={selected.util} />
            </div>
            <div className="lv-v2-meter-row">
              <div className="lv-v2-meter-row__head">
                <span>VRAM Gebruik</span>
                <span className="lv-v2-meter-row__value">
                  {selected.vramUsedBytes != null && selected.vramTotalBytes != null
                    ? `${formatBytes(selected.vramUsedBytes)} / ${formatBytes(selected.vramTotalBytes)}`
                    : "N/A"}
                </span>
              </div>
              <ProgressBar
                value={
                  selected.vramUsedBytes != null &&
                  selected.vramTotalBytes != null &&
                  selected.vramTotalBytes > 0
                    ? (selected.vramUsedBytes / selected.vramTotalBytes) * 100
                    : null
                }
              />
            </div>
            <div className="lv-v2-meter-row">
              <div className="lv-v2-meter-row__head">
                <span>Rendering Queue</span>
                <span className="lv-v2-meter-row__value">{gpuPanel.renderingQueue.label}</span>
              </div>
              <ProgressBar
                value={Math.min(100, gpuPanel.renderingQueue.active * 25)}
                tone="default"
              />
            </div>
            <div className="lv-v2-meter-row">
              <div className="lv-v2-meter-row__head">
                <span>Temperatuur</span>
                <span className="lv-v2-meter-row__value">
                  {selected.tempC != null ? `${Math.round(selected.tempC)}°C` : "N/A"}
                </span>
              </div>
              <ProgressBar
                value={selected.tempC != null ? Math.min(100, selected.tempC) : null}
                tone="warning"
              />
            </div>
          </div>
        )}
      </Panel>

      <Panel
        title="Media Prestaties"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M4 19V5M8 19v-8M12 19v-5M16 19V8M20 19v-3" />
          </svg>
        }
        action={
          <select
            className="lv-v2-select"
            aria-label="Periode media prestaties"
            value={perfRange}
            onChange={(e) => setPerfRange(e.target.value as "24h" | "7d" | "30d")}
          >
            <option value="24h">24 uur</option>
            <option value="7d">7 dagen</option>
            <option value="30d">30 dagen</option>
          </select>
        }
      >
        {!performance.available ? (
          <EmptyState title="Prestaties unavailable" detail="Nog geen media job metrics." />
        ) : (
          <div className="lv-v2-perf-stats">
            <div className="lv-v2-perf-stat">
              <div>
                <div className="lv-v2-perf-stat__label">Media gegenereerd</div>
                <div className="lv-v2-perf-stat__value">
                  {performance.generated != null ? performance.generated : "UNMEASURED"}
                </div>
              </div>
            </div>
            <div className="lv-v2-perf-stat">
              <div>
                <div className="lv-v2-perf-stat__label">Gem. render tijd</div>
                <div className="lv-v2-perf-stat__value">
                  {performance.avgRenderMin != null
                    ? `${performance.avgRenderMin.toFixed(1)} min`
                    : "UNMEASURED"}
                </div>
              </div>
            </div>
            <div className="lv-v2-perf-stat">
              <div>
                <div className="lv-v2-perf-stat__label">Succes ratio</div>
                <div className="lv-v2-perf-stat__value">
                  {performance.successPct != null
                    ? `${performance.successPct.toFixed(1)}%`
                    : "UNMEASURED"}
                </div>
              </div>
            </div>
          </div>
        )}
      </Panel>
    </section>
  );
}
