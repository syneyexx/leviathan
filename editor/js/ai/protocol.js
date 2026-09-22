/**
 * Leviathan Editor Context / Result protocol helpers (v1).
 */

export const CONTEXT_PROTOCOL = "leviathan.editor-context";
export const RESULT_PROTOCOL = "leviathan.editor-result";
export const CONTEXT_VERSION = 1;
export const RESULT_VERSION = 1;

export const STYLE_SOURCES = [
  { id: "page_and_selection", label: "Current page + selected element" },
  { id: "current_page", label: "Current page" },
  { id: "selected_element", label: "Selected element" },
  { id: "custom", label: "Custom" },
];

export const PLACEMENTS = [
  { id: "cover", label: "Cover" },
  { id: "contain", label: "Contain" },
  { id: "fill", label: "Fill" },
  { id: "original", label: "Original" },
  { id: "background", label: "Background" },
  { id: "inline", label: "Inline" },
  { id: "icon", label: "Icon" },
];

export const TASKS = [
  { id: "generate_image", label: "Generate image", capability: "image.generate", kinds: ["visual", "container", "image", "any"] },
  { id: "replace_image", label: "Replace image", capability: "image.generate", kinds: ["image"] },
  { id: "restyle_image", label: "Restyle image", capability: "image.edit", kinds: ["image"] },
  { id: "image_variants", label: "Image variants", capability: "image.variation", kinds: ["image", "visual"] },
  { id: "expand_image", label: "Expand / outpaint", capability: "image.outpaint", kinds: ["image"] },
  { id: "remove_background", label: "Remove background", capability: "image.background.remove", kinds: ["image"] },
  { id: "generate_icon", label: "Generate icon", capability: "image.generate", kinds: ["visual", "container", "any"] },
  { id: "generate_texture", label: "Generate texture", capability: "image.generate", kinds: ["visual", "container", "any"] },
  { id: "rewrite_text", label: "Rewrite text", capability: "text.rewrite", kinds: ["text"] },
  { id: "generate_text", label: "Generate text", capability: "text.generate", kinds: ["text", "any"] },
  { id: "shorten_text", label: "Shorten text", capability: "text.rewrite", kinds: ["text"] },
  { id: "expand_text", label: "Expand text", capability: "text.rewrite", kinds: ["text"] },
  { id: "analyze_style", label: "Analyze style", capability: "vision.analyze", kinds: ["any"] },
  { id: "suggest_design_change", label: "Suggest design change", capability: "layout.reason", kinds: ["any"] },
];

export function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID().replace(/-/g, "");
  return `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

export function emptyPolicy() {
  return {
    previewOnly: true,
    requireExplicitAccept: true,
    allowDirectSourceRewrite: false,
    allowAssetPersistenceBeforeAccept: false,
  };
}
