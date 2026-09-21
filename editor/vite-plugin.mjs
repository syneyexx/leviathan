/**
 * Vite plugin — only active when LEVIATHAN_EDITOR=1.
 * Injects the visual layout builder into the real Leviathan frontend.
 */
export function leviathanLayoutEditor(options = {}) {
  const apiOrigin = options.apiOrigin || "http://127.0.0.1:5199";

  return {
    name: "leviathan-layout-editor",
    apply: "serve",
    transformIndexHtml() {
      return [
        {
          tag: "link",
          attrs: {
            rel: "stylesheet",
            href: `${apiOrigin}/canvas.css`,
          },
          injectTo: "head",
        },
        {
          tag: "script",
          attrs: {
            type: "module",
            src: `${apiOrigin}/canvas.js`,
            crossorigin: "anonymous",
            "data-lv-editor-api": apiOrigin,
          },
          injectTo: "body",
        },
      ];
    },
  };
}
