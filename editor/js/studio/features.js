/**
 * LEVIATHAN STUDIO — Wave capabilities (stress, constraints, history, compare,
 * branches, states, fixtures, tokens, recipes, handoff, HUD, recovery).
 */

import { uid } from "../util.js";
import { diffSnapshots, applyPatch, hashDocument } from "../patches.js";
import { listFixtures, listRecipes, registerFixture, registerRecipe } from "../capabilities/registry.js";
import { resizeGroupMembers } from "../geometry.js";

export function createStudioFeatures(ctx) {
  const branches = new Map();
  let activeBranch = "main";
  const recoveryKey = "lvb.recovery.v1";

  function seedRecipes() {
    if (listRecipes().length) return;
    registerRecipe({
      id: "card-spacing",
      name: "Kaart met consistente spacing",
      version: 1,
      preconditions: { hasSelection: true },
      params: { gap: "12px", padding: "16px" },
      patches(selection, params) {
        return selection.map((el) => ({
          el,
          props: { gap: params.gap, padding: params.padding, display: "flex", "flex-direction": "column" },
        }));
      },
    });
    registerRecipe({
      id: "compact-form",
      name: "Compacte formuliergroep",
      version: 1,
      preconditions: { hasSelection: true },
      params: { gap: "8px" },
      patches(selection, params) {
        return selection.map((el) => ({
          el,
          props: { gap: params.gap, display: "grid" },
        }));
      },
    });
  }

  function seedFixtures() {
    if (listFixtures().length) return;
    registerFixture({ id: "empty", label: "Leeg", scenario: "empty" });
    registerFixture({ id: "loading", label: "Laden", scenario: "loading" });
    registerFixture({ id: "error", label: "Fout", scenario: "error" });
    registerFixture({ id: "success", label: "Succes", scenario: "success" });
    registerFixture({ id: "long-nl", label: "Lange NL-labels", scenario: "long-nl" });
    registerFixture({ id: "text-200", label: "Tekst 200%", scenario: "text-200" });
    registerFixture({ id: "missing-img", label: "Ontbrekende afbeelding", scenario: "missing-img" });
  }

  /**
   * Responsive Stress Lab — CONTAINER WIDTH PROBE only.
   * Does not vary viewport media queries, vw units, or fixed positioning.
   * Findings are heuristic until a real iframe viewport runner replaces this.
   */
  async function runStressLab({ from = 320, to = 1920, step = 80, fixtureId = null } = {}) {
    const findings = [];
    const generation = ctx.save?.getState?.()?.localGeneration ?? ctx.store.getState().saveRevision ?? 0;
    const host = document.createElement("div");
    host.className = "lvb-stress-lab";
    host.style.cssText = "position:fixed;left:-99999px;top:0;pointer-events:none;opacity:0;";
    document.documentElement.appendChild(host);
    const sample = document.querySelector(".lv-main") || document.getElementById("root");
    if (!sample) {
      host.remove();
      return {
        findings: [],
        error: "Geen documentroot",
        kind: "container-probe",
        unsupported: ["viewport-media-queries", "vw-units", "position-fixed"],
        generation,
      };
    }
    const clone = sample.cloneNode(true);
    clone.querySelectorAll("script").forEach((n) => n.remove());
    if (fixtureId === "long-nl") {
      clone.querySelectorAll("button, a, label, h1, h2, h3").forEach((el) => {
        el.textContent = `${el.textContent || ""} — Lang Nederlands label voor stress`;
      });
    }
    // Scope text-scale to the probe clone — never the parent document root
    if (fixtureId === "text-200") clone.style.fontSize = "200%";
    host.appendChild(clone);
    for (let w = from; w <= to; w += step) {
      host.style.width = `${w}px`;
      clone.style.width = `${w}px`;
      // Force layout
      const scrollW = clone.scrollWidth;
      const clientW = clone.clientWidth;
      if (scrollW > clientW + 1) {
        findings.push({
          width: w,
          rule: "horizontal-overflow",
          severity: "error",
          deterministic: true,
          kind: "container-probe",
          message: `Horizontale overflow bij container ${w}px (geen viewport MQ)`,
          evidence: `scrollWidth ${scrollW} > clientWidth ${clientW}`,
          generation,
        });
      }
      clone.querySelectorAll("button, a, [role='button']").forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24)) {
          findings.push({
            width: w,
            rule: "min-target-size",
            severity: "warning",
            deterministic: true,
            kind: "container-probe",
            message: `Doelgrootte < 24px bij container ${w}px`,
            nodeHint: el.className || el.tagName,
            evidence: `${Math.round(r.width)}×${Math.round(r.height)}`,
            generation,
          });
        }
      });
    }
    host.remove();
    const result = {
      findings,
      from,
      to,
      step,
      fixtureId,
      kind: "container-probe",
      unsupported: ["viewport-media-queries", "vw-units", "position-fixed"],
      generation,
    };
    ctx.store.setState({ stressFindings: findings, stressEpoch: Date.now(), stressMeta: result });
    return result;
  }

  /** B — Why is this here? */
  function explainLayout(el) {
    if (!(el instanceof Element)) return null;
    const cs = getComputedStyle(el);
    const parent = el.parentElement;
    const pcs = parent ? getComputedStyle(parent) : null;
    const entry = ctx.content.getEntry(ctx.selection.selectorFor(el));
    return {
      display: cs.display,
      position: cs.position,
      width: cs.width,
      height: cs.height,
      margin: cs.margin,
      parentDisplay: pcs?.display,
      containingBlock: pcs?.position,
      breakpoint: ctx.store.getState().breakpoint,
      overrideSource: entry?.styles ? "local override" : "computed/inherited",
      rules: [
        `parent display: ${pcs?.display || "—"}`,
        `position: ${cs.position}`,
        `width: ${cs.width} (min ${cs.minWidth}, max ${cs.maxWidth})`,
        entry?.breakpoints ? `breakpoint overrides: ${Object.keys(entry.breakpoints).join(", ")}` : "geen breakpoint overrides",
      ],
    };
  }

  /** D — checkpoints */
  function createCheckpoint(name) {
    return ctx.commands.namedCheckpoint(name || `Checkpoint ${new Date().toLocaleString()}`);
  }

  /** E — document diff against checkpoint (NOT rendered visual compare) */
  function compareToCheckpoint(cmd) {
    if (!cmd?.snapshot) return null;
    const now = ctx.content.snapshot();
    const patch = diffSnapshots(cmd.snapshot, now);
    return {
      kind: "document-diff",
      visualCompare: false,
      reason: "Rendered before/after captures are not available in this path",
      patch,
    };
  }

  /** F — design branches */
  function createBranch(name) {
    const id = uid("br");
    const snap = ctx.content.snapshot();
    branches.set(id, { id, name: name || `Variant ${branches.size + 1}`, base: snap, head: snap, createdAt: Date.now() });
    return branches.get(id);
  }

  function checkoutBranch(id) {
    const br = branches.get(id);
    if (!br) return false;
    activeBranch = id;
    ctx.content.restore(br.head);
    return true;
  }

  function commitBranch() {
    const br = branches.get(activeBranch);
    if (!br || activeBranch === "main") return null;
    br.head = ctx.content.snapshot();
    return br;
  }

  function mergeBranch(id) {
    const br = branches.get(id);
    if (!br) return { ok: false, error: "branch ontbreekt" };
    const mainNow = ctx.content.snapshot();
    const patch = diffSnapshots(br.base, br.head);
    const conflicts = [];
    for (const [key, pair] of Object.entries(patch.entries || {})) {
      const mainEntry = mainNow.content.entries?.[key];
      const baseEntry = br.base.content.entries?.[key];
      if (mainEntry && JSON.stringify(mainEntry) !== JSON.stringify(baseEntry) && JSON.stringify(mainEntry) !== JSON.stringify(pair.after)) {
        conflicts.push({ key, property: "*", ours: mainEntry, theirs: pair.after });
      }
    }
    if (conflicts.length) return { ok: false, conflicts };
    ctx.commands.capture(`Merge branch ${br.name}`, () => {
      const s = ctx.store.getState();
      const next = applyPatch(s, patch, "forward");
      ctx.store.setState({ content: next.content, files: next.files, contentDirty: true });
      ctx.content.reapply();
      ctx.content.markContentDirty();
    });
    return { ok: true, conflicts: [] };
  }

  /** G — state preview via stylesheet, no permanent app mutation */
  function previewState(stateName) {
    let style = document.getElementById("lvb-state-preview");
    if (!style) {
      style = document.createElement("style");
      style.id = "lvb-state-preview";
      document.head.appendChild(style);
    }
    const el = ctx.session.primary;
    if (!el) return;
    const sel = el.dataset.lvbNode ? `[data-lvb-node="${el.dataset.lvbNode}"]` : null;
    if (!sel) return;
    const map = {
      hover: `${sel}:hover, ${sel}.lvb-state-hover`,
      "focus-visible": `${sel}:focus-visible, ${sel}.lvb-state-focus`,
      pressed: `${sel}:active, ${sel}.lvb-state-pressed`,
      disabled: `${sel}:disabled, ${sel}.lvb-state-disabled`,
    };
    el.classList.remove("lvb-state-hover", "lvb-state-focus", "lvb-state-pressed", "lvb-state-disabled");
    if (stateName && stateName !== "default") {
      el.classList.add(`lvb-state-${stateName === "focus-visible" ? "focus" : stateName}`);
      style.textContent = `${map[stateName] || sel}{ outline: 1px dashed var(--studio-accent, #72C7FF); }`;
    } else style.textContent = "";
  }

  /** H — content scenarios (scoped to #root; never enlarge editor chrome via <html> font-size) */
  function applyFixture(id) {
    seedFixtures();
    const fx = listFixtures().find((f) => f.id === id);
    const root = document.getElementById("root");
    document.documentElement.dataset.lvbFixture = fx?.scenario || "";
    // Clear any legacy root font-size side effect from earlier builds
    document.documentElement.style.fontSize = "";
    if (root) {
      if (fx?.scenario === "text-200") root.style.fontSize = "200%";
      else root.style.fontSize = "";
      root.dataset.lvbFixture = fx?.scenario || "";
    }
    ctx.store.setState({ activeFixture: id || null });
    return fx || { unavailable: true, reason: "Geen adapter voor deze route" };
  }

  function clearFixture() {
    delete document.documentElement.dataset.lvbFixture;
    document.documentElement.style.fontSize = "";
    const root = document.getElementById("root");
    if (root) {
      delete root.dataset.lvbFixture;
      root.style.fontSize = "";
    }
    ctx.store.setState({ activeFixture: null });
  }

  /**
   * Change Impact Review — plan a patch and summarize affected scope before apply.
   * Counts come from the planned patch only (never invented).
   */
  function planImpact(before, after, { label = "wijziging" } = {}) {
    const patch = diffSnapshots(before, after);
    const summary = {
      label,
      entries: Object.keys(patch.entries || {}).length,
      nodeOps: (patch.nodeOps || []).length,
      componentOps: (patch.componentOps || []).length,
      metaKeys: Object.keys(patch.metaDiff || {}).length,
      files: Object.keys(patch.files || {}),
      pages: [],
    };
    const pages = new Set();
    for (const pair of Object.values(patch.entries || {})) {
      const e = pair.after || pair.before;
      if (e?.page && e.page !== "*") pages.add(e.page);
    }
    for (const op of patch.nodeOps || []) {
      const n = op.after || op.before;
      if (n?.page && n.page !== "*") pages.add(n.page);
    }
    summary.pages = [...pages];
    return { patch, summary, empty: !summary.entries && !summary.nodeOps && !summary.componentOps && !summary.metaKeys && !summary.files.length };
  }

  function applyImpact(plan, label) {
    if (!plan || plan.empty) return { ok: false, reason: "geen wijzigingen" };
    ctx.commands.capture(label || plan.summary?.label || "impact", () => {
      const s = ctx.store.getState();
      const next = applyPatch({ content: s.content, files: s.files }, plan.patch, "forward");
      ctx.store.setState({ content: next.content, files: next.files, contentDirty: true });
      ctx.content.markContentDirty?.();
      ctx.content.reapply?.();
    });
    return { ok: true, summary: plan.summary };
  }

  /**
   * Token rename — updates var(--old) references only inside token/CSS files
   * and content style entries that contain the exact var() form. Not a raw
   * global source replace.
   */
  function planTokenRename(oldName, newName) {
    if (!oldName || !newName || oldName === newName) return { empty: true, error: "ongeldige namen" };
    if (!/^--[\w-]+$/.test(oldName) || !/^--[\w-]+$/.test(newName)) {
      return { empty: true, error: "token namen moeten --ident zijn" };
    }
    const before = ctx.content.snapshot();
    const after = JSON.parse(JSON.stringify(before));
    const needle = `var(${oldName})`;
    const replacement = `var(${newName})`;
    const reDecl = new RegExp(`(^|[\\s;{])${oldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:`, "g");
    for (const [name, text] of Object.entries(after.files || {})) {
      let next = String(text || "").split(needle).join(replacement);
      next = next.replace(reDecl, `$1${newName}:`);
      after.files[name] = next;
    }
    for (const [key, entry] of Object.entries(after.content.entries || {})) {
      if (!entry?.styles) continue;
      for (const [prop, value] of Object.entries(entry.styles)) {
        if (typeof value === "string" && value.includes(needle)) {
          entry.styles[prop] = value.split(needle).join(replacement);
        }
      }
    }
    return planImpact(before, after, { label: `Token hernoemen ${oldName} → ${newName}` });
  }

  /** K — recipes */
  function dryRunRecipe(id) {
    seedRecipes();
    const recipe = listRecipes().find((r) => r.id === id);
    if (!recipe) return { ok: false, error: "onbekend" };
    const sel = ctx.selection.mutable("edit");
    const planned = recipe.patches(sel, recipe.params);
    return { ok: true, recipe, nodes: planned.length, planned };
  }

  function applyRecipe(id) {
    const dry = dryRunRecipe(id);
    if (!dry.ok) return dry;
    ctx.commands.capture(`Recipe: ${dry.recipe.name}`, () => {
      for (const item of dry.planned) {
        for (const [prop, value] of Object.entries(item.props || {})) {
          ctx.content.applyProp(item.el, prop, value);
        }
      }
    });
    return { ok: true };
  }

  /** L — handoff package */
  function exportChangePackage() {
    const s = ctx.store.getState();
    const pkg = {
      schema: 1,
      exportedAt: Date.now(),
      baseRevision: s.contentRevision || 0,
      baseHash: s.contentHash || hashDocument(s.content, s.files),
      content: s.content,
      files: s.files,
      summary: {
        entries: Object.keys(s.content?.entries || {}).length,
        nodes: s.content?.nodes?.length || 0,
        dirty: s.contentDirty,
      },
    };
    return pkg;
  }

  function importChangePackage(pkg, { preview = true } = {}) {
    if (!pkg || pkg.schema !== 1) return { ok: false, error: "Ongeldig schema" };
    const s = ctx.store.getState();
    if (pkg.baseHash && s.contentHash && pkg.baseHash !== s.contentHash) {
      return { ok: false, error: "conflict", conflict: true };
    }
    if (preview) return { ok: true, preview: true, summary: pkg.summary };
    ctx.commands.capture("Import change package", () => {
      ctx.store.setState({ content: pkg.content, files: pkg.files, contentDirty: true });
      ctx.content.reapply();
      ctx.content.markContentDirty();
    });
    return { ok: true, applied: true };
  }

  /** N — recovery */
  let freeTransformDraft = null;

  function captureFreeTransformState(origins) {
    freeTransformDraft = {
      at: Date.now(),
      boxes: (origins || []).map((o) => ({
        id: o.el?.dataset?.lvbNode || o.el?.dataset?.lvbId || null,
        left: o.left,
        top: o.top,
        width: o.width,
        height: o.height,
      })),
    };
    writeRecoveryDraft();
  }

  function clearFreeTransformState() {
    freeTransformDraft = null;
  }

  function writeRecoveryDraft() {
    try {
      const snap = ctx.content.snapshot();
      const s = ctx.store.getState();
      const draft = {
        savedAt: Date.now(),
        baseRevision: s.contentRevision || 0,
        baseHash: s.contentHash || "",
        docId: s.content?.docId,
        snap,
        freeTransform: freeTransformDraft,
      };
      localStorage.setItem(recoveryKey, JSON.stringify(draft));
    } catch {
      /* quota */
    }
  }

  function readRecoveryDraft() {
    try {
      return JSON.parse(localStorage.getItem(recoveryKey) || "null");
    } catch {
      return null;
    }
  }

  function clearRecoveryDraft() {
    localStorage.removeItem(recoveryKey);
    freeTransformDraft = null;
  }

  /** Stress preset: multi-select resize + image replace + undo across three pages (synthetic). */
  async function runMultiPageGestureStress() {
    const pages = (ctx.pages?.EDITOR_PAGES || []).slice(0, 3).map((p) => p.path);
    if (pages.length < 1) return { ok: false, error: "Geen pagina's" };
    const findings = [];
    let steps = 0;
    const startSnap = ctx.content.snapshot();
    try {
      for (const path of pages) {
        if (ctx.pages?.go) await ctx.pages.go(path);
        const els = [...document.querySelectorAll("[data-lvb-id], .lvb-widget, img")].filter(
          (el) => !el.closest?.("#lvb-root") && ctx.selection.canMutate?.(el),
        );
        if (els.length >= 2) {
          ctx.selection.set(els.slice(0, Math.min(5, els.length)), els[0]);
          const members = [];
          for (const el of ctx.session.selected) {
            const box = ctx.layout.ensureFreeTransform?.(el);
            if (box) members.push({ el, ...box });
          }
          if (members.length >= 2) {
            const starts = members.map(({ left, top, width, height }) => ({ left, top, width, height }));
            const nexts = resizeGroupMembers({
              members: starts,
              primaryIndex: 0,
              dir: "se",
              dx: 8,
              dy: 8,
              mode: "scale",
            });
            ctx.commands.capture("stress-group-resize", () => {
              members.forEach((m, i) => {
                ctx.layout.writeLiveBox(m.el, nexts[i]);
                ctx.layout.commitBox(m.el);
              });
            });
            steps += 1;
            ctx.commands.undo();
            steps += 1;
          }
        }
        const img = document.querySelector("img:not(#lvb-root img)");
        if (img && ctx.selection.canMutate?.(img)) {
          ctx.selection.set([img], img);
          const prev = img.getAttribute("src");
          ctx.commands.capture("stress-image", () => {
            img.setAttribute("src", prev || img.src);
            ctx.content.patchEntry(ctx.selection.selectorFor(img), { src: prev || img.getAttribute("src") });
          });
          steps += 1;
          ctx.commands.undo();
          steps += 1;
        }
      }
      // Restore original document if still dirty from stress
      const after = ctx.content.snapshot();
      if (JSON.stringify(after.content) !== JSON.stringify(startSnap.content)) {
        findings.push({ message: "Document drift after stress — restoring start snap" });
        ctx.content.restorePatch?.(ctx.content.patchBetween(startSnap, after), "back");
      }
      return { ok: true, steps, findings, pages };
    } catch (err) {
      return { ok: false, error: String(err.message || err), steps, findings };
    }
  }

  // Autosave recovery draft on dirty — never while an uncommitted gesture is open
  if (typeof window !== "undefined") {
    setInterval(() => {
      if (ctx.commands?.isGesturing?.()) return;
      if (ctx.save?.isDirty?.()) writeRecoveryDraft();
    }, 5000);
  }

  seedRecipes();
  seedFixtures();

  return {
    runStressLab,
    runMultiPageGestureStress,
    explainLayout,
    createCheckpoint,
    compareToCheckpoint,
    createBranch,
    checkoutBranch,
    commitBranch,
    mergeBranch,
    previewState,
    applyFixture,
    clearFixture,
    planImpact,
    applyImpact,
    planTokenRename,
    dryRunRecipe,
    applyRecipe,
    exportChangePackage,
    importChangePackage,
    writeRecoveryDraft,
    readRecoveryDraft,
    clearRecoveryDraft,
    captureFreeTransformState,
    clearFreeTransformState,
    listRecipes: () => (seedRecipes(), listRecipes()),
    listFixtures: () => (seedFixtures(), listFixtures()),
    getBranches: () => [...branches.values()],
  };
}
