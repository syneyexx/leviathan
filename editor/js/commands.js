/**
 * LEVIATHAN STUDIO — command stack with scoped patches.
 * Gestures produce one history entry; undo never clobbers unrelated pages.
 */

import { HISTORY_MAX } from "./constants.js";
import { patchIsEmpty } from "./patches.js";

export function createCommands(ctx) {
  let history = [];
  let index = -1;
  let suppress = 0;
  let gesture = null;
  /** @type {Array<object>} */
  const timeline = [];

  function emit() {
    ctx.store.setState({
      canUndo: index >= 0,
      canRedo: index < history.length - 1,
      historyLabel: index >= 0 ? history[index].label : "",
      historyDepth: history.length,
    });
  }

  function record(cmd) {
    if (suppress) return;
    history = history.slice(0, index + 1);
    history.push(cmd);
    while (history.length > HISTORY_MAX) history.shift();
    index = history.length - 1;
    timeline.push({
      id: `h_${Date.now()}_${timeline.length}`,
      label: cmd.label,
      at: Date.now(),
      page: cmd.page || null,
      summary: cmd.summary || null,
      checkpoint: !!cmd.checkpoint,
    });
    while (timeline.length > HISTORY_MAX * 2) timeline.shift();
    emit();
    ctx.studio?.history?.onRecord?.(cmd);
  }

  function execute({ label, do: apply, undo, page, summary }) {
    if (typeof apply !== "function" || typeof undo !== "function") {
      throw new Error("Command mist do/undo");
    }
    apply();
    record({ label: label || "bewerken", undo, redo: apply, page, summary });
  }

  function undo() {
    endGesture();
    if (index < 0) {
      ctx.content?.setStatus("Niets om terug te zetten", "dirty");
      return false;
    }
    const cmd = history[index];
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    suppress += 1;
    try {
      cmd.undo();
    } finally {
      suppress -= 1;
    }
    index -= 1;
    emit();
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    ctx.content?.setStatus(`Ongedaan: ${cmd.label}`, "ok");
    return true;
  }

  function redo() {
    endGesture();
    if (index >= history.length - 1) {
      ctx.content?.setStatus("Niets om opnieuw te doen", "dirty");
      return false;
    }
    const cmd = history[index + 1];
    ctx.session.uiEpoch = (ctx.session.uiEpoch || 0) + 1;
    suppress += 1;
    try {
      cmd.redo();
    } finally {
      suppress -= 1;
    }
    index += 1;
    emit();
    ctx.store.setState({ uiEpoch: ctx.session.uiEpoch });
    ctx.content?.setStatus(`Opnieuw: ${cmd.label}`, "ok");
    return true;
  }

  function beginGesture(label = "bewerken") {
    if (gesture || suppress || !ctx.content) return;
    gesture = { label, before: ctx.content.snapshot() };
  }

  function endGesture() {
    if (!gesture || suppress || !ctx.content) {
      gesture = null;
      return;
    }
    const { label, before } = gesture;
    gesture = null;
    const after = ctx.content.snapshot();
    if (ctx.content.sameSnap(before, after)) return;
    const patch = ctx.content.patchBetween(before, after);
    if (patchIsEmpty(patch)) return;
    record({
      label,
      page: after.page,
      summary: patch,
      undo: () => ctx.content.restorePatch(patch, "back"),
      redo: () => ctx.content.restorePatch(patch, "forward"),
    });
  }

  function cancelGesture() {
    if (!gesture || !ctx.content) {
      gesture = null;
      return false;
    }
    const { before } = gesture;
    gesture = null;
    // Restore only what this gesture changed so far
    const after = ctx.content.snapshot();
    const patch = ctx.content.patchBetween(before, after);
    if (!patchIsEmpty(patch)) ctx.content.restorePatch(patch, "back");
    ctx.content.setStatus("Gesture geannuleerd", "ok");
    return true;
  }

  function capture(label, fn) {
    if (suppress || gesture) {
      fn();
      return;
    }
    const before = ctx.content.snapshot();
    fn();
    const after = ctx.content.snapshot();
    if (ctx.content.sameSnap(before, after)) return;
    const patch = ctx.content.patchBetween(before, after);
    if (patchIsEmpty(patch)) return;
    record({
      label,
      page: after.page,
      summary: patch,
      undo: () => ctx.content.restorePatch(patch, "back"),
      redo: () => ctx.content.restorePatch(patch, "forward"),
    });
  }

  function reset() {
    history = [];
    index = -1;
    gesture = null;
    emit();
  }

  /** Page bags no longer swap history — selection/camera only. */
  function exportStack() {
    return { history: history.slice(), index };
  }

  function importStack(bag) {
    endGesture();
    history = Array.isArray(bag?.history) ? bag.history.slice() : [];
    index = typeof bag?.index === "number" ? Math.min(bag.index, history.length - 1) : history.length - 1;
    if (index < -1) index = -1;
    emit();
  }

  function namedCheckpoint(name) {
    const snap = ctx.content.snapshot();
    record({
      label: `Checkpoint: ${name}`,
      checkpoint: true,
      page: snap.page,
      summary: { checkpoint: name },
      undo: () => {},
      redo: () => {},
      snapshot: snap,
      name,
    });
    return history[index];
  }

  function getTimeline() {
    return timeline.slice();
  }

  return {
    execute,
    undo,
    redo,
    beginGesture,
    endGesture,
    cancelGesture,
    capture,
    reset,
    exportStack,
    importStack,
    namedCheckpoint,
    getTimeline,
    isGesturing: () => !!gesture,
    isSuppressed: () => suppress > 0,
    _debug: () => ({ length: history.length, index }),
  };
}
