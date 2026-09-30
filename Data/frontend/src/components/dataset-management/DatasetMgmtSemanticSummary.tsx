import type { DatasetManagementWorkspace } from "../../pages/dataset-management/useDatasetManagementWorkspace";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetMgmtSemanticSummary({ ws }: Props) {
  const selected = ws.selected;
  const summary = selected?.semanticProfile?.summary
    ? String(selected.semanticProfile.summary).slice(0, 400)
    : null;
  const validation = ws.selectedVersion?.validation as Record<string, unknown> | undefined;

  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-semantic" aria-label="Semantische samenvatting">
      <h3 className="lv-v2-panel__title">Semantische samenvatting</h3>
      {!selected ? (
        <p className="lv-v2-dm-muted">Selecteer een dataset</p>
      ) : summary ? (
        <p className="lv-v2-dm-muted">{summary}</p>
      ) : (
        <p className="lv-v2-dm-muted">
          Geen semantische samenvatting beschikbaar. Gebruik “Opnieuw analyseren” om er een te genereren.
        </p>
      )}
      {ws.recovery?.detail ? <p className="lv-v2-dm-muted lv-v2-dm-recovery-detail">{ws.recovery.detail}</p> : null}
      {validation ? (
        <pre className="lv-v2-dm-code lv-v2-dm-validation">{JSON.stringify(validation, null, 2)}</pre>
      ) : null}
    </section>
  );
}
