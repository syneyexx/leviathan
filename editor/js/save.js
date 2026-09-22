/**
 * LEVIATHAN STUDIO — save coordinator.
 */

import { FILES } from "./constants.js";
import { hashDocument } from "./patches.js";

export const SaveState = {
  CLEAN: "clean",
  DIRTY: "dirty",
  SAVING: "saving",
  SAVED: "saved",
  ERROR: "error",
  CONFLICT: "conflict",
  OFFLINE: "offline",
};

export function createSaveCoordinator(ctx) {
  let active = null;
  let queued = null;
  let localRevision = 0;
  let savedRevision = 0;
  let savedHash = "";
  let lastError = null;
  let saveState = SaveState.CLEAN;

  function emit() {
    ctx.store.setState({
      saveState,
      saveRevision: localRevision,
      savedRevision,
      saveError: lastError,
    });
  }

  function isDirty(s = ctx.store.getState()) {
    if (s.contentDirty) return true;
    if (localRevision > savedRevision) return true;
    return FILES.some((f) => s.files[f] !== s.saved[f]);
  }

  function refreshStatus() {
    if (saveState === SaveState.SAVING) {
      ctx.content?.setStatus?.("Opslaan…", "");
      return;
    }
    if (saveState === SaveState.CONFLICT) {
      ctx.content?.setStatus?.("Conflict — externe wijziging", "dirty");
      emit();
      return;
    }
    if (saveState === SaveState.ERROR) {
      ctx.content?.setStatus?.(lastError || "Opslaan mislukt", "dirty");
      emit();
      return;
    }
    if (saveState === SaveState.OFFLINE) {
      ctx.content?.setStatus?.("API offline", "dirty");
      emit();
      return;
    }
    if (isDirty()) {
      saveState = SaveState.DIRTY;
      ctx.content?.setStatus?.("Niet opgeslagen", "dirty");
    } else {
      saveState = SaveState.CLEAN;
      ctx.content?.setStatus?.("Gesynchroniseerd", "ok");
    }
    emit();
  }

  function bumpLocal() {
    localRevision += 1;
    if (saveState !== SaveState.SAVING && saveState !== SaveState.CONFLICT) {
      saveState = SaveState.DIRTY;
    }
    ctx.store.setState({ contentDirty: true });
    emit();
  }

  function takeSnapshot() {
    ctx.content?.syncNodesFromDom?.();
    const s = ctx.store.getState();
    const content = JSON.parse(JSON.stringify(ctx.content.ensure()));
    const files = {};
    for (const name of FILES) files[name] = s.files[name] ?? "";
    const dirtyFiles = FILES.filter((f) => files[f] !== (s.saved[f] ?? ""));
    return {
      revision: localRevision,
      baseRevision: savedRevision,
      baseHash: savedHash,
      content,
      files,
      dirtyFiles,
    };
  }

  async function run(snap) {
    saveState = SaveState.SAVING;
    lastError = null;
    emit();
    refreshStatus();
    try {
      const result = await ctx.api.saveTransaction({
        revision: snap.revision,
        baseRevision: snap.baseRevision,
        baseHash: snap.baseHash,
        content: snap.content,
        files: Object.fromEntries(snap.dirtyFiles.map((name) => [name, snap.files[name]])),
      });

      const s = ctx.store.getState();
      const saved = { ...s.saved };
      const dirtyFiles = { ...s.dirtyFiles };
      for (const name of snap.dirtyFiles) {
        if (s.files[name] === snap.files[name]) {
          saved[name] = snap.files[name];
          dirtyFiles[name] = false;
        } else {
          dirtyFiles[name] = true;
        }
      }

      savedRevision = result.revision ?? snap.revision;
      savedHash = result.hash || hashDocument(snap.content, snap.files);

      // Dirty stays true if edits continued during the request
      const editedDuring = localRevision > snap.revision;
      const stillFileDirty = FILES.some((f) => s.files[f] !== saved[f]);
      ctx.store.setState({
        saved,
        dirtyFiles,
        contentDirty: editedDuring,
        contentRevision: savedRevision,
        contentHash: savedHash,
      });

      if (editedDuring || stillFileDirty) {
        saveState = SaveState.DIRTY;
        ctx.content?.setStatus?.("Opgeslagen · nieuwe edits open", "dirty");
      } else {
        saveState = SaveState.SAVED;
        ctx.content?.setStatus?.("Opgeslagen", "ok");
        setTimeout(() => {
          if (saveState === SaveState.SAVED && !isDirty()) {
            saveState = SaveState.CLEAN;
            emit();
            refreshStatus();
          }
        }, 600);
      }
      emit();
      return result;
    } catch (err) {
      if (err?.status === 409 || err?.payload?.error === "conflict") {
        saveState = SaveState.CONFLICT;
        lastError = "Conflict met schijfversie";
      } else if (err?.status === 0 || /Failed to fetch|NetworkError|offline/i.test(String(err?.message || ""))) {
        saveState = SaveState.OFFLINE;
        lastError = "API offline";
      } else {
        saveState = SaveState.ERROR;
        lastError = String(err?.message || err);
      }
      emit();
      refreshStatus();
      throw err;
    } finally {
      active = null;
      if (queued) {
        const next = queued;
        queued = null;
        active = run(next);
      }
    }
  }

  function saveAll({ force = false } = {}) {
    if (!force && !isDirty() && saveState !== SaveState.CONFLICT) {
      saveState = SaveState.CLEAN;
      ctx.content?.setStatus?.("Niets te opslaan", "ok");
      emit();
      return Promise.resolve({ ok: true, skipped: true });
    }
    const snap = takeSnapshot();
    if (active) {
      queued = snap; // newest revision wins
      return active.then(() => ({ ok: true, queued: true }));
    }
    active = run(snap);
    return active;
  }

  function markDirty() {
    bumpLocal();
  }

  function adoptServer(meta) {
    if (meta?.revision != null) {
      savedRevision = meta.revision;
      localRevision = Math.max(localRevision, meta.revision);
    }
    if (meta?.hash) savedHash = meta.hash;
    saveState = SaveState.CLEAN;
    emit();
  }

  function getState() {
    return { saveState, localRevision, savedRevision, savedHash, lastError, busy: !!active };
  }

  return {
    SaveState,
    saveAll,
    markDirty,
    adoptServer,
    refreshStatus,
    isDirty,
    getState,
    bumpLocal,
  };
}
