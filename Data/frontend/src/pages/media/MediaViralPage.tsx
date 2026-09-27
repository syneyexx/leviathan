import { mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { MediaSectionUnavailable } from "./MediaSectionUnavailable";

export function MediaViralPage() {
  return (
    <MediaSectionUnavailable
      title="VIRAL RADAR"
      heroImage={mediaPageHeroes.viral}
      sectionLabel="Viral signals / reach / engagement"
    />
  );
}
