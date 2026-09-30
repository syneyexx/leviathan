import { PxIcon } from "../../pages/pixel/pixel-shared";
import { DM_SIDEBAR_ACTIONS } from "../../pages/dataset-management/constants";

type Props = {
  selectedCount: number;
  busy: boolean;
  exportReady: boolean;
  actionDisabledReason: (id: string) => string | null;
  onAction: (id: string) => void;
  onDownloadExport: () => void;
};

export function DatasetMgmtActions({
  selectedCount,
  busy,
  exportReady,
  actionDisabledReason,
  onAction,
  onDownloadExport,
}: Props) {
  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-actions" aria-label="Dataset Acties">
      <h3 className="lv-v2-panel__title">Dataset Acties</h3>
      <p className="lv-v2-dm-muted">
        Geselecteerd: {selectedCount > 0 ? `${selectedCount} dataset` : "geen"}
      </p>
      <div className="lv-v2-dm-action-list">
        {DM_SIDEBAR_ACTIONS.map((action) => {
          const reason = actionDisabledReason(action.id);
          return (
            <button
              key={action.id}
              type="button"
              className={`lv-v2-dm-action-btn${action.danger ? " is-danger" : ""}`}
              disabled={busy || Boolean(reason)}
              title={reason ?? undefined}
              onClick={() => onAction(action.id)}
            >
              <PxIcon name={action.icon} />
              <span>{action.label}</span>
            </button>
          );
        })}
      </div>
      {exportReady ? (
        <button
          type="button"
          className="lv-v2-button lv-v2-button--primary lv-v2-dm-export-btn"
          disabled={busy}
          onClick={onDownloadExport}
        >
          Download export
        </button>
      ) : null}
    </section>
  );
}
