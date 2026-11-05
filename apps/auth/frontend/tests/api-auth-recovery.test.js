import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


const apiSource = readFileSync(new URL("../src/api.js", import.meta.url), "utf8");
const implementationOffset = apiSource.indexOf("const DEFAULT_REQUEST_TIMEOUT_MS");
assert.notEqual(implementationOffset, -1);
let moduleSequence = 0;


function identityKey(session) {
  if (!session) return "signed-out";
  return [
    String(session.sessionId || ""),
    String(session.userId || ""),
    String(session.actorUserId || ""),
    session.isProxying ? "proxy" : "direct",
  ].join(":");
}


async function loadApi(harness) {
  globalThis.__authApiTestHarness = harness;
  const prelude = `
const API_BASE_URL = "https://platform.example.test";
const DING_CORP_ID = "";
const loginSessionIdentityKey = ${identityKey.toString()};
const {
  applyAuthTokenRefreshFromResponse,
  clearLoginSession,
  loadLoginSession,
  saveLoginSession,
  validateLoginSession,
} = globalThis.__authApiTestHarness;
const ensureDingTalkRuntimeSdk = async () => {};
`;
  const source = `${prelude}\n${apiSource.slice(implementationOffset)}`;
  const encoded = Buffer.from(source).toString("base64");
  moduleSequence += 1;
  return import(`data:text/javascript;base64,${encoded}#${moduleSequence}`);
}


function jsonResponse(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}


function createHarness(initialSession, validate) {
  let session = initialSession ? { ...initialSession } : null;
  let validationCalls = 0;
  let clearCalls = 0;
  const harness = {
    applyAuthTokenRefreshFromResponse() {},
    clearLoginSession() {
      clearCalls += 1;
      session = null;
    },
    loadLoginSession() {
      return session ? { ...session } : null;
    },
    saveLoginSession(next) {
      session = next ? { ...next } : null;
    },
    async validateLoginSession(current) {
      validationCalls += 1;
      return validate(current);
    },
    state() {
      return { session, validationCalls, clearCalls };
    },
  };
  globalThis.window = {
    clearTimeout: globalThis.clearTimeout,
    setTimeout: globalThis.setTimeout,
    location: { href: "" },
  };
  Object.defineProperty(globalThis, "navigator", {
    value: { userAgent: "" },
    configurable: true,
  });
  return harness;
}


test("Auth API revalidates a 401 and retries only for the same identity", async () => {
  const initial = { sessionId: "same", userId: "user-1" };
  const harness = createHarness(initial, async () => ({ ...initial, name: "Current" }));
  let businessCalls = 0;
  globalThis.fetch = async () => {
    businessCalls += 1;
    return businessCalls === 1
      ? jsonResponse(401, { error: "stale request", code: "AUTH_SESSION_MISMATCH" })
      : jsonResponse(200, { ok: true });
  };
  const { apiPost } = await loadApi(harness);

  assert.deepEqual(await apiPost("/api/org/action", { value: 1 }), { ok: true });
  assert.equal(businessCalls, 2);
  assert.equal(harness.state().validationCalls, 1);
  assert.equal(harness.state().session.name, "Current");
});


test("Auth API blocks a 401 replay after the cookie identity changed", async () => {
  const harness = createHarness(
    { sessionId: "before", userId: "user-1" },
    async () => ({ sessionId: "after", userId: "user-2" }),
  );
  let businessCalls = 0;
  globalThis.fetch = async () => {
    businessCalls += 1;
    return jsonResponse(401, { error: "stale request", code: "AUTH_SESSION_MISMATCH" });
  };
  const { apiPost } = await loadApi(harness);

  await assert.rejects(
    apiPost("/api/org/action", { value: 1 }),
    (error) => error.code === "AUTH_SESSION_CHANGED",
  );
  assert.equal(businessCalls, 1);
  assert.equal(harness.state().session.userId, "user-2");
  assert.equal(window.location.href, "");
});


test("Auth API revalidates and retries an authentication-related 403", async () => {
  const initial = { sessionId: "same", userId: "user-1" };
  const harness = createHarness(initial, async () => initial);
  let businessCalls = 0;
  globalThis.fetch = async () => {
    businessCalls += 1;
    return businessCalls === 1
      ? jsonResponse(403, { error: "stale auth", code: "AUTH_VERSION_MISMATCH" })
      : jsonResponse(200, { ok: true });
  };
  const { apiPost } = await loadApi(harness);

  assert.deepEqual(await apiPost("/api/org/action", { value: 1 }), { ok: true });
  assert.equal(businessCalls, 2);
  assert.equal(harness.state().validationCalls, 1);
  assert.equal(harness.state().clearCalls, 0);
});


test("Auth API does not revalidate an ordinary permission 403", async () => {
  const initial = { sessionId: "same", userId: "user-1" };
  const harness = createHarness(initial, async () => initial);
  globalThis.fetch = async () => jsonResponse(403, { error: "permission denied", code: "PERMISSION_DENIED" });
  const { apiPost } = await loadApi(harness);

  await assert.rejects(
    apiPost("/api/org/action", { value: 1 }),
    (error) => error.status === 403 && error.code === "PERMISSION_DENIED",
  );
  assert.equal(harness.state().validationCalls, 0);
  assert.equal(harness.state().clearCalls, 0);
  assert.equal(window.location.href, "");
});


test("Auth API redirects only after authentication 403 cookie validation also fails", async () => {
  const harness = createHarness(
    { sessionId: "expired", userId: "user-1" },
    async () => {
      const error = new Error("cookie expired");
      error.status = 401;
      error.code = "AUTH_SESSION_REVOKED";
      throw error;
    },
  );
  globalThis.fetch = async () => jsonResponse(403, { error: "stale auth", code: "AUTH_SESSION_REVOKED" });
  const { apiPost } = await loadApi(harness);

  await assert.rejects(apiPost("/api/org/action", { value: 1 }), (error) => error.status === 401);
  assert.equal(harness.state().validationCalls, 1);
  assert.equal(harness.state().clearCalls, 1);
  assert.match(window.location.href, /^\/auth\/\?error=/);
});
