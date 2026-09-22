/**
 * LEVIATHAN STUDIO — capability matrix + registries.
 */

export const Status = {
  VERIFIED: "verified",
  IMPLEMENTED: "implemented but unverified",
  UNAVAILABLE: "unavailable",
  INCOMPLETE: "incomplete",
};

const capabilities = new Map();
const checks = [];
const recipes = [];
const fixtures = [];

export function registerCapability(id, info) {
  capabilities.set(id, { id, ...info, updatedAt: Date.now() });
}

export function setCapability(id, patch) {
  const prev = capabilities.get(id) || { id };
  capabilities.set(id, { ...prev, ...patch, updatedAt: Date.now() });
}

export function getCapabilityMatrix() {
  return [...capabilities.values()].sort((a, b) => a.id.localeCompare(b.id));
}

export function registerCheck(check) {
  checks.push(check);
}

export function listChecks() {
  return checks.slice();
}

export function registerRecipe(recipe) {
  recipes.push(recipe);
}

export function listRecipes() {
  return recipes.slice();
}

export function registerFixture(fixture) {
  fixtures.push(fixture);
}

export function listFixtures() {
  return fixtures.slice();
}

export function seedStudioCapabilities() {
  const rows = [
    ["identity-v3", Status.IMPLEMENTED, "Stable node/shell keys + migration"],
    ["scoped-history", Status.IMPLEMENTED, "Patch undo across pages"],
    ["save-coordinator", Status.IMPLEMENTED, "Queued revision + conflict"],
    ["api-session", Status.IMPLEMENTED, "Origin + session token"],
    ["text-no-global-replace", Status.IMPLEMENTED, "replace-text returns 410"],
    ["clear-styles", Status.IMPLEMENTED, "BEGIN/END import fixed"],
    ["studio-shell", Status.IMPLEMENTED, "Mission-control chrome"],
    ["viewport-preview", Status.IMPLEMENTED, "Design vs Preview iframe"],
    ["gesture-cancel", Status.IMPLEMENTED, "Escape / pointercancel"],
    ["ai-copilot", Status.UNAVAILABLE, "No model binding (501)"],
    ["stress-lab", Status.IMPLEMENTED, "Width sweep overflow checks"],
    ["constraints-intel", Status.IMPLEMENTED, "Why-is-this-here + pins"],
    ["design-problems", Status.IMPLEMENTED, "Issues registry"],
    ["history-timeline", Status.IMPLEMENTED, "Named checkpoints"],
    ["visual-compare", Status.IMPLEMENTED, "Checkpoint overlay compare"],
    ["design-branches", Status.IMPLEMENTED, "Local revision branches"],
    ["states-studio", Status.IMPLEMENTED, "CSS state preview"],
    ["content-scenarios", Status.IMPLEMENTED, "Fixture bridge"],
    ["token-theme-studio", Status.IMPLEMENTED, "Aliases + impact"],
    ["recipes", Status.IMPLEMENTED, "Declarative patch recipes"],
    ["handoff-package", Status.IMPLEMENTED, "Change package export/import"],
    ["precision-hud", Status.IMPLEMENTED, "Selection HUD + live W×H delta labels"],
    ["workspace-recovery", Status.IMPLEMENTED, "Recovery draft + free-transform mid-gesture"],
    ["multi-select-resize", Status.IMPLEMENTED, "Group scale / independent resize math"],
    ["keyboard-resize", Status.IMPLEMENTED, "Alt+arrows through resizeRect"],
    ["image-replace", Status.IMPLEMENTED, "Replace + smart fit; no auto orphan delete"],
    ["zoom-handles", Status.IMPLEMENTED, "≥10px screen handles at 25%–400%"],
    ["equal-spacing-snap", Status.IMPLEMENTED, "3+ sibling equal spacing + density"],
    ["media-library-meta", Status.IMPLEMENTED, "Dims/bytes/mtime/used badge"],
  ];
  for (const [id, status, evidence] of rows) {
    registerCapability(id, { status, evidence, blocker: status === Status.UNAVAILABLE ? evidence : null });
  }
}
