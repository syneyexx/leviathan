import { mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { MediaSectionUnavailable } from "./MediaSectionUnavailable";

export function MediaQueuePage() {
  return (
    <MediaSectionUnavailable
      title="ALGEMENE PUBLICATIE WACHTRIJ"
      heroImage={mediaPageHeroes.queue}
      sectionLabel="Publication queue / live ops"
    />
  );
}
