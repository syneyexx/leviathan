import { DM_FOOTER_ACTIONS } from "../../pages/datasets/datasetManagementConstants";
import type { DatasetManagementWorkspace } from "../../hooks/useDatasetManagementWorkspace";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetManagementFooter({ ws }: Props) {
  return (
    <footer className="lv-v2-dm-footer" aria-label="Dataset actiebalk">
      {DM_FOOTER_ACTIONS.map((a) => {
        let reason: string | null = null;
        if (a.id === "delete") reason = ws.actionDisabledReason("delete");
        if (a.id === "validate") reason = ws.actionDisabledReason("validate");
        if (a.id === "learn") reason = ws.actionDisabledReason("learn");
        if (a.id === "save") reason = ws.actionDisabledReason("save");
        return (
          <button
            key={a.id}
            type="button"
            className={`lv-v2-dm-footer__btn${a.tone === "gold" ? " is-gold" : ""}${a.tone === "danger" ? " is-danger" : ""}`}
            disabled={ws.busy || Boolean(reason)}
            title={reason ?? undefined}
            onClick={() => void ws.onFooterAction(a.id)}
          >
            {a.label}
          </button>
        );
      })}
    </footer>
  );
}
