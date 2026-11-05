export const DING_OAUTH_STATE_KEY = "mj_program_ding_oauth_state";

function resolveSessionStorage(storage) {
  if (storage) return storage;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function createOAuthState(storage = null) {
  const bytes = new Uint8Array(16);
  globalThis.crypto?.getRandomValues?.(bytes);
  const state = Array.from(bytes).some(Boolean)
    ? Array.from(bytes, (item) => item.toString(16).padStart(2, "0")).join("")
    : btoa(`${Date.now()}-${Math.random()}`).replace(/=+$/g, "");
  resolveSessionStorage(storage)?.setItem(DING_OAUTH_STATE_KEY, state);
  return state;
}

export function consumeOAuthState(receivedState, storage = null) {
  const targetStorage = resolveSessionStorage(storage);
  const expectedState = targetStorage?.getItem(DING_OAUTH_STATE_KEY) || "";
  targetStorage?.removeItem(DING_OAUTH_STATE_KEY);
  return Boolean(expectedState && receivedState && expectedState === receivedState);
}
