import heroMcp from "./plugin-runtime/hero-mcp.jpg";
import heroPerformance from "./plugin-runtime/hero-performance.jpg";

/** Modules reuses the performance architectural crop — no fabricated external asset. */
export const pluginRuntimeHeroes = {
  mcp: heroMcp,
  performance: heroPerformance,
  modules: heroPerformance,
} as const;
