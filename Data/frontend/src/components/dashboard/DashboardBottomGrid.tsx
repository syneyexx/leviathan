import { useNavigate } from "react-router-dom";
import type { DashboardOverview } from "../../hooks/useDashboardOverview";
import { Button, EmptyState, LoadingState, Panel, ProgressBar } from "../ui";
import { formatBytes, formatPct } from "../../lib/dashboardNormalize";

type Props = {
  overview: DashboardOverview;
};

export function DashboardBottomGrid({ overview }: Props) {
  const navigate = useNavigate();
  const { ingestion, gpuPanel, performance, loading } = overview;
  const selected = gpuPanel.devices[gpuPanel.selectedIndex] ?? gpuPanel.devices[0] ?? null;

  return (
    <section className="lv-v2-bottom-grid" aria-label="Hardware en performance">
      <Panel
        title="Data Ingestie"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M12 16V5M8 9l4-4 4 4M5 19h14" />
          </svg>
        }
        action={
          <Button variant="ghost" size="sm" onClick={() => navigate("/datasets")}>
            Nieuwe dataset
          </Button>
        }
      >
        {!ingestion.available && loading ? (
          <LoadingState />
        ) : !ingestion.available ? (
          <EmptyState title="Ingestie unavailable" detail="Host source-ingestion status ontbreekt." />
        ) : (
          <div className="lv-v2-meter-block">
            <div className="lv-v2-meter-row">
              <div className="lv-v2-meter-row__head">
                <span>{ingestion.title}</span>
                <span className="lv-v2-meter-row__value">
                  {ingestion.progress != null ? formatPct(ingestion.progress, true) : "UNMEASURED"}
                </span>
              </div>
              <ProgressBar value={ingestion.progress} />
            </div>
            <div className="lv-v2-panel__meta">{ingestion.detail}</div>
          </div>
        )}
      </Panel>

      <Panel
        title="GPU & Hardware"
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
              onChange={(event) => gpuPanel.setSelectedIndex(Number(event.target.value))}
            >
              {gpuPanel.devices.map((d, index) => (
                <option key={d.index} value={index}>
                  {d.name}
                </option>
              ))}
            </select>
          ) : undefined
        }
      >
        {!selected ? (
          <EmptyState title="Geen GPU gedetecteerd" detail="Hardware enumeration unavailable." />
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
                <span>Temperatuur</span>
                <span className="lv-v2-meter-row__value">
                  {selected.tempC != null ? `${Math.round(selected.tempC)}°C` : "N/A"}
                </span>
              </div>
              <ProgressBar
                value={selected.tempC != null ? Math.min(100, (selected.tempC / 100) * 100) : null}
                tone="warning"
              />
            </div>
          </div>
        )}
      </Panel>

      <Panel
        title="Verwachte Performance"
        icon={
          <svg className="lv-v2-panel__title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M4 19V5M8 19v-8M12 19v-5M16 19V8M20 19v-3" />
          </svg>
        }
      >
        <div className="lv-v2-perf-stats">
          <div className="lv-v2-perf-stat">
            <div>
              <div className="lv-v2-perf-stat__label">Taken per uur</div>
              <div className="lv-v2-perf-stat__value">
                {performance.tasksPerHour != null ? Math.round(performance.tasksPerHour) : "UNMEASURED"}
              </div>
              {performance.trends.tasksPerHourDerived ? (
                <div className="lv-v2-perf-stat__delta">afgeleid (vandaag)</div>
              ) : null}
            </div>
          </div>
          <div className="lv-v2-perf-stat">
            <div>
              <div className="lv-v2-perf-stat__label">Gem. verwerkingstijd</div>
              <div className="lv-v2-perf-stat__value">
                {performance.avgProcessingMin != null
                  ? `${performance.avgProcessingMin.toFixed(1)} min`
                  : "UNMEASURED"}
              </div>
            </div>
          </div>
          <div className="lv-v2-perf-stat">
            <div>
              <div className="lv-v2-perf-stat__label">Systeem uptime</div>
              <div className="lv-v2-perf-stat__value">{performance.uptimeLabel ?? "UNMEASURED"}</div>
            </div>
          </div>
        </div>
      </Panel>
    </section>
  );
}
