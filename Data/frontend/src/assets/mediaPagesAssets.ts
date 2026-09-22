/** Bundled pixel-exact content crops for Media / Research / Evidence pages. */

import contentCalendar from "./media-pages/crops/content-calendar.jpg";
import contentEvidence from "./media-pages/crops/content-evidence.jpg";
import contentLibrary from "./media-pages/crops/content-library.jpg";
import contentPersonas from "./media-pages/crops/content-personas.jpg";
import contentQueue from "./media-pages/crops/content-queue.jpg";
import contentResearch from "./media-pages/crops/content-research.jpg";
import contentViral from "./media-pages/crops/content-viral.jpg";

import heroCalendar from "./media-pages/crops/hero-calendar.jpg";
import heroEvidence from "./media-pages/crops/hero-evidence.jpg";
import heroLibrary from "./media-pages/crops/hero-library.jpg";
import heroPersonas from "./media-pages/crops/hero-personas.jpg";
import heroQueue from "./media-pages/crops/hero-queue.jpg";
import heroResearch from "./media-pages/crops/hero-research.jpg";
import heroViral from "./media-pages/crops/hero-viral.jpg";

export const mediaPageContent = {
  queue: contentQueue,
  viral: contentViral,
  calendar: contentCalendar,
  library: contentLibrary,
  personas: contentPersonas,
  research: contentResearch,
  evidence: contentEvidence,
} as const;

export const mediaPageHeroes = {
  queue: heroQueue,
  viral: heroViral,
  calendar: heroCalendar,
  library: heroLibrary,
  personas: heroPersonas,
  research: heroResearch,
  evidence: heroEvidence,
} as const;

export type MediaPageKey = keyof typeof mediaPageContent;
