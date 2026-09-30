import { Dialog } from "../ui";
import type { DatasetManagementWorkspace } from "../../hooks/useDatasetManagementWorkspace";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetManagementDialogs({ ws }: Props) {
  return (
    <>
      <Dialog
        open={ws.modal === "create"}
        title="Nieuwe dataset"
        description="Maak een lege dataset-shell in DatasetService."
        confirmLabel="Aanmaken"
        busy={ws.busy}
        onClose={() => ws.setModal(null)}
        onConfirm={() => void ws.onCreateSubmit()}
      >
        <div className="lv-v2-dm-form">
          <label>
            Naam
            <input
              className="lv-v2-input"
              value={ws.createName}
              onChange={(e) => ws.setCreateName(e.target.value)}
              placeholder="mijn-corpus"
            />
          </label>
          <label>
            Beschrijving
            <textarea
              className="lv-v2-input"
              value={ws.createDesc}
              onChange={(e) => ws.setCreateDesc(e.target.value)}
              rows={3}
            />
          </label>
          <label>
            Licentie (optioneel)
            <input
              className="lv-v2-input"
              value={ws.createLicense}
              onChange={(e) => ws.setCreateLicense(e.target.value)}
              placeholder="MIT"
            />
          </label>
        </div>
      </Dialog>

      <Dialog
        open={ws.modal === "local"}
        title="Lokale bestanden importeren"
        description="Importeer een bestand dat al bereikbaar is op de LEVIATHAN-server (allowed roots)."
        confirmLabel="Importeren"
        busy={ws.busy}
        onClose={() => ws.setModal(null)}
        onConfirm={() => void ws.onLocalSubmit()}
      >
        <div className="lv-v2-dm-form">
          <label>
            Absoluut of toegestaan pad
            <input
              className="lv-v2-input"
              value={ws.localPath}
              onChange={(e) => ws.setLocalPath(e.target.value)}
              placeholder="/data/corpus.jsonl"
            />
          </label>
          <label>
            Optionele naam
            <input
              className="lv-v2-input"
              value={ws.localName}
              onChange={(e) => ws.setLocalName(e.target.value)}
            />
          </label>
          <label>
            Optionele beschrijving
            <textarea
              className="lv-v2-input"
              value={ws.localDesc}
              onChange={(e) => ws.setLocalDesc(e.target.value)}
              rows={2}
            />
          </label>
        </div>
      </Dialog>

      <Dialog
        open={ws.modal === "hf"}
        title="Importeren (Hugging Face)"
        description="Importeer een volledige repository (bestandsnaam optioneel) of één bestand. Token wordt niet in jobconfig of logs bewaard."
        confirmLabel="Importeren"
        busy={ws.busy}
        onClose={() => ws.setModal(null)}
        onConfirm={() => void ws.onHfSubmit()}
      >
        <div className="lv-v2-dm-form">
          <label>
            Repository ID
            <input
              className="lv-v2-input"
              value={ws.hfRepo}
              onChange={(e) => ws.setHfRepo(e.target.value)}
              placeholder="owner/dataset"
            />
          </label>
          <label>
            Revision
            <input
              className="lv-v2-input"
              value={ws.hfRevision}
              onChange={(e) => ws.setHfRevision(e.target.value)}
              placeholder="main"
            />
          </label>
          <label>
            Bestandsnaam (optioneel — leeg = volledige repo)
            <input
              className="lv-v2-input"
              value={ws.hfFilename}
              onChange={(e) => ws.setHfFilename(e.target.value)}
              placeholder="train.jsonl"
            />
          </label>
          <label>
            Weergavenaam (optioneel)
            <input
              className="lv-v2-input"
              value={ws.hfName}
              onChange={(e) => ws.setHfName(e.target.value)}
            />
          </label>
          <label>
            Beschrijving (optioneel)
            <textarea
              className="lv-v2-input"
              value={ws.hfDesc}
              onChange={(e) => ws.setHfDesc(e.target.value)}
              rows={2}
            />
          </label>
          <label>
            Access token (optioneel)
            <input
              className="lv-v2-input"
              type="password"
              value={ws.hfToken}
              onChange={(e) => ws.setHfToken(e.target.value)}
              autoComplete="off"
            />
          </label>
        </div>
      </Dialog>

      <Dialog
        open={ws.modal === "delete"}
        title="Dataset verwijderen"
        description={`Verwijder ${ws.selected?.name ?? "deze dataset"}? Actieve jobs of training-referenties blokkeren delete via DatasetService.`}
        confirmLabel="Verwijderen"
        danger
        busy={ws.busy}
        onClose={() => ws.setModal(null)}
        onConfirm={() => void ws.onDeleteConfirm()}
      />
    </>
  );
}
