import type { RunStatusTone } from "../viewModels";
import { runListItem, type LabRunRecord } from "../viewModels";

function Pill({ tone, label }: { tone: RunStatusTone; label: string }) {
  return <span className={`lv-rl-pill is-${tone}`}>{label}</span>;
}

export function ResearchRunListRail({
  labs,
  selectedLabId,
  loading,
  onSelect,
  onCreate,
}: {
  labs: LabRunRecord[];
  selectedLabId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  return (
    <aside className="lv-rl-rail" aria-label="Research runs">
      <div className="lv-rl-rail-head">
        <h2>Research Runs</h2>
        <button type="button" className="lv-rl-btn is-primary" onClick={onCreate}>
          + Create Run
        </button>
      </div>
      {loading && labs.length === 0 ? (
        <div className="lv-rl-skel" style={{ padding: 12 }}>
          <div className="lv-rl-skel-bar" />
          <div className="lv-rl-skel-bar" />
          <div className="lv-rl-skel-bar" />
        </div>
      ) : labs.length === 0 ? (
        <div className="lv-rl-empty" style={{ margin: 8 }}>
          <strong>No research runs</strong>
          Create a run to start autonomous strategy search on market simulation.
        </div>
      ) : (
        <ul className="lv-rl-run-list">
          {labs.map((lab) => {
            const item = runListItem(lab);
            const selected = item.labId === selectedLabId;
            return (
              <li key={item.labId}>
                <button
                  type="button"
                  className={`lv-rl-run${selected ? " is-selected" : ""}`}
                  onClick={() => onSelect(item.labId)}
                  aria-pressed={selected}
                >
                  <div className="lv-rl-run-top">
                    <div className="lv-rl-run-name">{item.name}</div>
                    <Pill tone={item.tone} label={item.label} />
                  </div>
                  <div className="lv-rl-run-meta">{item.meta}</div>
                  {item.progress != null ? (
                    <>
                      <div className="lv-rl-progress" aria-hidden="true">
                        <span style={{ width: `${item.progress}%` }} />
                      </div>
                      <div className="lv-rl-progress-label">
                        <span>{item.generationLabel || "Trial budget"}</span>
                        <span>{Math.round(item.progress)}%</span>
                      </div>
                    </>
                  ) : item.generationLabel ? (
                    <div className="lv-rl-progress-label">
                      <span>{item.generationLabel}</span>
                    </div>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
