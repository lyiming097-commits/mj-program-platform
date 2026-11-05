import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { projectListIdentity, readProjectListCache, writeProjectListCache } from "../src/projectListCache.js";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const fixtureId = "/__business-permissions.js";
const fixture = `
import { createApp } from 'vue';
import '/src/styles.css';
import AdminPermissionSettings from '/src/components/AdminPermissionSettings.vue';
import ProjectWorkspace from '/src/components/ProjectWorkspace.vue';
const params = new URL(location.href).searchParams;
createApp(params.get('view') === 'settings' ? AdminPermissionSettings : ProjectWorkspace,
  params.get('view') === 'settings' ? {} : { serviceType: 'presales', focusProjectId: 1,
    focusNodeKey: 'early-plan', session: { userId: params.get('role') } }).mount('#app');
`;

test("a cached project page cannot survive revoking one of multiple roles", () => {
  const originalWindow = globalThis.window;
  const storage = new Map();
  globalThis.window = { sessionStorage: {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  } };
  try {
    const session = { sessionId: "login", userId: "staff", canManageApp: true, appPermission: "service",
      canManageBusiness: true, canManageSettlements: true, appPermissions: ["service", "sales"] };
    const identity = projectListIdentity(session);
    assert.equal(identity, projectListIdentity({ ...session, sessionId: "renewed", appPermissions: ["sales", "service"] }));
    const response = { items: [{ id: 1 }], crmScopeReady: true, crmScopeExpiresAt: new Date(Date.now() + 60000).toISOString() };
    writeProjectListCache(identity, { page: 1 }, response);
    assert.deepEqual(readProjectListCache(identity, { page: 1 }), response);
    const revoked = projectListIdentity({ ...session, canManageSettlements: false, appPermissions: ["service"] });
    assert.equal(readProjectListCache(revoked, { page: 1 }), null);
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test("permission sources remain independent across roles; project controls follow object abilities", { timeout: 120000 }, async () => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-business-permissions"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "business-permissions-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (!request.url?.startsWith("/__business-permissions?")) return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const errors = [];
    const saves = [];
    page.on("pageerror", error => errors.push(error.message));
    let role = "admin";
    let reducedAccess = false;
    let conflict = false;
    const employee = (userId, name, deptId) => ({ userId, name, departments: [{ deptId, name: "技术部" }] });
    const initialRules = [
      { permission: "admin", scopeType: "employee", targetId: "admin", targetName: "管理员" },
      { permission: "service", scopeType: "departmentSub", targetId: "10", targetName: "技术部" },
      { permission: "sales", scopeType: "employee", targetId: "shared", targetName: "共享员工" },
    ];
    await page.route("https://g.alicdn.com/**", route => route.fulfill({ body: "", contentType: "text/javascript" }));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      const pathname = url.pathname;
      let body = { items: [] };
      let status = 200;
      if (pathname === "/api/after-sales/permissions/directory") {
        body = { orgRevision: "7", departments: [{ deptId: "10", name: "技术部", children: [{ deptId: "11", name: "技术一组", parentDeptId: "10" }] }],
          employees: [employee("admin", "管理员", "20"), employee("shared", "共享员工", "11"), employee("bob", "另一员工", "11")] };
      } else if (pathname === "/api/after-sales/permissions") {
        if (route.request().method() === "POST") {
          const payload = route.request().postDataJSON();
          saves.push(payload);
          status = conflict ? 409 : 200;
          body = conflict ? { code: "REVISION_CONFLICT", error: "权限配置已被其他人修改，请重新加载" }
            : { items: payload.items, revision: "4", orgRevision: "7" };
        } else body = { items: initialRules, revision: "3" };
      } else if (pathname.startsWith("/api/after-sales/projects")) {
        const manage = !reducedAccess && ["admin", "owner"].includes(role);
        const node = (id, nodeKey, name, assigned) => ({ id, nodeKey, name, kind: "delivery", enabled: true, status: "active",
          permissions: { canEdit: !reducedAccess && (manage || role === assigned), canAssign: manage }, estimatedFee: "20.00", actualFee: "10.00",
          updatedAt: "2026-10-15T00:00:00+00:00", businessData: { managementAssignment: { userId: assigned, name: "执行人" },
            schemeRounds: [{ roundId: `${id}`, note: "推进记录", attachmentIds: [] }] } });
        const project = { id: 1, code: "ACL-1", name: "权限验证项目", customer: "测试客户", ownerUserId: "owner", ownerName: "项目负责人",
          serviceType: "presales", status: "in_progress", currentNodeKey: "early-plan", sourceCrmId: "", businessData: {},
          permissions: { canManage: manage, canDelete: manage, canSettle: role === "admin" || role === "sales" },
          nodes: [node(11, "early-plan", "前期方案", "executor"), node(12, "budget-match", "预算匹配", "another")], assignments: [], events: [] };
        body = pathname.endsWith("/1") ? { item: project } : { items: [project], total: 1, totalPages: 1, page: 1, crmScopeReady: true };
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${origin}/__business-permissions?view=settings`);
    assert.equal(await page.getByRole("region", { name: "权限项", exact: true }).getByRole("button").count(), 3);
    assert.equal(await page.getByText("普通内部成员", { exact: true }).count(), 0);
    await page.getByRole("button", { name: /^服务管理员/ }).click();
    const sharedRow = page.getByRole("row").filter({ hasText: "共享员工" });
    await sharedRow.getByRole("button", { name: "排除", exact: true }).click();
    assert.match(await sharedRow.innerText(), /已排除/);
    await page.getByRole("button", { name: /^业务员/ }).click();
    assert.match(await sharedRow.innerText(), /有效/);
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByRole("button", { name: "已保存", exact: true }).waitFor();
    assert.deepEqual(saves[0].items.map(item => [item.permission, item.scopeType, item.targetId]).sort(), [
      ["admin", "employee", "admin"], ["service", "departmentSub", "10"],
      ["service", "excludedEmployee", "shared"], ["sales", "employee", "shared"],
    ].sort());
    assert.equal(saves[0].revision, "3");
    assert.equal(saves[0].orgRevision, "7");
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-permissions-desktop.png"), fullPage: true });
    for (const width of [1024, 390]) {
      await page.setViewportSize({ width, height: 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.getByRole("button", { name: /^业务员/ }).click();
    await sharedRow.getByRole("button", { name: "排除", exact: true }).click();
    conflict = true;
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByRole("button", { name: "重新加载权限" }).waitFor();
    assert.equal(await sharedRow.count(), 0);
    assert.equal(await page.getByRole("button", { name: "保存", exact: true }).isDisabled(), true);
    await page.getByRole("button", { name: "重新加载权限" }).click();
    await page.getByRole("button", { name: "继续编辑", exact: true }).click();
    assert.equal(saves.length, 2);

    for (role of ["executor", "sales", "owner", "admin"]) {
      await page.goto(`${origin}/__business-permissions?view=project&role=${role}`);
      await page.locator("summary").filter({ hasText: "费用信息" }).click();
      const fee = page.getByRole("spinbutton", { name: "当前节点预计费用", exact: true });
      await fee.waitFor({ state: "attached" });
      assert.equal(await fee.isDisabled(), role === "sales", role);
      const person = page.getByRole("button", { name: /^前期方案项目人员：/ });
      await page.locator("summary").filter({ hasText: /^项目人员$/ }).click();
      assert.equal(await person.isDisabled(), ["executor", "sales"].includes(role), role);
      await page.getByRole("button", { name: /^预算匹配，/ }).click();
      if (!(await fee.isVisible())) await page.locator("summary").filter({ hasText: "费用信息" }).click();
      assert.equal(await fee.isDisabled(), ["executor", "sales"].includes(role), `${role}: other node`);
    }
    reducedAccess = true;
    // No project/node timestamp changed: polling must still apply revocation.
    await page.waitForFunction(() => document.querySelector('[aria-label="当前节点预计费用"]')?.disabled, null, { timeout: 40000 });
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
