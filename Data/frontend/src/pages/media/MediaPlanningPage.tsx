import { Link } from "react-router-dom";
import { mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { MediaSectionUnavailable } from "./MediaSectionUnavailable";

/** Planning — publication schedule shell (no fabricated calendar truth). */
export function MediaPlanningPage() {
  return (
    <MediaSectionUnavailable
      title="PLANNING"
      heroImage={mediaPageHeroes.calendar ?? mediaPageHeroes.library}
      sectionLabel="Media planning / schedule"
    >
      <p style={{ marginTop: "0.5rem" }}>
        <Link to="/media/calendar">Open legacy calendar view</Link>
        {" · "}
        <Link to="/media/distributie">Distributie</Link>
      </p>
    </MediaSectionUnavailable>
  );
}
