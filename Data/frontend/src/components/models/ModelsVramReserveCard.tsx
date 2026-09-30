import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Button, Panel } from "../ui";

type Props = {
  ws: ModelsWorkspace;
};

function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
    </svg>
  );
}

function InfoIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8h.01M12 11v5" />
    </svg>
  );
}

export function ModelsVramReserveCard({ ws }: Props) {
  const d = ws.vramReserveDraft;

  return (
    <Panel title="VRAM Reservering" icon={<GearIcon />} className="lv-v2-models-vram-reserve">
      <div className="lv-v2-models-field-row">
        <label className="lv-v2-models-field-row__label" htmlFor="mv-display-reserve">
          Display GPU reserve
        </label>
        <div className="lv-v2-models-field-row__control lv-v2-models-vram-reserve__input-row">
          <input
            id="mv-display-reserve"
            type="number"
            min={0}
            step={0.5}
            value={d.displayGpuReserveGb}
            onChange={(e) => ws.setVramReserveDraft({ displayGpuReserveGb: Number(e.target.value) })}
          />
          <span>GB</span>
        </div>
      </div>
      <div className="lv-v2-models-field-row">
        <label className="lv-v2-models-field-row__label" htmlFor="mv-aux-reserve">
          Aux GPU reserve
        </label>
        <div className="lv-v2-models-field-row__control lv-v2-models-vram-reserve__input-row">
          <input
            id="mv-aux-reserve"
            type="number"
            min={0}
            step={0.5}
            value={d.auxGpuReserveGb}
            onChange={(e) => ws.setVramReserveDraft({ auxGpuReserveGb: Number(e.target.value) })}
          />
          <span>GB</span>
        </div>
      </div>
      <div className="lv-v2-models-field-row">
        <label className="lv-v2-models-field-row__label" htmlFor="mv-ram-reserve">
          Systeem RAM reserve
        </label>
        <div className="lv-v2-models-field-row__control lv-v2-models-vram-reserve__input-row">
          <input
            id="mv-ram-reserve"
            type="number"
            min={0}
            step={0.5}
            value={d.systemRamReserveGb}
            onChange={(e) => ws.setVramReserveDraft({ systemRamReserveGb: Number(e.target.value) })}
          />
          <span>GB</span>
        </div>
      </div>

      <p className="lv-v2-models-vram-reserve__note">
        <InfoIcon /> Deze reserveringen worden gebruikt bij optimalisatie en load-berekeningen.
      </p>

      <Button
        variant="secondary"
        size="sm"
        disabled={!ws.vramReserveDirty}
        loading={ws.savingVramReserve}
        onClick={() => void ws.saveVramReserve()}
      >
        Opslaan
      </Button>
    </Panel>
  );
}
