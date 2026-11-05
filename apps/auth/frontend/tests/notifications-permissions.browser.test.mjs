import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const frontendRoot = fileURLToPath(new URL("../", import.meta.url));

const session = {
  sessionId: "notification-permissions-fixture",
  userId: "admin-1",
  actorUserId: "admin-1",
  name: "通知管理员",
  canManagePlatformSettings: true,
  canConfigurePermissions: true,
  isFullAccessUser: true,
};

test("switching notification permission roles asks before discarding unsaved changes", async () => {
  const externalBase = process.env.NOTIFICATION_PERMISSIONS_BASE_URL;
  const server = externalBase ? null : await createServer({
    root: frontendRoot,
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  if (server) await server.listen();
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    const artifacts = fileURLToPath(new URL("../../../../.codex-artifacts/notification-permission-roles/", import.meta.url));
    await mkdir(artifacts, { recursive: true });
    const savedRules = { admin: [], publisher: [] }, writes = [], errors = [];
    let conflict = false;
    let releaseSave;
    let holdSave = false;
    await context.addInitScript((login) => {
      window.sessionStorage.setItem("mj_program_login_session", JSON.stringify(login));
    }, session);
    await context.route("**/api/**", async (route) => {
      const { pathname } = new URL(route.request().url());
      const fulfill = (body, status = 200) => route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
      if (pathname === "/api/auth/session/validate") return fulfill(session);
      if (pathname === "/api/org/notices/capabilities") return fulfill({ canManage: true, canPublish: true });
      if (pathname === "/api/org/notices/categories") return fulfill({ items: [] });
      if (pathname === "/api/org/notices") return fulfill({ items: [], total: 0 });
      if (pathname === "/api/org/notices/unread") return fulfill({ items: [], total: 0 });
      if (pathname === "/api/org/departments/tree") {
        return fulfill({ items: [{ deptId: "dept-1", name: "研发部", children: [] }] });
      }
      if (pathname === "/api/org/employees") {
        return fulfill({ items: [{ userId: "person-1", name: "测试员工", departments: [{ deptId: "dept-1" }] }] });
      }
      if (pathname === "/api/org/enabled-departments") return fulfill({ departmentIds: ["dept-1"] });
      if (pathname === "/api/org/notices/permissions/admin" || pathname === "/api/org/notices/permissions/publisher") {
        const role = pathname.split("/").at(-1);
        if (route.request().method() === "PUT") {
          const payload = route.request().postDataJSON();
          writes.push({ role, payload });
          if (holdSave) await new Promise(resolve => { releaseSave = resolve; });
          if (conflict) return fulfill({ error: "权限版本冲突" }, 409);
          savedRules[role] = payload.rules;
        }
        return fulfill({ rules: savedRules[role], revision: "1", orgRevision: "1" });
      }
      if (pathname === "/api/feedback/task-summary") return fulfill({ awaitingConfirmationCount: 0, inProgressCount: 0 });
      return fulfill({ items: [], total: 0, departmentIds: [], rules: [], revision: "1", orgRevision: "1" });
    });

    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    const base = externalBase || `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${base}/auth/settings/notifications`);
    await page.getByRole("tab", { name: "权限管理", exact: true }).click();
    await page.getByRole("button", { name: "添加部门通知管理员" }).waitFor();
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 960 });
      const roleGroup = page.getByRole("group", { name: "权限角色", exact: true });
      const admin = roleGroup.getByRole("button", { name: "通知管理员", exact: true });
      const publisher = roleGroup.getByRole("button", { name: "通知发布者", exact: true });
      const adminBox = await admin.boundingBox(), publisherBox = await publisher.boundingBox();
      assert.equal(await admin.count(), 1);
      assert.equal(await publisher.count(), 1);
      assert.equal(adminBox.x, publisherBox.x);
      assert.ok(publisherBox.y >= adminBox.y + adminBox.height, "both roles are stacked in the permission column");
      assert.equal(await roleGroup.evaluate(node => node.closest("aside") !== null), true);
      assert.equal(await page.locator(".notification-role-tabs, .notification-role-summary").count(), 0);
      for (const name of ["权限选择", "人员配置", "具体人员"]) assert.equal(await page.getByRole("heading", { name, exact: true }).count(), 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: `${artifacts}${externalBase ? "deployed-" : ""}permissions-${width}.png` });
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.getByRole("button", { name: "添加部门通知管理员" }).click();
    const department = page.getByRole("checkbox", { name: "研发部部门" });
    await department.waitFor();
    await department.check();
    await page.getByRole("button", { name: "关闭" }).click();

    await page.getByRole("button", { name: "通知发布者", exact: true }).click();
    await page.getByRole("alertdialog", { name: "是否放弃修改" }).waitFor();
    await page.getByRole("button", { name: "继续编辑" }).click();
    await page.getByRole("button", { name: "添加部门通知管理员" }).click();
    const retainedDepartment = page.getByRole("checkbox", { name: "研发部部门" });
    await retainedDepartment.waitFor();
    assert.equal(await retainedDepartment.isChecked(), true, "canceling role switch keeps the unsaved selection");
    await page.getByRole("button", { name: "关闭" }).click();

    await page.getByRole("button", { name: "通知发布者", exact: true }).click();
    await page.getByRole("button", { name: "确认放弃" }).click();
    await page.getByRole("heading", { name: "通知发布者权限" }).waitFor();
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "通知发布者");
    await page.getByRole("button", { name: "通知管理员", exact: true }).click();
    await page.getByRole("button", { name: "添加部门通知管理员" }).waitFor();
    await page.getByRole("button", { name: "添加部门通知管理员" }).click();
    const reloadedDepartment = page.getByRole("checkbox", { name: "研发部部门" });
    await reloadedDepartment.waitFor();
    assert.equal(await reloadedDepartment.isChecked(), false, "confirming role switch discards the unsaved selection");
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    assert.equal(writes.length, 0, "switching roles does not submit discarded drafts");
    await page.getByRole("button", { name: "通知发布者", exact: true }).focus();
    await page.keyboard.press("Enter");
    await page.getByRole("button", { name: "添加人员通知发布者" }).click();
    await page.getByRole("checkbox", { name: "测试员工通知发布者", exact: true }).check();
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    holdSave = true;
    await page.getByRole("button", { name: "保存", exact: true }).click();
    try {
      await page.waitForFunction(() => document.querySelector('[aria-label="通知管理员"]')?.disabled === true);
      assert.equal(await page.getByRole("tab", { name: "通知列表", exact: true }).isDisabled(), true);
      await page.getByRole("button", { name: "通知管理员", exact: true, includeHidden: true }).evaluate(node => node.click());
      assert.equal(await page.getByRole("button", { name: "通知发布者", exact: true, includeHidden: true }).getAttribute("aria-pressed"), "true");
    } finally { holdSave = false; releaseSave?.(); }
    await page.getByRole("button", { name: "已保存", exact: true }).waitFor();
    assert.deepEqual(writes.map(item => item.role), ["publisher"]);
    assert.equal(savedRules.admin.length, 0);
    assert.equal(savedRules.publisher[0].targetId, "person-1");
    assert.equal(writes[0].payload.revision, "1");
    assert.equal(writes[0].payload.orgRevision, "1");
    await page.getByRole("button", { name: "通知管理员", exact: true }).click();
    await page.getByRole("button", { name: "添加部门通知管理员" }).click();
    await page.getByRole("checkbox", { name: "研发部部门" }).check();
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    conflict = true;
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "当前修改尚未提交" }).waitFor();
    await page.getByRole("button", { name: "通知发布者", exact: true }).click();
    await page.getByRole("button", { name: "继续编辑", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: "通知管理员", exact: true }).getAttribute("aria-pressed"), "true");
    assert.equal(await page.getByRole("button", { name: "移除研发部", exact: true }).count(), 1);
    const mobile = await context.newPage();
    mobile.on("pageerror", error => errors.push(error.message));
    await mobile.setViewportSize({ width: 390, height: 844 });
    await mobile.goto(`${base}/auth/settings/permissions`);
    await mobile.getByRole("heading", { name: "后台管理权限", exact: true }).waitFor();
    await mobile.getByRole("heading", { name: "权限选择", exact: true }).waitFor();
    assert.equal(await mobile.getByRole("group", { name: "权限角色", exact: true }).count(), 0);
    assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await mobile.screenshot({ path: `${artifacts}${externalBase ? "deployed-" : ""}phone-unchanged.png` });
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    if (server) await server.close();
  }
});
