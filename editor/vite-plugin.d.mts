import type { Plugin } from "vite";

export type LeviathanLayoutEditorOptions = {
  apiOrigin?: string;
};

/** Vite plugin — only active when LEVIATHAN_EDITOR=1. */
export function leviathanLayoutEditor(
  options?: LeviathanLayoutEditorOptions,
): Plugin;
