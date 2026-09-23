/**
 * LEVIATHAN STUDIO — save coordinator.
 *
 * Distinct counters (never treat as interchangeable):
 * - localGeneration: bumps on every local edit
 * - acknowledgedLocalGeneration: highest local generation whose snapshot (or a
 *   later superseding snapshot) has been acknowledged by the server
 * - serverRevision / serverHash: authoritative concurrency token from the server
 *
 * One active immutable snapshot at a time. Newer save intents coalesce into a
 * single queued intent. Each caller resolves only when its requested generation
 * or a later superseding generation is acknowledged; terminal failure rejects
 * pending callers. Automatic drain pauses on conflict until explicit retry.
 */

import { FILES } from "./constants.js";

export const SaveState = {
  CLEAN: "clean",
  DIRTY: "dirty",
  SAVING: "saving",
  SAVED: "saved",
  ERROR: "error",
  CONFLICT: "conflict",
  OFFLINE: "offline",
};

/**
 * @typedef {{
 *   generation: number,
 *   baseRevision: number,
 *   baseHash: string,
 *   content: object,
 *   files: Record<string, string>,
 *   dirtyFiles: string[],
 * }} SaveSnapshot
 */

export function createSaveCoordinator(ctx) {
  /** @type {Promise<any> | null} */
  let activePromise = null;
  /** @type {SaveSnapshot | null} */
  let activeSnap = null;
  /** @type {SaveSnapshot | null} */
  let queuedIntent = null;

  let localGeneration = 0;
  let acknowledgedLocalGeneration = 0;
  let serverRevision = 0;
  let serverHash = "";
  /** Baseline of files last acknowledged on disk (may lag the live buffer). */
  let acknowledgedFiles = Object.fromEntries(FILES.map((f) => [f, ""]));
  /** Baseline content clone last acknowledged (null until first adopt/ack). */
  let acknowledgedContent = null;

  let lastError = null;
  let saveState = SaveState.CLEAN;
  /** When true, do not auto-start queued intent (conflict / terminal error). */
  let drainPaused = false;

  /** @type {Array<{ generation: number, resolve: Function, reject: Function }>} */
  let waiters = [];

  function emit() {
    ctx.store.setState({
      saveState,
      saveRevision: localGeneration,
      savedRevision: serverRevision,
      saveError: lastError,
      contentRevision: serverRevision,
      contentHash: serverHash,
    });
  }

  function bufferDiffersFromAck(s = ctx.store.getState()) {
    if (localGeneration > acknowledgedLocalGeneration) return true;
    if (s.contentDirty && localGeneration > acknowledgedLocalGeneration) return true;
    for (const name of FILES) {
      if ((s.files[name] ?? "") !== (acknowledgedFiles[name] ?? "")) return true;
    }
    return false;
  }

  function isDirty(s = ctx.store.getState()) {
    if (saveState === SaveState.CONFLICT || saveState === SaveState.ERROR || saveState === SaveState.OFFLINE) {
      return true;
    }
    return bufferDiffersFromAck(s);
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
    localGeneration += 1;
    if (saveState !== SaveState.SAVING && saveState !== SaveState.CONFLICT) {
      saveState = SaveState.DIRTY;
    }
    ctx.store.setState({ contentDirty: true });
    emit();
  }

  /**
   * Capture an immutable snapshot of the current buffer.
   * baseRevision/baseHash are stamped from the *current* acknowledged server
   * token at capture time; run() re-stamps again immediately before dispatch so
   * a queued intent never reuses a pre-ack base.
   */
  function takeSnapshot() {
    ctx.content?.syncNodesFromDom?.();
    const s = ctx.store.getState();
    const content = JSON.parse(JSON.stringify(ctx.content.ensure()));
    const files = {};
    for (const name of FILES) files[name] = s.files[name] ?? "";
    const dirtyFiles = FILES.filter((f) => files[f] !== (acknowledgedFiles[f] ?? ""));
    return {
      generation: localGeneration,
      baseRevision: serverRevision,
      baseHash: serverHash,
      content,
      files,
      dirtyFiles,
    };
  }

  function stampBase(snap) {
    return {
      ...snap,
      baseRevision: serverRevision,
      baseHash: serverHash,
    };
  }

  function resolveWaiters(ackedGeneration, result) {
    const kept = [];
    for (const w of waiters) {
      if (w.generation <= ackedGeneration) w.resolve(result);
      else kept.push(w);
    }
    waiters = kept;
  }

  function rejectWaiters(err, { all = false } = {}) {
    if (all) {
      const batch = waiters;
      waiters = [];
      for (const w of batch) w.reject(err);
      return;
    }
    // Reject only waiters whose generation was covered by the failed active snap
    const failedGen = activeSnap?.generation ?? -1;
    const kept = [];
    for (const w of waiters) {
      if (w.generation <= failedGen) w.reject(err);
      else kept.push(w);
    }
    waiters = kept;
  }

  function applyAck(snap, result) {
    const s = ctx.store.getState();
    const saved = { ...s.saved };
    const dirtyFiles = { ...s.dirtyFiles };

    for (const name of snap.dirtyFiles) {
      acknowledgedFiles[name] = snap.files[name];
      // Live buffer may have advanced past this snap
      if (s.files[name] === snap.files[name]) {
        saved[name] = snap.files[name];
        dirtyFiles[name] = false;
      } else {
        dirtyFiles[name] = true;
      }
    }

    acknowledgedContent = JSON.parse(JSON.stringify(snap.content));
    acknowledgedLocalGeneration = Math.max(acknowledgedLocalGeneration, snap.generation);
    serverRevision = result.revision != null ? Number(result.revision) : serverRevision + 1;
    serverHash = result.hash != null ? String(result.hash) : serverHash;

    const stillDirty = bufferDiffersFromAck({ ...s, files: s.files, contentDirty: false });
    // contentDirty tracks unacked local generation, not server revision
    const contentDirty = localGeneration > acknowledgedLocalGeneration || stillDirty;

    ctx.store.setState({
      saved,
      dirtyFiles,
      contentDirty,
      contentRevision: serverRevision,
      contentHash: serverHash,
    });

    if (contentDirty) {
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
  }

  async function run(snap) {
    const stamped = stampBase(snap);
    activeSnap = stamped;
    saveState = SaveState.SAVING;
    lastError = null;
    emit();
    refreshStatus();

    try {
      const result = await ctx.api.saveTransaction({
        revision: stamped.generation,
        baseRevision: stamped.baseRevision,
        baseHash: stamped.baseHash,
        content: stamped.content,
        files: Object.fromEntries(stamped.dirtyFiles.map((name) => [name, stamped.files[name]])),
      });

      applyAck(stamped, result);
      resolveWaiters(stamped.generation, { ok: true, ...result, generation: stamped.generation });
      return result;
    } catch (err) {
      if (err?.status === 409 || err?.payload?.error === "conflict") {
        saveState = SaveState.CONFLICT;
        lastError = "Conflict met schijfversie";
        drainPaused = true;
      } else if (err?.status === 0 || /Failed to fetch|NetworkError|offline/i.test(String(err?.message || ""))) {
        saveState = SaveState.OFFLINE;
        lastError = "API offline";
        drainPaused = true;
      } else {
        saveState = SaveState.ERROR;
        lastError = String(err?.message || err);
        drainPaused = true;
      }
      emit();
      refreshStatus();
      // Terminal failure: every pending caller for this attempt must settle.
      // Drain is paused — queued intent is retained for explicit retry only.
      rejectWaiters(err, { all: true });
      throw err;
    } finally {
      const failed = drainPaused;
      activeSnap = null;
      activePromise = null;
      if (!failed && queuedIntent) {
        const next = queuedIntent;
        queuedIntent = null;
        activePromise = run(next).catch(() => {});
      }
    }
  }

  /**
   * Persist the current buffer (or force a conflicted retry).
   * Resolves when this caller's generation — or a later coalesced generation —
   * is acknowledged. Rejects on terminal failure covering that generation.
   */
  function saveAll({ force = false } = {}) {
    if (force) drainPaused = false;

    if (!force && !isDirty() && saveState !== SaveState.CONFLICT) {
      saveState = SaveState.CLEAN;
      ctx.content?.setStatus?.("Niets te opslaan", "ok");
      emit();
      return Promise.resolve({ ok: true, skipped: true, generation: acknowledgedLocalGeneration });
    }

    if (drainPaused && !force && saveState === SaveState.CONFLICT) {
      return Promise.reject(Object.assign(new Error("Conflict — expliciet retry vereist"), { status: 409, paused: true }));
    }

    const requestedGeneration = Math.max(localGeneration, 1);
    // Ensure there is something to save if force was used on a clean doc
    if (localGeneration === 0 && force) {
      localGeneration = 1;
    }

    const snap = takeSnapshot();
    // If the buffer generation is behind the caller's mark (edge), stamp call gen
    if (snap.generation < requestedGeneration) snap.generation = requestedGeneration;

    return new Promise((resolve, reject) => {
      waiters.push({ generation: snap.generation, resolve, reject });

      if (activePromise) {
        // Coalesce: newer intent replaces queued; waiters stay until that gen acks
        queuedIntent = snap;
        return;
      }

      if (drainPaused && !force) {
        // Offline/error: keep waiter + intent for explicit retry
        queuedIntent = snap;
        return;
      }

      drainPaused = false;
      activePromise = run(snap).catch(() => {});
    });
  }

  function markDirty() {
    bumpLocal();
  }

  function adoptServer(meta) {
    if (meta?.revision != null) {
      serverRevision = Number(meta.revision);
    }
    if (meta?.hash) serverHash = String(meta.hash);
    const s = ctx.store.getState();
    for (const name of FILES) {
      acknowledgedFiles[name] = s.saved?.[name] ?? s.files?.[name] ?? "";
    }
    if (s.content) acknowledgedContent = JSON.parse(JSON.stringify(s.content));
    // Align local generation floor without inventing dirtiness
    if (localGeneration < acknowledgedLocalGeneration) {
      localGeneration = acknowledgedLocalGeneration;
    }
    saveState = SaveState.CLEAN;
    drainPaused = false;
    emit();
  }

  /** Explicit resume after conflict resolution (caller already reconciled buffer). */
  function clearConflictAndRetry() {
    drainPaused = false;
    saveState = SaveState.DIRTY;
    return saveAll({ force: true });
  }

  function getState() {
    return {
      saveState,
      localGeneration,
      acknowledgedLocalGeneration,
      localRevision: localGeneration,
      savedRevision: serverRevision,
      serverRevision,
      serverHash,
      savedHash: serverHash,
      lastError,
      busy: !!activePromise,
      drainPaused,
      queued: !!queuedIntent,
      acknowledgedFiles: { ...acknowledgedFiles },
    };
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
    clearConflictAndRetry,
    /** @internal test hook */
    _debug: () => ({
      localGeneration,
      acknowledgedLocalGeneration,
      serverRevision,
      serverHash,
      activeSnap,
      queuedIntent,
      drainPaused,
      waiterCount: waiters.length,
    }),
  };
}
