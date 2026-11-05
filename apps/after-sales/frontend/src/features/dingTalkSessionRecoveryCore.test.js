import assert from "node:assert/strict";
import test from "node:test";

import { createDingTalkSessionRecovery } from "./dingTalkSessionRecoveryCore.js";

function authError(code = "MISSING_AUTH_TOKEN") {
  const reason = new Error(code === "MISSING_AUTH_TOKEN" ? "Missing auth token" : "Session revoked");
  reason.status = 401;
  reason.code = code;
  return reason;
}

function harness({ userAgent = "DingTalk Windows", code = "MISSING_AUTH_TOKEN", emptySession = false, initialLogin = false } = {}) {
  let session = emptySession ? null : {
    sessionId: "expired",
    userId: "user-1",
    isProxying: false,
    canManageApp: true,
  };
  let authCalls = 0;
  let validationCalls = 0;
  const store = {
    loadLoginSession: () => session ? ({ ...session }) : null,
    saveLoginSession: (next) => { session = { ...next }; },
    validateLoginSession: async () => { validationCalls += 1; throw authError(code); },
  };
  const recovery = createDingTalkSessionRecovery({
    apiBaseUrl: "https://platform.example.test",
    corpId: "corp-1",
    sessionStore: store,
    allowInitialLogin: () => initialLogin,
    navigatorObject: { userAgent },
    windowObject: {
      dd: { runtime: { permission: { requestAuthCode: ({ onSuccess }) => onSuccess({ code: "ding-code" }) } } },
      setTimeout,
      clearTimeout,
      location: { reload() {} },
    },
    fetchImpl: async () => {
      authCalls += 1;
      return new Response(JSON.stringify({ sessionId: "fresh", userId: "user-1", isProxying: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  });
  return { recovery, state: () => ({ authCalls, validationCalls, session }) };
}

test("DingTalk cookie loss is recovered once and keeps app permissions", async () => {
  const current = harness();
  const results = await Promise.all([
    current.recovery.validateOrRecoverLoginSession(),
    current.recovery.validateOrRecoverLoginSession(),
  ]);
  assert.equal(results[0].recovered, true);
  assert.equal(current.state().validationCalls, 1);
  assert.equal(current.state().authCalls, 1);
  assert.equal(current.state().session.sessionId, "fresh");
  assert.equal(current.state().session.canManageApp, true);
});

test("non-DingTalk and revoked sessions keep the normal login fallback", async () => {
  const browser = harness({ userAgent: "Mozilla/5.0" });
  await assert.rejects(browser.recovery.validateOrRecoverLoginSession(), (reason) => reason.code === "MISSING_AUTH_TOKEN");
  assert.equal(browser.state().authCalls, 0);

  const revoked = harness({ code: "AUTH_SESSION_REVOKED" });
  await assert.rejects(revoked.recovery.validateOrRecoverLoginSession(), (reason) => reason.code === "AUTH_SESSION_REVOKED");
  assert.equal(revoked.state().authCalls, 0);
});

test("a forwarded link can establish a native login in a new DingTalk window", async () => {
  const freshWindow = harness({ emptySession: true, initialLogin: true });
  assert.equal((await freshWindow.recovery.validateOrRecoverLoginSession()).recovered, true);
  assert.equal(freshWindow.state().session.userId, "user-1");
  assert.equal(freshWindow.state().session.canManageApp, undefined, "application permission still needs the business session endpoint");
  const normalEntry = harness({ emptySession: true });
  await assert.rejects(normalEntry.recovery.validateOrRecoverLoginSession());
  assert.equal(normalEntry.state().authCalls, 0);
  const revoked = harness({ emptySession: true, initialLogin: true, code: "AUTH_SESSION_REVOKED" });
  await assert.rejects(revoked.recovery.validateOrRecoverLoginSession());
  assert.equal(revoked.state().authCalls, 0);
});
