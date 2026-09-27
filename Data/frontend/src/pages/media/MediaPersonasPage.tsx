import { mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { MediaSectionUnavailable } from "./MediaSectionUnavailable";

export function MediaPersonasPage() {
  return (
    <MediaSectionUnavailable
      title="PERSONAS"
      heroImage={mediaPageHeroes.personas}
      sectionLabel="Audience reach / persona metrics"
    />
  );
}
