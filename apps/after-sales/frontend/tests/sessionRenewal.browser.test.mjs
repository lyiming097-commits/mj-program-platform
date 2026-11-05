import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const intervalMs = 10 * 60 * 1000;
let broadcastSequence = 0;

async function setup({ access, initialPath = "/after-sales/presales/", providers = [] } = {}) {
  const server = await createServer({
    root, configFile: path.join(root, "vite.config.ts"),
    define: { "import.meta.env.VITE_DING_CORP_ID": JSON.stringify("test-corp") },
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-session-renewal"),
    server: { host: "127.0.0.1", port: 0 },
  });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await page.clock.install();
    const state = {
      identity: { sessionId: "service-session", userId: "service-admin", actorUserId: "service-admin", isProxying: false, name: "管理员", loginType: "workbench" },
      access: access || { canManageApp: true, canManageSettings: true, appPermission: "admin" },
      accessStatus: 200, missingCookie: false, rejectProjects: false,
      validations: 0, accessRequests: 0, logins: 0, projectRequests: 0, pageErrors: [], requests: [],
    };
    page.on("pageerror", error => state.pageErrors.push(error.message));
    await page.addInitScript(identity => {
      if (!sessionStorage.getItem("mj_program_login_session")) {
        sessionStorage.setItem("mj_program_login_session", JSON.stringify(identity));
      }
      window.dd = { env: { platform: "pc" }, runtime: { permission: {
        requestAuthCode({ onSuccess }) { onSuccess({ code: "test-ding-code" }); },
      } } };
    }, state.identity);
    await page.route("https://g.alicdn.com/**", route => route.fulfill({ contentType: "text/javascript", body: "" }));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      state.requests.push({ path: url.pathname, method: route.request().method() });
      let status = 200;
      let body = { items: [] };
      if (url.pathname === "/api/auth/session/validate") {
        state.validations += 1;
        status = state.missingCookie ? 401 : 200;
        body = status === 401 ? { error: "Missing auth token", code: "MISSING_AUTH_TOKEN" } : state.identity;
      } else if (url.pathname === "/api/auth/code") {
        state.logins += 1;
        state.missingCookie = false;
        state.identity = { ...state.identity, sessionId: `renewed-${state.logins}` };
        body = state.identity;
      } else if (url.pathname === "/api/after-sales/session/") {
        state.accessRequests += 1;
        status = state.accessStatus;
        body = status === 200 ? state.access : { error: "权限服务暂时不可用", code: "AUTH_ORG_UNAVAILABLE" };
      } else if (url.pathname === "/api/after-sales/projects") {
        state.projectRequests += 1;
        status = state.rejectProjects ? 401 : 200;
        state.rejectProjects = false;
        body = status === 401 ? { error: "Missing auth token", code: "MISSING_AUTH_TOKEN" }
          : { items: [], total: 0, totalPages: 1, page: 1, crmScopeReady: true, crmSyncing: false };
      } else if (url.pathname === "/api/after-sales/providers") {
        body = { items: providers };
      } else if (url.pathname.startsWith("/api/after-sales/providers/")) {
        const item = providers.find(item => String(item.id) === url.pathname.split("/").at(-1));
        body = { item };
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${origin}${initialPath}`);
    const admitted = state.access.canManageApp && [state.access.appPermission, ...(state.access.appPermissions || [])]
      .some(role => ["admin", "service", "sales"].includes(role));
    if (admitted) await page.getByRole("button", { name: "新增售前项目", exact: true }).waitFor();
    else await page.getByRole("heading", { name: "无权使用迈杰服务", exact: true }).waitFor();
    return { page, context, state, origin, close: async () => { await browser.close(); await server.close(); } };
  } catch (error) {
    await browser?.close();
    await server.close();
    throw error;
  }
}

async function broadcastSession(harness, session) {
  const messageSession = { ...session, nick: `门户同步的管理员-${++broadcastSequence}` };
  const sender = await harness.context.newPage();
  await sender.goto(`${harness.origin}/after-sales/round-share.svg`);
  await sender.evaluate(session => {
    const channel = new BroadcastChannel("mj-program-auth-session");
    channel.postMessage({ sourceId: "portal-test", messageId: crypto.randomUUID(), sentAt: Date.now(), session });
    channel.close();
  }, messageSession);
  await harness.page.waitForFunction(({ sessionId, nick }) => (
    JSON.parse(sessionStorage.getItem("mj_program_login_session"))?.sessionId === sessionId
    && JSON.parse(sessionStorage.getItem("mj_program_login_session"))?.nick === nick
    && !Object.hasOwn(JSON.parse(sessionStorage.getItem("mj_program_login_session")), "canManageApp")
  ), messageSession);
  await sender.close();
}

async function draftProject(page) {
  await page.getByRole("button", { name: "新增售前项目", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新增售前项目", exact: true });
  await dialog.getByRole("textbox", { name: "客户单位 *", exact: true }).fill("未提交的客户");
  await dialog.getByRole("textbox", { name: "项目名称 *", exact: true }).fill("续期前正在填写的项目");
  return dialog;
}

test("platform session broadcasts and periodic renewal preserve service access and drafts", { timeout: 60000 }, async () => {
  const harness = await setup();
  const { page, state } = harness;
  try {
    const dialog = await draftProject(page);
    await broadcastSession(harness, state.identity);
    const validations = state.validations;
    const rechecked = page.waitForResponse(response => new URL(response.url()).pathname === "/api/after-sales/session/", { timeout: 5000 });
    await page.clock.runFor(intervalMs);
    await rechecked;
    await page.getByRole("button", { name: "新增售前项目", exact: true }).waitFor({ timeout: 5000 });
    assert.ok(state.validations > validations);
    assert.equal(await dialog.getByRole("textbox", { name: "项目名称 *", exact: true }).inputValue(), "续期前正在填写的项目");
    assert.equal(await page.getByRole("heading", { name: "无权使用迈杰服务" }).count(), 0);
    assert.ok(state.accessRequests >= 2, "keepalive rechecks business permissions independently");
    assert.equal(new URL(page.url()).pathname, "/after-sales/presales/");
    await broadcastSession(harness, { ...state.identity, canManageApp: false, canManageSettings: false, appPermission: "none" });
    assert.equal(await dialog.getByRole("textbox", { name: "项目名称 *", exact: true }).inputValue(), "续期前正在填写的项目");
    assert.equal(await page.getByRole("heading", { name: "无权使用迈杰服务" }).count(), 0, "other applications cannot replace service permissions");
    assert.deepEqual(state.pageErrors, []);
  } finally { await harness.close(); }
});

test("DingTalk cookie recovery and API retry retain the current service workspace", { timeout: 60000 }, async () => {
  const harness = await setup();
  const { page, state } = harness;
  try {
    const dialog = await draftProject(page);
    state.missingCookie = true;
    const rechecked = page.waitForResponse(response => new URL(response.url()).pathname === "/api/after-sales/session/");
    await page.clock.runFor(intervalMs);
    await rechecked;
    assert.equal(state.logins, 1);
    assert.equal(await dialog.getByRole("textbox", { name: "客户单位 *", exact: true }).inputValue(), "未提交的客户");
    assert.equal(new URL(page.url()).pathname, "/after-sales/presales/");
    assert.equal(await page.getByRole("heading", { name: "无权使用迈杰服务" }).count(), 0);

    state.missingCookie = true;
    state.rejectProjects = true;
    const projects = state.projectRequests;
    const result = await page.evaluate(async () => {
      const { apiGet } = await import("/after-sales/src/api.js");
      return apiGet("/api/after-sales/projects", { type: "presales" });
    });
    assert.equal(result.total, 0);
    assert.equal(state.logins, 2);
    assert.equal(state.projectRequests, projects + 2);
    assert.equal(await dialog.getByRole("textbox", { name: "项目名称 *", exact: true }).inputValue(), "续期前正在填写的项目");
    assert.deepEqual(state.pageErrors, []);
  } finally { await harness.close(); }
});

test("temporary permission errors are distinct from confirmed permission removal", { timeout: 60000 }, async () => {
  const harness = await setup();
  const { page, state } = harness;
  try {
    state.accessStatus = 503;
    await page.clock.runFor(intervalMs);
    await page.getByRole("alert").filter({ hasText: "权限服务暂时不可用" }).waitFor();
    assert.equal(await page.getByRole("heading", { name: "无权使用迈杰服务" }).count(), 0);
    await page.getByRole("button", { name: "新增售前项目", exact: true }).waitFor();
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-session-renewal.png") });
    state.accessStatus = 200;
    state.access = { canManageApp: false, canManageSettings: false, appPermission: "none" };
    await page.getByRole("button", { name: "重新验证权限", exact: true }).click();
    await page.getByRole("heading", { name: "无权使用迈杰服务" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "新增售前项目", exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "本软件优化建议", exact: true }).count(), 0);
    await page.evaluate(() => {
      history.pushState({}, "", "/after-sales/settlements/");
      dispatchEvent(new PopStateEvent("popstate"));
    });
    await page.getByRole("heading", { name: "无权使用迈杰服务" }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/after-sales/");
    assert.deepEqual(state.pageErrors, []);
  } finally { await harness.close(); }
});

test("changed accounts and proxies reload and obtain their own service permissions", { timeout: 60000 }, async () => {
  for (const identityChange of [
    { userId: "other-user", actorUserId: "other-user", isProxying: false },
    { userId: "proxy-target", actorUserId: "service-admin", isProxying: true },
  ]) {
    const harness = await setup();
    const { page, state } = harness;
    try {
      await draftProject(page);
      state.identity = { ...state.identity, ...identityChange, sessionId: "changed-identity" };
      state.access = { canManageApp: false, canManageSettings: false, appPermission: "none" };
      const loaded = page.waitForEvent("domcontentloaded");
      await broadcastSession(harness, state.identity);
      await loaded;
      await page.getByRole("heading", { name: "无权使用迈杰服务" }).waitFor();
      assert.equal(await page.getByRole("dialog", { name: "新增售前项目", exact: true }).count(), 0);
      assert.equal(await page.getByRole("button", { name: "新增售前项目", exact: true }).count(), 0);
      assert.ok(state.accessRequests >= 2);
      assert.deepEqual(state.pageErrors, []);
    } finally { await harness.close(); }
  }
});

test("an authenticated account without any application role cannot open a business deep link", { timeout: 60000 }, async () => {
  for (const canManageApp of [false, true]) {
    const harness = await setup({
      access: { canManageApp, canManageSettings: false, appPermission: "", appPermissions: [] },
      initialPath: "/after-sales/presales/?projectId=1&nodeKey=early-plan",
    });
    const { page, state } = harness;
    try {
      await page.getByRole("alert").filter({ hasText: "请联系系统管理员分配业务员、服务管理员或系统管理员权限" }).waitFor();
      assert.equal(state.projectRequests, 0);
      assert.equal(state.logins, 0, "application denial does not force repeated platform logins");
      assert.equal(await page.getByRole("button", { name: "售前服务", exact: true }).count(), 0);
      assert.equal(await page.getByRole("button", { name: "新增售前项目", exact: true }).count(), 0);
      assert.equal(new URL(page.url()).pathname, "/after-sales/");
      await page.clock.runFor(intervalMs);
      await page.getByRole("heading", { name: "无权使用迈杰服务" }).waitFor();
      assert.equal(state.projectRequests, 0);
      assert.deepEqual(state.pageErrors, []);
    } finally { await harness.close(); }
  }
});

test("role menus include collaboration and settlements; the sales team view has no management actions", { timeout: 120000 }, async () => {
  for (const role of ["sales", "service", "admin"]) {
    const provider = { id: 91, name: "待审测试人员", certificationStatus: "pending", phone: "13800000000", city: "杭州" };
    const harness = await setup({
      access: { canManageApp: true, appPermission: role, appPermissions: [role],
        canManageSettings: role === "admin", canManageBusiness: true, canManageService: role !== "sales", canManageSettlements: true },
      providers: [provider],
    });
    const { page, state, origin } = harness;
    try {
      const nav = page.getByRole("navigation", { name: "主导航", exact: true });
      for (const label of ["总览", "售前服务", "售中服务", "售后服务", "工单与反馈", "结算中心", "服务团队"]) {
        assert.equal(await nav.getByRole("button", { name: label, exact: true }).isVisible(), true, `${role}: ${label}`);
      }
      assert.equal(await nav.getByRole("button", { name: "服务奖励", exact: true }).count(), role === "sales" ? 0 : 1);
      assert.equal(await nav.getByRole("button", { name: "设置 / 权限", exact: true }).count(), role === "admin" ? 1 : 0);
      await nav.getByRole("button", { name: "工单与反馈", exact: true }).click();
      await page.getByRole("table", { name: "工单列表", exact: true }).waitFor();
      await nav.getByRole("button", { name: "服务团队", exact: true }).click();
      await page.getByRole("row").filter({ hasText: provider.name }).click();
      await page.getByRole("heading", { name: provider.name, exact: true }).waitFor();
      const audit = page.getByRole("button", { name: "审核通过", exact: true });
      assert.equal(await audit.count(), role === "sales" ? 0 : 1);
      assert.equal(await page.getByRole("heading", { name: "状态操作", exact: true }).count(), role === "sales" ? 0 : 1);
      if (role === "sales") {
        assert.equal(state.requests.some(request => request.path === "/api/after-sales/rewards"), false);
        await page.clock.runFor(500);
        await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-sales-team-readonly.png"), fullPage: true });
      }
      if (role !== "admin") {
        await page.evaluate(() => {
          history.pushState({}, "", "/after-sales/settings/permissions/");
          dispatchEvent(new PopStateEvent("popstate"));
        });
        await page.waitForURL(`${origin}/after-sales/`);
        assert.equal(state.requests.some(request => request.path === "/api/after-sales/permissions"), false);
      }
      assert.deepEqual(state.pageErrors, []);
    } finally { await harness.close(); }
  }
});
