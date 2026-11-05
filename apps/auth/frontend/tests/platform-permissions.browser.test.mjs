import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const frontendRoot = fileURLToPath(new URL("../", import.meta.url));

const session = {
  sessionId: "platform-permissions-fixture",
  userId: "assigned-admin",
  name: "后台管理员",
  isFullAccessUser: false,
  canUseSystemAdmin: false,
  canManagePlatformSettings: true,
  canConfigurePermissions: true,
  canManageEmployeeAccountStatus: true,
  canSyncContacts: true,
  canAccessInactiveEmployees: true,
  canStartProxy: false,
  canSwitchProxy: false,
};

const departments = [{
  deptId: 1,
  name: "迈杰",
  pinyinInitials: "mj",
  children: [{
    deptId: 2,
    parentDeptId: 1,
    name: "研发部",
    pinyinInitials: "yfb",
    children: [],
  }],
}];

const employees = [
  {
    userId: "manager-1",
    name: "王主管",
    pinyinInitials: "wzg",
    departments: [{ deptId: 1, name: "迈杰", pinyinInitials: "mj" }],
  },
  {
    userId: "developer-1",
    name: "研发专员",
    pinyinInitials: "yfzy",
    departments: [{ deptId: 2, name: "研发部", pinyinInitials: "yfb" }],
  },
];

test("desktop platform permissions use the template workflow and preserve conflicts", async () => {
  const server = await createServer({
    root: frontendRoot,
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addInitScript((initialSession) => {
      window.sessionStorage.setItem("mj_program_login_session", JSON.stringify(initialSession));
    }, session);

    let savedRules = [];
    let permissionRevision = 1;
    let saveCount = 0;
    await context.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const fulfill = (body, status = 200) => route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
      if (path === "/api/auth/session/validate") return fulfill(session);
      if (path === "/api/org/departments/tree") return fulfill({ items: departments, orgRevision: 8 });
      if (path === "/api/org/enabled-departments") {
        return fulfill({ departmentIds: [1, 2], revision: 3, orgRevision: 8 });
      }
      if (path === "/api/org/employees") return fulfill({ items: employees, orgRevision: 8 });
      if (path === "/api/org/departments/1") return fulfill({ manager: employees[0], orgRevision: 8 });
      if (path === "/api/org/departments/1/employees") return fulfill({ items: employees, orgRevision: 8 });
      if (path === "/api/org/permissions" && request.method() === "GET") {
        return fulfill({ rules: savedRules, revision: permissionRevision, orgRevision: 8 });
      }
      if (path === "/api/org/permissions" && request.method() === "PUT") {
        saveCount += 1;
        const payload = request.postDataJSON();
        if (saveCount > 1) {
          return fulfill({ code: "REVISION_CONFLICT", error: "配置已发生变化" }, 409);
        }
        savedRules = payload.rules;
        permissionRevision += 1;
        return fulfill({ rules: savedRules, revision: permissionRevision, orgRevision: 8 });
      }
      return fulfill({ items: [], orgRevision: 8 });
    });

    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const baseUrl = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(`${baseUrl}/auth/settings/permissions`);

    await page.getByRole("heading", { name: "后台管理权限", exact: true }).waitFor();
    assert.equal(await page.getByText("可使用后台管理内全部功能，代理除外。", { exact: true }).count(), 1);
    assert.deepEqual(
      await page.getByRole("navigation", { name: "主导航" }).getByRole("button").allTextContents(),
      ["组织架构", "我司主体", "省市区域", "工商信息查询", "机器人群发", "通知"],
    );

    const addDepartment = page.getByRole("button", { name: "添加部门后台管理员" });
    await addDepartment.click();
    let picker = page.getByRole("dialog", { name: "添加部门" });
    const departmentSearch = picker.getByRole("searchbox", { name: "搜索部门" });
    await departmentSearch.waitFor();
    assert.equal(await departmentSearch.evaluate((node) => document.activeElement === node), true);
    await departmentSearch.fill("yfb");
    assert.equal(await picker.getByText("研发部", { exact: true }).count(), 1);
    await departmentSearch.fill("");
    await picker.getByRole("checkbox", { name: "迈杰包含子部门" }).check();
    await page.keyboard.press("Escape");
    await picker.waitFor({ state: "detached" });
    assert.equal(await addDepartment.evaluate((node) => document.activeElement === node), true);

    const addEmployee = page.getByRole("button", { name: "添加人员后台管理员" });
    await addEmployee.click();
    picker = page.getByRole("dialog", { name: "添加人员" });
    await picker.getByRole("checkbox", { name: "王主管后台管理员" }).check();
    assert.equal(await picker.count(), 1);
    await picker.getByRole("checkbox", { name: "研发专员后台管理员" }).check();
    await picker.getByRole("button", { name: "关闭" }).click();

    const members = page.getByRole("table", { name: "后台管理权限具体人员" });
    assert.equal(await members.getByRole("row").count(), 3);
    await members.getByRole("button", { name: "排除研发专员" }).click();
    assert.equal(await members.getByText("研发专员", { exact: true }).count(), 0);
    await page.getByRole("button", { name: "恢复研发专员" }).click();
    assert.equal(await members.getByText("研发专员", { exact: true }).count(), 1);

    const save = page.locator('[data-ai-action="auth.platform-permissions.save"]');
    const firstSaveRequest = page.waitForRequest((request) => (
      request.method() === "PUT" && new URL(request.url()).pathname === "/api/org/permissions"
    ));
    await save.click();
    const firstPayload = (await firstSaveRequest).postDataJSON();
    assert.equal(firstPayload.revision, "1");
    assert.equal(firstPayload.orgRevision, "8");
    assert.deepEqual(firstPayload.rules.map((rule) => [rule.scopeType, rule.targetId]), [
      ["departmentSub", "1"],
      ["employee", "manager-1"],
    ]);
    await page.getByRole("status").filter({ hasText: "权限配置已保存" }).waitFor();

    await page.getByRole("button", { name: "移除迈杰" }).click();
    await save.click();
    await page.getByRole("alert").filter({ hasText: "权限或组织已更新" }).waitFor();
    assert.equal(await save.isDisabled(), true);
    await page.getByRole("button", { name: "重新加载" }).click();
    const discard = page.getByRole("alertdialog", { name: "是否放弃修改" });
    await discard.getByRole("button", { name: "确认放弃" }).click();
    await page.getByRole("button", { name: "移除迈杰" }).waitFor();

    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(pageErrors, []);
    await page.screenshot({ path: "/tmp/mj-auth-platform-permissions-1440.png", fullPage: true });

    await page.getByRole("button", { name: "移除迈杰" }).click();
    const organizationTab = page.getByRole("tab", { name: "部门与成员" });
    await organizationTab.click();
    let leaveDialog = page.getByRole("alertdialog", { name: "是否放弃修改" });
    await leaveDialog.getByRole("button", { name: "继续编辑" }).click();
    assert.equal(await page.getByRole("heading", { name: "后台管理权限", exact: true }).count(), 1);
    assert.equal(await page.getByRole("button", { name: "移除迈杰" }).count(), 0);

    await organizationTab.click();
    leaveDialog = page.getByRole("alertdialog", { name: "是否放弃修改" });
    await leaveDialog.getByRole("button", { name: "确认放弃" }).click();
    await page.getByRole("tabpanel", { name: "部门与成员" }).waitFor();
    await context.close();
  } finally {
    await browser.close();
    await server.close();
  }
});
