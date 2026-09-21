/**
 * Leviathan Visual Builder — command stack.
 * execute({ do, undo, label }) plus snapshot gestures (history on pointerup, not per move).
 */

import { HISTORY_MAX } from "./constants.js";

export function createCommands(ctx) {
  let history = [];
  let index = -1;
  let suppress = 0;
  let gesture = null;

  function emit() {
    ctx.store.setState({
      canUndo: index >= 0,
      canRedo: index < history.length - 1,
      historyLabel: index >= 0 ? history[index].label : "",
    });
  }

  function record(cmd) {
    if (suppress) return;
    history = history.slice(0, index + 1);
    history.push(cmd);
    while (history.length > HISTORY_MAX) history.shift();
    index = history.length - 1;
    emit();
  }

  function execute({ label, do: apply, undo }) {
    if (typeof apply !== "function" || typeof undo !== "function") {
      throw new Error("Command mist do/undo");
    }
    apply();
    record({ label: label || "bewerken", undo, redo: apply });
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
    record({
      label,
      undo: () => ctx.content.restore(before),
      redo: () => ctx.content.restore(after),
    });
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
    record({
      label,
      undo: () => ctx.content.restore(before),
      redo: () => ctx.content.restore(after),
    });
  }

  function reset() {
    history = [];
    index = -1;
    gesture = null;
    emit();
  }

  return {
    execute,
    undo,
    redo,
    beginGesture,
    endGesture,
    capture,
    reset,
    isGesturing: () => !!gesture,
    isSuppressed: () => suppress > 0,
    _debug: () => ({ length: history.length, index }),
  };
}
