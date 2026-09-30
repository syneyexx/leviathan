import type { DatasetManagementWorkspace } from "../../hooks/useDatasetManagementWorkspace";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetManagementServices({ ws }: Props) {
  return (
    <section className="lv-v2-panel lv-v2-dm-services" aria-label="Dataset Services">
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">Dataset Services</h3>
      </div>
      <div className="lv-v2-panel__body">
        <ul className="lv-v2-dm-services__list">
          {ws.datasetServices.map((s) => (
            <li key={s.id} className={`lv-v2-dm-services__row is-${s.tone}`}>
              <span className="lv-v2-dm-services__dot" aria-hidden="true" />
              <span className="lv-v2-dm-services__label">{s.label}</span>
              <span className="lv-v2-dm-services__state">{s.state}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
