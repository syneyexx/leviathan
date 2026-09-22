/** Bundled assets for Onderzoek & Kennis mock pages (Datasets / Knowledge / Geheugen). */

import contentDatasets from "./onderzoek-kennis/crops/content-datasetsknowledge.jpg";
import contentGeheugen from "./onderzoek-kennis/crops/content-geheugen.jpg";
import contentKnowledge from "./onderzoek-kennis/crops/content-knowledgelibary.jpg";
import heroDatasets from "./onderzoek-kennis/crops/hero-datasetsknowledge.jpg";
import heroGeheugen from "./onderzoek-kennis/crops/hero-geheugen.jpg";
import heroKnowledge from "./onderzoek-kennis/crops/hero-knowledgelibary.jpg";

export const onderzoekHeroes = {
  datasets: heroDatasets,
  knowledge: heroKnowledge,
  geheugen: heroGeheugen,
} as const;

/** Full content crops kept for visual QA / walkthroughs — pages use live mock UI. */
export const onderzoekContentCrops = {
  datasets: contentDatasets,
  knowledge: contentKnowledge,
  geheugen: contentGeheugen,
} as const;

export type OnderzoekPageKey = keyof typeof onderzoekHeroes;
