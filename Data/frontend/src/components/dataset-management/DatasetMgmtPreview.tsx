import { DM_SAMPLE_TABS } from "../../pages/dataset-management/constants";
import { previewSampleTable, previewSampleText } from "../../pages/dataset-management/viewModels";
import type { DatasetManagementWorkspace } from "../../pages/dataset-management/useDatasetManagementWorkspace";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetMgmtPreview({ ws }: Props) {
  const content = (() => {
    if (ws.samplePreview) return ws.samplePreview;
    if (ws.sampleTab === "JSON") return JSON.stringify(ws.preview, null, 2);
    if (ws.sampleTab === "Tekst") return previewSampleText(ws.preview);
    return previewSampleTable(ws.preview);
  })();

  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-preview" aria-label="Voorbeeld data">
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">Voorbeeld data</h3>
        <div className="lv-v2-dm-tabs" role="tablist">
          {DM_SAMPLE_TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={ws.sampleTab === tab}
              className={`lv-v2-dm-tab${ws.sampleTab === tab ? " is-active" : ""}`}
              onClick={() => ws.setSampleTab(tab)}
            >
              {tab}
            </button>
          ))}
          <button
            type="button"
            className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm"
            onClick={() => void ws.copyPreview()}
          >
            Kopieer
          </button>
        </div>
      </div>
      <pre className="lv-v2-dm-code">{content}</pre>
    </section>
  );
}
