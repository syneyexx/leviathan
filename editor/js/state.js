/**
 * Leviathan Visual Builder — store.
 * Shallow merge + subscribe. Nested content/files are mutated in place, then a patch notifies.
 */

export function createStore(initial) {
  let state = { ...initial };
  const listeners = new Set();

  function emit() {
    for (const fn of listeners) fn(state);
  }

  return {
    getState: () => state,
    setState(patch) {
      const partial = typeof patch === "function" ? patch(state) : patch;
      if (!partial) return;
      let changed = false;
      for (const key of Object.keys(partial)) {
        if (state[key] !== partial[key]) {
          changed = true;
          break;
        }
      }
      if (!changed) return;
      state = { ...state, ...partial };
      emit();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
