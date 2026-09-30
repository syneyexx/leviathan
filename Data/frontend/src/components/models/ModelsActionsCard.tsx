import type { ModelsWorkspace } from "../../hooks/useModelsWorkspace";
import { Button, Panel } from "../ui";

type Props = {
  ws: ModelsWorkspace;
};

function PlayIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M6 4l14 8-14 8V4z" />
    </svg>
  );
}

export function ModelsActionsCard({ ws }: Props) {
  const model = ws.selectedModel;
  const busy = ws.busy != null;
  const canStop =
    ws.activeJobId != null ||
    ws.busy != null ||
    (ws.optimization != null && ["PENDING", "RUNNING"].includes(ws.optimization.status));

  return (
    <Panel title="Acties" icon={<PlayIcon />} className="lv-v2-models-actions">
      <Button
        variant="primary"
        size="sm"
        className="lv-v2-models-actions__load"
        disabled={!model || busy}
        loading={ws.busy === "load"}
        onClick={() => void ws.loadSelected()}
      >
        {model ? `Model laden in ${ws.activeProvider?.name || "LM Studio"}` : "Selecteer eerst een model"}
      </Button>
      <Button
        variant="secondary"
        size="sm"
        disabled={!model || busy}
        loading={ws.estimating}
        onClick={() => void ws.runEstimate()}
      >
        Eerst schatten (zonder laden)
      </Button>
      <Button
        variant="secondary"
        size="sm"
        disabled={!model || !model.loaded || busy}
        loading={ws.busy === "unload"}
        onClick={() => void ws.unloadSelected()}
      >
        Model ontladen
      </Button>
      <Button
        variant="secondary"
        size="sm"
        className="lv-v2-button--danger"
        disabled={!canStop}
        title="Annuleert de actieve Leviathan-operatie — stopt LM Studio niet"
        onClick={() => void ws.stop()}
      >
        Stoppen
      </Button>
      {ws.activeJobId ? (
        <p className="lv-v2-models-cap-note">Actieve job: {ws.activeJobId}</p>
      ) : null}
      {ws.dirty ? <p className="lv-v2-models-cap-note">Er zijn niet-toegepaste wijzigingen in de configuratie.</p> : null}
    </Panel>
  );
}
