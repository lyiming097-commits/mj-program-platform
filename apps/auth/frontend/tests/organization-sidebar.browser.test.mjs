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
  sessionId: "sidebar-fixture",
  userId: "sidebar-fixture",
  name: "组织架构管理员",
  isFullAccessUser: true,
  canUseSystemAdmin: true,
  canManagePlatformSettings: true,
  canConfigurePermissions: true,
  canManageEmployeeAccountStatus: true,
  canSyncContacts: true,
  canAccessInactiveEmployees: true,
};
const inactiveFixtures = [
  { userId: "u1", rawName: "张三", name: "张三（未交接）", formerOrganizationRecordedAt: "2026-09-21T10:00:00Z", formerDingTalkDepartments: [{ pathText: "公司 / 研发部" }] },
  { userId: "01000442011033779", rawName: "李四", name: "李四（未交接）", formerOrganizationRecordedAt: "", formerDingTalkDepartments: [] },
  ...Array.from({ length: 115 }, (_, index) => ({
    userId: `fixture-${index + 1}`,
    rawName: `测试员工${index + 1}`,
    formerOrganizationRecordedAt: index === 0
      ? "2026-09-23T09:00:00Z"
      : index === 1
        ? "2026-08-01T09:00:00Z"
        : "",
    formerDingTalkDepartments: [],
  })),
];
const departmentFixtures = [{
  deptId: 1,
  name: "杭州市迈杰教育科技有限公司",
  pinyinInitials: "hzsmjjykjyxgs",
  children: [{
    deptId: 2,
    name: "研发部",
    pinyinInitials: "yfb",
    children: [{ deptId: 3, name: "后端组", pinyinInitials: "hdz", children: [] }],
  }],
}];
const departmentEmployeeFixtures = {
  1: [
    { userId: "manager-1", name: "王主管", accountStatus: "启用", departments: [{ deptId: 1, name: "杭州市迈杰教育科技有限公司" }] },
    { userId: "developer-1", name: "研发专员", accountStatus: "启用", departments: [{ deptId: 2, name: "研发部" }] },
  ],
  2: [
    { userId: "developer-1", name: "研发专员", accountStatus: "启用", departments: [{ deptId: 2, name: "研发部" }] },
  ],
};

test("backend management keeps organization tabs alongside the desktop company entity entry", async () => {
  const server = await createServer({
    root: frontendRoot,
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1440, 1024, 800, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 844 } });
      await context.addInitScript((initialSession) => {
        window.sessionStorage.setItem("mj_program_login_session", JSON.stringify(initialSession));
      }, session);
      await context.route("**/api/**", (route) => {
        const url = new URL(route.request().url());
        const path = url.pathname;
        const employeeMatch = path.match(/^\/api\/org\/departments\/(\d+)\/employees$/);
        const detailMatch = path.match(/^\/api\/org\/departments\/(\d+)$/);
        const data = path === "/api/auth/session/validate" ? session
          : path === "/api/org/employees/inactive" ? { items: inactiveFixtures }
            : path === "/api/org/departments/tree" ? { items: departmentFixtures }
              : path === "/api/org/enabled-departments" ? (
                route.request().method() === "PUT"
                  ? { departmentIds: JSON.parse(route.request().postData() || "{}").departmentIds || [], revision: 2, orgRevision: 1 }
                  : { departmentIds: [1], revision: 1, orgRevision: 1 }
              )
                : employeeMatch ? { items: departmentEmployeeFixtures[employeeMatch[1]] || [] }
                  : detailMatch ? {
                    manager: departmentEmployeeFixtures[detailMatch[1]]?.[0] || null,
                  }
                    : path === "/api/org/permissions" ? { rules: [], revision: 1, orgRevision: 1 }
                      : { items: [], orgRevision: 1 };
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/auth/settings/organization`);
      const tabs = page.getByRole("tablist", { name: "组织架构页面" });
      await tabs.getByRole("tab", { name: width > 767 ? "部门与成员" : "钉钉组织架构" }).waitFor();
      assert.deepEqual(
        await tabs.getByRole("tab").allTextContents(),
        [width > 767 ? "部门与成员" : "钉钉组织架构", "离职人员", "权限设置"],
      );

      if (width > 767) {
        const sidebar = page.getByRole("navigation", { name: "主导航" });
        assert.deepEqual(await sidebar.getByRole("button").allTextContents(), ["组织架构", "我司主体", "省市区域", "工商信息查询", "机器人群发"]);
        assert.equal(await page.getByRole("complementary").getByText("后台管理", { exact: true }).count(), 1);
        assert.equal(await page.getByRole("complementary").getByText("设置模块", { exact: true }).count(), 0);
        const sideBounds = await page.getByRole("complementary").boundingBox();
        const tabBounds = await page.getByRole("navigation", { name: "组织架构页面" }).boundingBox();
        assert.equal(Math.round(sideBounds.width), 216);
        assert.equal(Math.round(tabBounds.x), 216);
        const permissionsBounds = await tabs.getByRole("tab", { name: "权限设置" }).boundingBox();
        assert.ok(Math.abs(permissionsBounds.x + permissionsBounds.width - (tabBounds.x + tabBounds.width - 12)) <= 2);
        const organizationPanel = page.getByRole("tabpanel", { name: width > 767 ? "部门与成员" : "钉钉组织架构" });
        const departmentSettings = organizationPanel.getByRole("region", { name: "部门设置" });
        const editEnabledDepartments = departmentSettings.getByRole("button", { name: "启用范围", exact: true });
        await editEnabledDepartments.waitFor();
        assert.equal(await departmentSettings.getByRole("checkbox").count(), 0);
        assert.equal(await organizationPanel.getByRole("button", { name: "研发部", exact: true }).count(), 0);

        await editEnabledDepartments.click();
        const showDisabledDepartments = departmentSettings.getByRole("checkbox", { name: "查看未启用部门" });
        await showDisabledDepartments.waitFor();
        assert.equal(await showDisabledDepartments.isChecked(), true);
        assert.equal(await editEnabledDepartments.count(), 0);
        const developmentDepartment = organizationPanel.getByRole("button", { name: "研发部", exact: true });
        await developmentDepartment.waitFor();
        const rootDepartmentName = "杭州市迈杰教育科技有限公司";
        const rootEnabled = organizationPanel.getByRole("checkbox", { name: `停用${rootDepartmentName}` });
        const rootDepartment = organizationPanel.getByRole("button", { name: rootDepartmentName, exact: true });
        const rootExpand = organizationPanel.getByRole("button", { name: `收起${rootDepartmentName}` });
        const rootDepartmentRow = rootDepartment.locator("xpath=ancestor::*[contains(@class, 'department-tree-row')]");
        assert.equal(await rootDepartmentRow.locator(".department-tree-icon").count(), 1);

        await rootExpand.click();
        assert.equal(await organizationPanel.getByRole("button", { name: "研发部", exact: true }).count(), 0);
        await rootDepartment.click();
        await developmentDepartment.waitFor();
        assert.equal(await organizationPanel.getByRole("button", { name: `收起${rootDepartmentName}` }).count(), 1);
        assert.equal(await organizationPanel.getByRole("button", { name: "后端组", exact: true }).count(), 0);

        const [rootEnabledBounds, rootDepartmentBounds, rootExpandBounds] = await Promise.all([
          rootEnabled.boundingBox(),
          rootDepartment.boundingBox(),
          organizationPanel.getByRole("button", { name: `收起${rootDepartmentName}` }).boundingBox(),
        ]);
        assert.ok(rootEnabledBounds.x < rootDepartmentBounds.x);
        assert.ok(rootDepartmentBounds.x < rootExpandBounds.x);
        assert.equal(
          await rootDepartmentRow.evaluate(
            (node) => getComputedStyle(node).borderBottomWidth,
          ),
          "1px",
        );

        const developmentEnabled = organizationPanel.getByRole("checkbox", { name: "启用研发部" });
        assert.equal(await developmentEnabled.isChecked(), false);
        await developmentDepartment.click();
        await organizationPanel.getByRole("button", { name: "后端组", exact: true }).waitFor();
        const developmentRegion = organizationPanel.getByRole("region", { name: "研发部人员" });
        await developmentRegion.getByRole("table", { name: "组织成员" }).getByText("研发专员", { exact: true }).waitFor();
        assert.equal(await developmentRegion.getByRole("checkbox", { name: "启用部门" }).count(), 0);
        await developmentEnabled.check();
        assert.equal(await showDisabledDepartments.isChecked(), true);

        await showDisabledDepartments.uncheck();
        assert.equal(await organizationPanel.getByRole("button", { name: "研发部", exact: true }).count(), 1);
        await rootDepartment.click();
        const rootRegion = organizationPanel.getByRole("region", { name: `${rootDepartmentName}人员` });
        await rootEnabled.uncheck();
        assert.equal(await showDisabledDepartments.isChecked(), true);
        assert.equal(await organizationPanel.getByRole("button", { name: rootDepartmentName, exact: true }).count(), 1);

        const saveButton = departmentSettings.getByRole("button", { name: "保存", exact: true });
        const organizationActionButton = rootRegion.getByRole("button", { name: "操作", exact: true });
        assert.equal(await rootRegion.getByRole("button", { name: "保存", exact: true }).count(), 0);
        assert.equal(await departmentSettings.getByRole("button", { name: "操作", exact: true }).count(), 0);
        assert.equal(await saveButton.isEnabled(), true);
        const [saveBounds, organizationActionBounds] = await Promise.all([
          saveButton.boundingBox(),
          organizationActionButton.boundingBox(),
        ]);
        assert.ok(saveBounds.x < organizationActionBounds.x);
        await page.screenshot({ path: `/tmp/mj-auth-organization-editing-${width}.png` });

        await organizationActionButton.click();
        const organizationActionDialog = page.getByRole("dialog", { name: "操作" });
        await organizationActionDialog.waitFor();
        assert.equal(await organizationActionDialog.getByText("全部禁用", { exact: true }).count(), 1);
        assert.equal(await organizationActionDialog.getByText("全部启用", { exact: true }).count(), 1);
        await organizationActionDialog.getByRole("button", { name: "关闭操作窗口" }).click();

        const saveRequestPromise = page.waitForRequest((request) => (
          request.method() === "PUT" && new URL(request.url()).pathname === "/api/org/enabled-departments"
        ));
        await saveButton.click();
        const saveRequest = await saveRequestPromise;
        assert.deepEqual(JSON.parse(saveRequest.postData()).departmentIds, ["2"]);
        await page.getByText("启用部门设置已保存").waitFor();
        const editAfterSave = departmentSettings.getByRole("button", { name: "启用范围", exact: true });
        await editAfterSave.waitFor();
        assert.equal(await departmentSettings.getByRole("button", { name: "保存", exact: true }).count(), 0);
        assert.equal(await departmentSettings.getByRole("checkbox").count(), 0);

        await editAfterSave.click();
        assert.equal(await departmentSettings.getByRole("checkbox", { name: "查看未启用部门" }).isChecked(), true);
        await departmentSettings.getByRole("button", { name: "取消", exact: true }).click();
        await departmentSettings.getByRole("button", { name: "启用范围", exact: true }).waitFor();
        assert.equal(await departmentSettings.getByRole("checkbox").count(), 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: `/tmp/mj-auth-organization-enabled-${width}.png` });

        await tabs.getByRole("tab", { name: "离职人员" }).click();
        assert.equal(await sidebar.getByRole("button", { name: "组织架构" }).getAttribute("class").then((value) => value.includes("active")), true);
      } else {
        assert.equal(await page.getByRole("checkbox", { name: "查看未启用部门" }).count(), 0);
        assert.equal(await page.getByRole("checkbox", { name: /^(启用|停用).+/ }).count(), 0);
        await tabs.getByRole("tab", { name: "离职人员" }).click();
        assert.equal(await tabs.getByRole("tab", { name: "离职人员" }).getAttribute("aria-selected"), "true");
      }
      const panel = page.getByRole("tabpanel", { name: "离职人员" });
      await panel.getByText("公司 / 研发部").waitFor();
      assert.equal(await panel.getByText("离职日期").count(), width > 767 ? 1 : 20);
      assert.equal(await panel.getByText("2026-09-23").count(), 1);
      assert.equal(await panel.getByText("2026-09-21").count(), 1);
      assert.equal(await panel.getByText("2026-08-01").count(), 1);
      assert.equal(await panel.getByText("未记录").count(), 34);
      assert.equal(await panel.getByRole("button", { name: "移交" }).count(), 0);
      const pagination = panel.getByRole("navigation", { name: "离职人员分页" });
      assert.equal(await pagination.getByRole("button", { name: "下一页" }).isEnabled(), true);
      assert.equal(await pagination.getByRole("button", { name: "上一页" }).isDisabled(), true);
      if (width > 767) {
        assert.equal(await pagination.getByRole("button", { name: "第 1 页" }).getAttribute("aria-current"), "page");
      } else {
        assert.equal(await pagination.getByText("第 1 / 6 页").count(), 1);
      }
      assert.equal(await panel.getByText("共 117 人 · 每页 20 人").count(), 1);
      if (width > 767) {
        const inactiveTable = panel.getByRole("table", { name: "离职人员" });
        assert.equal(await inactiveTable.getByRole("row").count(), 22);
        const inactiveRows = inactiveTable.locator("tbody tr");
        assert.match(await inactiveRows.nth(0).textContent(), /测试员工1.*2026-09-23/);
        assert.match(await inactiveRows.nth(1).textContent(), /张三.*2026-09-21/);
        assert.match(await inactiveRows.nth(2).textContent(), /测试员工2.*2026-08-01/);
        const tableRegion = panel.getByRole("region", { name: "离职人员表格，可使用方向键横向浏览" });
        assert.equal(await tableRegion.evaluate((node) => getComputedStyle(node).cursor), "auto");
        assert.equal(await tableRegion.evaluate((node) => node.scrollHeight > node.clientHeight), true);
        assert.equal(await panel.getByText("01000442011033779").evaluate((node) => getComputedStyle(node).whiteSpace), "nowrap");
        if (width === 800) {
          await tableRegion.focus();
          await page.keyboard.press("ArrowRight");
          assert.ok(await tableRegion.evaluate((node) => node.scrollLeft) > 0);
        }
        if (width === 1024) {
          const lastColumn = await panel.getByRole("columnheader", { name: "离职前钉钉组织架构" }).boundingBox();
          assert.ok(lastColumn.x + lastColumn.width <= 1024);
        }
      } else {
        assert.equal(await panel.getByRole("article").count(), 20);
        assert.match(await panel.getByRole("article").nth(0).textContent(), /张三.*2026-09-21/);
        assert.match(await panel.getByRole("article").nth(1).textContent(), /李四.*未记录/);
      }
      const footerBounds = await pagination.boundingBox();
      assert.ok(footerBounds.y + footerBounds.height <= 844);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      assert.equal(overflow, false);
      await page.screenshot({ path: `/tmp/mj-auth-inactive-${width}.png` });
      if (width > 767) {
        await pagination.getByRole("button", { name: "第 6 页" }).click();
        assert.equal(await panel.getByRole("table", { name: "离职人员" }).getByRole("row").count(), 19);
        assert.equal(await pagination.getByRole("button", { name: "下一页" }).isDisabled(), true);
        await pagination.getByRole("button", { name: "第 1 页" }).click();
      }
      await pagination.getByRole("button", { name: "下一页" }).click();
      if (width > 767) {
        assert.equal(await pagination.getByRole("button", { name: "第 2 页" }).getAttribute("aria-current"), "page");
      } else {
        assert.equal(await pagination.getByText("第 2 / 6 页").count(), 1);
      }
      await panel.getByText("测试员工19", { exact: true }).waitFor();
      assert.equal(await panel.getByText("张三", { exact: true }).count(), 0);
      const search = panel.getByRole("searchbox", { name: width > 767 ? "搜索离职人员姓名或 ID" : "搜索离职人员" });
      await search.fill("张三");
      await panel.getByText("张三", { exact: true }).waitFor();
      if (width > 767) {
        assert.equal(await pagination.getByRole("button", { name: "第 1 页" }).getAttribute("aria-current"), "page");
      } else {
        assert.equal(await pagination.getByText("第 1 / 1 页").count(), 1);
      }
      await search.fill("不存在的名字");
      await panel.getByText("没有匹配的离职人员").waitFor();
      await tabs.getByRole("tab", { name: "权限设置" }).click();
      await page.getByRole("heading", { name: "后台管理权限", exact: true }).waitFor();
      await page.getByRole("heading", { name: "权限选择", exact: true }).waitFor();
      await page.getByRole("heading", { name: "人员配置", exact: true }).waitFor();
      await page.getByRole("heading", { name: "具体人员", exact: true }).waitFor();
      assert.equal(await page.getByText("可使用后台管理内全部功能，代理除外。", { exact: true }).count(), 1);
      if (width > 767) {
        assert.equal(await page.getByRole("button", { name: "保存" }).isDisabled(), true);
        assert.equal(await page.getByRole("navigation", { name: "主导航" }).getByRole("button").count(), 5);
        assert.equal(await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "应用模板", exact: true }).getAttribute("href"), "/?app=starter-app");
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({ path: `/tmp/mj-auth-permission-toolbar-${width}.png` });
      assert.deepEqual(errors, []);
      await context.close();
    }
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 844 } });
      await context.addInitScript((initialSession) => {
        window.sessionStorage.setItem("mj_program_login_session", JSON.stringify(initialSession));
      }, session);
      await context.route("**/api/**", (route) => {
        const pathname = new URL(route.request().url()).pathname;
        const data = pathname === "/api/auth/session/validate" ? session : { items: [], orgRevision: 1 };
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const appUrl = `http://127.0.0.1:${server.httpServer.address().port}/auth/settings/organization`;
      await page.goto(appUrl);
      await page.setContent(`<iframe title="后台管理应用" data-portal-embed="true" src="${appUrl}" style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe>`);
      const embedded = page.frameLocator('iframe[title="后台管理应用"]');
      await embedded.getByRole("tablist", { name: "组织架构页面" }).waitFor();
      assert.equal(await embedded.locator("header.platform-topbar").count(), 0);
      if (width > 767) {
        const bodyTop = await embedded.locator(".settings-workspace-body").evaluate((node) => Math.round(node.getBoundingClientRect().top));
        assert.equal(bodyTop, 0);
        const sidebar = embedded.getByRole("complementary");
        assert.equal(Math.round((await sidebar.boundingBox()).y), 0);
        assert.equal(await sidebar.getByText("后台管理", { exact: true }).count(), 1);
      }
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally {
    await browser.close();
    await server.close();
  }
});
