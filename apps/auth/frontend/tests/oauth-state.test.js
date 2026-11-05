import test from "node:test";
import assert from "node:assert/strict";

import { consumeOAuthState, createOAuthState, DING_OAUTH_STATE_KEY } from "../src/oauth-state.js";


function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

test("OAuth state is random, matched once, then consumed", () => {
  const storage = memoryStorage();
  const state = createOAuthState(storage);
  assert.equal(storage.getItem(DING_OAUTH_STATE_KEY), state);
  assert.equal(consumeOAuthState(state, storage), true);
  assert.equal(consumeOAuthState(state, storage), false);
});

test("OAuth state rejects a different callback value", () => {
  const storage = memoryStorage();
  createOAuthState(storage);
  assert.equal(consumeOAuthState("wrong-state", storage), false);
});
