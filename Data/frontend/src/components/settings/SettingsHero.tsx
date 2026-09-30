import { media } from "../../assets/media";
import { Button } from "../ui";
import type { SettingsWorkspace } from "../../hooks/useSettingsWorkspace";

type Props = {
  ws: SettingsWorkspace;
};

export function SettingsHero({ ws }: Props) {
  const restartPending = ws.saveReceipt?.some((r) => r.restart_required || r.status === "RESTART_REQUIRED");

  return (
    <section className="lv-v2-hero lv-v2-hero--settings" aria-label="Systeem Instellingen">
      <div className="lv-v2-hero__media lv-v2-hero__media--settings" aria-hidden="true">
        <img src={media.hero} alt="" width={1600} height={440} />
      </div>
      <div className="lv-v2-hero__shade lv-v2-hero__shade--settings" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Systeem Instellingen</h2>
        <p className="lv-v2-hero__copy">
          Configureer je AI infrastructuur, modellen, providers, geheugen, tools en systeemvoorkeuren.
        </p>
        <p className="lv-v2-hero__copy lv-v2-hero__copy--secondary">
          Hot settings worden direct toegepast. Restart-vereiste waarden worden veilig opgeslagen en
          actief na herstart. Gevraagde en effectieve waarden blijven gescheiden.
        </p>
        <div className="lv-v2-hero__actions">
          <Button
            variant="primary"
            size="sm"
            loading={ws.saving}
            disabled={!ws.dirty || ws.saving}
            onClick={() => void ws.saveDirty()}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M5 3h11l3 3v15H5V3z" />
              <path d="M8 3v6h8V3" />
              <path d="M8 17h8" />
            </svg>
            Wijzigingen opslaan
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={ws.saving}
            onClick={() => void ws.resetAllVisible()}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M3 12a9 9 0 1 0 3-6.7" />
              <path d="M3 4v5h5" />
            </svg>
            Instellingen resetten
          </Button>
        </div>
        {ws.dirty ? (
          <p className="lv-v2-settings-dirty" role="status">
            {ws.dirtyKeys.length} niet-opgeslagen wijziging{ws.dirtyKeys.length === 1 ? "" : "en"}
          </p>
        ) : null}
        {restartPending ? (
          <p className="lv-v2-settings-restart" role="status">
            Opgeslagen — herstart vereist voor een of meer waarden.
          </p>
        ) : null}
      </div>
      <blockquote className="lv-v2-hero__quote">
        “Controle vandaag,
        <br />
        een intelligentere morgen.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
