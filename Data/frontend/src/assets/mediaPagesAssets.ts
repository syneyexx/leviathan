/** Bundled assets for Media Queue / Viral / Calendar / Library / Personas / Research / Evidence. */

import heroQueue from "./media-pages/crops/hero-queue.jpg";
import heroViral from "./media-pages/crops/hero-viral.jpg";
import heroCalendar from "./media-pages/crops/hero-calendar.jpg";
import heroLibrary from "./media-pages/crops/hero-library.jpg";
import heroPersonas from "./media-pages/crops/hero-personas.jpg";
import heroResearch from "./media-pages/crops/hero-research.jpg";
import heroEvidence from "./media-pages/crops/hero-evidence.jpg";

import queueDetail from "./media-pages/crops/queue-detail.jpg";
import viralMap from "./media-pages/crops/viral-map.jpg";
import viralTrendHero from "./media-pages/crops/viral-trend-hero.jpg";
import calendarSelected from "./media-pages/crops/calendar-selected.jpg";
import calendarVisual1 from "./media-pages/crops/calendar-visual-1.jpg";
import calendarVisual2 from "./media-pages/crops/calendar-visual-2.jpg";
import calendarVisual3 from "./media-pages/crops/calendar-visual-3.jpg";
import libraryPreview from "./media-pages/crops/library-preview.jpg";
import libraryTile1 from "./media-pages/crops/library-tile-1.jpg";
import libraryTile2 from "./media-pages/crops/library-tile-2.jpg";
import libraryTile3 from "./media-pages/crops/library-tile-3.jpg";
import libraryTile4 from "./media-pages/crops/library-tile-4.jpg";
import libraryTile5 from "./media-pages/crops/library-tile-5.jpg";
import libraryTile6 from "./media-pages/crops/library-tile-6.jpg";
import libraryTile7 from "./media-pages/crops/library-tile-7.jpg";
import libraryTile8 from "./media-pages/crops/library-tile-8.jpg";
import personaDetail from "./media-pages/crops/persona-detail.jpg";
import persona1 from "./media-pages/crops/persona-1.jpg";
import persona2 from "./media-pages/crops/persona-2.jpg";
import persona3 from "./media-pages/crops/persona-3.jpg";
import persona4 from "./media-pages/crops/persona-4.jpg";
import persona5 from "./media-pages/crops/persona-5.jpg";
import persona6 from "./media-pages/crops/persona-6.jpg";
import researchBust from "./media-pages/crops/research-bust.jpg";
import evidenceSat from "./media-pages/crops/evidence-sat.jpg";
import evidenceBust from "./media-pages/crops/evidence-bust.jpg";

import { mediaControlCrops, platformTiles } from "./mediaControlAssets";

export const mediaPageHeroes = {
  queue: heroQueue,
  viral: heroViral,
  calendar: heroCalendar,
  library: heroLibrary,
  personas: heroPersonas,
  research: heroResearch,
  evidence: heroEvidence,
} as const;

export const mediaPageArt = {
  queueDetail,
  viralMap,
  viralTrendHero,
  calendarSelected,
  calendarVisual1,
  calendarVisual2,
  calendarVisual3,
  libraryPreview,
  libraryTiles: [
    libraryTile1,
    libraryTile2,
    libraryTile3,
    libraryTile4,
    libraryTile5,
    libraryTile6,
    libraryTile7,
    libraryTile8,
  ] as const,
  personaDetail,
  personas: [persona1, persona2, persona3, persona4, persona5, persona6] as const,
  researchBust,
  evidenceSat,
  evidenceBust,
  /** Cinematic thumbs for queue rows (shared media-control art). */
  queueThumbs: [
    mediaControlCrops.youtubeThumb1,
    mediaControlCrops.youtubeThumb2,
    platformTiles.youtube[0],
    platformTiles.youtube[1],
    platformTiles.tiktok[0],
    platformTiles.instagram[0],
    platformTiles.facebook[0],
    mediaControlCrops.mediaPoster,
  ] as const,
} as const;
