import { mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { MediaSectionUnavailable } from "./MediaSectionUnavailable";

export function MediaCalendarPage() {
  return (
    <MediaSectionUnavailable
      title="CALENDAR"
      heroImage={mediaPageHeroes.calendar}
      sectionLabel="Schedules / launch windows"
    />
  );
}
