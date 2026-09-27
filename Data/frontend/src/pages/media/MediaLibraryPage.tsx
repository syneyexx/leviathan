import { mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { MediaSectionUnavailable } from "./MediaSectionUnavailable";

export function MediaLibraryPage() {
  return (
    <MediaSectionUnavailable
      title="BIBLIOTHEEK"
      heroImage={mediaPageHeroes.library}
      sectionLabel="Asset library inventory"
    />
  );
}
