/** Bundled assets for Onderzoek & Kennis mock pages (Geheugen). */

import contentGeheugen from "./onderzoek-kennis/crops/content-geheugen.jpg";
import heroGeheugen from "./onderzoek-kennis/crops/hero-geheugen.jpg";

export const onderzoekHeroes = {
  geheugen: heroGeheugen,
} as const;

/** Full content crops kept for visual QA / walkthroughs — pages use live mock UI. */
export const onderzoekContentCrops = {
  geheugen: contentGeheugen,
} as const;

export type OnderzoekPageKey = keyof typeof onderzoekHeroes;
