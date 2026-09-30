import { DM_SIDEBAR_ACTIONS } from "../../pages/datasets/datasetManagementConstants";
import type { DatasetManagementWorkspace } from "../../hooks/useDatasetManagementWorkspace";
import { DmIcon } from "./DatasetManagementIcons";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetManagementActions({ ws }: Props) {
  return (
    <section className="lv-v2-panel lv-v2-dm-actions" aria-label="Dataset Acties">
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">Dataset Acties</h3>
        <span className="lv-v2-panel__meta">
          {ws.selected ? "1 geselecteerd" : "geen selectie"}
        </span>
      </div>
      <div className="lv-v2-panel__body">
        <div className="lv-v2-dm-action-list">
          {DM_SIDEBAR_ACTIONS.map((action) => {
            const reason = ws.actionDisabledReason(action.id);
            return (
              <button
                key={action.id}
                type="button"
                className={`lv-v2-dm-action${action.danger ? " is-danger" : ""}${action.id === "upload" ? " is-primary" : ""}`}
                disabled={ws.busy || Boolean(reason)}
                title={reason ?? undefined}
                onClick={() => void ws.onSidebarAction(action.id)}
              >
                <DmIcon name={action.icon} />
                <span>{action.label}</span>
              </button>
            );
          })}
        </div>
        {ws.exportArtifact ? (
          <button
            type="button"
            className="lv-v2-dm-action is-gold"
            disabled={ws.busy}
            onClick={() => void ws.onDownloadExport()}
          >
            <DmIcon name="download" />
            <span>Download export</span>
          </button>
        ) : null}
      </div>
    </section>
  );
}
