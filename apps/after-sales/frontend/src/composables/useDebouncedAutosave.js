import { onBeforeUnmount, readonly, shallowRef } from "vue";

export function useDebouncedAutosave(save, { delay = 700, onError = () => {} } = {}) {
  const saving = shallowRef(false);
  const pendingState = shallowRef(false);
  let timer = 0;
  let pending = null;
  let savedSignature = "";
  let inFlight = null;
  let generation = 0;

  function signature(value) {
    return JSON.stringify(value);
  }

  function reset(value) {
    generation += 1;
    window.clearTimeout(timer);
    timer = 0;
    pending = null;
    pendingState.value = false;
    savedSignature = value == null ? "" : signature(value);
  }

  function schedule(value) {
    if (value == null) return;
    const nextSignature = signature(value);
    if (nextSignature === savedSignature && !inFlight) {
      pending = null;
      pendingState.value = false;
      window.clearTimeout(timer);
      return;
    }
    if (nextSignature === pending?.signature) return;
    // API drafts are JSON. Detach nested Vue proxies and freeze exactly the
    // payload represented by the queued signature.
    pending = { value: JSON.parse(nextSignature), signature: nextSignature };
    pendingState.value = true;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { void flush().catch(() => {}); }, delay);
  }

  async function flush() {
    window.clearTimeout(timer);
    timer = 0;
    if (inFlight) {
      await inFlight;
      return flush();
    }
    if (!pending) return;
    const task = pending;
    const taskGeneration = generation;
    saving.value = true;
    inFlight = Promise.resolve().then(async () => {
      try {
        await save(task.value);
        if (generation === taskGeneration) {
          savedSignature = task.signature;
          if (pending === task) pending = null;
          pendingState.value = Boolean(pending);
        }
      } catch (reason) {
        onError(reason);
        throw reason;
      } finally {
        saving.value = false;
        inFlight = null;
      }
    });
    await inFlight;
    if (generation === taskGeneration && pending) return flush();
  }

  // The navigation owner protects dirty/busy state. Confirmed discard must not
  // accidentally retry a failed request while the component is unmounting.
  onBeforeUnmount(() => reset(null));

  return { saving: readonly(saving), pending: readonly(pendingState), reset, schedule, flush };
}
