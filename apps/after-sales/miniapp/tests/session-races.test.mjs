import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Script, createContext } from "node:vm";
import test from "node:test";
import ts from "typescript";

function loadModule(path, context) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  context.exports = {};
  new Script(output, { filename: path }).runInContext(context);
  return context.exports;
}

function makeSession(userId, token = `token-${userId}`) {
  return {
    token,
    sessionId: `session-${userId}`,
    tokenExpiresAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    sessionExpiresAt: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
    user: { userId, name: userId },
  };
}

function harness() {
  const storage = new Map();
  const pending = [];
  const uni = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    removeStorageSync: (key) => storage.delete(key),
    login: ({ success }) => success({ code: "test-code" }),
    request: (options) => pending.push(options),
  };
  const context = createContext({
    uni,
    __API_BASE_URL__: "https://api.example.test",
    __WECHAT_DEV_AUTH__: false,
    Promise,
    Date,
    setTimeout,
    clearTimeout,
  });
  const client = loadModule("../src/api/client.ts", context);
  context.require = (name) => {
    if (name === "@/api/client") return client;
    if (name === "@/composables/useMobileTasks") return { resetMobileTasks() {} };
    if (name === "vue") return { shallowRef: (value) => ({ value }), readonly: (value) => value };
    throw new Error(`Unexpected import: ${name}`);
  };
  const sessions = loadModule("../src/composables/useSession.ts", context);
  async function nextRequest() {
    for (let attempt = 0; attempt < 20 && !pending.length; attempt += 1) await Promise.resolve();
    assert.ok(pending.length, "expected a pending API request");
    return pending.shift();
  }
  return { client, sessions, pending, nextRequest };
}

test("a previous account's failed renewal cannot remove a newly signed-in account", async () => {
  const { client, nextRequest } = harness();
  client.writeStoredSession(makeSession("old"));
  const renewal = client.renewStoredSession({ preferWechatLogin: true });
  const request = await nextRequest();
  client.writeStoredSession(null);
  const current = makeSession("new");
  client.writeStoredSession(current);

  request.success({ statusCode: 401, data: { code: "INVALID_AUTH_TOKEN" } });
  await assert.rejects(renewal, (error) => error.code === "INVALID_AUTH_TOKEN");
  assert.equal(client.readStoredSession().token, current.token);
});

test("a previous account's failed request is not retried with the new account", async () => {
  const { client, pending, nextRequest } = harness();
  client.writeStoredSession(makeSession("old"));
  const result = client.post("/api/after-sales/feedback", { title: "old-account-data" });
  const request = await nextRequest();
  assert.equal(request.header.Authorization, "Bearer token-old");
  client.writeStoredSession(null);
  client.writeStoredSession(makeSession("new"));

  request.success({ statusCode: 401, data: { code: "INVALID_AUTH_TOKEN" } });
  await assert.rejects(result, (error) => error.code === "AUTH_SESSION_CHANGED");
  assert.equal(pending.length, 0);
  assert.equal(client.readStoredSession().user.userId, "new");
});

test("a successful old restore cannot undo a manual logout", async () => {
  const { client, sessions, nextRequest } = harness();
  client.writeStoredSession(makeSession("old"));
  const restoring = sessions.restoreSession();
  const request = await nextRequest();
  sessions.clearSession();

  request.success({ statusCode: 200, data: makeSession("old", "refreshed-token") });
  assert.equal(await restoring, false);
  assert.equal(client.readStoredSession(), null);
  assert.equal(sessions.useSession().state.value.status, "anonymous");
});

test("a successful renewal restores the account using the new token", async () => {
  const { client, sessions, nextRequest } = harness();
  client.writeStoredSession(makeSession("old"));
  const restoring = sessions.restoreSession();
  const request = await nextRequest();
  request.success({ statusCode: 200, data: makeSession("old", "refreshed-token") });

  assert.equal(await restoring, true);
  assert.equal(client.readStoredSession().token, "refreshed-token");
  assert.equal(sessions.useSession().state.value.status, "authenticated");
});

test("an old logout response cannot sign out a newly signed-in account", async () => {
  const { client, sessions, nextRequest } = harness();
  client.writeStoredSession(makeSession("old"));
  const loggingOut = sessions.logoutWithWeChat();
  const request = await nextRequest();
  sessions.clearSession();
  const current = makeSession("new");
  client.writeStoredSession(current);

  request.success({ statusCode: 200, data: { ok: true } });
  await loggingOut;
  assert.equal(client.readStoredSession().token, current.token);
  assert.notEqual(sessions.isManuallyLoggedOut(), true);
});

test("logout stays manual when an expired session is cleared during the request", async () => {
  const { client, sessions, nextRequest } = harness();
  client.writeStoredSession(makeSession("old"));
  const loggingOut = sessions.logoutWithWeChat();
  const logoutRequest = await nextRequest();
  logoutRequest.success({ statusCode: 401, data: { code: "INVALID_AUTH_TOKEN" } });
  const renewalRequest = await nextRequest();
  renewalRequest.success({ statusCode: 401, data: { code: "INVALID_AUTH_TOKEN" } });
  const loginRequest = await nextRequest();
  loginRequest.success({ statusCode: 401, data: { code: "INVALID_AUTH_TOKEN" } });

  await loggingOut;
  assert.equal(client.readStoredSession(), null);
  assert.equal(sessions.isManuallyLoggedOut(), true);
});

test("a new login can renew while an old account renewal remains pending", async () => {
  const { client, nextRequest } = harness();
  client.writeStoredSession(makeSession("old"));
  const oldRenewal = client.renewStoredSession({ preferWechatLogin: true });
  const oldRequest = await nextRequest();
  client.writeStoredSession(null);
  client.writeStoredSession(makeSession("new"));
  const newRenewal = client.renewStoredSession({ preferWechatLogin: true });
  const newRequest = await nextRequest();

  newRequest.success({ statusCode: 200, data: makeSession("new", "new-token") });
  assert.equal((await newRenewal).token, "new-token");
  oldRequest.success({ statusCode: 401, data: { code: "INVALID_AUTH_TOKEN" } });
  await assert.rejects(oldRenewal);
  assert.equal(client.readStoredSession().token, "new-token");
});
